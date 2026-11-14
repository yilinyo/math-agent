"""Incremental, unverified projection of the declared public solution protocol."""
import re
import time
from uuid import uuid4

from agent_platform.observability import redact_trace_value
from agent_platform.presentation.instructions import SECTIONS


class PublicAnswerStream:
    def __init__(self, context, stage, check_running, selected=SECTIONS):
        self.context, self.stage = context, stage
        self.check_running = check_running
        self.selected = selected
        self.id = str(uuid4())
        self.started = time.monotonic()
        self.index = 0
        self.pending = ""
        self.line = ""
        self.private = []
        self.current = None
        self.heading_pending = False
        self.fence = None
        self.check_block = False
        self.total = 0
        self.opened = False
        self.record("answer.started", preview=True)
        self.opened = True

    def record(self, kind, **payload):
        self.check_running()
        self.context.record(self.stage, kind, {"stream_id": self.id, **payload})

    def feed(self, text):
        self.check_running()
        self.total += len(text)
        if self.total > 48000:
            self.discard()
            return
        self.pending += text
        # Retain incomplete tags across transport chunks and lines.
        while self.pending:
            position = self.pending.find("<")
            if position < 0:
                self._visible(self.pending)
                self.pending = ""
                break
            self._visible(self.pending[:position])
            self.pending = self.pending[position:]
            if len(self.pending) > 1 and not re.match(r"[A-Za-z/\s]", self.pending[1]):
                self._visible("<")
                self.pending = self.pending[1:]
                continue
            end = self.pending.find(">")
            if end < 0:
                break
            tag = self.pending[:end + 1]
            self.pending = self.pending[end + 1:]
            private = re.fullmatch(r"<\s*(/?)\s*(think|analysis)\b[^>]*>", tag, re.I)
            if private:
                name = private[2].lower()
                if private[1]:
                    if self.private and self.private[-1] == name:
                        self.private.pop()
                else:
                    self.private.append(name)
            else:
                self._visible(tag)

    def _visible(self, text):
        if self.private:
            return
        self.line += text
        while "\n" in self.line:
            line, self.line = self.line.split("\n", 1)
            self._line(line.rstrip("\r"))

    def _line(self, line):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if self.fence:
            if marker and marker[1][0] == self.fence[0] and len(marker[1]) >= len(self.fence) and not marker[2].strip():
                self.fence = None
                if self.check_block:
                    self.check_block = False
                    return
            if self.check_block:
                return
        elif marker:
            self.fence = marker[1]
            self.check_block = marker[2].strip().lower().split(maxsplit=1)[:1] == ["check"]
            if self.check_block:
                return
        elif heading := re.match(r"^\s{0,3}##\s+(.+?)\s*#*\s*$", line):
            self.current = heading[1] if heading[1] in self.selected else None
            self.heading_pending = True
            return
        if self.current and (line.strip() or not self.heading_pending):
            # Redact complete lines so secrets split across tokens cannot leak.
            public = redact_trace_value(line)
            if self.heading_pending:
                public = ("\n" if self.index else "") + f"## {self.current}\n" + public
                self.heading_pending = False
            if not self.opened:
                self.record("answer.started", preview=True)
                self.opened = True
            self.record("answer.delta", index=self.index, text=public + "\n")
            self.index += 1

    def complete(self):
        self.check_running()
        if self.total > 48000:
            return
        # An unfinished tag or private block is intentionally never flushed.
        if not self.private:
            self._line(self.line)
        if self.opened:
            self.record("answer.completed", chunks=self.index, preview=True,
                        duration_ms=max(0, int((time.monotonic() - self.started) * 1000)))

    def discard(self):
        if self.opened:
            self.record("answer.discarded")
            self.opened = False
