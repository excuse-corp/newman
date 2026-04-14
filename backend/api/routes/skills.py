from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.tools.workspace_fs import build_path_access_policy, ensure_readable_path


router = APIRouter(prefix="/api/skills", tags=["skills"])


class ImportSkillRequest(BaseModel):
    source_path: str = Field(..., min_length=1, description="可读目录内待导入的 skill 文件夹路径")


class UpdateSkillRequest(BaseModel):
    content: str = Field(..., min_length=0)


@router.get("")
async def list_skills(request: Request):
    runtime = request.app.state.runtime
    runtime.skill_registry.sync_snapshot()
    return {"skills": [item.model_dump(mode="json") for item in runtime.skill_registry.list_skills()]}


@router.post("/import")
async def import_skill(payload: ImportSkillRequest, request: Request):
    runtime = request.app.state.runtime
    policy = build_path_access_policy(request.app.state.settings)
    source_dir = ensure_readable_path(policy, payload.source_path)
    try:
        skill = runtime.plugin_service.import_system_skill(source_dir)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    runtime.reload_ecosystem()
    return {"skill": _build_skill_detail(runtime, skill.name)}


@router.get("/{skill_name}")
async def get_skill(skill_name: str, request: Request):
    runtime = request.app.state.runtime
    return {"skill": _build_skill_detail(runtime, skill_name)}


@router.put("/{skill_name}")
async def update_skill(skill_name: str, payload: UpdateSkillRequest, request: Request):
    runtime = request.app.state.runtime
    try:
        skill = runtime.plugin_service.update_system_skill(skill_name, payload.content)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    runtime.reload_ecosystem()
    return {"skill": _build_skill_detail(runtime, skill.name)}


@router.delete("/{skill_name}")
async def delete_skill(skill_name: str, request: Request):
    runtime = request.app.state.runtime
    try:
        skill = runtime.plugin_service.delete_system_skill(skill_name)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    runtime.reload_ecosystem()
    return {"deleted": True, "skill_name": skill.name}


def _build_skill_detail(runtime, skill_name: str) -> dict:
    skill = runtime.plugin_service.get_skill(skill_name)
    content = runtime.plugin_service.read_skill_content(skill)
    tool_names = [tool.meta.name for tool in runtime.registry.list_tools()]
    return {
        **skill.model_dump(mode="json"),
        "content": content,
        "readonly": skill.source != "system",
        "available": True,
        "tool_dependencies": _extract_tool_dependencies(content, tool_names),
        "usage_limits_summary": _extract_usage_limits_summary(content),
        "directory_path": str(Path(skill.path).parent),
    }


def _extract_tool_dependencies(content: str, tool_names: list[str]) -> list[str]:
    matches: list[str] = []
    for tool_name in sorted(set(tool_names), key=len, reverse=True):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(tool_name)}(?![A-Za-z0-9_])"
        if re.search(pattern, content):
            matches.append(tool_name)
    return sorted(matches)


def _extract_usage_limits_summary(content: str) -> str:
    lines = content.splitlines()
    collected: list[str] = []
    in_constraints = False

    for raw_line in lines:
        stripped = raw_line.strip()
        lowered = stripped.lower()
        if stripped.startswith("#"):
            in_constraints = "constraint" in lowered or "限制" in stripped or "约束" in stripped
            continue
        if in_constraints and stripped:
            collected.append(stripped)
            if len(collected) >= 3:
                break

    if not collected:
        for raw_line in lines:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            lowered = stripped.lower()
            if (
                stripped.startswith("- ")
                and (
                    "do not" in lowered
                    or "must" in lowered
                    or "only" in lowered
                    or "不要" in stripped
                    or "必须" in stripped
                    or "仅" in stripped
                )
            ):
                collected.append(stripped)
                if len(collected) >= 3:
                    break

    return " ".join(collected)
