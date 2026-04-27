from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from backend.config.schema import ModelConfig
from backend.providers.factory import build_provider
from backend.usage.recorder import ModelRequestContext, record_model_usage
from backend.usage.store import PostgresModelUsageStore


class MultimodalAnalyzer:
    def __init__(self, config: ModelConfig, usage_store: PostgresModelUsageStore | None = None):
        self.config = config
        self.provider = build_provider(config)
        self.usage_store = usage_store

    async def parse_user_input(
        self,
        prompt: str,
        image_paths: list[Path],
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        if not image_paths:
            return _empty_parse_result(self.config)

        if self.config.type == "mock":
            attachment_summaries = [
                f"[mock] 已接收图片 {path.name}，当前未启用真实多模态解析。"
                for path in image_paths
            ]
            return {
                "schema_version": "v1",
                "status": "completed",
                "parser_provider": self.config.type,
                "parser_model": self.config.model,
                "normalized_user_input": (prompt or "请结合上传的图片理解用户意图。").strip(),
                "task_intent": "describe_uploaded_images",
                "key_facts": attachment_summaries,
                "ocr_text": [],
                "uncertainties": ["当前使用 mock provider，未执行真实视觉理解。"],
                "attachment_summaries": attachment_summaries,
            }

        content = [{"type": "text", "text": _build_user_prompt(prompt, image_paths)}]
        for path in image_paths:
            mime_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            if self.config.type == "anthropic_compatible":
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": encoded,
                        },
                    }
                )
            else:
                content.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}})

        response = await self.provider.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 Newman 的多模态输入解析器。"
                        "请基于用户文字和全部图片做联合理解，并只返回一个 JSON 对象。"
                        "字段要求："
                        'normalized_user_input(string)，task_intent(string)，key_facts(string[])，'
                        'ocr_text(string[])，uncertainties(string[])，attachment_summaries(string[])。'
                        "attachment_summaries 必须和输入图片顺序一一对应；"
                        "不要输出 markdown，不要输出代码块，不要补充 JSON 之外的任何文字。"
                    ),
                },
                {"role": "user", "content": content},
            ],
            tools=None,
            temperature=0.1,
        )
        record_model_usage(
            self.usage_store,
            ModelRequestContext(
                request_kind="multimodal_analysis",
                model_config=self.config,
                provider_type=self.config.type,
                streaming=False,
                counts_toward_context_window=False,
                session_id=session_id,
                turn_id=turn_id,
                metadata={
                    "image_count": len(image_paths),
                    "filenames": [path.name for path in image_paths],
                },
            ),
            response,
        )
        return _normalize_parse_result(
            response.content,
            prompt=prompt,
            image_paths=image_paths,
            config=self.config,
        )

    async def analyze_images(
        self,
        prompt: str,
        image_paths: list[Path],
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> list[dict[str, str]]:
        if not image_paths:
            return []
        parsed = await self.parse_user_input(
            prompt,
            image_paths,
            session_id=session_id,
            turn_id=turn_id,
        )
        attachment_summaries = _coerce_string_list(parsed.get("attachment_summaries"))
        fallback_summary = _build_fallback_attachment_summary(prompt, "")
        summaries: list[dict[str, str]] = []
        for index, path in enumerate(image_paths):
            summary = attachment_summaries[index] if index < len(attachment_summaries) else fallback_summary
            summaries.append({"filename": path.name, "summary": summary})
        return summaries


def _build_user_prompt(prompt: str, image_paths: list[Path]) -> str:
    lines = [
        "请把这次输入解析成适合后续主模型继续处理的一轮用户请求。",
        "",
        "用户原始文字：",
        prompt.strip() or "（无文字，仅上传附件）",
        "",
        "上传附件（按顺序）：",
    ]
    for index, path in enumerate(image_paths, start=1):
        lines.append(f"{index}. {path.name}")
    lines.extend(
        [
            "",
            "输出要求：",
            "- normalized_user_input: 保留用户真实意图的归一化请求",
            "- task_intent: 一句话概括任务类型",
            "- key_facts: 图片里与任务最相关的关键事实",
            "- ocr_text: 看得见的关键文字",
            "- uncertainties: 目前仍不确定的点",
            "- attachment_summaries: 按图片顺序给出每张图的简短摘要",
        ]
    )
    return "\n".join(lines)


def _normalize_parse_result(
    content: str,
    *,
    prompt: str,
    image_paths: list[Path],
    config: ModelConfig,
) -> dict[str, Any]:
    parsed = _parse_json_payload(content)
    attachment_summaries = _coerce_string_list(parsed.get("attachment_summaries"))
    key_facts = _coerce_string_list(parsed.get("key_facts"))
    ocr_text = _coerce_string_list(parsed.get("ocr_text"))
    uncertainties = _coerce_string_list(parsed.get("uncertainties"))
    task_intent = _coerce_string(parsed.get("task_intent"))
    normalized_user_input = _coerce_string(parsed.get("normalized_user_input"))
    fallback_summary = _build_fallback_attachment_summary(prompt, content)

    if not attachment_summaries:
        attachment_summaries = [fallback_summary for _ in image_paths]
    elif len(attachment_summaries) < len(image_paths):
        attachment_summaries.extend([attachment_summaries[-1]] * (len(image_paths) - len(attachment_summaries)))
    else:
        attachment_summaries = attachment_summaries[: len(image_paths)]

    if not normalized_user_input:
        normalized_user_input = (prompt or "请结合上传附件理解用户意图。").strip()
    if not key_facts:
        key_facts = [fallback_summary]

    return {
        "schema_version": "v1",
        "status": "completed",
        "parser_provider": config.type,
        "parser_model": config.model,
        "normalized_user_input": normalized_user_input,
        "task_intent": task_intent,
        "key_facts": key_facts,
        "ocr_text": ocr_text,
        "uncertainties": uncertainties,
        "attachment_summaries": attachment_summaries,
    }


def _parse_json_payload(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if not stripped:
        return {}
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            payload = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return payload if isinstance(payload, dict) else {}


def _coerce_string(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if isinstance(item, str):
            cleaned = item.strip()
            if cleaned:
                normalized.append(cleaned)
    return normalized


def _build_fallback_attachment_summary(prompt: str, content: str) -> str:
    cleaned = content.strip()
    if cleaned:
        return cleaned[:160]
    if prompt.strip():
        return f"已根据用户请求“{prompt.strip()[:80]}”接收图片，未获得更细的结构化解析。"
    return "已接收图片，未获得更细的结构化解析。"


def _empty_parse_result(config: ModelConfig) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "status": "completed",
        "parser_provider": config.type,
        "parser_model": config.model,
        "normalized_user_input": "",
        "task_intent": "",
        "key_facts": [],
        "ocr_text": [],
        "uncertainties": [],
        "attachment_summaries": [],
    }
