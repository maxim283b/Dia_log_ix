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
    def __init__(self, llm_provider: LLMProvider) -> None:
        self.llm_provider = llm_provider

    async def evaluate(self, *, digest: str, source_messages: list[dict]) -> EvaluationResult:
        response = await self.llm_provider.generate_json(
            system="Evaluate digest quality. Return strict JSON.",
            prompt=json.dumps({"digest": digest, "messages": source_messages}, ensure_ascii=False),
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
