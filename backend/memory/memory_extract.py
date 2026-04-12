from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.config.schema import ModelConfig
from backend.memory.checkpoint_store import CheckpointStore
from backend.providers.base import BaseProvider
from backend.sessions.models import CheckpointRecord, SessionRecord, utc_now
from backend.sessions.session_store import SessionStore
from backend.usage.recorder import ModelRequestContext, record_model_usage
from backend.usage.store import PostgresModelUsageStore


@dataclass(frozen=True)
class MemoryFileSpec:
    path: Path
    header: str
    block_begin: str
    block_end: str
    section_title: str
    description: str
    empty_text: str = "暂无条目"


MAX_CONTEXT_MESSAGES = 12
MAX_ITEMS_PER_SECTION = 8
EXPLICIT_MEMORY_PATTERNS = [
    r"记住",
    r"记一下",
    r"帮我记",
    r"请记住",
    r"别忘了",
    r"写入\s*memory",
    r"记到\s*memory",
    r"add (?:this|it) to memory",
    r"keep (?:this|it) in mind",
    r"please remember",
    r"remember (?:this|it|that)",
]
EXPLICIT_USER_MEMORY_PATTERNS = [
    r"以后.*默认",
    r"默认.*(回复|回答|输出|使用|叫我|称呼|中文|英文|简洁|详细)",
    r"以后.*请",
    r"之后都",
    r"今后都",
    r"请一直",
    r"统一用",
    r"我习惯",
    r"我的习惯",
    r"我偏好",
    r"我的偏好",
    r"希望你以后",
    r"回答.*(简洁|详细|中文|英文)",
    r"不要用.*emoji",
]
EPHEMERAL_PATTERNS = [
    r"当前会话",
    r"本次会话",
    r"这次会话",
    r"当前任务",
    r"正在",
    r"刚刚",
    r"下一步",
    r"待会",
    r"稍后",
    r"临时",
    r"today",
    r"currently",
]
SYSTEM_RULE_PATTERNS = [
    r"系统提示",
    r"工具规则",
    r"审批策略",
    r"agent 规则",
    r"newman 规则",
]
USER_MEMORY_FORBIDDEN_PATTERNS = EPHEMERAL_PATTERNS + SYSTEM_RULE_PATTERNS


class MemoryExtractor:
    def __init__(
        self,
        provider: BaseProvider,
        model_config: ModelConfig,
        provider_type: str,
        session_store: SessionStore,
        checkpoints: CheckpointStore,
        user_path: Path,
        prompt_path: Path,
        usage_store: PostgresModelUsageStore | None = None,
    ):
        self.provider = provider
        self.model_config = model_config
        self.provider_type = provider_type
        self.session_store = session_store
        self.checkpoints = checkpoints
        self.prompt_path = prompt_path
        self.usage_store = usage_store
        self.user_spec = MemoryFileSpec(
            path=user_path,
            header="# USER.md",
            block_begin="<!-- BEGIN AUTO USER MEMORY -->",
            block_end="<!-- END AUTO USER MEMORY -->",
            section_title="## User Memory",
            description="仅记录跨 session 稳定成立的用户偏好、沟通方式和长期协作约定，不记录一次性任务或项目事实。",
        )
        self._write_lock = asyncio.Lock()

    @classmethod
    def looks_like_explicit_persistence_signal(cls, content: str) -> bool:
        text = content.strip()
        if not text:
            return False
        patterns = EXPLICIT_MEMORY_PATTERNS + EXPLICIT_USER_MEMORY_PATTERNS
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)

    async def extract_session(self, session_id: str, trigger: str) -> dict[str, Any]:
        if self.provider_type == "mock":
            return {
                "ok": False,
                "reason": "mock_provider",
                "scheduled": False,
                "source_session_id": session_id,
                "trigger": trigger,
            }

        try:
            session = self.session_store.get(session_id)
        except FileNotFoundError:
            return {
                "ok": False,
                "reason": "session_not_found",
                "scheduled": False,
                "source_session_id": session_id,
                "trigger": trigger,
            }

        checkpoint = self.checkpoints.get(session_id)
        fingerprint = self._source_fingerprint(session, checkpoint)
        if session.metadata.get("extraction_last_source") == fingerprint:
            return {
                "ok": False,
                "reason": "already_processed",
                "scheduled": False,
                "source_session_id": session_id,
                "trigger": trigger,
            }

        if not self._has_extractable_context(session, checkpoint, trigger):
            self.session_store.update_metadata(
                session_id,
                {
                    "extraction_last_source": fingerprint,
                    "extraction_last_at": utc_now(),
                    "extraction_last_trigger": trigger,
                    "extraction_last_user_count": 0,
                    "extraction_last_status": "skipped_short_session",
                },
                touch_updated_at=False,
            )
            return {
                "ok": False,
                "reason": "session_too_short",
                "scheduled": False,
                "source_session_id": session_id,
                "trigger": trigger,
            }

        prompt = self.prompt_path.read_text(encoding="utf-8")
        payload = self._build_payload(session, checkpoint, trigger)
        response = await self.provider.chat(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        "请基于以下会话材料完成稳定记忆分类抽取，并严格只输出 JSON。\n\n"
                        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
                    ),
                },
            ],
            temperature=0,
        )
        record_model_usage(
            self.usage_store,
            ModelRequestContext(
                request_kind="memory_extraction",
                model_config=self.model_config,
                provider_type=self.provider_type,
                streaming=False,
                counts_toward_context_window=False,
                session_id=session_id,
                metadata={
                    "trigger": trigger,
                    "recent_message_count": len(payload["recent_messages"]),
                    "has_checkpoint": checkpoint is not None,
                },
            ),
            response,
        )
        user_items = self._parse_extraction_result(response.content)
        added_user_items = await self._merge_updates(user_items)
        status = "updated" if added_user_items else "no_new_fact"
        self.session_store.update_metadata(
            session_id,
            {
                "extraction_last_source": fingerprint,
                "extraction_last_at": utc_now(),
                "extraction_last_trigger": trigger,
                "extraction_last_user_count": len(added_user_items),
                "extraction_last_status": status,
            },
            touch_updated_at=False,
        )
        return {
            "ok": True,
            "scheduled": False,
            "source_session_id": session_id,
            "trigger": trigger,
            "user_memory": added_user_items,
        }

    def _has_extractable_context(
        self,
        session: SessionRecord,
        checkpoint: CheckpointRecord | None,
        trigger: str,
    ) -> bool:
        meaningful_messages = [
            message
            for message in session.messages
            if message.role in {"user", "assistant", "tool"} and message.content.strip()
        ]
        if checkpoint and checkpoint.summary.strip():
            return True
        if trigger == "explicit_user_request":
            return bool(meaningful_messages)
        return len(meaningful_messages) >= 2

    def _source_fingerprint(self, session: SessionRecord, checkpoint: CheckpointRecord | None) -> str:
        checkpoint_id = checkpoint.checkpoint_id if checkpoint else "none"
        last_message_id = session.messages[-1].id if session.messages else "none"
        last_message_at = session.messages[-1].created_at if session.messages else "none"
        return f"{checkpoint_id}:{len(session.messages)}:{last_message_id}:{last_message_at}"

    def _build_payload(
        self,
        session: SessionRecord,
        checkpoint: CheckpointRecord | None,
        trigger: str,
    ) -> dict[str, Any]:
        recent_messages = session.messages[-MAX_CONTEXT_MESSAGES:]
        return {
            "trigger": trigger,
            "session": {
                "session_id": session.session_id,
                "title": session.title,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "message_count": len(session.messages),
                "metadata": self._filter_session_metadata(session.metadata),
            },
            "checkpoint": checkpoint.model_dump(mode="json") if checkpoint else None,
            "current_user_memory": self.user_spec.path.read_text(encoding="utf-8") if self.user_spec.path.exists() else "",
            "recent_messages": [
                {
                    "role": message.role,
                    "content": message.content,
                    "created_at": message.created_at,
                    "metadata": message.metadata,
                }
                for message in recent_messages
            ],
        }

    def _filter_session_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        prefixes = ("memory_", "extraction_")
        return {key: value for key, value in metadata.items() if not key.startswith(prefixes)}

    def _parse_extraction_result(self, content: str) -> list[str]:
        payload = self._parse_json_payload(content)
        if not isinstance(payload, dict):
            return []
        user_items = self._parse_item_list(payload.get("user_memory"), USER_MEMORY_FORBIDDEN_PATTERNS)
        return user_items

    def _parse_item_list(self, raw_items: Any, forbidden_patterns: list[str]) -> list[str]:
        if not isinstance(raw_items, list):
            return []

        items: list[str] = []
        seen: set[str] = set()
        for raw in raw_items[:MAX_ITEMS_PER_SECTION]:
            if isinstance(raw, dict):
                text = str(raw.get("fact", "")).strip()
            else:
                text = str(raw).strip()
            text = re.sub(r"^[\-\*\d\.\s]+", "", text)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) < 4:
                continue
            if self._matches_any(text, forbidden_patterns):
                continue
            normalized = self._normalize_item(text)
            if normalized in seen:
                continue
            seen.add(normalized)
            items.append(text)
        return items

    def _parse_json_payload(self, content: str) -> dict[str, Any]:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)
        for candidate in [stripped, *re.findall(r"\{.*\}", stripped, re.DOTALL)]:
            try:
                loaded = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(loaded, dict):
                return loaded
        return {}

    async def _merge_updates(self, user_items: list[str]) -> list[str]:
        if not user_items:
            return []

        async with self._write_lock:
            return self._merge_file(self.user_spec, user_items)

    def _merge_file(self, spec: MemoryFileSpec, new_items: list[str]) -> list[str]:
        original = spec.path.read_text(encoding="utf-8") if spec.path.exists() else f"{spec.header}\n"
        existing_items = self._extract_existing_items(original, spec)
        merged = list(existing_items)
        seen = {self._normalize_item(item) for item in existing_items}
        added: list[str] = []

        for item in new_items:
            normalized = self._normalize_item(item)
            if normalized in seen:
                continue
            seen.add(normalized)
            merged.append(item)
            added.append(item)

        updated = self._render_file(original, spec, merged)
        if updated != original:
            spec.path.write_text(updated, encoding="utf-8")
        return added

    def _extract_existing_items(self, content: str, spec: MemoryFileSpec) -> list[str]:
        if spec.block_begin in content and spec.block_end in content:
            start = content.index(spec.block_begin) + len(spec.block_begin)
            end = content.index(spec.block_end)
            source = content[start:end]
        else:
            source = content

        items: list[str] = []
        seen: set[str] = set()
        for line in source.splitlines():
            stripped = line.strip()
            if not stripped.startswith("- "):
                continue
            item = stripped[2:].strip()
            if not item or item == spec.empty_text:
                continue
            normalized = self._normalize_item(item)
            if normalized in seen:
                continue
            seen.add(normalized)
            items.append(item)
        return items

    def _render_file(self, original: str, spec: MemoryFileSpec, items: list[str]) -> str:
        managed_lines = [
            spec.block_begin,
            spec.section_title,
            spec.description,
            "",
        ]
        if items:
            managed_lines.extend(f"- {item}" for item in items)
        else:
            managed_lines.append(f"- {spec.empty_text}")
        managed_lines.append(spec.block_end)
        managed_block = "\n".join(managed_lines)

        stripped = original.strip()
        if spec.block_begin in original and spec.block_end in original:
            start = original.index(spec.block_begin)
            end = original.index(spec.block_end) + len(spec.block_end)
            rendered = original[:start].rstrip() + "\n\n" + managed_block + "\n"
            suffix = original[end:].strip()
            if suffix:
                rendered += "\n" + suffix + "\n"
            return rendered

        if not stripped:
            return f"{spec.header}\n\n{managed_block}\n"
        return stripped + "\n\n" + managed_block + "\n"

    def _normalize_item(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.strip()).casefold()

    def _matches_any(self, text: str, patterns: list[str]) -> bool:
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)
