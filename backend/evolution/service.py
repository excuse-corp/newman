from __future__ import annotations

import asyncio
import difflib
import json
import py_compile
import re
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

import yaml

from backend.config.schema import AppConfig, EvolutionConfig, ModelConfig
from backend.evolution.models import EvolutionChange, EvolutionRunRecord, EvolutionTrigger
from backend.evolution.prompts import EVOLUTION_ANALYSIS_PROMPT, SKILL_EDIT_PROMPT
from backend.evolution.store import EvolutionStore
from backend.memory.checkpoint_store import CheckpointStore
from backend.plugin_runtime.models import SkillDescriptor
from backend.plugin_runtime.service import PluginService
from backend.plugin_runtime.skill_parser import parse_skill_file
from backend.providers.base import BaseProvider
from backend.sessions.models import CheckpointRecord, SessionMessage, SessionRecord, utc_now
from backend.sessions.session_store import SessionStore
from backend.skill_runtime.registry import SkillRegistry
from backend.usage.recorder import ModelRequestContext, record_model_usage
from backend.usage.store import PostgresModelUsageStore


AUTO_MEMORY_BEGIN = "<!-- BEGIN AUTO EVOLUTION MEMORY -->"
AUTO_MEMORY_END = "<!-- END AUTO EVOLUTION MEMORY -->"
EMPTY_MEMORY_ITEM = "暂无条目"
TEXT_SKILL_FILENAMES = {"SKILL.md", "README.md", "requirements.txt"}
TEXT_SKILL_SUFFIXES = {
    ".md",
    ".py",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".sh",
    ".js",
    ".ts",
    ".tsx",
    ".css",
    ".html",
    ".htm",
}


class EvolutionService:
    def __init__(
        self,
        *,
        settings: AppConfig,
        provider: BaseProvider,
        model_config: ModelConfig,
        provider_type: str,
        session_store: SessionStore,
        checkpoints: CheckpointStore,
        plugin_service: PluginService,
        skill_registry: SkillRegistry,
        store: EvolutionStore,
        reload_ecosystem,
        usage_store: PostgresModelUsageStore | None = None,
    ):
        self.settings = settings
        self.config: EvolutionConfig = settings.evolution
        self.provider = provider
        self.model_config = model_config
        self.provider_type = provider_type
        self.session_store = session_store
        self.checkpoints = checkpoints
        self.plugin_service = plugin_service
        self.skill_registry = skill_registry
        self.store = store
        self.reload_ecosystem = reload_ecosystem
        self.usage_store = usage_store
        self.memory_path = settings.paths.memory_dir / "MEMORY.md"
        self.user_path = settings.paths.memory_dir / "USER.md"
        self._lock = asyncio.Lock()

    def should_run_for_turn_interval(self, session: SessionRecord) -> bool:
        if not self.config.enabled:
            return False
        user_turn_count = self._user_turn_count(session)
        last_count = _coerce_int(session.metadata.get("evolution_last_user_turn_count")) or 0
        return user_turn_count - last_count >= self.config.turn_interval

    async def run_for_session(self, session_id: str, trigger: EvolutionTrigger) -> EvolutionRunRecord:
        async with self._lock:
            return await self._run_for_session_locked(session_id, trigger)

    async def _run_for_session_locked(self, session_id: str, trigger: EvolutionTrigger) -> EvolutionRunRecord:
        run = EvolutionRunRecord(run_id=uuid4().hex, trigger=trigger, source_session_id=session_id)
        self.store.save_run(run)

        if not self.config.enabled:
            return self._finish_run(run, "skipped", "Evolution is disabled.")
        if self.provider_type == "mock":
            return self._finish_run(run, "skipped", "Mock provider cannot produce structured evolution updates.")

        try:
            session = self.session_store.get(session_id)
        except FileNotFoundError:
            return self._finish_run(run, "skipped", "Session not found.")

        checkpoint = self.checkpoints.get(session_id)
        fingerprint = self._source_fingerprint(session, checkpoint)
        if session.metadata.get("evolution_last_source") == fingerprint:
            return self._finish_run(run, "skipped", "Session source already processed.")

        if trigger == "turn_interval" and not self.should_run_for_turn_interval(session):
            return self._finish_run(run, "skipped", "Turn interval threshold not reached.")

        if not self._has_evolution_context(session, checkpoint):
            self._mark_session_processed(session, fingerprint, trigger, "skipped_short_session")
            return self._finish_run(run, "skipped", "Session has too little context.")

        context = self._build_context(session, checkpoint, trigger)
        run.message_range = list(context["message_range"])
        run.user_turn_count = int(context["user_turn_count"])
        run.metadata["context_message_count"] = len(context["messages"])
        self.store.save_run(run)

        try:
            analysis = await self._analyze_context(context)
        except Exception as exc:
            self._mark_session_processed(session, fingerprint, trigger, "analysis_failed")
            run.errors.append(f"analysis_failed: {exc}")
            return self._finish_run(run, "failed", "Evolution analysis failed.")

        run.metadata["analysis"] = analysis
        self._apply_memory_updates(run, analysis.get("memory_updates"))
        await self._apply_skill_updates(run, analysis.get("skill_update_requests"), context)

        status = self._resolve_run_status(run)
        if status in {"applied", "partial"}:
            run.summary = self._build_run_summary(run)
        elif not run.errors:
            run.summary = str(analysis.get("skip_reason") or "No useful evolution update.")
        self._mark_session_processed(session, fingerprint, trigger, status)
        return self._finish_run(run, status, run.summary)

    async def _analyze_context(self, context: dict[str, Any]) -> dict[str, Any]:
        response = await self.provider.chat(
            [
                {"role": "system", "content": EVOLUTION_ANALYSIS_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "请基于以下材料生成 Newman 自进化更新计划，只输出 JSON。\n\n"
                        f"```json\n{json.dumps(context, ensure_ascii=False, indent=2)}\n```"
                    ),
                },
            ],
            temperature=0.1,
            max_tokens=2400,
        )
        record_model_usage(
            self.usage_store,
            ModelRequestContext(
                request_kind="evolution_analysis",
                model_config=self.model_config,
                provider_type=self.provider_type,
                streaming=False,
                session_id=str(context["session"]["session_id"]),
                metadata={
                    "trigger": context["trigger"],
                    "context_message_count": len(context["messages"]),
                },
            ),
            response,
        )
        payload = _parse_json_object(response.content)
        return payload if isinstance(payload, dict) else {}

    def _apply_memory_updates(self, run: EvolutionRunRecord, raw_updates: Any) -> None:
        updates = self._normalize_memory_updates(raw_updates)
        if not updates:
            return

        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        before = self.memory_path.read_text(encoding="utf-8") if self.memory_path.exists() else "# MEMORY.md\n"
        after, added = _merge_memory_items(before, [item["text"] for item in updates])
        if not added or after == before:
            return

        before_exists, snapshot_path = self.store.save_file_snapshot(run.run_id, self.memory_path)
        self.memory_path.write_text(after, encoding="utf-8")
        added_reasons = [
            item.get("reason", "")
            for item in updates
            if item["text"] in added and item.get("reason")
        ]
        run.changes.append(
            EvolutionChange(
                change_id=uuid4().hex,
                kind="memory_update",
                action="append",
                target_path=str(self.memory_path),
                summary=f"新增 {len(added)} 条经验记忆",
                reason="; ".join(added_reasons[:3]),
                diff=_unified_diff(before, after, str(self.memory_path)),
                before_exists=before_exists,
                snapshot_path=snapshot_path,
                validation_status="passed",
            )
        )

    async def _apply_skill_updates(
        self,
        run: EvolutionRunRecord,
        raw_requests: Any,
        context: dict[str, Any],
    ) -> None:
        requests = self._normalize_skill_requests(raw_requests)
        if not requests:
            return

        for request in requests:
            try:
                skill = self._resolve_skill_request(request)
                skill_root = Path(skill.path).resolve().parent
                payload = self._build_skill_edit_payload(skill, skill_root, request, context)
                edit = await self._generate_skill_edit(payload)
                self._apply_skill_edit(run, skill, skill_root, edit, request)
            except Exception as exc:
                run.errors.append(f"skill_update_failed: {exc}")

    async def _generate_skill_edit(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self.provider.chat(
            [
                {"role": "system", "content": SKILL_EDIT_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "请生成该 skill 目录的文件操作，只输出 JSON。\n\n"
                        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
                    ),
                },
            ],
            temperature=0.1,
            max_tokens=5000,
        )
        record_model_usage(
            self.usage_store,
            ModelRequestContext(
                request_kind="evolution_skill_update",
                model_config=self.model_config,
                provider_type=self.provider_type,
                streaming=False,
                session_id=str(payload.get("source_session_id") or ""),
                metadata={
                    "skill_name": payload.get("skill", {}).get("name"),
                    "file_count": len(payload.get("files", [])),
                },
            ),
            response,
        )
        parsed = _parse_json_object(response.content)
        return parsed if isinstance(parsed, dict) else {}

    def _apply_skill_edit(
        self,
        run: EvolutionRunRecord,
        skill: SkillDescriptor,
        skill_root: Path,
        edit: dict[str, Any],
        request: dict[str, str],
    ) -> None:
        raw_operations = edit.get("file_operations")
        if not isinstance(raw_operations, list) or not raw_operations:
            return

        operations = self._normalize_file_operations(skill_root, raw_operations)
        if not operations:
            return

        applied_changes: list[EvolutionChange] = []
        try:
            for operation in operations:
                change = self._apply_skill_file_operation(
                    run,
                    skill_root,
                    operation,
                    reason=str(request.get("reason") or request.get("desired_change") or ""),
                    summary=str(edit.get("change_summary") or request.get("desired_change") or "更新 Skill"),
                )
                applied_changes.append(change)
                run.changes.append(change)

            validation_errors = self._validate_skill_root(skill, skill_root)
            if validation_errors:
                raise ValueError("; ".join(validation_errors))
            for change in applied_changes:
                change.validation_status = "passed"
        except Exception as exc:
            self._rollback_changes(applied_changes)
            for change in applied_changes:
                change.validation_status = "rolled_back"
                change.validation_errors.append(str(exc))
            run.errors.append(f"skill_validation_failed:{skill.name}: {exc}")

    def _apply_skill_file_operation(
        self,
        run: EvolutionRunRecord,
        skill_root: Path,
        operation: dict[str, Any],
        *,
        reason: str,
        summary: str,
    ) -> EvolutionChange:
        action = operation["action"]
        target = operation["target"]
        before = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        before_exists, snapshot_path = self.store.save_file_snapshot(run.run_id, target)

        if action == "delete":
            if target.exists():
                target.unlink()
            after = ""
        else:
            content = str(operation.get("content") or "")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            after = content

        return EvolutionChange(
            change_id=uuid4().hex,
            kind="skill_update",
            action=action,
            target_path=str(target),
            summary=summary,
            reason=reason,
            diff=_unified_diff(before, after, str(target)),
            before_exists=before_exists,
            snapshot_path=snapshot_path,
            validation_status="not_run",
        )

    def rollback_run(self, run_id: str) -> EvolutionRunRecord:
        run = self.store.get_run(run_id)
        self._rollback_changes(run.changes)
        for change in run.changes:
            change.validation_status = "rolled_back"
        run.status = "rolled_back"
        run.updated_at = utc_now()
        run.summary = "已回滚本次自进化变更"
        self.reload_ecosystem()
        self.store.save_run(run)
        return run

    def _rollback_changes(self, changes: list[EvolutionChange]) -> None:
        for change in reversed(changes):
            target = Path(change.target_path)
            if change.before_exists:
                if not change.snapshot_path:
                    continue
                snapshot = Path(change.snapshot_path)
                if snapshot.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(snapshot.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            elif target.exists():
                target.unlink()

    def _validate_skill_root(self, skill: SkillDescriptor, skill_root: Path) -> list[str]:
        errors: list[str] = []
        skill_file = skill_root / "SKILL.md"
        if not skill_file.exists():
            errors.append("SKILL.md missing after update")
        else:
            try:
                parse_skill_file(skill_file, skill_root.name)
            except Exception as exc:
                errors.append(f"SKILL.md parse failed: {exc}")

        for path in skill_root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix == ".py":
                try:
                    py_compile.compile(str(path), doraise=True)
                except py_compile.PyCompileError as exc:
                    errors.append(f"Python compile failed for {path.relative_to(skill_root)}: {exc.msg}")
            elif path.suffix == ".json":
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    errors.append(f"JSON parse failed for {path.relative_to(skill_root)}: {exc}")
            elif path.suffix in {".yaml", ".yml"}:
                try:
                    yaml.safe_load(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    errors.append(f"YAML parse failed for {path.relative_to(skill_root)}: {exc}")

        if errors:
            return errors
        try:
            self.reload_ecosystem()
            self.plugin_service.get_skill_by_path(skill_file)
        except Exception as exc:
            errors.append(f"Skill reload failed: {exc}")
        return errors

    def _normalize_file_operations(self, skill_root: Path, raw_operations: list[Any]) -> list[dict[str, Any]]:
        operations: list[dict[str, Any]] = []
        seen: set[Path] = set()
        for item in raw_operations:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "").strip().lower()
            if action not in {"create", "update", "delete"}:
                continue
            raw_path = str(item.get("path") or "").strip()
            target = self._resolve_skill_relative_path(skill_root, raw_path)
            if target in seen:
                raise ValueError(f"Duplicate skill file operation: {raw_path}")
            seen.add(target)
            if target.exists() and target.is_dir():
                raise ValueError(f"Skill file operation targets a directory: {raw_path}")
            if action in {"create", "update"}:
                content = item.get("content")
                if not isinstance(content, str):
                    raise ValueError(f"Missing content for {action}: {raw_path}")
                operations.append({"action": action, "target": target, "content": content})
            else:
                if target.name == "SKILL.md":
                    raise ValueError("Deleting SKILL.md is not allowed")
                operations.append({"action": action, "target": target})
        return operations

    def _resolve_skill_relative_path(self, skill_root: Path, raw_path: str) -> Path:
        if not raw_path:
            raise ValueError("Skill file path is empty")
        posix = PurePosixPath(raw_path.replace("\\", "/"))
        if posix.is_absolute() or any(part in {"..", ""} for part in posix.parts):
            raise ValueError(f"Skill file path is outside the skill directory: {raw_path}")
        target = (skill_root / Path(*posix.parts)).resolve()
        try:
            target.relative_to(skill_root)
        except ValueError as exc:
            raise ValueError(f"Skill file path is outside the skill directory: {raw_path}") from exc
        return target

    def _resolve_skill_request(self, request: dict[str, str]) -> SkillDescriptor:
        raw_path = request.get("skill_path")
        if raw_path:
            try:
                skill = self.plugin_service.get_skill_by_path(Path(raw_path))
                if self._skill_is_writable(skill):
                    return skill
            except Exception:
                pass
        raw_name = request.get("skill_name")
        if raw_name:
            skill = self.plugin_service.get_skill(raw_name)
            if self._skill_is_writable(skill):
                return skill
        raise FileNotFoundError(f"Writable skill not found: {raw_name or raw_path}")

    def _skill_is_writable(self, skill: SkillDescriptor) -> bool:
        skill_path = Path(skill.path).resolve()
        allowed_roots = [
            self.settings.paths.skills_dir.resolve(),
            self.settings.paths.plugins_dir.resolve(),
        ]
        return any(_is_relative_to(skill_path, root) for root in allowed_roots)

    def _build_skill_edit_payload(
        self,
        skill: SkillDescriptor,
        skill_root: Path,
        request: dict[str, str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        files = self._read_skill_files(skill_root)
        return {
            "source_session_id": context["session"]["session_id"],
            "trigger": context["trigger"],
            "skill": skill.model_dump(mode="json"),
            "skill_root": str(skill_root),
            "request": request,
            "memory": context["current_memory"],
            "session_summary": {
                "message_range": context["message_range"],
                "messages": context["messages"],
                "checkpoint": context.get("checkpoint"),
            },
            "files": files,
        }

    def _read_skill_files(self, skill_root: Path) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        total_bytes = 0
        for path in sorted(skill_root.rglob("*")):
            if not path.is_file():
                continue
            if not _is_text_skill_file(path):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > self.config.max_skill_file_bytes:
                files.append({"path": path.relative_to(skill_root).as_posix(), "omitted": True, "reason": "file_too_large"})
                continue
            if total_bytes + size > self.config.max_skill_total_bytes:
                files.append({"path": path.relative_to(skill_root).as_posix(), "omitted": True, "reason": "total_size_limit"})
                continue
            total_bytes += size
            files.append(
                {
                    "path": path.relative_to(skill_root).as_posix(),
                    "content": path.read_text(encoding="utf-8", errors="replace"),
                }
            )
        return files

    def _normalize_memory_updates(self, raw_updates: Any) -> list[dict[str, str]]:
        if not isinstance(raw_updates, list):
            return []
        updates: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in raw_updates[: self.config.max_memory_updates_per_run]:
            if not isinstance(item, dict):
                continue
            text = _clean_memory_text(str(item.get("text") or ""))
            if not text or len(text) < 6:
                continue
            normalized = _normalize_memory_item(text)
            if normalized in seen:
                continue
            seen.add(normalized)
            updates.append({"text": text, "reason": str(item.get("reason") or "").strip()})
        return updates

    def _normalize_skill_requests(self, raw_requests: Any) -> list[dict[str, str]]:
        if not isinstance(raw_requests, list):
            return []
        requests: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in raw_requests[: self.config.max_skill_updates_per_run]:
            if not isinstance(item, dict):
                continue
            skill_name = str(item.get("skill_name") or "").strip()
            skill_path = str(item.get("skill_path") or "").strip()
            key = skill_path or skill_name
            if not key or key in seen:
                continue
            seen.add(key)
            requests.append(
                {
                    "skill_name": skill_name,
                    "skill_path": skill_path,
                    "reason": str(item.get("reason") or "").strip(),
                    "desired_change": str(item.get("desired_change") or "").strip(),
                }
            )
        return requests

    def _build_context(
        self,
        session: SessionRecord,
        checkpoint: CheckpointRecord | None,
        trigger: EvolutionTrigger,
    ) -> dict[str, Any]:
        start_index = self._context_start_index(session, trigger)
        messages = list(session.messages)[start_index:]
        if len(messages) > self.config.max_context_messages:
            start_index = len(session.messages) - self.config.max_context_messages
            messages = list(session.messages)[start_index:]

        return {
            "trigger": trigger,
            "session": {
                "session_id": session.session_id,
                "title": session.title,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "metadata": self._filter_session_metadata(session.metadata),
            },
            "message_range": [start_index, len(session.messages)],
            "user_turn_count": self._user_turn_count(session),
            "checkpoint": checkpoint.model_dump(mode="json") if checkpoint else None,
            "current_memory": self.memory_path.read_text(encoding="utf-8") if self.memory_path.exists() else "",
            "current_user_memory": self.user_path.read_text(encoding="utf-8") if self.user_path.exists() else "",
            "recent_evolution_runs": [
                {
                    "run_id": run.run_id,
                    "status": run.status,
                    "summary": run.summary,
                    "changes": [
                        {"kind": change.kind, "target_path": change.target_path, "summary": change.summary}
                        for change in run.changes
                    ],
                }
                for run in self.store.list_runs(limit=5)
            ],
            "skills": [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "when_to_use": skill.when_to_use,
                    "summary": skill.summary,
                    "path": skill.path,
                    "source": skill.source,
                    "plugin_name": skill.plugin_name,
                }
                for skill in self.skill_registry.list_skills()
            ],
            "messages": [self._serialize_message(message) for message in messages],
        }

    def _serialize_message(self, message: SessionMessage) -> dict[str, Any]:
        metadata = dict(message.metadata or {})
        payload: dict[str, Any] = {
            "id": message.id,
            "role": message.role,
            "created_at": message.created_at,
            "metadata": self._filter_message_metadata(metadata),
        }
        if message.role == "tool":
            payload.update(self._serialize_tool_message(message, metadata))
        else:
            payload["content"] = _truncate_text(message.content, 8000)
        return payload

    def _serialize_tool_message(self, message: SessionMessage, metadata: dict[str, Any]) -> dict[str, Any]:
        return {
            "tool": metadata.get("tool"),
            "action": metadata.get("action"),
            "success": metadata.get("success"),
            "summary": metadata.get("summary"),
            "recommended_next_step": metadata.get("recommended_next_step"),
            "content_preview": _truncate_text(message.content, self.config.max_tool_output_chars),
        }

    def _filter_message_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "turn_id",
            "finish_reason",
            "turn_outcome",
            "tool",
            "success",
            "summary",
            "action",
            "path",
            "bytes",
            "status",
            "phase",
            "tool_calls",
            "attachments",
            "attachment_summaries",
        }
        return {key: value for key, value in metadata.items() if key in allowed}

    def _filter_session_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        prefixes = ("evolution_", "memory_", "extraction_")
        return {key: value for key, value in metadata.items() if not key.startswith(prefixes)}

    def _context_start_index(self, session: SessionRecord, trigger: EvolutionTrigger) -> int:
        if trigger in {"new_session_created", "manual"}:
            return 0
        last_message_count = _coerce_int(session.metadata.get("evolution_last_message_count")) or 0
        start = min(max(last_message_count, 0), len(session.messages))
        return self._apply_user_turn_overlap(session.messages, start, self.config.overlap_user_turns)

    def _apply_user_turn_overlap(self, messages: list[SessionMessage], start: int, overlap_user_turns: int) -> int:
        if start <= 0 or overlap_user_turns <= 0:
            return start
        user_seen = 0
        for index in range(start - 1, -1, -1):
            if messages[index].role == "user":
                user_seen += 1
                if user_seen >= overlap_user_turns:
                    return index
        return 0

    def _has_evolution_context(self, session: SessionRecord, checkpoint: CheckpointRecord | None) -> bool:
        if checkpoint and checkpoint.summary.strip():
            return True
        meaningful = [
            message
            for message in session.messages
            if message.role in {"user", "assistant", "tool"} and message.content.strip()
        ]
        return len(meaningful) >= 2

    def _source_fingerprint(self, session: SessionRecord, checkpoint: CheckpointRecord | None) -> str:
        checkpoint_id = checkpoint.checkpoint_id if checkpoint else "none"
        last_message_id = session.messages[-1].id if session.messages else "none"
        last_message_at = session.messages[-1].created_at if session.messages else "none"
        return f"{checkpoint_id}:{len(session.messages)}:{last_message_id}:{last_message_at}"

    def _mark_session_processed(
        self,
        session: SessionRecord,
        fingerprint: str,
        trigger: EvolutionTrigger,
        status: str,
    ) -> None:
        self.session_store.update_metadata(
            session.session_id,
            {
                "evolution_last_source": fingerprint,
                "evolution_last_at": utc_now(),
                "evolution_last_trigger": trigger,
                "evolution_last_status": status,
                "evolution_last_message_count": len(session.messages),
                "evolution_last_user_turn_count": self._user_turn_count(session),
            },
            touch_updated_at=False,
        )

    def _user_turn_count(self, session: SessionRecord) -> int:
        return sum(1 for message in session.messages if message.role == "user")

    def _finish_run(self, run: EvolutionRunRecord, status: str, summary: str) -> EvolutionRunRecord:
        run.status = status  # type: ignore[assignment]
        run.summary = summary
        run.updated_at = utc_now()
        self.store.save_run(run)
        return run

    def _resolve_run_status(self, run: EvolutionRunRecord) -> str:
        passed = [change for change in run.changes if change.validation_status == "passed"]
        failed = bool(run.errors) or any(change.validation_status in {"failed", "rolled_back"} for change in run.changes)
        if passed and failed:
            return "partial"
        if passed:
            return "applied"
        if failed:
            return "failed"
        return "skipped"

    def _build_run_summary(self, run: EvolutionRunRecord) -> str:
        memory_count = sum(1 for change in run.changes if change.kind == "memory_update" and change.validation_status == "passed")
        skill_count = sum(1 for change in run.changes if change.kind == "skill_update" and change.validation_status == "passed")
        parts = []
        if memory_count:
            parts.append(f"memory 更新 {memory_count} 项")
        if skill_count:
            parts.append(f"skill 文件更新 {skill_count} 项")
        return "；".join(parts) or "No changes applied."


def _merge_memory_items(content: str, new_items: list[str]) -> tuple[str, list[str]]:
    existing = _extract_memory_items(content)
    seen = {_normalize_memory_item(item) for item in existing if item != EMPTY_MEMORY_ITEM}
    added: list[str] = []
    merged = [item for item in existing if item != EMPTY_MEMORY_ITEM]
    for item in new_items:
        normalized = _normalize_memory_item(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(item)
        added.append(item)
    if not added:
        return content, []
    block = _render_memory_block(merged)
    if AUTO_MEMORY_BEGIN in content and AUTO_MEMORY_END in content:
        start = content.index(AUTO_MEMORY_BEGIN)
        end = content.index(AUTO_MEMORY_END) + len(AUTO_MEMORY_END)
        return content[:start].rstrip() + "\n\n" + block + "\n" + content[end:].lstrip(), added
    return content.rstrip() + "\n\n" + block + "\n", added


def _extract_memory_items(content: str) -> list[str]:
    if AUTO_MEMORY_BEGIN in content and AUTO_MEMORY_END in content:
        start = content.index(AUTO_MEMORY_BEGIN) + len(AUTO_MEMORY_BEGIN)
        end = content.index(AUTO_MEMORY_END)
        body = content[start:end]
    else:
        body = content
    items: list[str] = []
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("- "):
            continue
        text = _clean_memory_text(stripped[2:])
        if text:
            items.append(text)
    return items or [EMPTY_MEMORY_ITEM]


def _render_memory_block(items: list[str]) -> str:
    rendered_items = items or [EMPTY_MEMORY_ITEM]
    lines = [AUTO_MEMORY_BEGIN, "## Learned Experience", ""]
    lines.extend(f"- {item}" for item in rendered_items)
    lines.append(AUTO_MEMORY_END)
    return "\n".join(lines)


def _clean_memory_text(value: str) -> str:
    text = re.sub(r"^[\-\*\d\.\s]+", "", value)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_memory_item(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _parse_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _unified_diff(before: str, after: str, path: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n[truncated {len(value) - limit} chars]"


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_text_skill_file(path: Path) -> bool:
    return path.name in TEXT_SKILL_FILENAMES or path.suffix.lower() in TEXT_SKILL_SUFFIXES

