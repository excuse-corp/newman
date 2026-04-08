from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.sessions.session_store import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_rename_updates_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(Path(tmp))
            session = store.create(title="old title")

            renamed = store.rename(session.session_id, "new title")

            self.assertEqual(renamed.title, "new title")
            self.assertEqual(store.get(session.session_id).title, "new title")


if __name__ == "__main__":
    unittest.main()
