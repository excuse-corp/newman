from __future__ import annotations

import base64
from pathlib import Path

from backend.config.schema import ModelConfig
from backend.providers.factory import build_provider


class MultimodalAnalyzer:
    def __init__(self, config: ModelConfig):
        self.config = config
        self.provider = build_provider(config)

    async def analyze_images(self, prompt: str, image_paths: list[Path]) -> list[dict[str, str]]:
        if not image_paths:
            return []
        if self.config.type == "mock":
            return [
                {
                    "filename": path.name,
                    "summary": f"[mock] 已接收图片 {path.name}，当前未启用真实多模态分析。",
                }
                for path in image_paths
            ]

        content = [{"type": "text", "text": prompt or "请描述图片中的关键信息、文字、界面和与用户任务相关的线索。"}]
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
                        "你负责分析用户上传的图片。请输出简洁、结构化的中文观察，覆盖："
                        "1. 场景/主体 2. 可见文字 3. 与当前任务相关的关键信息 4. 不确定点。"
                    ),
                },
                {"role": "user", "content": content},
            ],
            tools=None,
            temperature=0.1,
        )

        summary = response.content.strip() or "未获得可用图片分析结果。"
        return [{"filename": path.name, "summary": summary} for path in image_paths]
