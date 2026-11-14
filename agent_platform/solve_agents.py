"""Versioned, nonsecret solver profiles for the local single-user application."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Query
from pydantic import Field, field_validator

from agent_platform.models import PlatformError, StrictRequest
from agent_platform.safety import sanitize_text

SNAPSHOT_KEY = "_solve_agent"
REQUEST_KEY = "_solve_agent_request"
BUILTIN_ID = "builtin"
SOLVE_CALLS = {"solver", "solver_repair", "solver_compressed", "emergency_integrator", "emergency_direct_solver"}


class SolveAgentDraft(StrictRequest):
    name: str = Field(min_length=1, max_length=80)
    provider: Literal["intern", "compatible"] = "compatible"
    api_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=160)
    credential_env: str = Field(default="", max_length=100, pattern=r"^(?:[A-Z][A-Z0-9_]*_API_KEY)?$")
    temperature: float = Field(default=.3, ge=0, le=2, allow_inf_nan=False)
    max_tokens: int = Field(default=8192, ge=256, le=65536)
    timeout: int = Field(default=240, ge=10, le=600)
    preference: str = Field(default="", max_length=1500)
    enabled: bool = True

    @field_validator("name", "model", "preference")
    @classmethod
    def safe_text(cls, value):
        value = value.strip()
        if sanitize_text(value) != value:
            raise ValueError("nonsecret_text_required")
        return value

    @field_validator("name", "model")
    @classmethod
    def nonempty(cls, value):
        if not value:
            raise ValueError("empty_value")
        return value

    @field_validator("api_url")
    @classmethod
    def endpoint(cls, value):
        value = value.strip()
        try:
            parsed = urlsplit(value)
            valid = (parsed.scheme in {"http", "https"} and parsed.hostname and parsed.port != 0
                     and not parsed.username and not parsed.password and not parsed.query
                     and not parsed.fragment and parsed.path.endswith("/chat/completions")
                     and not any(char.isspace() for char in value) and sanitize_text(value) == value)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("full_chat_completion_url_required")
        return value


class SolveAgentUpdate(SolveAgentDraft):
    revision: int = Field(ge=1)


class SolveAgentSnapshot(StrictRequest):
    id: str = Field(min_length=1, max_length=80)
    revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=80)
    model: str = Field(max_length=160)
    config: SolveAgentDraft | None = None


def snapshot_hash(snapshot):
    value = SolveAgentSnapshot.model_validate(snapshot).model_dump(mode="json")
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def public_agent(snapshot):
    return {key: snapshot[key] for key in ("id", "revision", "name", "model")} if snapshot else None


class SolveAgents:
    def __init__(self, root, *, model="default", available=True, tester=None):
        Path(root).mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(Path(root) / "agents.sqlite"), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, revision INTEGER, deleted INTEGER, data TEXT);
            CREATE TABLE IF NOT EXISTS agent_revisions (id TEXT, revision INTEGER, data TEXT, PRIMARY KEY(id,revision));
            CREATE TABLE IF NOT EXISTS agent_settings (key TEXT PRIMARY KEY, value TEXT);
        """)
        self.builtin = {"id": BUILTIN_ID, "revision": 1, "name": "默认 Solve Agent", "model": sanitize_text(model)[:160],
                        "builtin": True, "enabled": True, "credential_ready": True}
        self.available, self.tester = available, tester

    def close(self):
        self.db.close()

    def _default(self):
        row = self.db.execute("SELECT value FROM agent_settings WHERE key='default'").fetchone()
        return row[0] if row else BUILTIN_ID

    def _get(self, identifier):
        if identifier == BUILTIN_ID:
            return dict(self.builtin)
        row = self.db.execute("SELECT revision,data FROM agents WHERE id=? AND deleted=0", (identifier,)).fetchone()
        if not row:
            raise PlatformError("solve_agent_not_found", 404)
        value = json.loads(row[1])
        return {**value, "id": identifier, "revision": row[0], "builtin": False,
                "credential_ready": not value["credential_env"] or bool(os.environ.get(value["credential_env"]))}

    def list(self):
        with self.lock:
            ids = [row[0] for row in self.db.execute("SELECT id FROM agents WHERE deleted=0 ORDER BY rowid")]
            return {"items": [self._get(BUILTIN_ID), *[self._get(identifier) for identifier in ids]],
                    "default_id": self._default() if self.available else BUILTIN_ID, "solving_available": self.available}

    def save(self, draft, identifier=None, revision=None):
        data = draft.model_dump(mode="json", exclude={"revision"})
        # Credentials belong exclusively in the backend environment, even when pasted into a text field.
        encoded = json.dumps(data)
        if any(secret and len(secret) >= 8 and secret in encoded for key, secret in os.environ.items()
               if key.endswith("_API_KEY")):
            raise PlatformError("solve_agent_secret_in_config", 400)
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if identifier:
                old = self._get(identifier)
                if identifier == BUILTIN_ID or old["revision"] != revision:
                    raise PlatformError("solve_agent_conflict", 409)
                next_revision = revision + 1
            else:
                if self.db.execute("SELECT count(*) FROM agents WHERE deleted=0").fetchone()[0] >= 100:
                    raise PlatformError("solve_agent_capacity", 409)
                identifier, next_revision = str(uuid4()), 1
            self.db.execute("INSERT OR REPLACE INTO agents VALUES (?,?,0,?)", (identifier, next_revision, encoded))
            self.db.execute("INSERT INTO agent_revisions VALUES (?,?,?)", (identifier, next_revision, encoded))
            if not data["enabled"] and self._default() == identifier:
                self.db.execute("DELETE FROM agent_settings WHERE key='default'")
            return self._get(identifier)

    def delete(self, identifier, revision):
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = self._get(identifier)
            if identifier == BUILTIN_ID or old["revision"] != revision:
                raise PlatformError("solve_agent_conflict", 409)
            self.db.execute("UPDATE agents SET deleted=1 WHERE id=?", (identifier,))
            if self._default() == identifier:
                self.db.execute("DELETE FROM agent_settings WHERE key='default'")
            return {"deleted": True}

    def default(self, identifier, revision):
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            item = self._get(identifier)
            if not self.available and not item.get("builtin"):
                raise PlatformError("solve_agents_unavailable", 503)
            if not item["enabled"] or item["revision"] != revision:
                raise PlatformError("solve_agent_conflict", 409)
            self.db.execute("INSERT OR REPLACE INTO agent_settings VALUES ('default',?)", (identifier,))
            return {"default_id": identifier}

    def freeze(self, identifier=None):
        with self.lock:
            item = self._get(identifier or (self._default() if self.available else BUILTIN_ID))
            if not self.available and not item.get("builtin"):
                raise PlatformError("solve_agents_unavailable", 503)
            if not item["enabled"]:
                raise PlatformError("solve_agent_disabled", 409)
            if not item["credential_ready"]:
                raise PlatformError("solve_agent_credential_missing", 409)
            config = None if item.get("builtin") else SolveAgentDraft.model_validate(
                {key: item[key] for key in SolveAgentDraft.model_fields}).model_dump(mode="json")
            return {**public_agent(item), "config": config}

    def submission(self, store, session, key, identifier):
        previous = store.lookup_submission(session, key) if key else None
        if previous:
            if previous.metadata.get(REQUEST_KEY) != identifier:
                raise PlatformError("idempotency_conflict", 409)
            if SNAPSHOT_KEY in previous.metadata:
                return previous.metadata[SNAPSHOT_KEY]
            return None
        return self.freeze(identifier)


def solve_agents_router(agents, limit):
    router = APIRouter(prefix="/v1/solve-agents")

    def catalog(mutation=False):
        limit("agents_mutation" if mutation else "agents_read", "local", 20, 5)
        if agents is None:
            raise PlatformError("solve_agents_unavailable", 503)
        return agents

    @router.get("")
    async def listing():
        return catalog().list()

    @router.post("", status_code=201)
    async def create(body: SolveAgentDraft):
        return catalog(True).save(body)

    @router.put("/{identifier}")
    async def update(identifier: str, body: SolveAgentUpdate):
        return catalog(True).save(body, identifier, body.revision)

    @router.delete("/{identifier}")
    async def remove(identifier: str, revision: int = Query(ge=1)):
        return catalog(True).delete(identifier, revision)

    @router.post("/{identifier}/default")
    async def default(identifier: str, revision: int = Query(ge=1)):
        return catalog(True).default(identifier, revision)

    @router.post("/{identifier}/test")
    async def test(identifier: str, revision: int = Query(ge=1)):
        instance = catalog(True)
        limit("agent_test", "local", 1, .1)
        if not instance.available or instance.tester is None:
            raise PlatformError("solve_agents_unavailable", 503)
        snapshot = instance.freeze(identifier)
        if snapshot["revision"] != revision:
            raise PlatformError("solve_agent_conflict", 409)
        from llm_client import chat_failure_diagnostics
        try:
            await asyncio.wait_for(asyncio.to_thread(instance.tester, snapshot), timeout=8)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error_code": chat_failure_diagnostics(exc)["error_code"]}

    return router
