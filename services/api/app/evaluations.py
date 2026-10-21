from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any

from .providers.http import ProviderError
from .providers.registry import ProviderRegistry
from .model_config import ModelTier
from .model_router import ModelRouter, RouteTrace
from .vision_preview import make_vision_preview


class AIEvaluator:
    """Evaluate a generated image through the configured multimodal model.

    The deterministic branch exists only for the automated test suite. A
    production request always sends the persisted image bytes to the real
    OpenAI-compatible text model and rejects malformed responses.
    """

    def __init__(self, providers: ProviderRegistry) -> None:
        self.providers = providers

    def evaluate_image(self, *, prompt: str, params: dict[str, Any], provider: str, has_lineage: bool, image_content: bytes, image_mime: str, trace_id: str | None = None) -> dict[str, Any]:
        if os.environ.get("AICS_TEST_MODE") == "1":
            return self._test_evaluation(prompt=prompt, params=params, provider=provider, has_lineage=has_lineage)
        if not image_content:
            raise ProviderError("图像资产为空")
        catalog = self.providers.catalog
        preferred = catalog.settings().preferredTextProvider if catalog else None
        if not preferred or not preferred.key:
            raise ProviderError("请先在模型设置中选择首选文本 Provider")
        endpoint = ModelRouter(catalog, self.providers).endpoint(
            ModelTier.STANDARD,
            {"key": preferred.key, "baseUrl": preferred.baseUrl},
        )
        record = catalog.record(endpoint['key'], endpoint['baseUrl'], endpoint['model'])
        modalities = record.get('inputModalities') or []
        if modalities and 'image' not in modalities:
            raise ProviderError(f"模型 {endpoint['model']} 不支持图片输入")
        preview = make_vision_preview(image_content)
        if not preview:
            raise ProviderError("无法生成安全的图像评价预览")
        preview_content = preview.pop('content')
        text_provider = self.providers.text(endpoint['key'], base_url=endpoint['baseUrl'], model=endpoint['model'])
        started = time.time()
        try:
            response = text_provider.complete(
                system=(
                    "你是文旅文创视觉评审。只评价附件中的真实图像与给定 Prompt，"
                    "不要补写不存在的文化来源或项目数据。返回严格 JSON："
                    '{"score":{"overall":0,"promptCompleteness":0,"culturalRelevance":0,"styleMaterialControl":0,"visualConsistency":0},'
                    '"feedback":"..."}。所有分数为 0 到 5 的数字，feedback 使用中文。'
                ),
                prompt=json.dumps({"prompt": prompt, "params": params, "sourceProvider": provider}, ensure_ascii=False),
                attachments=[{"filename": "generated-image", "mime": preview['mime'], "byteSize": preview['byteSize'],
                              "visionPreview": {**preview, "normalized": True}, "data": base64.b64encode(preview_content).decode("ascii")}],
            )
        except Exception as error:
            if trace_id:
                RouteTrace(catalog.store).append(trace_id, {
                    "call_kind": "image_evaluation", "tier": ModelTier.STANDARD.value, "provider": endpoint["key"],
                    "base_url": endpoint["baseUrl"], "model": endpoint["model"], "route_source": "automatic-standard",
                    "started_at": started, "latency_ms": round((time.time() - started) * 1000), "status": "failed",
                    "error_type": type(error).__name__, "submitted": None, "billing_certainty": "unknown",
                })
            raise
        if trace_id:
            RouteTrace(catalog.store).append(trace_id, {
                "call_kind": "image_evaluation", "tier": ModelTier.STANDARD.value, "provider": endpoint["key"],
                "base_url": endpoint["baseUrl"], "model": endpoint["model"], "route_source": "automatic-standard",
                "started_at": started, "latency_ms": round((time.time() - started) * 1000), "status": "succeeded",
                "error_type": None, "submitted": True, "billing_certainty": "settled",
            })
        parsed = self._parse_json(response)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("score"), dict) or not str(parsed.get("feedback") or "").strip():
            raise ProviderError("AI 评价模型返回的 JSON 不符合评价契约")
        score = parsed["score"]
        required = ("overall", "promptCompleteness", "culturalRelevance", "styleMaterialControl", "visualConsistency")
        if any(not isinstance(score.get(key), (int, float)) for key in required):
            raise ProviderError("AI 评价模型未返回完整分数")
        normalized_score = {key: max(0, min(5, float(score[key]))) for key in required}
        return {"score": normalized_score, "feedback": str(parsed["feedback"]).strip(), "provenance": {"evaluator": "preferred-provider-multimodal", "provider": endpoint['key'], "model": endpoint['model'], "mode": "remote-image-evaluation", "explainable": False}}

    @staticmethod
    def _parse_json(value: Any) -> dict[str, Any] | None:
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(value or "").strip(), flags=re.I).strip()
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
        return None

    @staticmethod
    def _test_evaluation(*, prompt: str, params: dict[str, Any], provider: str, has_lineage: bool) -> dict[str, Any]:
        """Deterministic test fixture; never reachable in a packaged run."""
        prompt_score = 5 if len(prompt.strip()) >= 18 else 3
        culture_score = 5 if re.search(r"西湖|宋|文化|文旅|博物馆|传统|IP|礼赠", prompt) else 3
        controls_score = 5 if params.get("style") and params.get("material") else 3
        consistency_score = 5 if has_lineage or params.get("ipProfileVersion") else 3
        overall = round((prompt_score + culture_score + controls_score + consistency_score) / 4, 1)
        return {"score": {"overall": overall, "promptCompleteness": prompt_score, "culturalRelevance": culture_score, "styleMaterialControl": controls_score, "visualConsistency": consistency_score}, "feedback": "测试评价结果", "provenance": {"evaluator": "test-fixture", "provider": provider, "mode": "test-only", "explainable": True}}
