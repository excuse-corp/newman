from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from backend.tools.impl.read_file import MAX_INLINE_READ_BYTES, MAX_RANGE_LINES, ReadFileRangeTool, ReadFileTool


class ReadFileToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_text_file_as_plain_text_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.txt"
            content = "alpha\nbeta\ngamma\ndelta\n"
            target.write_text(content, encoding="utf-8")

            result = await ReadFileTool(root).run({"path": "demo.txt"}, "session-1")

            self.assertTrue(result.success)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["content"], content)
            self.assertEqual(payload["encoding"], "utf-8")
            self.assertFalse(payload["binary"])
            self.assertNotIn("dataBase64", payload)
            self.assertEqual(
                result.metadata,
                {
                    "path": str(target),
                    "size_bytes": len(content.encode("utf-8")),
                },
            )
            self.assertIn("\"contentPersisted\":false", result.persisted_output)
            self.assertIn("\"mode\":\"full_text\"", result.persisted_output)
            self.assertNotIn(content, result.persisted_output)

    async def test_reads_utf8_non_ascii_text_as_plain_text_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "cn.md"
            content = "你好，Newman\n用于处理真实任务\n"
            target.write_text(content, encoding="utf-8")

            result = await ReadFileTool(root).run({"path": "cn.md"}, "session-2")

            self.assertTrue(result.success)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["content"], content)
            self.assertEqual(payload["encoding"], "utf-8")
            self.assertEqual(result.metadata["path"], str(target))

    async def test_reads_binary_file_as_complete_base64_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "image.bin"
            content = b"\x00\x01\x02binary\xffpayload"
            target.write_bytes(content)

            result = await ReadFileTool(root).run({"path": "image.bin"}, "session-3")

            self.assertTrue(result.success)
            payload = json.loads(result.stdout)
            self.assertEqual(base64.b64decode(payload["dataBase64"]), content)
            self.assertEqual(payload["encoding"], "base64")
            self.assertTrue(payload["binary"])
            self.assertIn("do not use terminal", payload["note"])
            self.assertEqual(result.metadata["size_bytes"], len(content))
            self.assertIn("\"mode\":\"full_base64\"", result.persisted_output)

    async def test_reads_empty_file_as_empty_text_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "empty.txt"
            target.write_text("", encoding="utf-8")

            result = await ReadFileTool(root).run({"path": "empty.txt"}, "session-4")

            self.assertTrue(result.success)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["content"], "")
            self.assertEqual(payload["encoding"], "utf-8")
            self.assertFalse(payload["binary"])
            self.assertEqual(result.metadata["path"], str(target))
            self.assertEqual(result.metadata["size_bytes"], 0)

    async def test_reads_non_utf8_file_as_base64_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "latin1.txt"
            content = "caf\xe9".encode("latin-1")
            target.write_bytes(content)

            result = await ReadFileTool(root).run({"path": "latin1.txt"}, "session-4b")

            self.assertTrue(result.success)
            payload = json.loads(result.stdout)
            self.assertEqual(base64.b64decode(payload["dataBase64"]), content)
            self.assertEqual(payload["encoding"], "base64")
            self.assertTrue(payload["binary"])

    async def test_rejects_directory_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "folder"
            target.mkdir()

            result = await ReadFileTool(root).run({"path": "folder"}, "session-5")

            self.assertFalse(result.success)
            self.assertEqual(result.category, "validation_error")
            self.assertEqual(result.summary, "path 必须是文件")

    async def test_rejects_large_file_and_points_to_range_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "big.txt"
            target.write_text("a" * (MAX_INLINE_READ_BYTES + 1), encoding="utf-8")

            result = await ReadFileTool(root).run({"path": "big.txt"}, "session-6")

            self.assertFalse(result.success)
            self.assertEqual(result.category, "validation_error")
            self.assertIn("read_file_range(path, offset, limit)", result.summary)
            self.assertEqual(result.metadata["size_bytes"], MAX_INLINE_READ_BYTES + 1)


class ReadFileRangeToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_requested_line_range_from_text_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.txt"
            target.write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")

            result = await ReadFileRangeTool(root).run({"path": "demo.txt", "offset": 2, "limit": 2}, "session-7")

            self.assertTrue(result.success)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["startLine"], 2)
            self.assertEqual(payload["endLine"], 3)
            self.assertEqual(payload["returnedLines"], 2)
            self.assertEqual(payload["nextOffset"], 4)
            self.assertFalse(payload["eof"])
            self.assertEqual(payload["content"], "2: beta\n3: gamma")
            self.assertIn("\"contentPersisted\":false", result.persisted_output)
            self.assertNotIn("2: beta", result.persisted_output)

    async def test_rejects_binary_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "image.bin"
            target.write_bytes(b"\x00\x01\xffbinary")

            result = await ReadFileRangeTool(root).run({"path": "image.bin", "offset": 1, "limit": 10}, "session-8")

            self.assertFalse(result.success)
            self.assertEqual(result.category, "validation_error")
            self.assertIn("仅支持 UTF-8 文本文件", result.summary)

    async def test_rejects_limit_above_chunk_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.txt"
            target.write_text("alpha\nbeta\n", encoding="utf-8")

            result = await ReadFileRangeTool(root).run(
                {"path": "demo.txt", "offset": 1, "limit": MAX_RANGE_LINES + 1},
                "session-9",
            )

            self.assertFalse(result.success)
            self.assertEqual(result.category, "validation_error")
            self.assertEqual(result.summary, f"limit 不能超过 {MAX_RANGE_LINES} 行")


if __name__ == "__main__":
    unittest.main()
