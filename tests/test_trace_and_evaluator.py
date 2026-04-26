from __future__ import annotations

import pytest

from app.agent.evaluator import DigestEvaluator
from app.agent.runner import TraceRecorder
from app.llm.providers import MockLLMProvider
from app.models.agent_run import AgentRun


class EvaluationSpyLLMProvider(MockLLMProvider):
    def __init__(self) -> None:
        self.last_prompt = ""
        self.last_timeout_seconds = None

    async def generate_json(
        self,
        *,
        system: str,
        prompt: str,
        timeout_seconds: int | None = None,
    ) -> dict:
        self.last_prompt = prompt
        self.last_timeout_seconds = timeout_seconds
        return {
            "correctness": 5,
            "groundedness": 5,
            "completeness": 5,
            "coverage_of_required_fields": 5,
            "source_consistency": 5,
            "comment": "ok",
        }


@pytest.mark.asyncio
async def test_trace_save(session):
    run = AgentRun(
        chat_id=1,
        chat_telegram_id=1001,
        user_id=2,
        objective="test",
        mode="agent",
        status="running",
        history=[],
    )
    session.add(run)
    await session.flush()

    recorder = TraceRecorder(session, run)
    await recorder.save(
        action="step_one",
        input_json={"a": 1},
        output_json={"b": 2},
        latency_ms=10,
        status="ok",
        reason_next_step="next",
    )
    await session.commit()

    assert run.history == [{"step_id": 1, "action": "step_one", "status": "ok", "reason_next_step": "next"}]


def test_evaluator_json_parsing():
    evaluator = DigestEvaluator(MockLLMProvider())
    parsed = evaluator.parse_json(
        "Here is the result:\n```json\n{\"correctness\": 5, \"groundedness\": 4, \"completeness\": 3, "
        "\"coverage_of_required_fields\": 2, \"source_consistency\": 1, \"comment\": \"ok\"}\n```"
    )

    assert parsed.correctness == 5
    assert parsed.groundedness == 4
    assert parsed.completeness == 3
    assert parsed.coverage_of_required_fields == 2
    assert parsed.source_consistency == 1
    assert parsed.comment == "ok"


@pytest.mark.asyncio
async def test_evaluator_uses_compact_prompt_and_timeout():
    provider = EvaluationSpyLLMProvider()
    evaluator = DigestEvaluator(provider, timeout_seconds=17)
    source_messages = [
        {
            "author_display_name": "Максим",
            "message_type": "text",
            "text": f"message {idx} with a plan to meet at 19:00 and discuss the project in detail",
        }
        for idx in range(1, 121)
    ]

    result = await evaluator.evaluate(digest="Краткий дайджест.", source_messages=source_messages)

    assert result.correctness == 5
    assert provider.last_timeout_seconds == 17
    assert len(provider.last_prompt) < 12000
    assert "message 1" in provider.last_prompt
    assert "message 120" in provider.last_prompt
