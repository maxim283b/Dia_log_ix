from __future__ import annotations

import pytest

from app.agent.evaluator import DigestEvaluator
from app.agent.runner import AgentRunner, BaselineRunner
from app.agent.tools import AgentTools
from app.llm.base import LLMResponse
from app.llm.providers import MockLLMProvider
from app.repositories.agent_runs import AgentRunRepository
from app.repositories.messages import MessageRepository
from app.transcription.providers import MockTranscriptionProvider
from tests.conftest import seed_message, seed_user_chat


class TimeoutOnJsonLLMProvider(MockLLMProvider):
    async def generate_text(self, *, system: str, prompt: str) -> LLMResponse:
        return LLMResponse(text="1. Summary\nFallback digest")

    async def generate_json(self, *, system: str, prompt: str) -> dict:
        raise TimeoutError("timed out")


@pytest.mark.asyncio
async def test_baseline_runner(session):
    chat, user = await seed_user_chat(session)
    await seed_message(session, chat=chat, user=user, telegram_message_id=1, text="hello")
    await seed_message(session, chat=chat, user=user, telegram_message_id=2, text="plan the release")
    await seed_message(session, chat=chat, user=user, telegram_message_id=3, text="thanks")
    await session.commit()

    message_repo = MessageRepository(session)
    run_repo = AgentRunRepository(session)
    tools = AgentTools(
        message_repository=message_repo,
        llm_provider=MockLLMProvider(),
        transcription_provider=MockTranscriptionProvider(),
    )
    evaluator = DigestEvaluator(MockLLMProvider())
    runner = BaselineRunner(
        session=session,
        message_repository=message_repo,
        run_repository=run_repo,
        tools=tools,
        evaluator=evaluator,
    )

    run = await runner.run(
        chat_id=chat.id,
        user_id=user.id,
        objective="digest",
        start_message_id=1,
        end_message_id=4,
    )
    await session.commit()

    assert run.mode == "baseline"
    assert run.status == "completed"
    assert run.final_digest is not None
    assert "Сводка" in run.final_digest
    assert run.collected_messages and len(run.collected_messages) == 3


@pytest.mark.asyncio
async def test_agent_runner_with_mock_tools(session):
    chat, user = await seed_user_chat(session)
    await seed_message(session, chat=chat, user=user, telegram_message_id=1, text="initial")
    await seed_message(session, chat=chat, user=user, telegram_message_id=2, text="topic one")
    await seed_message(session, chat=chat, user=user, telegram_message_id=3, text="topic two")
    await session.commit()

    message_repo = MessageRepository(session)
    run_repo = AgentRunRepository(session)
    tools = AgentTools(
        message_repository=message_repo,
        llm_provider=MockLLMProvider(),
        transcription_provider=MockTranscriptionProvider(),
    )
    evaluator = DigestEvaluator(MockLLMProvider())
    runner = AgentRunner(
        session=session,
        tools=tools,
        run_repository=run_repo,
        evaluator=evaluator,
    )

    run = await runner.run(
        chat_id=chat.id,
        user_id=user.id,
        objective="digest",
        start_message_id=1,
        end_message_id=4,
    )
    await session.commit()

    assert run.mode == "agent"
    assert run.status == "completed"
    assert run.history is not None
    assert [step["action"] for step in run.history] == [
        "get_last_user_message",
        "get_messages_from",
        "transcribe_media_messages",
        "group_messages_by_topic",
        "extract_decisions",
        "extract_tasks",
        "extract_open_questions",
        "generate_digest",
        "evaluate_digest",
    ]


@pytest.mark.asyncio
async def test_baseline_runner_skips_evaluation_timeout(session):
    chat, user = await seed_user_chat(session)
    await seed_message(session, chat=chat, user=user, telegram_message_id=1, text="hello")
    await seed_message(session, chat=chat, user=user, telegram_message_id=2, text="plan the release")
    await session.commit()

    message_repo = MessageRepository(session)
    run_repo = AgentRunRepository(session)
    tools = AgentTools(
        message_repository=message_repo,
        llm_provider=TimeoutOnJsonLLMProvider(),
        transcription_provider=MockTranscriptionProvider(),
    )
    evaluator = DigestEvaluator(TimeoutOnJsonLLMProvider())
    runner = BaselineRunner(
        session=session,
        message_repository=message_repo,
        run_repository=run_repo,
        tools=tools,
        evaluator=evaluator,
    )

    run = await runner.run(
        chat_id=chat.id,
        user_id=user.id,
        objective="digest",
        start_message_id=1,
        end_message_id=3,
    )
    await session.commit()

    assert run.status == "completed"
    assert run.final_digest is not None
    assert "hello" in run.final_digest.lower() or "plan the release" in run.final_digest.lower()
