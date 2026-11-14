"""Local user-authored mathematical material, separate from built-in corpora."""

import json
import math
import sqlite3
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Query
from pydantic import Field, field_validator

from agent_platform.models import PlatformError, StrictRequest
from agent_platform.safety import sanitize
from reasoning_agent.lexical_strategy_retrieval import tokenize


class LibraryEntry(StrictRequest):
    kind: Literal['strategy', 'skill']
    title: str = Field(min_length=1, max_length=120)
    category: str = Field(default='', max_length=80)
    keywords: str = Field(default='', max_length=300)
    content: str = Field(min_length=1, max_length=10000)
    enabled: bool = True

    @field_validator('title', 'content')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('empty_material')
        return value.strip()


class LibraryUpdate(LibraryEntry):
    revision: int = Field(ge=1)


class CustomLibrary:
    def __init__(self, root):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / 'library.sqlite'
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS entries ('
                       'id TEXT PRIMARY KEY, revision INTEGER NOT NULL, '
                       'updated_at TEXT NOT NULL, data TEXT NOT NULL)')

    @contextmanager
    def connection(self):
        try:
            with closing(sqlite3.connect(self.path, timeout=5)) as db:
                db.row_factory = sqlite3.Row
                with db:
                    yield db
        except (sqlite3.Error, OSError):
            raise PlatformError('library_unavailable', 503) from None

    @staticmethod
    def row(row):
        return {**json.loads(row['data']), 'id': row['id'], 'revision': row['revision'],
                'updated_at': row['updated_at']}

    def list(self):
        with self.connection() as db:
            return [self.row(row) for row in db.execute('SELECT * FROM entries ORDER BY updated_at DESC, id')]

    def save(self, entry, identifier=None, revision=None):
        data = sanitize(entry.model_dump(exclude={'revision'}))
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if identifier is None:
                if db.execute('SELECT count(*) FROM entries').fetchone()[0] >= 500:
                    raise PlatformError('library_capacity', 409)
                identifier, revision = str(uuid4()), 1
                db.execute('INSERT INTO entries VALUES (?, ?, ?, ?)',
                           (identifier, revision, now, json.dumps(data, ensure_ascii=False)))
            else:
                result = db.execute('UPDATE entries SET revision=revision+1, updated_at=?, data=? '
                                    'WHERE id=? AND revision=?',
                                    (now, json.dumps(data, ensure_ascii=False), identifier, revision))
                if not result.rowcount:
                    raise PlatformError('library_conflict', 409)
                revision += 1
        return {**data, 'id': identifier, 'revision': revision, 'updated_at': now}

    def delete(self, identifier, revision):
        with self.connection() as db:
            if not db.execute('DELETE FROM entries WHERE id=? AND revision=?', (identifier, revision)).rowcount:
                raise PlatformError('library_conflict', 409)

    def select(self, problem):
        query = tokenize(problem)
        ranked = []
        for entry in self.list():
            if not entry['enabled']:
                continue
            terms = tokenize(' '.join(entry[key] for key in ('title', 'category', 'keywords', 'content')))
            overlap = set(query) & set(terms)
            if not overlap:
                continue
            score = sum(min(query[key], terms[key]) for key in overlap) / math.sqrt(
                max(1, sum(query.values()) * sum(terms.values())))
            ranked.append((score, entry))
        selected, size = [], 0
        for _, entry in sorted(ranked, key=lambda pair: (-pair[0], pair[1]['id'])):
            if len(selected) == 4:
                break
            material = {key: entry[key] for key in ('id', 'revision', 'kind', 'title', 'category', 'content')}
            encoded = json.dumps(material, ensure_ascii=False)
            # Preserve the whole method, including its applicability conditions.
            if size + len(encoded) > 11500:
                continue
            selected.append(material)
            size += len(encoded) + 2
        return json.dumps(selected, ensure_ascii=False) if selected else ''


def library_router(library, limit):
    router = APIRouter(prefix='/v1/library')

    def available():
        if library is None:
            raise PlatformError('library_unavailable', 503)
        return library

    @router.get('')
    def listing():
        limit('library_read', 'local', 20, 20)
        return {'items': available().list()}

    @router.post('', status_code=201)
    def create(body: LibraryEntry):
        limit('library_write', 'local', 10, 2)
        return available().save(body)

    @router.put('/{identifier}')
    def update(identifier: str, body: LibraryUpdate):
        limit('library_write', 'local', 10, 2)
        return available().save(body, identifier, body.revision)

    @router.delete('/{identifier}')
    def delete(identifier: str, revision: int = Query(ge=1)):
        limit('library_write', 'local', 10, 2)
        available().delete(identifier, revision)
        return {'deleted': True}

    return router
