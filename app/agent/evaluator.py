from __future__ import annotations

from dataclasses import dataclass
import json
import re

from app.llm.base import LLMProvider


@dataclass(slots=True)
class EvaluationResult:
    correctness: int
    groundedness: int
    completeness: int
    coverage_of_required_fields: int
    source_consistency: int
    comment: str
    raw_json: dict | None = None


class DigestEvaluator:
    def __init__(self, llm_provider: LLMProvider, *, timeout_seconds: int = 45) -> None:
        self.llm_provider = llm_provider
        self.timeout_seconds = timeout_seconds

    def _compact_source_messages(self, source_messages: list[dict], *, max_messages: int = 40) -> list[dict]:
        if len(source_messages) <= max_messages:
            selected = source_messages
        else:
            head = max_messages // 2
            tail = max_messages - head
            selected = source_messages[:head] + source_messages[-tail:]
        compacted: list[dict] = []
        for item in selected:
            compacted.append(
                {
                    "author_display_name": str(item.get("author_display_name") or item.get("author") or "unknown").strip(),
                    "message_type": str(item.get("message_type") or "text").strip() or "text",
                    "text": " ".join(str(item.get("text") or item.get("resolved_text") or "").split())[:180],
                }
            )
        return compacted

    async def evaluate(self, *, digest: str, source_messages: list[dict]) -> EvaluationResult:
        compact_source_messages = self._compact_source_messages(source_messages)
        response = await self.llm_provider.generate_json(
            system="Evaluate digest quality. Return strict JSON.",
            prompt=json.dumps({"digest": digest[:6000], "messages": compact_source_messages}, ensure_ascii=False),
            timeout_seconds=self.timeout_seconds,
        )
        return self.parse_json(response)

    def parse_json(self, payload: dict | str) -> EvaluationResult:
        if isinstance(payload, str):
            payload = self._extract_json(payload)
        return EvaluationResult(
            correctness=self._score(payload.get("correctness")),
            groundedness=self._score(payload.get("groundedness")),
            completeness=self._score(payload.get("completeness")),
            coverage_of_required_fields=self._score(payload.get("coverage_of_required_fields")),
            source_consistency=self._score(payload.get("source_consistency")),
            comment=str(payload.get("comment", "")),
            raw_json=payload,
        )

    def _extract_json(self, text: str) -> dict:
        text = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
        if fenced:
            return json.loads(fenced.group(1))
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            inline = re.search(r"\{.*\}", text, flags=re.S)
            if inline:
                return json.loads(inline.group(0))
            return {"comment": text}

    def _score(self, value: object) -> int:
        try:
            score = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0
        return max(0, min(5, score))
