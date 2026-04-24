from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
import re
from urllib import request

from app.llm.base import LLMResponse


class MockLLMProvider:
    async def generate_text(self, *, system: str, prompt: str) -> LLMResponse:
        text = self._render_text(system, prompt)
        return LLMResponse(text=text, raw={"provider": "mock"})

    async def generate_json(self, *, system: str, prompt: str) -> dict:
        return self._render_json(system, prompt)

    def _render_text(self, system: str, prompt: str) -> str:
        lowered = system.lower()
        if "digest" in lowered or "сводк" in lowered or "summary" in lowered:
            return "Чат обсуждает несколько конкретных тем, которые можно кратко и по-русски свести в дайджест."
        if "group telegram chat messages by topic" in lowered or "сгруппируй сообщения" in lowered:
            return prompt[:400]
        return prompt[:400]

    def _render_json(self, system: str, prompt: str) -> dict:
        lowered = f"{system}\n{prompt}".lower()
        if "evaluate" in lowered:
            return {
                "correctness": 4,
                "groundedness": 4,
                "completeness": 4,
                "coverage_of_required_fields": 4,
                "source_consistency": 4,
                "comment": "Mock evaluator output.",
            }
        if "summary" in lowered and "open_questions" in lowered and "warnings" in lowered:
            return {
                "summary": "Краткая русская сводка.",
                "topics": [{"title": "Общая тема", "who_said_what": "Короткое русское описание."}],
                "decisions": [],
                "tasks": [],
                "open_questions": [],
                "warnings": [],
            }
        if "group" in lowered:
            return {"topics": [{"title": "General", "message_indexes": [0]}]}
        if "decision" in lowered:
            return {"decisions": []}
        if "task" in lowered:
            return {"tasks": []}
        return {"result": prompt[:200]}


class OpenAICompatibleLLMProvider:
    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def generate_text(self, *, system: str, prompt: str) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        data = await asyncio.to_thread(self._post_json, "/chat/completions", payload)
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        return LLMResponse(text=content, raw=data)

    async def generate_json(self, *, system: str, prompt: str) -> dict:
        response = await self.generate_text(system=system, prompt=prompt)
        return self._extract_json(response.text)

    def _post_json(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except TimeoutError as exc:
            raise TimeoutError(
                f"LLM request timed out after {self.timeout_seconds}s for {path}"
            ) from exc

    def _extract_json(self, text: str) -> dict:
        text = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            inline = re.search(r"\{.*\}", text, flags=re.S)
            if inline:
                try:
                    return json.loads(inline.group(0))
                except json.JSONDecodeError:
                    pass
            return {"result": text}
