from __future__ import annotations

import ast
import json
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from backend.config.schema import ModelConfig
from backend.providers.base import BaseProvider


ALLOWED_UPLOAD_SUFFIXES = {".md", ".py", ".jpg", ".jpeg", ".png"}
MAX_UPLOAD_FILES = 200
MAX_UPLOAD_FILE_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_TOTAL_BYTES = 80 * 1024 * 1024
SKILL_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")

COMMON_IMPORT_PACKAGES = {
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "docx": "python-docx",
    "fitz": "pymupdf",
    "numpy": "numpy",
    "openpyxl": "openpyxl",
    "pandas": "pandas",
    "PIL": "Pillow",
    "pptx": "python-pptx",
    "pydantic": "pydantic",
    "requests": "requests",
    "yaml": "pyyaml",
}


@dataclass(frozen=True)
class UploadedSkillFile:
    filename: str
    content: bytes


@dataclass
class SkillImportReport:
    mode: str = "upload"
    optimizer: str = "deterministic"
    source_files: list[str] = field(default_factory=list)
    normalized_files: list[str] = field(default_factory=list)
    generated_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skill_directory: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "optimizer": self.optimizer,
            "source_files": self.source_files,
            "normalized_files": self.normalized_files,
            "generated_files": self.generated_files,
            "warnings": self.warnings,
            "skill_directory": self.skill_directory,
            "file_count": len(self.source_files),
        }


class SkillImportLoader:
    """Normalize uploaded files into a Newman-compatible skill directory."""

    def __init__(self, provider: BaseProvider | None = None, provider_config: ModelConfig | None = None):
        self.provider = provider
        self.provider_config = provider_config

    async def prepare_upload(
        self,
        files: list[UploadedSkillFile],
        staging_dir: Path,
        *,
        requested_name: str | None = None,
        optimize_with_llm: bool = True,
    ) -> tuple[Path, SkillImportReport]:
        report = SkillImportReport()
        upload_root = staging_dir / "upload"
        normalized_parent = staging_dir / "normalized"
        upload_root.mkdir(parents=True, exist_ok=True)
        normalized_parent.mkdir(parents=True, exist_ok=True)

        report.source_files = _write_upload_files(files, upload_root)
        input_root = _select_input_root(upload_root)
        skill_content, metadata, source_skill_path = _build_skill_content(input_root, requested_name, report)
        skill_name = _normalize_skill_name(requested_name or metadata.get("name") or input_root.name)
        metadata["name"] = skill_name
        normalized_root = normalized_parent / skill_name
        normalized_root.mkdir(parents=True, exist_ok=True)

        copied_files = _copy_resources(input_root, normalized_root, source_skill_path, report)
        skill_content = _render_skill_markdown(
            content=skill_content,
            metadata=metadata,
            copied_files=copied_files,
            report=report,
        )
        skill_content, optimizer = await self._maybe_optimize_skill_markdown(
            skill_content,
            copied_files,
            report,
            optimize_with_llm=optimize_with_llm,
        )
        report.optimizer = optimizer

        script_paths = sorted(path for path in normalized_root.rglob("*.py") if path.is_file())
        if script_paths:
            wrapper_path = _write_python_runtime_files(normalized_root, script_paths, report)
            skill_content = _ensure_python_runtime_section(skill_content, wrapper_path)

        skill_path = normalized_root / "SKILL.md"
        skill_path.write_text(skill_content.rstrip() + "\n", encoding="utf-8")
        _refresh_normalized_files(normalized_root, report)
        report.skill_directory = str(normalized_root)
        return normalized_root, report

    async def _maybe_optimize_skill_markdown(
        self,
        content: str,
        copied_files: list[Path],
        report: SkillImportReport,
        *,
        optimize_with_llm: bool,
    ) -> tuple[str, str]:
        if not optimize_with_llm or self.provider is None or self.provider_config is None:
            return content, "deterministic"
        if self.provider_config.type == "mock":
            return content, "deterministic"

        inventory = [path.as_posix() for path in copied_files]
        try:
            response = await self.provider.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是 Newman 的 Skill 装载器。只返回 JSON 对象，不要输出 markdown 代码块。"
                            "目标是改写 SKILL.md 正文，让它简洁、程序化，并兼容 Newman skill 体系。"
                            "不要更改 frontmatter 中的 name。不要删除资源文件引用。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "current_skill_md": content,
                                "resource_inventory": inventory,
                                "required_frontmatter": ["name", "description", "when_to_use"],
                                "response_schema": {
                                    "description": "short capability summary",
                                    "when_to_use": "plain trigger scenario",
                                    "body_markdown": "SKILL.md body without YAML frontmatter",
                                },
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                tools=[],
                temperature=0.1,
                max_tokens=2200,
            )
            payload = _parse_llm_json_object(response.content)
            frontmatter, body = _split_frontmatter(content)
            metadata = _parse_frontmatter(frontmatter)
            description = _clean_llm_string(payload.get("description")) or str(metadata.get("description") or "")
            when_to_use = _clean_llm_string(payload.get("when_to_use")) or str(metadata.get("when_to_use") or "")
            body_markdown = _clean_llm_string(payload.get("body_markdown"))
            if not body_markdown:
                raise ValueError("LLM response missing body_markdown")
            next_content = _compose_skill_markdown(
                {
                    "name": str(metadata.get("name") or "imported-skill"),
                    "description": description,
                    "when_to_use": when_to_use,
                },
                body_markdown,
            )
            return next_content, "llm"
        except Exception as exc:  # pragma: no cover - network/model failures are non-deterministic
            report.warnings.append(f"LLM 优化未完成，已使用确定性装载结果：{exc}")
            return content, "deterministic"


def _write_upload_files(files: list[UploadedSkillFile], upload_root: Path) -> list[str]:
    if not files:
        raise ValueError("请至少上传一个 Skill 文件")
    if len(files) > MAX_UPLOAD_FILES:
        raise ValueError(f"一次最多上传 {MAX_UPLOAD_FILES} 个 Skill 文件")

    total_bytes = 0
    seen: set[str] = set()
    written: list[str] = []
    rejected: list[str] = []

    for item in files:
        relative_path = _safe_upload_relative_path(item.filename)
        suffix = Path(relative_path.name).suffix.lower()
        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            rejected.append(str(relative_path))
            continue
        if len(item.content) == 0:
            raise ValueError(f"《{relative_path.name}》为空文件，无法导入为 Skill")
        if len(item.content) > MAX_UPLOAD_FILE_BYTES:
            raise ValueError(f"《{relative_path.name}》超过 20MB，无法导入为 Skill")
        total_bytes += len(item.content)
        if total_bytes > MAX_UPLOAD_TOTAL_BYTES:
            raise ValueError("本次 Skill 上传总大小超过 80MB")

        key = relative_path.as_posix().lower()
        if key in seen:
            raise ValueError(f"上传文件路径重复：{relative_path}")
        seen.add(key)

        target = upload_root / Path(*relative_path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.content)
        written.append(relative_path.as_posix())

    if rejected:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_SUFFIXES))
        raise ValueError(f"不支持的 Skill 上传文件：{', '.join(rejected)}；仅支持 {allowed}")
    if not written:
        raise ValueError("没有可导入的 Skill 文件")
    return written


def _safe_upload_relative_path(filename: str) -> PurePosixPath:
    normalized = (filename or "uploaded").replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError(f"上传文件路径无效：{filename}")
    path = PurePosixPath(*parts)
    if path.is_absolute() or any(part.startswith("..") for part in path.parts):
        raise ValueError(f"上传文件路径无效：{filename}")
    return path


def _select_input_root(upload_root: Path) -> Path:
    children = [item for item in upload_root.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return upload_root


def _build_skill_content(
    input_root: Path,
    requested_name: str | None,
    report: SkillImportReport,
) -> tuple[str, dict[str, str], Path | None]:
    skill_candidates = sorted(path for path in input_root.rglob("*") if path.is_file() and path.name.lower() == "skill.md")
    root_candidate = input_root / "SKILL.md"
    if root_candidate.exists():
        source_skill_path: Path | None = root_candidate
    else:
        source_skill_path = skill_candidates[0] if skill_candidates else None
        if len(skill_candidates) > 1:
            report.warnings.append(f"检测到多个 SKILL.md，仅使用 {source_skill_path.relative_to(input_root).as_posix()}")

    if source_skill_path is not None:
        raw_content = source_skill_path.read_text(encoding="utf-8", errors="replace")
        frontmatter, body = _split_frontmatter(raw_content)
        metadata = _parse_frontmatter(frontmatter)
        if requested_name:
            metadata["name"] = requested_name
        if not metadata.get("description"):
            metadata["description"] = _extract_summary(body) or f"Imported Newman skill for {metadata.get('name') or input_root.name}."
        if not metadata.get("when_to_use"):
            metadata["when_to_use"] = _default_when_to_use(str(metadata.get("name") or input_root.name))
        return body.strip() or "# Workflow\n\n- Inspect the uploaded resources before acting.", metadata, source_skill_path

    markdown_files = sorted(path for path in input_root.rglob("*.md") if path.is_file())
    source_markdown = markdown_files[0] if markdown_files else None
    source_body = (
        source_markdown.read_text(encoding="utf-8", errors="replace").strip()
        if source_markdown is not None
        else "# Workflow\n\n- Inspect the bundled resources before acting."
    )
    raw_name = requested_name or (source_markdown.stem if source_markdown else input_root.name)
    metadata = {
        "name": raw_name,
        "description": _extract_summary(source_body) or f"Imported Newman skill for {raw_name}.",
        "when_to_use": _default_when_to_use(raw_name),
    }
    report.warnings.append("上传内容未包含 SKILL.md，已基于 Markdown 内容生成 Newman skill 入口。")
    return source_body, metadata, source_markdown


def _copy_resources(
    input_root: Path,
    normalized_root: Path,
    source_skill_path: Path | None,
    report: SkillImportReport,
) -> list[Path]:
    copied: list[Path] = []
    for source in sorted(path for path in input_root.rglob("*") if path.is_file()):
        if source_skill_path is not None and source.resolve() == source_skill_path.resolve():
            continue
        suffix = source.suffix.lower()
        relative = source.relative_to(input_root)
        if suffix == ".md":
            target_relative = _resource_relative_path(relative, "references", preserve_roots={"references", "templates"})
        elif suffix == ".py":
            target_relative = _resource_relative_path(relative, "scripts", preserve_roots={"scripts"})
        elif suffix in {".jpg", ".jpeg", ".png"}:
            target_relative = _resource_relative_path(relative, "assets", preserve_roots={"assets"})
        else:
            continue

        target = _unique_target(normalized_root, target_relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target.relative_to(normalized_root))
    return copied


def _resource_relative_path(relative: Path, default_root: str, *, preserve_roots: set[str]) -> Path:
    parts = tuple(_sanitize_path_part(part) for part in relative.parts)
    if parts and parts[0].lower() in preserve_roots:
        return Path(*parts)
    return Path(default_root, *parts)


def _unique_target(root: Path, relative: Path) -> Path:
    target = root / relative
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    for index in range(2, 1000):
        candidate = target.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError(f"无法生成不冲突的资源文件名：{relative}")


def _render_skill_markdown(
    *,
    content: str,
    metadata: dict[str, str],
    copied_files: list[Path],
    report: SkillImportReport,
) -> str:
    name = _normalize_skill_name(metadata.get("name") or "imported-skill")
    description = str(metadata.get("description") or f"Imported Newman skill for {name}.").strip()
    when_to_use = str(metadata.get("when_to_use") or _default_when_to_use(name)).strip()
    body = content.strip()
    if not body.startswith("#"):
        body = f"# {name}\n\n{body}"
    body = _ensure_core_sections(body)
    body = _ensure_resource_inventory_section(body, copied_files)
    report.warnings.extend(_compatibility_warnings(body, copied_files))
    return _compose_skill_markdown(
        {
            "name": name,
            "description": description,
            "when_to_use": when_to_use,
        },
        body,
    )


def _compose_skill_markdown(metadata: dict[str, str], body: str) -> str:
    frontmatter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).strip()
    return f"---\n{frontmatter}\n---\n\n{body.strip()}\n"


def _ensure_core_sections(body: str) -> str:
    lowered = body.lower()
    sections: list[str] = []
    if "## goal" not in lowered and "## 目标" not in body:
        sections.append("## Goal\n\nUse this skill to apply the uploaded workflow and bundled resources.")
    if "## workflow" not in lowered and "## 工作流" not in body and "## 流程" not in body:
        sections.append("## Workflow\n\n1. Read `SKILL.md` first.\n2. Inspect only the bundled resources needed for the task.\n3. Use scripts through the documented entrypoints when deterministic execution is needed.")
    if "## constraints" not in lowered and "## 约束" not in body and "## 限制" not in body:
        sections.append("## Constraints\n\n- Keep changes scoped to the user's request.\n- Do not load large bundled files unless they are directly relevant.")
    if not sections:
        return body
    return body.rstrip() + "\n\n" + "\n\n".join(sections)


def _ensure_resource_inventory_section(body: str, copied_files: list[Path]) -> str:
    if not copied_files:
        return body
    if "## bundled resources" in body.lower() or "## 资源" in body:
        return body
    lines = ["## Bundled Resources", ""]
    for relative in sorted(path.as_posix() for path in copied_files):
        lines.append(f"- `{relative}`")
    return body.rstrip() + "\n\n" + "\n".join(lines)


def _ensure_python_runtime_section(content: str, wrapper_path: Path) -> str:
    frontmatter, body = _split_frontmatter(content)
    if "python runtime" in body.lower() or ".venv" in body:
        return content
    section = textwrap.dedent(
        f"""
        ## Python Runtime

        - Run bundled Python scripts through `python {wrapper_path.as_posix()} scripts/<script>.py` from the skill root.
        - The wrapper creates `<skill-root>/.venv`, installs `requirements.txt`, and runs the target script with the skill-local interpreter.
        - Do not commit or copy the generated `.venv` directory.
        """
    ).strip()
    return _with_body(frontmatter, body.rstrip() + "\n\n" + section)


def _write_python_runtime_files(normalized_root: Path, script_paths: list[Path], report: SkillImportReport) -> Path:
    scripts_dir = normalized_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    wrapper_path = _unique_target(normalized_root, Path("scripts/run_python.py"))
    wrapper_relative = wrapper_path.relative_to(normalized_root)
    wrapper_path.write_text(_python_wrapper_source(wrapper_relative.as_posix()), encoding="utf-8")

    local_modules = {path.stem for path in script_paths}
    detected_packages, unknown_imports = _detect_third_party_imports(script_paths, local_modules)
    requirements_path = normalized_root / "requirements.txt"
    requirements_lines = [
        "# Generated by Newman skill loader.",
        "# Keep third-party Python packages for this skill here.",
    ]
    requirements_lines.extend(sorted(detected_packages))
    if unknown_imports:
        requirements_lines.append(f"# Review imports and add packages if needed: {', '.join(sorted(unknown_imports))}")
        report.warnings.append(f"检测到未确认的 Python 依赖：{', '.join(sorted(unknown_imports))}")
    requirements_path.write_text("\n".join(requirements_lines).rstrip() + "\n", encoding="utf-8")

    report.generated_files.extend([wrapper_relative.as_posix(), "requirements.txt"])
    return wrapper_relative


def _python_wrapper_source(wrapper_display_path: str) -> str:
    source = textwrap.dedent(
        """
        from __future__ import annotations

        import os
        import subprocess
        import sys
        from pathlib import Path


        def main() -> None:
            skill_root = Path(__file__).resolve().parents[1]
            if len(sys.argv) < 2:
                raise SystemExit("usage: python __WRAPPER_DISPLAY_PATH__ scripts/<script>.py [args...]")

            target = (skill_root / sys.argv[1]).resolve()
            if not target.is_file() or not target.is_relative_to(skill_root):
                raise SystemExit(f"script must be inside this skill: {sys.argv[1]}")

            venv_dir = skill_root / ".venv"
            python_bin = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            if not python_bin.exists():
                subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])

            requirements = skill_root / "requirements.txt"
            if requirements.exists() and requirements.read_text(encoding="utf-8", errors="replace").strip():
                subprocess.check_call([str(python_bin), "-m", "pip", "install", "-r", str(requirements)])

            os.execv(str(python_bin), [str(python_bin), str(target), *sys.argv[2:]])


        if __name__ == "__main__":
            main()
        """
    ).lstrip()
    return source.replace("__WRAPPER_DISPLAY_PATH__", wrapper_display_path)


def _detect_third_party_imports(script_paths: list[Path], local_modules: set[str]) -> tuple[set[str], set[str]]:
    stdlib = getattr(sys, "stdlib_module_names", set())
    detected_packages: set[str] = set()
    unknown_imports: set[str] = set()
    for path in script_paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            module_name: str | None = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split(".", 1)[0]
                    _classify_import(module_name, local_modules, stdlib, detected_packages, unknown_imports)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                module_name = node.module.split(".", 1)[0]
                _classify_import(module_name, local_modules, stdlib, detected_packages, unknown_imports)
    return detected_packages, unknown_imports


def _classify_import(
    module_name: str,
    local_modules: set[str],
    stdlib: set[str],
    detected_packages: set[str],
    unknown_imports: set[str],
) -> None:
    if not module_name or module_name in local_modules or module_name in stdlib or module_name == "__future__":
        return
    if module_name in COMMON_IMPORT_PACKAGES:
        detected_packages.add(COMMON_IMPORT_PACKAGES[module_name])
    else:
        unknown_imports.add(module_name)


def _refresh_normalized_files(normalized_root: Path, report: SkillImportReport) -> None:
    report.normalized_files = [
        path.relative_to(normalized_root).as_posix()
        for path in sorted(normalized_root.rglob("*"))
        if path.is_file()
    ]


def _compatibility_warnings(body: str, copied_files: list[Path]) -> list[str]:
    warnings: list[str] = []
    if len(body.splitlines()) > 500:
        warnings.append("SKILL.md 超过 500 行，建议继续拆分到 references/。")
    if any(path.parts and path.parts[0] == "references" for path in copied_files) and "references/" not in body:
        warnings.append("已添加 references/ 文件，请在使用时按需读取，避免一次性加载全部资源。")
    return warnings


def _parse_llm_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM response is not JSON")
    payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM response JSON must be an object")
    return payload


def _clean_llm_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _split_frontmatter(content: str) -> tuple[str | None, str]:
    normalized = content.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return None, normalized
    end = normalized.find("\n---\n", 4)
    if end == -1:
        return None, normalized
    return normalized[4:end], normalized[end + 5 :]


def _parse_frontmatter(frontmatter: str | None) -> dict[str, str]:
    if not frontmatter:
        return {}
    try:
        payload = yaml.safe_load(frontmatter) or {}
    except yaml.YAMLError:
        return {}
    if not isinstance(payload, dict):
        return {}
    metadata: dict[str, str] = {}
    for key in ("name", "description", "when_to_use"):
        raw = payload.get(key, payload.get("when-to-use") if key == "when_to_use" else None)
        if isinstance(raw, str) and raw.strip():
            metadata[key] = raw.strip()
    return metadata


def _with_body(frontmatter: str | None, body: str) -> str:
    if frontmatter:
        return f"---\n{frontmatter.strip()}\n---\n\n{body.strip()}\n"
    return body.strip() + "\n"


def _extract_summary(body: str) -> str:
    for raw_line in body.splitlines():
        text = raw_line.strip().strip("#").strip("-*0123456789. ")
        if text:
            return text[:160]
    return ""


def _default_when_to_use(name: str) -> str:
    return f"Use when the user asks for work related to {name}."


def _normalize_skill_name(raw_name: str) -> str:
    normalized = SKILL_NAME_RE.sub("-", raw_name.strip().lower()).strip("-_")
    return normalized or "imported-skill"


def _sanitize_path_part(part: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", part.strip()).strip("-")
    return cleaned or "file"
