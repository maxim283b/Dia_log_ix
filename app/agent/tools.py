from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.agent.state import AgentState
from app.llm.base import LLMProvider
from app.models.message import Message
from app.repositories.messages import MessageRepository
from app.transcription.base import TranscriptionProvider
from app.transcription.service import TelegramMediaTranscriber
from app.utils.digest import (
    build_digest_prompt,
    normalize_named_items,
    normalize_topic_items,
    render_structured_digest,
)

logger = logging.getLogger(__name__)


def _message_to_payload(message: Message) -> dict[str, Any]:
    author = message.user
    display_name_parts = [
        getattr(author, "first_name", None),
        getattr(author, "last_name", None),
    ]
    display_name = " ".join(part for part in display_name_parts if part)
    if not display_name:
        display_name = getattr(author, "username", None) or f"user_{message.user_id}"
    username = getattr(author, "username", None)
    return {
        "id": message.id,
        "telegram_message_id": message.telegram_message_id,
        "date": message.date.isoformat(),
        "message_type": message.message_type,
        "text": message.text,
        "file_id": message.file_id,
        "transcribed_text": message.transcribed_text,
        "user_id": message.user_id,
        "chat_id": message.chat_id,
        "author_display_name": display_name,
        "author_username": username,
        "author_is_bot": bool(getattr(author, "is_bot", False)) if author is not None else False,
    }


def _participant_from_message(message: Message) -> dict[str, Any]:
    author = message.user
    display_name = _message_to_payload(message)["author_display_name"]
    return {
        "user_id": message.user_id,
        "telegram_user_id": getattr(author, "telegram_user_id", None),
        "display_name": display_name,
        "username": getattr(author, "username", None),
        "is_bot": bool(getattr(author, "is_bot", False)) if author is not None else False,
    }


def _normalize_text(value: object | None) -> str:
    return str(value or "").strip()


def _message_score_for_fallback(message: dict[str, Any]) -> int:
    text = _normalize_text(message.get("resolved_text") or message.get("text"))
    score = len(text)
    lowered = text.lower()
    if any(char.isdigit() for char in text):
        score += 12
    if "?" in text:
        score += 10
    if any(keyword in lowered for keyword in ("план", "вопрос", "надо", "хочу", "нужно", "может", "сейчас", "сегодня", "завтра", "воскрес", "следующ")):
        score += 4
    if message.get("message_type") in {"voice", "audio", "video_note"}:
        score += 6
    if message.get("author_is_bot"):
        score -= 5
    if text.startswith("/"):
        score -= 20
    return score


def _best_message_snippets(messages: list[dict[str, Any]], limit: int = 3) -> list[str]:
    ranked = sorted(messages, key=_message_score_for_fallback, reverse=True)
    snippets: list[str] = []
    seen_texts: set[str] = set()
    for item in ranked:
        text = _normalize_text(item.get("resolved_text") or item.get("text"))
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        author = _normalize_text(item.get("author_display_name") or item.get("author") or "unknown")
        snippets.append(f"{author}: {text}")
        if len(snippets) >= limit:
            break
    return snippets


def _fallback_summary_from_messages(messages: list[dict[str, Any]], topics: list[dict[str, str]] | None = None) -> str:
    if not messages:
        return "Нет краткого резюме."
    if topics:
        topic_titles = [str(topic.get("title") or "").strip() for topic in topics[:3] if isinstance(topic, dict)]
        topic_titles = [title for title in topic_titles if title]
        snippets = _best_message_snippets(messages, limit=2)
        topic_part = "; ".join(topic_titles)
        snippet_part = " ".join(snippets)
        if topic_titles or snippets:
            base = "В чате обсуждаются " + (topic_part or "несколько конкретных тем")
            if snippet_part:
                return f"{base}: {snippet_part}"
            return base
    parts = _best_message_snippets(messages, limit=3)
    if not parts:
        return "В чате есть сообщения, но их содержимое не удалось кратко извлечь."
    joined = " ".join(parts)
    return f"В чате обсуждаются конкретные личные и бытовые вопросы: {joined}"


def _fallback_topics_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not messages:
        return []
    text_messages = [item for item in messages if (item.get("message_type") or "text") == "text"]
    media_messages = [item for item in messages if (item.get("message_type") or "text") in {"voice", "audio", "video_note"}]
    topics: list[dict[str, str]] = []
    if text_messages:
        topics.append(
            {
                "title": "Текстовый диалог",
                "who_said_what": "Участники обсуждают свои вопросы и отвечают друг другу в тексте.",
                "evidence": " ".join(
                    _normalize_text(item.get("resolved_text") or item.get("text"))
                    for item in text_messages[:3]
                )[:240],
            }
        )
    if media_messages:
        topics.append(
            {
                "title": "Голосовые и медиа-сообщения",
                "who_said_what": "Часть смысла передана через voice, audio или video note.",
                "evidence": " ".join(
                    _normalize_text(item.get("resolved_text") or item.get("text"))
                    for item in media_messages[:3]
                )[:240],
            }
        )
    if not topics:
        topics.append(
            {
                "title": "Обсуждение чата",
                "who_said_what": "Участники обмениваются сообщениями и уточняют детали.",
                "evidence": " ".join(
                    _normalize_text(item.get("resolved_text") or item.get("text"))
                    for item in messages[:3]
                )[:240],
            }
        )
    return topics


def _structured_digest_has_content(payload: dict[str, Any]) -> bool:
    summary = _normalize_text(payload.get("summary"))
    topics = payload.get("topics") or []
    decisions = payload.get("decisions") or []
    tasks = payload.get("tasks") or []
    open_questions = payload.get("open_questions") or []
    warnings = payload.get("warnings") or []
    return bool(summary) or any((topics, decisions, tasks, open_questions, warnings))


def _is_generic_summary(summary: str) -> bool:
    lowered = summary.strip().lower()
    if not lowered:
        return True
    generic_phrases = (
        "нет краткого резюме",
        "в чате обсуждаются",
        "чат обсуждает несколько конкретных тем",
        "конкретные личные и бытовые вопросы",
        "обсуждаются несколько конкретных тем",
        "свести в дайджест",
        "кратко и по-русски",
        "summary:",
        "topics:",
        "decisions:",
        "tasks:",
        "open questions:",
        "fallback digest",
        "discussed several topics",
    )
    if any(phrase in lowered for phrase in generic_phrases):
        return True
    return lowered.startswith("1. summary")


def _clean_snippet(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _extract_questions_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    questions: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in messages:
        text = _normalize_text(item.get("resolved_text") or item.get("text"))
        lowered = text.lower()
        if not text:
            continue
        if "?" not in text and not lowered.startswith(("как ", "когда ", "какой ", "какая ", "какие ", "почему ", "зачем ", "стоит ли", "может ли")):
            continue
        key = lowered[:160]
        if key in seen:
            continue
        seen.add(key)
        questions.append(
            {
                "who": _normalize_text(item.get("author_display_name") or item.get("author") or ""),
                "question": _clean_snippet(text, 180),
            }
        )
        if len(questions) >= 3:
            break
    return questions


def _extract_tasks_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    tasks: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in messages:
        text = _normalize_text(item.get("resolved_text") or item.get("text"))
        lowered = text.lower()
        if not text:
            continue
        if not any(keyword in lowered for keyword in ("надо", "нужно", "стоит", "планирую", "собираюсь", "хочу", "давай", "можно", "попробовать", "купить", "сделать", "перестать", "посмотреть")):
            continue
        key = lowered[:160]
        if key in seen:
            continue
        seen.add(key)
        tasks.append(
            {
                "who": _normalize_text(item.get("author_display_name") or item.get("author") or ""),
                "what": _clean_snippet(text, 180),
            }
        )
        if len(tasks) >= 3:
            break
    return tasks


def _extract_decisions_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    decisions: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in messages:
        text = _normalize_text(item.get("resolved_text") or item.get("text"))
        lowered = text.lower()
        if not text:
            continue
        if not any(keyword in lowered for keyword in ("решили", "договорились", "согласились", "ок", "ладно", "хорошо", "пусть", "будем")):
            continue
        key = lowered[:160]
        if key in seen:
            continue
        seen.add(key)
        decisions.append(
            {
                "who": _normalize_text(item.get("author_display_name") or item.get("author") or ""),
                "text": _clean_snippet(text, 180),
            }
        )
        if len(decisions) >= 3:
            break
    return decisions


def _derive_summary_from_topics(payload: dict[str, Any], messages: list[dict[str, Any]] | None = None) -> str:
    topics = payload.get("topics") or []
    participants = payload.get("participants") or []
    descriptions: list[str] = []
    titles: list[str] = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        title = _normalize_text(topic.get("title") or topic.get("topic"))
        who_said_what = _normalize_text(topic.get("who_said_what") or topic.get("details") or topic.get("who"))
        if title and title not in titles:
            titles.append(title)
        if who_said_what and who_said_what not in descriptions:
            descriptions.append(who_said_what)
        if len(titles) >= 3:
            break
        if len(descriptions) >= 2:
            break
    participant_names: list[str] = []
    for participant in participants:
        if not isinstance(participant, dict):
            continue
        name = _normalize_text(participant.get("display_name") or participant.get("username") or participant.get("user_id"))
        if name and name not in participant_names:
            participant_names.append(name)
        if len(participant_names) >= 2:
            break
    generic_titles = {"Текстовый диалог", "Голосовые и медиа-сообщения", "Обсуждение чата"}
    if messages and (not descriptions or all(title in generic_titles for title in titles)):
        snippets = _best_message_snippets(messages, limit=2)
        if snippets:
            subject = " и ".join(participant_names) if participant_names else "Участники"
            verb = "обсуждали" if len(participant_names) != 1 else "обсуждал"
            return f"{subject} {verb} {snippets[0]}" if len(snippets) == 1 else f"{subject} {verb} {snippets[0]}; {snippets[1]}"
    if participant_names and descriptions:
        subject = " и ".join(participant_names)
        verb = "обсуждал" if len(participant_names) == 1 else "обсуждали"
        return f"{subject} {verb} {', '.join(descriptions)}."
    if descriptions:
        return f"В чате обсуждали: {', '.join(descriptions)}."
    if participant_names and titles:
        subject = " и ".join(participant_names)
        verb = "обсуждал" if len(participant_names) == 1 else "обсуждали"
        return f"{subject} {verb} {', '.join(titles)}."
    if titles:
        return f"В чате обсуждали {', '.join(titles)}."
    return "В чате обсуждаются несколько конкретных тем."


def _render_from_agent_state(
    *,
    participants: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    topics: list[Any],
    decisions: list[Any],
    tasks: list[Any],
    open_questions: list[Any],
    summary_override: str | None = None,
    warnings: list[str] | None = None,
) -> str:
    normalized_topics = normalize_topic_items(topics)
    normalized_decisions = normalize_named_items(decisions, text_keys=("text", "decision", "title"), who_keys=("who", "owner"))
    normalized_tasks = normalize_named_items(tasks, text_keys=("what", "task", "text"), who_keys=("who", "owner"))
    normalized_questions = normalize_named_items(open_questions, text_keys=("question", "text"), who_keys=("who", "author"))
    summary = summary_override or _derive_summary_from_topics(
        {
            "topics": normalized_topics,
            "participants": participants,
        },
        messages,
    )
    return render_structured_digest(
        {
            "summary": summary,
            "topics": normalized_topics,
            "decisions": normalized_decisions,
            "tasks": normalized_tasks,
            "open_questions": normalized_questions,
            "warnings": warnings or [],
        }
    )


class AgentTools:
    def __init__(
        self,
        *,
        message_repository: MessageRepository,
        llm_provider: LLMProvider,
        transcription_provider: TranscriptionProvider,
        media_transcriber: TelegramMediaTranscriber | None = None,
    ) -> None:
        self.message_repository = message_repository
        self.llm_provider = llm_provider
        self.transcription_provider = transcription_provider
        self.media_transcriber = media_transcriber

    async def get_last_user_message(self, *, chat_id: int, user_id: int, before_message_id: int) -> Message | None:
        return await self.message_repository.get_last_user_message_before(chat_id, user_id, before_message_id)

    async def get_messages_after(
        self,
        *,
        chat_id: int,
        start_message_id: int,
        before_message_id: int | None = None,
    ) -> list[Message]:
        return await self.message_repository.get_messages_after(chat_id, start_message_id, before_message_id)

    async def get_messages_from(
        self,
        *,
        chat_id: int,
        start_message_id: int,
        before_message_id: int | None = None,
    ) -> list[Message]:
        return await self.message_repository.get_messages_from(chat_id, start_message_id, before_message_id)

    async def transcribe_media_messages(self, messages: list[Message]) -> list[dict]:
        results: list[dict] = []
        for message in messages:
            if not message.file_id or message.message_type not in {"voice", "audio", "video_note"}:
                continue
            if message.transcribed_text:
                results.append({"telegram_message_id": message.telegram_message_id, "text": message.transcribed_text})
                continue
            if self.media_transcriber is not None:
                try:
                    text = await self.media_transcriber.transcribe_message(message)
                except Exception as exc:
                    logger.warning("Failed to transcribe media message %s: %s", message.telegram_message_id, exc)
                    text = None
            else:
                try:
                    result = await self.transcription_provider.transcribe(
                        audio_bytes=b"",
                        filename=f"{message.file_id}.{message.message_type}",
                        mime_type=None,
                    )
                    text = result.text
                except Exception as exc:
                    logger.warning("Failed to transcribe media message %s: %s", message.telegram_message_id, exc)
                    text = None
            message.transcribed_text = text
            if text:
                results.append({"telegram_message_id": message.telegram_message_id, "text": text})
        return results

    async def group_messages_by_topic(self, messages: list[Message]) -> list[dict]:
        payload = [
            {
                "telegram_message_id": m.telegram_message_id,
                "author_display_name": _message_to_payload(m)["author_display_name"],
                "author_username": _message_to_payload(m)["author_username"],
                "text": m.text or m.transcribed_text,
                "message_type": m.message_type,
            }
            for m in messages
        ]
        try:
            logger.info("Grouping messages by topic: count=%s", len(payload))
            started = time.perf_counter()
            result = await self.llm_provider.generate_json(
                system=(
                    "Сгруппируй сообщения Telegram-чата по темам. "
                    "Верни строгий JSON с массивом 'topics'. "
                    "Не придумывай темы, которых нет в сообщениях. "
                    "Все поля, заголовки и краткие описания должны быть на русском языке. "
                    "По возможности укажи, кто что сказал, внутри описания темы."
                ),
                prompt=f"Messages JSON: {payload}",
            )
            topics = result.get("topics", [])
            if topics:
                logger.info(
                    "Grouped messages by topic: topics=%s latency_ms=%s",
                    len(topics),
                    int((time.perf_counter() - started) * 1000),
                )
                return topics
        except Exception as exc:
            logger.warning("Failed to group messages by topic: %s", exc)
        return [{"title": "General", "messages": payload}]

    async def extract_decisions(self, messages: list[Message]) -> list[dict]:
        payload = [
            {
                "telegram_message_id": m.telegram_message_id,
                "author_display_name": _message_to_payload(m)["author_display_name"],
                "author_username": _message_to_payload(m)["author_username"],
                "text": m.text or m.transcribed_text,
            }
            for m in messages
        ]
        try:
            logger.info("Extracting decisions: count=%s", len(payload))
            started = time.perf_counter()
            result = await self.llm_provider.generate_json(
                system=(
                    "Извлеки только явные решения из обсуждения. "
                    "Верни строгий JSON с массивом 'decisions'. "
                    "Если решений нет, верни пустой массив. "
                    "Каждое решение и имя участника должны быть на русском языке, если имя известно."
                ),
                prompt=f"Messages JSON: {payload}",
            )
            decisions = result.get("decisions", [])
            logger.info(
                "Extracted decisions: count=%s latency_ms=%s",
                len(decisions),
                int((time.perf_counter() - started) * 1000),
            )
            return decisions
        except Exception as exc:
            logger.warning("Failed to extract decisions: %s", exc)
            return []

    async def extract_tasks(self, messages: list[Message]) -> list[dict]:
        payload = [
            {
                "telegram_message_id": m.telegram_message_id,
                "author_display_name": _message_to_payload(m)["author_display_name"],
                "author_username": _message_to_payload(m)["author_username"],
                "text": m.text or m.transcribed_text,
            }
            for m in messages
        ]
        try:
            logger.info("Extracting tasks: count=%s", len(payload))
            started = time.perf_counter()
            result = await self.llm_provider.generate_json(
                system=(
                    "Извлеки только явные задачи или действия из обсуждения. "
                    "Верни строгий JSON с массивом 'tasks'. "
                    "Если задач нет, верни пустой массив. "
                    "Сохраняй имя участника в каждой задаче, если оно известно. "
                    "Предпочитай поля who/owner, what, deadline. "
                    "Все текстовые поля должны быть на русском языке."
                ),
                prompt=f"Messages JSON: {payload}",
            )
            tasks = result.get("tasks", [])
            logger.info(
                "Extracted tasks: count=%s latency_ms=%s",
                len(tasks),
                int((time.perf_counter() - started) * 1000),
            )
            return tasks
        except Exception as exc:
            logger.warning("Failed to extract tasks: %s", exc)
            return []

    async def extract_open_questions(self, messages: list[Message]) -> list[dict]:
        payload = [
            {
                "telegram_message_id": m.telegram_message_id,
                "author_display_name": _message_to_payload(m)["author_display_name"],
                "author_username": _message_to_payload(m)["author_username"],
                "text": m.text or m.transcribed_text,
            }
            for m in messages
        ]
        try:
            logger.info("Extracting open questions: count=%s", len(payload))
            started = time.perf_counter()
            result = await self.llm_provider.generate_json(
                system=(
                    "Извлеки только открытые вопросы, неопределённости, просьбы о прояснении или нерешённые сомнения. "
                    "Верни строгий JSON с массивом 'open_questions'. "
                    "Если открытых вопросов нет, верни пустой массив. "
                    "Сохраняй имя участника, если оно известно. "
                    "Предпочитай поля who, question, context. "
                    "Все текстовые поля должны быть на русском языке."
                ),
                prompt=f"Messages JSON: {payload}",
            )
            open_questions = result.get("open_questions", [])
            logger.info(
                "Extracted open questions: count=%s latency_ms=%s",
                len(open_questions),
                int((time.perf_counter() - started) * 1000),
            )
            return open_questions
        except Exception as exc:
            logger.warning("Failed to extract open questions: %s", exc)
            return []

    async def generate_digest(self, *, state: AgentState, messages: list[Message]) -> str:
        payload = self.serialize_messages(messages)
        participants = self.serialize_participants(messages)
        topics = state.grouped_topics or _fallback_topics_from_messages(payload)
        decisions = state.decisions or _extract_decisions_from_messages(payload)
        tasks = state.tasks or _extract_tasks_from_messages(payload)
        open_questions = state.open_questions or _extract_questions_from_messages(payload)
        warnings: list[str] = []
        logger.info(
            "Generating digest: participants=%s messages=%s topics=%s decisions=%s tasks=%s open_questions=%s",
            len(participants),
            len(payload),
            len(topics),
            len(decisions),
            len(tasks),
            len(open_questions),
        )

        # Ask the LLM only for a better summary over already extracted structure.
        try:
            started = time.perf_counter()
            summary_response = await self.llm_provider.generate_text(
                system=(
                    "Напиши краткую, но конкретную сводку на русском языке для дайджеста Telegram-чата. "
                    "Используй только предоставленные структурированные данные и фрагменты сообщений. "
                    "Не придумывай факты. "
                    "Не используй английский язык ни в сводке, ни в названиях тем, ни в формулировках полей. "
                    "Сохраняй имена, даты и числовые факты как есть. "
                    "Ограничься 1-3 предложениями."
                ),
                prompt=json.dumps(
                    {
                        "participants": participants,
                        "topics": topics,
                        "decisions": decisions,
                        "tasks": tasks,
                        "open_questions": open_questions,
                        "messages": payload[:12],
                    },
                    ensure_ascii=False,
                ),
            )
            summary_text = _normalize_text(summary_response.text)
            if summary_text and not _is_generic_summary(summary_text):
                logger.info(
                    "Digest summary accepted from LLM: summary_len=%s latency_ms=%s",
                    len(summary_text),
                    int((time.perf_counter() - started) * 1000),
                )
                return _render_from_agent_state(
                    participants=participants,
                    messages=payload,
                    topics=topics,
                    decisions=decisions,
                    tasks=tasks,
                    open_questions=open_questions,
                    summary_override=summary_text,
                    warnings=warnings,
                )
            warnings.append("LLM summary was empty or too generic, so the digest summary was assembled from extracted state.")
            logger.info(
                "Digest summary rejected as generic: summary_len=%s latency_ms=%s",
                len(summary_text),
                int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            logger.warning("Failed to generate digest summary via LLM: %s", exc)
            warnings.append(f"LLM summary request failed: {exc}")

        logger.info("Digest rendered from structured state: warnings=%s", len(warnings))
        return _render_from_agent_state(
            participants=participants,
            messages=payload,
            topics=topics,
            decisions=decisions,
            tasks=tasks,
            open_questions=open_questions,
            warnings=warnings,
        )

    async def evaluate_digest(self, *, digest: str, source_messages: list[Message]) -> dict:
        payload = {
            "digest": digest,
            "source_messages": [m.text or m.transcribed_text for m in source_messages],
        }
        logger.info(
            "Evaluating digest: digest_len=%s source_messages=%s",
            len(digest or ""),
            len(source_messages),
        )
        started = time.perf_counter()
        result = await self.llm_provider.generate_json(
            system="Evaluate the digest and return JSON with scoring fields.",
            prompt=str(payload),
        )
        logger.info("Digest evaluation completed: latency_ms=%s", int((time.perf_counter() - started) * 1000))
        return result

    def serialize_messages(self, messages: list[Message]) -> list[dict]:
        return [_message_to_payload(message) for message in messages]

    def serialize_participants(self, messages: list[Message]) -> list[dict]:
        seen: set[int | None] = set()
        participants: list[dict[str, Any]] = []
        for message in messages:
            if message.user_id in seen:
                continue
            seen.add(message.user_id)
            participants.append(_participant_from_message(message))
        return participants
