"""Edit the actual handbooks and retrieval corpus, publishing indexes together."""
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
import threading
from uuid import uuid4

from fastapi import APIRouter, Query
from pydantic import Field

from agent_platform.models import PlatformError, StrictRequest
from reasoning_agent.custom2.strategy_skills import ALLOWED_SKILL_CATEGORIES
from reasoning_agent.lexical_strategy_retrieval import build_lexical_payloads
from reasoning_agent.resource_files import resource_lock, ResourcesBusy
from reasoning_agent.strategy_documents import build_strategy_text

ROOT = Path(__file__).resolve().parents[1]
INDEX_FILES = ('strategy_meta.json', 'strategy_embeddings.npy', 'strategy_index.json',
               'strategy_lexical_index.json', 'strategy_lexical_manifest.json')
VERSION = '.resources-version'
JOURNAL = '.resources-transaction.json'
logger = logging.getLogger(__name__)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def revision(value):
    return hashlib.sha256(value if isinstance(value, bytes) else encoded(value)).hexdigest()


def atomic_bytes(path, value):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ResourceCreate(StrictRequest):
    content: str = Field(min_length=1, max_length=1_000_000)


class ResourceUpdate(ResourceCreate):
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')


class KnowledgeResources:
    def __init__(self, root=ROOT, *, embedder=None):
        self.root = Path(root).resolve()
        self.data = self.root / 'strategy_data'
        self.embedder = embedder or self._embed
        self._cache_lock = threading.RLock()
        self._cache = None
        self._cache_stamp = None
        if (self.data / JOURNAL).exists():
            with resource_lock(self.data, exclusive=True):
                self._recover()

    def version(self):
        path = self.data / VERSION
        return path.read_text().strip() if path.is_file() else ''

    def _skill_path(self, identifier):
        if identifier not in ALLOWED_SKILL_CATEGORIES:
            raise PlatformError('resource_not_found', 404)
        path = self.root / 'skill2_en' / identifier / f'{identifier}_skill.md'
        if not path.is_file() or path.resolve() != path.absolute():
            raise PlatformError('resource_not_found', 404)
        return path

    def _cards(self):
        path = self.data / 'strategy_meta.json'
        stamp = (path.stat().st_mtime_ns, path.stat().st_size)
        with self._cache_lock:
            if self._cache_stamp != stamp:
                self._cache = json.loads(path.read_text(encoding='utf-8'))
                self._cache_stamp = stamp
            return self._cache

    def _card(self, identifier):
        for row, card in enumerate(self._cards()):
            if str(card['id']) == identifier:
                return row, card
        raise PlatformError('resource_not_found', 404)

    def _summary(self, kind, identifier, item):
        if kind == 'skill':
            path = self._skill_path(identifier)
            return {'id': identifier, 'title': identifier.replace('_', ' ').title(),
                    'category': identifier, 'source': path.relative_to(self.root).as_posix()}
        return {'id': str(item['id']), 'title': item.get('name', ''),
                'category': ', '.join(str(tag) for tag in item.get('tags', [])),
                'source': 'strategy_data/strategy_meta.json'}

    def list(self, kind, query='', offset=0, limit=40):
        with resource_lock(self.data):
            if (self.data / JOURNAL).exists():
                raise PlatformError('resource_unavailable', 503)
            if kind == 'skill':
                rows = [self._summary(kind, category, None) for category in ALLOWED_SKILL_CATEGORIES
                        if (self.root / 'skill2_en' / category / f'{category}_skill.md').is_file()]
            else:
                rows = [self._summary(kind, str(card['id']), card) for card in self._cards()]
            total = len(rows)
            query = query.strip().casefold()
            if query:
                rows = [item for item in rows if query in ' '.join(
                    str(item[key]) for key in ('id', 'title', 'category')).casefold()]
            manifest = self.data / 'strategy_index.json'
            index = json.loads(manifest.read_text()) if manifest.is_file() else {}
            return {'items': rows[offset:offset + limit], 'total': len(rows), 'corpus_total': total,
                    'next_offset': offset + limit if offset + limit < len(rows) else None,
                    'indexes': {'lexical': (self.data / 'strategy_lexical_index.json').is_file(),
                                'vector': (self.data / 'strategy_embeddings.npy').is_file(),
                                'embedding_dim': index.get('embedding_dim'),
                                'embedding_model': index.get('embedding_model')}}

    def get(self, kind, identifier):
        with resource_lock(self.data):
            if (self.data / JOURNAL).exists():
                raise PlatformError('resource_unavailable', 503)
            if kind == 'skill':
                raw = self._skill_path(identifier).read_bytes()
                return {**self._summary(kind, identifier, None), 'kind': kind,
                        'revision': revision(raw), 'content': raw.decode('utf-8')}
            _, card = self._card(identifier)
            return {**self._summary(kind, identifier, card), 'kind': kind,
                    'revision': revision(card), 'content': encoded(card).decode('utf-8')}

    def save(self, kind, identifier, update):
        creating = identifier is None
        if creating and kind != 'strategy':
            raise PlatformError('resource_not_found', 404)
        try:
            with resource_lock(self.data, exclusive=True, blocking=False):
                self._recover()
                if creating:
                    ids = [card['id'] for card in self._cards()]
                    if any(type(value) is not int or value < 0 for value in ids) or len(set(ids)) != len(ids):
                        raise PlatformError('resource_invalid_index', 409)
                    identifier = str(max(ids, default=-1) + 1)
                else:
                    current = self.get_unlocked(kind, identifier)
                    if current['revision'] != update.revision:
                        raise PlatformError('resource_conflict', 409)
                if not update.content.strip():
                    raise PlatformError('resource_invalid', 400)
                stage = Path(tempfile.mkdtemp(prefix='.resource-edit-', dir=self.data))
                try:
                    if kind == 'skill':
                        relative = self._skill_path(identifier).relative_to(self.root)
                        (stage / 'handbook').write_text(update.content, encoding='utf-8')
                        replacements = {str(relative): 'handbook'}
                    else:
                        replacements = self._stage_strategy(identifier, update.content, stage, creating=creating)
                    (stage / 'version').write_text(uuid4().hex)
                    replacements[f'strategy_data/{VERSION}'] = 'version'
                    self._publish(stage, replacements)
                finally:
                    # Preserve rollback material if interrupted publication needs recovery.
                    if not (self.data / JOURNAL).exists():
                        shutil.rmtree(stage, ignore_errors=True)
                self._cache_stamp = None
        except ResourcesBusy:
            raise PlatformError('resource_busy', 409) from None
        except PlatformError:
            raise
        except (OSError, ValueError, KeyError, TypeError, ImportError):
            raise PlatformError('resource_unavailable', 503) from None
        logger.warning('[资源保存完成] 类型=%s ID=%s；后续任务读取最新资源。', kind, identifier)
        return self.get(kind, identifier)

    def get_unlocked(self, kind, identifier):
        # The caller already owns the exclusive lock; do not acquire a second file lock.
        if kind == 'skill':
            return {'revision': revision(self._skill_path(identifier).read_bytes())}
        return {'revision': revision(self._card(identifier)[1])}

    def _stage_strategy(self, identifier, content, stage, *, creating=False):
        import numpy as np
        from reasoning_agent.lexical_strategy_retrieval import LexicalStrategyRetriever
        from reasoning_agent.strategy_retrieval import EMBEDDING_DIM, EMBEDDING_MODEL_NAME

        original = self._cards()
        row, old = (len(original), {}) if creating else self._card(identifier)
        try:
            card = json.loads(content)
            if creating:
                if not isinstance(card, dict) or 'id' in card:
                    raise ValueError('server_assigned_id_required')
                card['id'] = int(identifier)
            valid = (isinstance(card, dict) and (creating or (
                     type(card.get('id')) is type(old['id']) and card['id'] == old['id']))
                     and set(old) <= set(card)
                     and all(isinstance(card.get(key), str) and card[key].strip() for key in ('name', 'description'))
                     and all(isinstance(card.get(key), list) and all(isinstance(x, str) for x in card[key])
                             for key in ('tags', 'applicability'))
                     and isinstance(card.get('steps'), list)
                     and all(isinstance(x, dict) and all(isinstance(x.get(k, ''), str) for k in ('step', 'detail'))
                             for x in card['steps']))
            if creating:
                valid = (valid and isinstance(card.get('example'), dict)
                         and all(isinstance(card['example'].get(key), str) and card['example'][key].strip()
                                 for key in ('problem', 'solution'))
                         and all(card[key] and all(value.strip() for value in card[key])
                                 for key in ('tags', 'applicability'))
                         and bool(card['steps'])
                         and all(all(isinstance(step.get(key), str) and step[key].strip()
                                     for key in ('step', 'detail')) for step in card['steps']))
            encoded(card)
        except (ValueError, TypeError, KeyError):
            valid = False
        if not valid:
            raise PlatformError('resource_invalid_new_strategy' if creating else 'resource_invalid_strategy', 400)
        cards = original + [card] if creating else [card if i == row else item for i, item in enumerate(original)]
        manifest = json.loads((self.data / 'strategy_index.json').read_text())
        vectors = np.load(self.data / 'strategy_embeddings.npy', allow_pickle=False)
        if (vectors.shape != (len(original), EMBEDDING_DIM) or not np.isfinite(vectors).all()
                or manifest.get('embedding_model') != EMBEDDING_MODEL_NAME
                or manifest.get('embedding_dim') != EMBEDDING_DIM):
            raise PlatformError('resource_invalid_index', 409)
        vectors = vectors.astype(np.float32, copy=True)
        if creating:
            vectors = np.concatenate([vectors, np.zeros((1, EMBEDDING_DIM), dtype=np.float32)])
        if creating or build_strategy_text(old) != build_strategy_text(card):
            logger.warning('[策略向量更新] ID=%s；使用本地模型编码修改后的策略。', identifier)
            try:
                vector = np.asarray(self.embedder(build_strategy_text(card)), dtype=np.float32)
                norm = np.linalg.norm(vector)
                if vector.shape != (EMBEDDING_DIM,) or not np.isfinite(vector).all() or not norm > 0:
                    raise ValueError('invalid_embedding')
                vectors[row] = vector / norm
            except Exception:
                raise PlatformError('resource_embedding_failed', 503) from None
        logger.warning('[词法索引更新] 策略数=%s；保持现有分词与评分规则。', len(cards))
        lexical, lexical_manifest = build_lexical_payloads(cards)
        manifest.update(num_strategies=len(cards), cards_digest=lexical_manifest['cards_digest'])
        for name, value in [('strategy_meta.json', cards), ('strategy_index.json', manifest),
                            ('strategy_lexical_index.json', lexical), ('strategy_lexical_manifest.json', lexical_manifest)]:
            (stage / name).write_bytes(encoded(value))
        np.save(stage / 'strategy_embeddings.npy', vectors, allow_pickle=False)
        LexicalStrategyRetriever(stage)
        return {f'strategy_data/{name}': name for name in INDEX_FILES}

    def _publish(self, stage, replacements):
        entries = []
        for index, (relative, source) in enumerate(replacements.items()):
            target = self.root / relative
            backup = f'backup-{index}' if target.exists() else None
            if backup:
                shutil.copyfile(target, stage / backup)
            entries.append({'target': relative, 'source': source, 'backup': backup})
        atomic_bytes(self.data / JOURNAL, encoded({'stage': stage.name, 'entries': entries}))
        try:
            for entry in entries:
                os.replace(stage / entry['source'], self.root / entry['target'])
            (self.data / JOURNAL).unlink()
        except BaseException:
            self._recover()
            raise

    def _recover(self):
        path = self.data / JOURNAL
        if not path.exists():
            return
        journal = json.loads(path.read_text())
        stage = self.data / journal['stage']
        if (stage.parent != self.data or not stage.name.startswith('.resource-edit-')
                or stage.is_symlink() or stage.resolve().parent != self.data.resolve()):
            raise PlatformError('resource_unavailable', 503)
        allowed = {f'strategy_data/{name}' for name in (*INDEX_FILES, VERSION)} | {
            f'skill2_en/{key}/{key}_skill.md' for key in ALLOWED_SKILL_CATEGORIES}
        for entry in journal['entries']:
            if entry['target'] not in allowed or (entry['backup'] and Path(entry['backup']).name != entry['backup']):
                raise PlatformError('resource_unavailable', 503)
            target = self.root / entry['target']
            if entry['backup']:
                atomic_bytes(target, (stage / entry['backup']).read_bytes())
            else:
                target.unlink(missing_ok=True)
        path.unlink()
        shutil.rmtree(stage, ignore_errors=True)

    def _embed(self, text):
        from reasoning_agent.strategy_retrieval import _get_shared_embedding_model, preferred_device
        resource = _get_shared_embedding_model(self.root / 'strategyrag/Qwen3-Embedding-0.6B', preferred_device())
        model = resource.get_model()
        with resource.encode_lock:
            return model.encode([text], normalize_embeddings=True, convert_to_numpy=True,
                                show_progress_bar=False)[0]


def resources_router(resources, limit):
    router = APIRouter(prefix='/v1/resources')

    def instance(kind, mutation=False):
        limit('resources_write' if mutation else 'resources_read', 'local', 10 if mutation else 60, 2 if mutation else 20)
        if resources is None:
            raise PlatformError('resource_unavailable', 503)
        if kind not in {'skill', 'strategy'}:
            raise PlatformError('resource_not_found', 404)
        return resources

    @router.get('/{kind}')
    def listing(kind: str, q: str = Query('', max_length=200), offset: int = Query(0, ge=0), limit_size: int = Query(40, ge=1, le=100)):
        try:
            return instance(kind).list(kind, q, offset, limit_size)
        except (OSError, ValueError, KeyError, TypeError):
            raise PlatformError('resource_unavailable', 503) from None

    @router.get('/{kind}/{identifier}')
    def get(kind: str, identifier: str):
        try:
            return instance(kind).get(kind, identifier)
        except (OSError, ValueError, KeyError, TypeError):
            raise PlatformError('resource_unavailable', 503) from None

    @router.put('/{kind}/{identifier}')
    def update(kind: str, identifier: str, body: ResourceUpdate):
        return instance(kind, True).save(kind, identifier, body)

    @router.post('/strategy', status_code=201)
    def create(body: ResourceCreate):
        return instance('strategy', True).save('strategy', None, body)

    return router
