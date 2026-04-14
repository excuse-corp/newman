from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from backend.sessions.models import SessionMessage, SessionRecord, SessionSummary, utc_now


class SessionStore:
    def __init__(self, sessions_dir: Path):
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create(self, title: str | None = None) -> SessionRecord:
        session_id = uuid4().hex
        session = SessionRecord(
            session_id=session_id,
            title=title or "未命名会话",
        )
        self.save(session)
        return session

    def list(self) -> list[SessionSummary]:
        records = self.list_records()
        items: list[SessionSummary] = []
        for session in records:
            items.append(
                SessionSummary(
                    session_id=session.session_id,
                    title=session.title,
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                    message_count=len(session.messages),
                )
            )
        return items

    def list_records(self) -> list[SessionRecord]:
        items_by_session_id: dict[str, SessionRecord] = {}
        for path in self._all_session_paths():
            record = SessionRecord.model_validate_json(path.read_text(encoding="utf-8"))
            existing = items_by_session_id.get(record.session_id)
            if existing is None or record.updated_at > existing.updated_at:
                items_by_session_id[record.session_id] = record
        items = list(items_by_session_id.values())
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items

    def latest(self, exclude_session_ids: set[str] | None = None, require_messages: bool = False) -> SessionRecord | None:
        excluded = exclude_session_ids or set()
        for session in self.list_records():
            if session.session_id in excluded:
                continue
            if require_messages and not session.messages:
                continue
            return session
        return None

    def get(self, session_id: str) -> SessionRecord:
        path = self._existing_path_for(session_id)
        if path is None:
            raise FileNotFoundError(f"Session not found: {session_id}")
        return SessionRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, session: SessionRecord, touch_updated_at: bool = True) -> None:
        if touch_updated_at:
            session.updated_at = utc_now()
        path = self._path_for(session)
        path.write_text(
            json.dumps(session.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._cleanup_duplicate_paths(session.session_id, keep=path)

    def delete(self, session_id: str) -> None:
        for path in self._matching_paths(session_id):
            path.unlink()
        checkpoint_path = self.sessions_dir / f"{session_id}_checkpoint.json"
        if checkpoint_path.exists():
            checkpoint_path.unlink()

    def append_message(self, session_id: str, message: SessionMessage) -> SessionRecord:
        session = self.get(session_id)
        session.messages.append(message)
        if session.title == "未命名会话" and message.role == "user":
            session.title = message.content[:24] or session.title
        self.save(session)
        return session

    def update_metadata(self, session_id: str, updates: dict[str, object], touch_updated_at: bool = False) -> SessionRecord:
        session = self.get(session_id)
        session.metadata.update(updates)
        self.save(session, touch_updated_at=touch_updated_at)
        return session

    def rename(self, session_id: str, title: str) -> SessionRecord:
        session = self.get(session_id)
        session.title = title.strip() or session.title
        self.save(session)
        return session

    def _all_session_paths(self) -> list[Path]:
        return [
            path
            for path in self.sessions_dir.glob("*.json")
            if not path.name.endswith("_checkpoint.json")
        ]

    def _existing_path_for(self, session_id: str) -> Path | None:
        preferred_matches = sorted(self.sessions_dir.glob(f"*_{session_id}.json"))
        if preferred_matches:
            return preferred_matches[-1]
        legacy_path = self.sessions_dir / f"{session_id}.json"
        if legacy_path.exists():
            return legacy_path
        return None

    def _matching_paths(self, session_id: str) -> list[Path]:
        matches: dict[Path, None] = {}
        legacy_path = self.sessions_dir / f"{session_id}.json"
        if legacy_path.exists():
            matches[legacy_path] = None
        for path in self.sessions_dir.glob(f"*_{session_id}.json"):
            matches[path] = None
        return sorted(matches)

    def _cleanup_duplicate_paths(self, session_id: str, keep: Path) -> None:
        for path in self._matching_paths(session_id):
            if path != keep and path.exists():
                path.unlink()

    def _path_for(self, session: SessionRecord) -> Path:
        date_prefix = self._date_prefix(session.created_at)
        return self.sessions_dir / f"{date_prefix}_{session.session_id}.json"

    def _date_prefix(self, created_at: str) -> str:
        if len(created_at) >= 10:
            candidate = created_at[:10]
            if candidate[4:5] == "-" and candidate[7:8] == "-":
                return candidate
        return utc_now()[:10]
