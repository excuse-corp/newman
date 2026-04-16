from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.middleware.error_handler import install_error_handlers
from backend.api.routes.workspace import router as workspace_router


def _build_app(settings) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings
    install_error_handlers(app)
    app.include_router(workspace_router)
    return app


class WorkspacePermissionRouteTests(unittest.TestCase):
    def test_workspace_files_can_read_additional_readable_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            readable = root / "backend"
            workspace.mkdir()
            readable.mkdir()
            target = readable / "app.py"
            target.write_text("print('ok')\n", encoding="utf-8")
            settings = SimpleNamespace(
                paths=SimpleNamespace(workspace=workspace, memory_dir=root / "memory"),
                permissions=SimpleNamespace(
                    readable_paths=[readable],
                    writable_paths=[],
                    protected_paths=[],
                ),
            )
            client = TestClient(_build_app(settings))

            response = client.get("/api/workspace/files", params={"path": str(target)})

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["type"], "file")
            self.assertEqual(payload["access"], "readable")
            self.assertIn("print('ok')", payload["content"])

    def test_workspace_file_content_can_stream_readable_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            readable = root / "backend_data" / "uploads"
            workspace.mkdir()
            readable.mkdir(parents=True)
            target = readable / "screen.png"
            target.write_bytes(b"\x89PNG\r\n\x1a\nmock")
            settings = SimpleNamespace(
                paths=SimpleNamespace(workspace=workspace, memory_dir=root / "memory"),
                permissions=SimpleNamespace(
                    readable_paths=[readable],
                    writable_paths=[],
                    protected_paths=[],
                ),
            )
            client = TestClient(_build_app(settings))

            response = client.get("/api/workspace/file-content", params={"path": str(target)})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"\x89PNG\r\n\x1a\nmock")
            self.assertIn("inline", response.headers.get("content-disposition", ""))

    def test_workspace_files_rejects_protected_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            protected = root / ".env"
            workspace.mkdir()
            protected.write_text("SECRET=1\n", encoding="utf-8")
            settings = SimpleNamespace(
                paths=SimpleNamespace(workspace=workspace, memory_dir=root / "memory"),
                permissions=SimpleNamespace(
                    readable_paths=[],
                    writable_paths=[],
                    protected_paths=[protected],
                ),
            )
            client = TestClient(_build_app(settings))

            response = client.get("/api/workspace/files", params={"path": str(protected)})

            self.assertEqual(response.status_code, 400)

    def test_workspace_roots_returns_permission_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            readable = root / "docs"
            writable = root / "skills"
            protected = root / ".env"
            workspace.mkdir()
            readable.mkdir()
            writable.mkdir()
            protected.write_text("SECRET=1\n", encoding="utf-8")
            settings = SimpleNamespace(
                paths=SimpleNamespace(workspace=workspace, memory_dir=root / "memory"),
                permissions=SimpleNamespace(
                    readable_paths=[readable],
                    writable_paths=[writable],
                    protected_paths=[protected],
                ),
            )
            client = TestClient(_build_app(settings))

            response = client.get("/api/workspace/roots")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["workspace"], str(workspace))
            self.assertIn(str(readable), payload["readable_roots"])
            self.assertIn(str(writable), payload["writable_roots"])
            self.assertIn(str(protected), payload["protected_roots"])


if __name__ == "__main__":
    unittest.main()
