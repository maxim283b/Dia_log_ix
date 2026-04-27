from __future__ import annotations

import pytest

from app.agent.state import AgentState
from app.agent.tools import AgentTools
from app.llm.providers import MockLLMProvider
from app.repositories.messages import MessageRepository
from app.transcription.providers import MockTranscriptionProvider
from app.utils.digest import build_digest_prompt, render_structured_digest
from tests.conftest import seed_message, seed_user_chat


@pytest.mark.asyncio
async def test_serialize_messages_and_prompt_include_participant_names(session):
    chat, user = await seed_user_chat(session, user_id=2001, bot=False)
    user.first_name = "Максим"
    user.last_name = "Борисов"
    user.username = "maxim_b"
    await session.flush()
    await seed_message(session, chat=chat, user=user, telegram_message_id=1, text="я хочу протестировать агента")
    await session.commit()

    repo = MessageRepository(session)
    tools = AgentTools(
        message_repository=repo,
        llm_provider=MockLLMProvider(),
        transcription_provider=MockTranscriptionProvider(),
    )
    messages = await repo.get_messages_from(chat.id, start_telegram_message_id=0, before_telegram_message_id=2)
    serialized = tools.serialize_messages(messages)
    prompt = build_digest_prompt(serialized)

    assert serialized[0]["author_display_name"] == "Максим Борисов"
    assert serialized[0]["author_username"] == "maxim_b"
    assert "Максим Борисов" in prompt
    assert "@maxim_b" in prompt


@pytest.mark.asyncio
async def test_serialize_messages_uses_transcription_as_resolved_text(session):
    chat, user = await seed_user_chat(session, user_id=2003, bot=False)
    message = await seed_message(
        session,
        chat=chat,
        user=user,
        telegram_message_id=1,
        text=None,
        message_type="video_note",
    )
    message.transcribed_text = "В голосовом сказали встретиться в 19:00."
    await session.commit()

    repo = MessageRepository(session)
    tools = AgentTools(
        message_repository=repo,
        llm_provider=MockLLMProvider(),
        transcription_provider=MockTranscriptionProvider(),
    )
    messages = await repo.get_messages_from(chat.id, start_telegram_message_id=0, before_telegram_message_id=2)
    serialized = tools.serialize_messages(messages)

    assert serialized[0]["resolved_text"] == "В голосовом сказали встретиться в 19:00."


def test_digest_prompt_prevents_media_overgeneralization():
    prompt = build_digest_prompt(
        [
            {
                "author_display_name": "Максим Борисов",
                "author_username": "maxim_b",
                "date": "2026-04-24T09:30:00+00:00",
                "message_type": "voice",
                "resolved_text": "Я немножко травмировался. Сейчас восстанавливаюсь и на следующей неделе планирую вернуться обратно на ковёр.",
                "text": None,
            }
        ]
    )

    assert "Do not turn a personal status update into a new story" in prompt
    assert "preserve them separately instead of merging them into a generic summary" in prompt
    assert "faithful paraphrase over abstraction" in prompt
    assert "All output must be in Russian" in prompt


@pytest.mark.asyncio
async def test_generate_digest_falls_back_when_llm_returns_empty_json(session):
    chat, user = await seed_user_chat(session, user_id=2002, bot=False)
    user.first_name = "Максим"
    user.last_name = "Борисов"
    await session.flush()
    await seed_message(session, chat=chat, user=user, telegram_message_id=1, text="мы едем в винницы 29 апреля")
    await seed_message(session, chat=chat, user=user, telegram_message_id=2, text="я в основном люблю ужасы")
    await session.commit()

    class EmptyJsonLLMProvider(MockLLMProvider):
        async def generate_json(self, *, system: str, prompt: str, timeout_seconds: int | None = None) -> dict:
            return {}

    repo = MessageRepository(session)
    tools = AgentTools(
        message_repository=repo,
        llm_provider=EmptyJsonLLMProvider(),
        transcription_provider=MockTranscriptionProvider(),
    )
    messages = await repo.get_messages_from(chat.id, start_telegram_message_id=0, before_telegram_message_id=3)
    digest = await tools.generate_digest(
        state=AgentState(objective="digest", chat_id=chat.id, user_id=user.id),
        messages=messages,
    )

    assert "Сводка" in digest
    assert "Темы" in digest
    assert "Винницы" in digest or "29 апреля" in digest or "ужасы" in digest


def test_fallback_summary_prefers_informative_messages():
    from app.agent.tools import _fallback_summary_from_messages, _fallback_topics_from_messages

    messages = [
        {"author_display_name": "Максим Борисов", "text": "привет", "resolved_text": "привет", "author_is_bot": False},
        {
            "author_display_name": "Максим Борисов",
            "text": "мы едем 29 апреля в Винницы и покупаем билеты",
            "resolved_text": "мы едем 29 апреля в Винницы и покупаем билеты",
            "author_is_bot": False,
        },
        {
            "author_display_name": "Максим Борисов",
            "text": "после тренировки люблю смотреть ужасы",
            "resolved_text": "после тренировки люблю смотреть ужасы",
            "author_is_bot": False,
        },
    ]
    topics = _fallback_topics_from_messages(messages)
    summary = _fallback_summary_from_messages(messages, topics)

    assert "Винницы" in summary
    assert "29 апреля" in summary
    assert "ужасы" in summary


def test_fallback_topics_ignores_untranscribed_media():
    from app.agent.tools import _fallback_topics_from_messages

    topics = _fallback_topics_from_messages(
        [
            {
                "author_display_name": "Максим Борисов",
                "message_type": "video_note",
                "text": None,
                "transcribed_text": None,
                "resolved_text": None,
            }
        ]
    )

    assert all("медиа" not in topic["title"].lower() for topic in topics)


def test_render_structured_digest_omits_evidence():
    digest = render_structured_digest(
        {
            "summary": "Максим обсуждает погоду и кошку.",
            "topics": [
                {
                    "title": "Погода",
                    "who_said_what": "Максим предпочитает солнечную погоду.",
                    "evidence": "raw message text",
                }
            ],
            "decisions": [],
            "tasks": [],
            "open_questions": [],
            "warnings": [],
        }
    )

    assert "evidence:" not in digest.lower()
    assert "raw message text" not in digest
    assert "Погода" in digest
    assert "Сводка" in digest
    assert "Темы" in digest
    assert "Решения" in digest
    assert "Задачи" in digest
    assert "Открытые вопросы" in digest
    assert "Предупреждения" in digest
    assert "**" not in digest


def test_render_structured_digest_skips_who_only_tasks_and_cleans_markdown():
    digest = render_structured_digest(
        {
            "summary": "**Краткая сводка**",
            "topics": [],
            "decisions": [{"who": "Артемий", "text": ""}],
            "tasks": [{"who": "Артемий", "what": ""}],
            "open_questions": [{"who": "Максим", "question": "**Что дальше?**"}],
            "warnings": ["**Нет предупреждений**"],
        }
    )

    assert "**" not in digest
    assert "Артемий" not in digest.split("Задачи", 1)[1]
    assert "Что дальше?" in digest
    assert "Нет предупреждений" in digest


def test_time_based_plans_are_extracted_as_tasks():
    from app.agent.tools import _extract_tasks_from_messages

    messages = [
        {
            "author_display_name": "Максим Борисов",
            "text": "собираюсь встретиться с друзьями в 19:00 и сходить в новое заведение",
            "resolved_text": "собираюсь встретиться с друзьями в 19:00 и сходить в новое заведение",
            "message_type": "text",
        }
    ]

    tasks = _extract_tasks_from_messages(messages)

    assert tasks
    assert "19:00" in tasks[0]["what"]
    assert "встретиться" in tasks[0]["what"]
