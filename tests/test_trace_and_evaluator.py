from __future__ import annotations

import pytest

from app.agent.evaluator import DigestEvaluator
from app.agent.runner import TraceRecorder
from app.llm.providers import MockLLMProvider
from app.models.agent_run import AgentRun


@pytest.mark.asyncio
async def test_trace_save(session):
    run = AgentRun(
        chat_id=1,
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

