from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def format_messages_for_digest(messages: Iterable[dict]) -> str:
    lines: list[str] = []
    for item in messages:
        author = item.get("author_display_name") or item.get("author") or "unknown"
        stamp = item.get("date") or ""
        text = item.get("resolved_text") or item.get("text") or ""
        lines.append(f"[{stamp}] {author}: {text}")
    return "\n".join(lines)


def messages_to_digest_payload(messages: Iterable[dict]) -> dict:
    return {
        "message_count": sum(1 for _ in messages),
    }


def build_digest_prompt(messages: list[dict], language_hint: str = "ru", structured_output: bool = False) -> str:
    transcript = format_messages_for_digest(messages)
    message_count = len(messages)
    participants: list[str] = []
    seen: set[str] = set()
    for item in messages:
        display_name = str(item.get("author_display_name") or item.get("author") or "").strip()
        username = str(item.get("author_username") or "").strip()
        if not display_name:
            continue
        key = display_name.lower()
        if key in seen:
            continue
        seen.add(key)
        if username:
            participants.append(f"{display_name} (@{username.lstrip('@')})")
        else:
            participants.append(display_name)
    participants_block = ", ".join(participants) if participants else "unknown"
    text_count = sum(1 for item in messages if (item.get("message_type") or "text") == "text")
    voice_count = sum(1 for item in messages if item.get("message_type") == "voice")
    audio_count = sum(1 for item in messages if item.get("message_type") == "audio")
    video_note_count = sum(1 for item in messages if item.get("message_type") == "video_note")
    base = (
        f"Language: {language_hint}\n"
        f"Collected message count: {message_count}\n"
        f"Participants: {participants_block}\n"
        f"Text messages: {text_count}\n"
        f"Voice messages: {voice_count}\n"
        f"Audio messages: {audio_count}\n"
        f"Video notes: {video_note_count}\n"
        "You are summarizing a Telegram group chat.\n"
        "Use ONLY the information present in the messages below.\n"
        "Do NOT invent meeting/project context, dates, decisions, or tasks.\n"
        "Do NOT say there is only one message if Collected message count is greater than 1.\n"
        "If there are voice messages or video notes, use their transcribed meaning as content, not as noise.\n"
        "For voice messages and video notes, keep concrete first-person facts: injuries, recovery, training history, weights, dates, return plans.\n"
        "Do not turn a personal status update into a new story about goals, competitions, or future plans unless those are explicitly stated.\n"
        "If a message has several separate facts, preserve them separately instead of merging them into a generic summary.\n"
        "If there are no explicit decisions, say so.\n"
        "If there are no tasks, say so.\n"
        "If the chat is casual or unrelated to work, summarize it literally, but still be specific.\n"
        "Keep numbers, dates, nicknames, and named entities exactly as written when possible.\n"
        "When a message clearly belongs to a participant, mention that participant by name in the summary or open questions.\n"
        "If a participant expresses a desire, concern, or uncertainty, phrase it as 'X хочет...' or 'X спрашивает...', where X is the participant's name if known.\n"
        "Prefer concrete wording over generic labels like 'general discussion' or 'personal matters'.\n"
        "Include notable facts, intent, and context from the conversation.\n"
        "Prefer faithful paraphrase over abstraction: 'Maxim says he is recovering from a minor injury and expects to return to the mat next week' is better than 'Maxim has sports plans'.\n"
        "If a short quote helps, include at most one brief quote in the 'Warnings' or 'Open questions' section.\n"
        "All output must be in Russian. Do not use English section names, English topic titles, or English labels for people, decisions, tasks, or questions.\n"
    )
    if structured_output:
        return (
            base
            + "The digest should be detailed but still concise enough to read in under a minute.\n"
            + "Return strict JSON only with these keys: summary, topics, decisions, tasks, open_questions, warnings.\n"
            + "summary: string in Russian.\n"
            + "topics: array of objects with title and who_said_what, both in Russian.\n"
            + "decisions: array of objects with who and text, both in Russian.\n"
            + "tasks: array of objects with who, what, deadline, all in Russian except names, dates, and proper nouns that should stay as written.\n"
            + "open_questions: array of objects with who and question, both in Russian.\n"
            + "warnings: array of strings in Russian.\n\n"
            + f"Messages:\n{transcript}"
        )
    return base + "The digest should be detailed but still concise enough to read in under a minute.\n" + f"Messages:\n{transcript}"


def render_structured_digest(payload: dict[str, Any]) -> str:
    summary = str(payload.get("summary") or "Нет краткого резюме.").strip()
    topics = payload.get("topics") or []
    decisions = payload.get("decisions") or []
    tasks = payload.get("tasks") or []
    open_questions = payload.get("open_questions") or []
    warnings = payload.get("warnings") or []

    lines: list[str] = []
    lines.append("Сводка")
    lines.append(summary)
    lines.append("")
    lines.append("Темы")
    if topics:
        for idx, topic in enumerate(topics, start=1):
            if isinstance(topic, dict):
                title = str(topic.get("title") or topic.get("topic") or "Без названия").strip()
                who = str(topic.get("who_said_what") or topic.get("details") or topic.get("who") or "").strip()
                parts = [title]
                if who:
                    parts.append(who)
                lines.append(f"{idx}. " + " — ".join(parts))
            else:
                lines.append(f"{idx}. {str(topic).strip()}")
    else:
        lines.append("Тем нет.")
    lines.append("")
    lines.append("Решения")
    if decisions:
        for idx, decision in enumerate(decisions, start=1):
            if isinstance(decision, dict):
                who = str(decision.get("who") or decision.get("owner") or "").strip()
                text = str(decision.get("text") or decision.get("decision") or "").strip()
                if who and text:
                    lines.append(f"{idx}. {who}: {text}")
                else:
                    lines.append(f"{idx}. {text or who or 'Без деталей'}")
            else:
                lines.append(f"{idx}. {str(decision).strip()}")
    else:
        lines.append("Явных решений нет.")
    lines.append("")
    lines.append("Задачи")
    if tasks:
        for idx, task in enumerate(tasks, start=1):
            if isinstance(task, dict):
                who = str(task.get("who") or task.get("owner") or "").strip()
                what = str(task.get("what") or task.get("task") or "").strip()
                deadline = str(task.get("deadline") or task.get("when") or "").strip()
                parts = []
                if who:
                    parts.append(who)
                if what:
                    parts.append(what)
                if deadline:
                    parts.append(f"deadline: {deadline}")
                lines.append(f"{idx}. " + " — ".join(parts or ["Без деталей"]))
            else:
                lines.append(f"{idx}. {str(task).strip()}")
    else:
        lines.append("Явных задач нет.")
    lines.append("")
    lines.append("Открытые вопросы")
    if open_questions:
        for idx, question in enumerate(open_questions, start=1):
            if isinstance(question, dict):
                who = str(question.get("who") or question.get("author") or "").strip()
                text = str(question.get("question") or question.get("text") or "").strip()
                if who and text:
                    lines.append(f"{idx}. {who}: {text}")
                else:
                    lines.append(f"{idx}. {text or who or 'Без деталей'}")
            else:
                lines.append(f"{idx}. {str(question).strip()}")
    else:
        lines.append("Открытых вопросов нет.")
    lines.append("")
    lines.append("Предупреждения")
    if warnings:
        for idx, warning in enumerate(warnings, start=1):
            lines.append(f"{idx}. {str(warning).strip()}")
    else:
        lines.append("Предупреждений нет.")
    return "\n".join(lines)


def normalize_topic_items(topics: list[Any]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for topic in topics:
        if isinstance(topic, dict):
            title = str(topic.get("title") or topic.get("topic") or "").strip()
            who_said_what = str(topic.get("who_said_what") or topic.get("details") or topic.get("who") or "").strip()
        else:
            title = str(topic).strip()
            who_said_what = ""
        if not title and not who_said_what:
            continue
        key = (title.lower(), who_said_what.lower())
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"title": title or "Тема", "who_said_what": who_said_what})
    return normalized


def normalize_named_items(items: list[Any], *, text_keys: tuple[str, ...], who_keys: tuple[str, ...]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if isinstance(item, dict):
            who = ""
            text = ""
            for key in who_keys:
                value = str(item.get(key) or "").strip()
                if value:
                    who = value
                    break
            for key in text_keys:
                value = str(item.get(key) or "").strip()
                if value:
                    text = value
                    break
        else:
            who = ""
            text = str(item).strip()
        if not who and not text:
            continue
        key = (who.lower(), text.lower())
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"who": who, "text": text})
    return normalized
