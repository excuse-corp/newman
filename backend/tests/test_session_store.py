from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.sessions.models import SessionRecord
from backend.sessions.session_store import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_create_uses_created_date_in_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SessionStore(root)

            session = store.create(title="dated title")

            expected_path = root / f"{session.created_at[:10]}_{session.session_id}.json"
            self.assertTrue(expected_path.exists())

    def test_get_reads_legacy_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SessionStore(root)
            session = SessionRecord(session_id="legacy-session", title="legacy title")
            legacy_path = root / f"{session.session_id}.json"
            legacy_path.write_text(
                json.dumps(session.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            loaded = store.get(session.session_id)

            self.assertEqual(loaded.session_id, session.session_id)
            self.assertEqual(loaded.title, session.title)

    def test_save_migrates_legacy_filename_to_dated_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SessionStore(root)
            session = SessionRecord(session_id="legacy-session", title="legacy title")
            legacy_path = root / f"{session.session_id}.json"
            legacy_path.write_text(
                json.dumps(session.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            renamed = store.rename(session.session_id, "new title")

            dated_path = root / f"{session.created_at[:10]}_{session.session_id}.json"
            self.assertEqual(renamed.title, "new title")
            self.assertFalse(legacy_path.exists())
            self.assertTrue(dated_path.exists())

    def test_rename_updates_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(Path(tmp))
            session = store.create(title="old title")

            renamed = store.rename(session.session_id, "new title")

            self.assertEqual(renamed.title, "new title")
            self.assertEqual(store.get(session.session_id).title, "new title")


if __name__ == "__main__":
    unittest.main()
