from __future__ import annotations

from .draft_models import PluginRiskReport, PluginSpec


def assess_plugin_risk(spec: PluginSpec) -> PluginRiskReport:
    reasons: list[str] = []
    level = "low"

    if spec.commands:
        level = "medium"
        reasons.append("插件会注册外部 CLI wrapper tools")
    if any(command.approval_behavior == "confirmable" for command in spec.commands):
        level = "high"
        reasons.append("至少一个命令会修改外部状态并要求运行时确认")
    if any(command.writable_roots for command in spec.commands):
        level = "high"
        reasons.append("插件声明了可写目录")
    if any(command.readable_roots for command in spec.commands):
        level = "high" if level in {"low", "medium"} else level
    if any(command.readable_roots for command in spec.commands):
        reasons.append("插件声明了额外可读目录")
    if not spec.skills and not spec.commands:
        reasons.append("插件没有声明可用能力")

    return PluginRiskReport(
        level=level,
        reasons=reasons,
        requires_user_confirmation=level in {"high", "critical"},
        blocked=level == "critical",
    )
