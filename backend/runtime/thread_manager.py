from __future__ import annotations

from backend.sessions.models import SessionRecord
from backend.sessions.session_store import SessionStore


class ThreadManager:
    def __init__(self, store: SessionStore):
        self.store = store

    def create_or_restore(self, session_id: str | None = None, title: str | None = None) -> tuple[SessionRecord, bool]:
        if session_id:
            return self.store.get(session_id), False
        return self.store.create(title=title), True

    def list_sessions(self):
        return self.store.list()

    def delete(self, session_id: str) -> None:
        self.store.delete(session_id)
