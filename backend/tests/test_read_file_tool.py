from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.tools.impl.read_file import DEFAULT_PREVIEW_BYTES, MAX_TEXT_LINE_CHARS, ReadFileTool


class ReadFileToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_text_file_with_line_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.txt"
            target.write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")

            result = await ReadFileTool(root).run({"path": "demo.txt", "offset": 2, "limit": 2}, "session-1")

            self.assertTrue(result.success)
            self.assertEqual(result.stdout, "L2: beta\nL3: gamma")
            self.assertEqual(
                result.metadata,
                {
                    "path": str(target),
                    "binary": False,
                    "offset": 2,
                    "limit": 2,
                    "returned_lines": 2,
                    "start_line": 2,
                    "end_line": 3,
                    "truncated": True,
                    "next_offset": 4,
                    "line_char_limit": MAX_TEXT_LINE_CHARS,
                },
            )

    async def test_returns_validation_error_when_offset_exceeds_text_length(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "demo.txt").write_text("alpha\nbeta\n", encoding="utf-8")

            result = await ReadFileTool(root).run({"path": "demo.txt", "offset": 4, "limit": 1}, "session-2")

            self.assertFalse(result.success)
            self.assertEqual(result.category, "validation_error")
            self.assertEqual(result.summary, "offset 超出文件总行数")

    async def test_reads_empty_text_file_successfully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "empty.txt"
            target.write_text("", encoding="utf-8")

            result = await ReadFileTool(root).run({"path": "empty.txt"}, "session-3")

            self.assertTrue(result.success)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.metadata["path"], str(target))
            self.assertEqual(result.metadata["returned_lines"], 0)
            self.assertFalse(result.metadata["truncated"])

    async def test_truncates_long_text_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            long_line = "x" * (MAX_TEXT_LINE_CHARS + 25)
            (root / "long.txt").write_text(f"{long_line}\nshort\n", encoding="utf-8")

            result = await ReadFileTool(root).run({"path": "long.txt", "limit": 1}, "session-4")

            self.assertTrue(result.success)
            self.assertEqual(result.stdout, f"L1: {'x' * MAX_TEXT_LINE_CHARS}")

    async def test_keeps_binary_preview_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "image.bin"
            target.write_bytes(b"\x00\x01\x02" + b"x" * 32)

            result = await ReadFileTool(root).run({"path": "image.bin", "max_bytes": 8}, "session-5")

            self.assertTrue(result.success)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["binary"])
            self.assertEqual(payload["preview_bytes"], 8)
            self.assertEqual(payload["size_bytes"], 35)
            self.assertTrue(payload["truncated"])

    async def test_uses_default_limit_for_text_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.txt"
            target.write_text("alpha\nbeta\n", encoding="utf-8")

            result = await ReadFileTool(root).run({"path": "demo.txt", "max_bytes": DEFAULT_PREVIEW_BYTES}, "session-6")

            self.assertTrue(result.success)
            self.assertEqual(result.stdout, "L1: alpha\nL2: beta")


if __name__ == "__main__":
    unittest.main()
