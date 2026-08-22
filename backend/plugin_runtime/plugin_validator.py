from __future__ import annotations

import re
from pathlib import Path

import yaml

from .draft_models import PluginSpec, PluginValidationReport
from .models import PluginManifest
from .plugin_builder import normalize_plugin_name, normalize_skill_name
from .plugin_loader import PluginLoader


TOOL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,63}$")
ENV_REF_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$|^[A-Za-z_][A-Za-z0-9_]*$")


def validate_plugin_spec(spec: PluginSpec) -> PluginValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    checks = ["plugin_spec_schema"]
    try:
        if normalize_plugin_name(spec.name) != spec.name:
            warnings.append("插件名称会被规范化为小写连字符格式")
        skill_names = [normalize_skill_name(skill.name) for skill in spec.skills]
        if len(skill_names) != len(set(skill_names)):
            errors.append("Skill 名称不能重复")
        tool_names = [command.tool_name for command in spec.commands]
        if len(tool_names) != len(set(tool_names)):
            errors.append("Tool 名称不能重复")
        for tool_name in tool_names:
            if not TOOL_NAME_RE.fullmatch(tool_name):
                errors.append(f"非法 Tool 名称: {tool_name}")
        for command in spec.commands:
            for raw_root in [*command.readable_roots, *command.writable_roots]:
                if ".." in Path(raw_root).parts:
                    errors.append(f"插件路径不能包含 ..: {raw_root}")
            for key, value in command.env.items():
                if not ENV_REF_RE.fullmatch(value):
                    errors.append(f"环境变量 {key} 只能引用变量名，不能包含明文值")
        if not spec.skills and not spec.commands:
            errors.append("插件至少需要一个 Skill 或 CLI Tool")
        checks.append("capability_shape")
    except ValueError as exc:
        errors.append(str(exc))
    return PluginValidationReport(ok=not errors, errors=errors, warnings=warnings, checks=checks)


def validate_plugin_package(package_dir: Path, spec: PluginSpec) -> PluginValidationReport:
    report = validate_plugin_spec(spec)
    if not package_dir.exists() or not package_dir.is_dir():
        report.errors.append("插件草稿目录不存在")
        report.ok = False
        return report

    manifest_path = package_dir / "plugin.yaml"
    if not manifest_path.exists():
        report.errors.append("插件目录缺少 plugin.yaml")
        report.ok = False
        return report
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        PluginLoader(package_dir.parent)._validate_manifest_paths(package_dir, PluginManifest.model_validate(manifest))
        report.checks.append("manifest_schema")
    except Exception as exc:
        report.errors.append(f"manifest 校验失败: {exc}")

    for path in package_dir.rglob("*"):
        if path.is_symlink():
            report.errors.append(f"插件不允许包含符号链接: {path.relative_to(package_dir)}")
        if path.is_file() and path.stat().st_size > 200_000:
            report.errors.append(f"插件文件超过 200KB: {path.relative_to(package_dir)}")
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", text):
                report.errors.append(f"检测到私钥内容: {path.relative_to(package_dir)}")
            if re.search(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"][^'\"]{12,}", text):
                report.warnings.append(f"文件可能包含凭据，请人工复核: {path.relative_to(package_dir)}")
    report.checks.append("filesystem_safety")
    report.ok = not report.errors
    return report
