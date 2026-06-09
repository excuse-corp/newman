from __future__ import annotations

import unittest

from backend.runtime.turn_completion import TurnProgressState, final_answer_gate_reason
from backend.tools.result import ToolExecutionResult


class TurnCompletionGateTests(unittest.TestCase):
    def test_blocks_boss_prefixed_action_statement(self) -> None:
        progress = TurnProgressState()

        reason = final_answer_gate_reason(
            "老板，让我先看看这张图片的内容。",
            progress,
        )

        self.assertEqual(reason, "incomplete_action_statement")

    def test_blocks_direct_regeneration_statement(self) -> None:
        progress = TurnProgressState()

        reason = final_answer_gate_reason(
            "JSON格式问题复杂，让我直接用Python重新生成plan.json。",
            progress,
        )

        self.assertEqual(reason, "incomplete_action_statement")

    def test_blocks_future_retry_statement_even_when_it_mentions_failure(self) -> None:
        progress = TurnProgressState()
        progress.record_tool_result(
            ToolExecutionResult(
                success=False,
                tool="terminal",
                action="execute",
                category="runtime_exception",
                summary="terminal 执行异常",
                recovery_class="recoverable",
            )
        )

        reason = final_answer_gate_reason(
            "上次失败是因为命令格式问题，prompt 文本被当成了文件名。这次我用正确格式重试，并传入原图作为参考输入。",
            progress,
        )

        self.assertEqual(reason, "incomplete_action_statement")

    def test_allows_recoverable_failure_summary_when_it_is_a_real_result(self) -> None:
        progress = TurnProgressState()
        progress.record_tool_result(
            ToolExecutionResult(
                success=False,
                tool="terminal",
                action="execute",
                category="runtime_exception",
                summary="DNS 解析失败",
                recovery_class="recoverable",
            )
        )

        reason = final_answer_gate_reason(
            "图片生成失败，原因是 DNS 解析临时失败；当前没有生成输出文件。",
            progress,
        )

        self.assertIsNone(reason)

    def test_diagnostic_success_does_not_clear_unresolved_recoverable_failure(self) -> None:
        progress = TurnProgressState()
        progress.record_tool_result(
            ToolExecutionResult(
                success=False,
                tool="terminal",
                action="execute",
                category="runtime_exception",
                summary="渲染 PPT 失败",
                recovery_class="recoverable",
            )
        )

        progress.record_tool_result(
            ToolExecutionResult(
                success=True,
                tool="terminal",
                action="execute",
                summary="已打印出错误行",
            )
        )

        self.assertTrue(progress.has_unresolved_recoverable_failure)

    def test_output_artifact_success_clears_unresolved_recoverable_failure(self) -> None:
        progress = TurnProgressState()
        progress.record_tool_result(
            ToolExecutionResult(
                success=False,
                tool="terminal",
                action="execute",
                category="runtime_exception",
                summary="渲染 PPT 失败",
                recovery_class="recoverable",
            )
        )

        progress.record_tool_result(
            ToolExecutionResult(
                success=True,
                tool="terminal",
                action="execute",
                summary="重新渲染成功",
                metadata={"output_files": [{"path": "/tmp/demo.pptx"}]},
            )
        )

        self.assertFalse(progress.has_unresolved_recoverable_failure)


if __name__ == "__main__":
    unittest.main()
