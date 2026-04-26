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
    async def generate_text(self, *, system: str, prompt: str, timeout_seconds: int | None = None) -> LLMResponse:
        return LLMResponse(text="1. Summary\nFallback digest")

    async def generate_json(self, *, system: str, prompt: str, timeout_seconds: int | None = None) -> dict:
        raise TimeoutError("timed out")


class TopicSpyLLMProvider(MockLLMProvider):
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
        return {"topics": [{"title": "Тестовая тема", "who_said_what": "Короткое описание."}]}


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
        chat_telegram_id=chat.telegram_chat_id,
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
        chat_telegram_id=chat.telegram_chat_id,
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
        chat_telegram_id=chat.telegram_chat_id,
        user_id=user.id,
        objective="digest",
        start_message_id=1,
        end_message_id=3,
    )
    await session.commit()

    assert run.status == "completed"
    assert run.final_digest is not None
    assert "hello" in run.final_digest.lower() or "plan the release" in run.final_digest.lower()


@pytest.mark.asyncio
async def test_group_messages_by_topic_uses_compact_prompt_and_short_timeout(session):
    chat, user = await seed_user_chat(session)
    for idx in range(1, 131):
        await seed_message(
            session,
            chat=chat,
            user=user,
            telegram_message_id=idx,
            text=f"message {idx} with a plan to meet at 19:00 and discuss the project in detail",
        )
    await session.commit()

    message_repo = MessageRepository(session)
    tools = AgentTools(
        message_repository=message_repo,
        llm_provider=TopicSpyLLMProvider(),
        transcription_provider=MockTranscriptionProvider(),
        llm_topics_timeout_seconds=33,
    )
    messages = await message_repo.get_messages_from(chat.id, start_telegram_message_id=0, before_telegram_message_id=200)

    topics = await tools.group_messages_by_topic(messages)

    assert topics and topics[0]["title"] == "Тестовая тема"
    assert tools.llm_provider.last_timeout_seconds == 33
    assert len(tools.llm_provider.last_prompt) < 20000
    assert "message 1" in tools.llm_provider.last_prompt
    assert "message 130" in tools.llm_provider.last_prompt
