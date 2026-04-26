from __future__ import annotations

from dataclasses import dataclass
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.exc import IntegrityError

from app.agent.evaluator import DigestEvaluator
from app.agent.runner import AgentRunner, BaselineRunner
from app.agent.tools import AgentTools
from app.config import Settings
from app.llm.providers import MockLLMProvider, OpenAICompatibleLLMProvider
from app.repositories.agent_runs import AgentRunRepository
from app.repositories.chats import ChatRepository
from app.repositories.messages import MessageRepository
from app.repositories.users import UserRepository
from app.transcription.providers import (
    FasterWhisperTranscriptionProvider,
    MockTranscriptionProvider,
    SimpleHTTPTranscriptionProvider,
)
from app.transcription.service import TelegramMediaTranscriber
from app.utils.digest import build_clarification_prompt
from app.utils.telegram import get_message_text, is_command_message, is_digest_trigger

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BotServices:
    session_factory: object
    settings: Settings
    llm_provider: object
    transcription_provider: object


def build_llm_provider(settings: Settings):
    if settings.llm_model == "mock" or not settings.llm_base_url:
        return MockLLMProvider()
    return OpenAICompatibleLLMProvider(
        settings.llm_base_url,
        settings.llm_api_key,
        settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def build_transcription_provider(settings: Settings):
    mode = settings.transcription_mode.lower()
    if mode == "mock":
        return MockTranscriptionProvider()
    if mode == "faster_whisper":
        return FasterWhisperTranscriptionProvider(settings.transcription_model)
    if not settings.transcription_base_url:
        raise RuntimeError("TRANSCRIPTION_BASE_URL is required for HTTP transcription mode")
    return SimpleHTTPTranscriptionProvider(
        base_url=settings.transcription_base_url,
        api_key=settings.transcription_api_key,
        model=settings.transcription_model,
    )


def build_bot(settings: Settings) -> Bot:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    session = AiohttpSession(proxy=settings.telegram_proxy_url or None)
    if not settings.telegram_ssl_verify:
        session._connector_init["ssl"] = False
    return Bot(token=settings.telegram_bot_token, session=session)


def build_dispatcher() -> Dispatcher:
    return Dispatcher()


async def setup_bot(session_factory, settings: Settings) -> tuple[Bot, Dispatcher]:
    bot = build_bot(settings)
    logger.info(
        "Telegram bot initialized: proxy=%s ssl_verify=%s bot_username=%s",
        "enabled" if settings.telegram_proxy_url else "disabled",
        settings.telegram_ssl_verify,
        settings.bot_username or "<auto>",
    )
    if not settings.bot_username:
        try:
            me = await bot.get_me()
        except Exception:
            logger.warning("Failed to resolve bot username from Telegram API; using empty username")
        else:
            settings.bot_username = me.username or ""
    dispatcher = build_dispatcher()
    register_routes(dispatcher, bot, session_factory, settings)
    return bot, dispatcher


def register_routes(dispatcher: Dispatcher, bot: Bot, session_factory, settings: Settings) -> None:
    router = Router()

    @router.message(Command("start"))
    async def start_handler(message: Message) -> None:
        await message.answer(
            "Я собираю дайджесты групповых чатов.\n"
            "Команды: /help, /digest, /ask, /tasks, /decisions."
        )

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await message.answer(
            "Отправь /digest или упомяни бота в группе. "
            "После дайджеста можно задать уточняющий вопрос командой /ask <вопрос>."
        )

    @router.message(Command("digest"))
    async def digest_command(message: Message) -> None:
        await _handle_digest(message, bot, session_factory, settings)

    @router.message(Command("ask"))
    async def ask_handler(message: Message) -> None:
        await _handle_clarification(message, session_factory, settings)

    @router.message(Command("clarify"))
    async def clarify_handler(message: Message) -> None:
        await _handle_clarification(message, session_factory, settings)

    @router.message(Command("tasks"))
    async def tasks_handler(message: Message) -> None:
        await _handle_tasks(message, session_factory)

    @router.message(Command("decisions"))
    async def decisions_handler(message: Message) -> None:
        await _handle_decisions(message, session_factory)

    @router.message(F.chat.type.in_({"group", "supergroup"}), F.text.func(lambda text: not is_command_message(text)))
    async def store_group_message(message: Message) -> None:
        logger.debug(
            "Incoming group message: chat_id=%s message_id=%s user_id=%s text_len=%s",
            message.chat.id,
            message.message_id,
            getattr(message.from_user, "id", None),
            len(message.text or ""),
        )
        await _ingest_message(message, session_factory)
        if is_digest_trigger(message.text, settings.bot_username):
            logger.info("Digest trigger detected: chat_id=%s message_id=%s", message.chat.id, message.message_id)
            await _handle_digest(message, bot, session_factory, settings)

    dispatcher.include_router(router)


async def _ingest_message(message: Message, session_factory) -> None:
    if message.from_user is None or message.from_user.is_bot:
        return
    text = get_message_text(message)
    if is_command_message(text):
        return
    message_type = "voice" if message.voice else "audio" if message.audio else "video_note" if message.video_note else "text"
    logger.info(
        "Ingest message start: chat_id=%s message_id=%s user_id=%s type=%s text_len=%s",
        message.chat.id,
        message.message_id,
        getattr(message.from_user, "id", None),
        message_type,
        len(text or ""),
    )
    async with session_factory() as session:
        users = UserRepository(session)
        chats = ChatRepository(session)
        messages = MessageRepository(session)
        try:
            user = await users.get_or_create_from_payload(message.from_user)
            chat = await chats.get_or_create_from_payload(message.chat)
            await session.flush()
            existing = await messages.get_or_create_by_telegram_message_id(chat.id, message.message_id)
            if existing is not None:
                logger.debug("Skipping duplicate message: chat_db_id=%s message_id=%s", chat.id, message.message_id)
                return
            message_row = await messages.create(
                chat=chat,
                user=user,
                telegram_message_id=message.message_id,
                date=message.date,
                message_type=message_type,
                text=text,
                file_id=getattr(
                    getattr(message, "voice", None)
                    or getattr(message, "audio", None)
                    or getattr(message, "video_note", None),
                    "file_id",
                    None,
                ),
                transcribed_text=None,
                is_command=False,
                raw_json=message.model_dump(mode="json"),
            )
            await session.flush()
            await session.commit()
            logger.info(
                "Ingest message stored: chat_db_id=%s message_id=%s user_db_id=%s row_id=%s",
                chat.id,
                message.message_id,
                user.id,
                getattr(message_row, "id", None),
            )
            return
        except IntegrityError:
            await session.rollback()
            logger.exception("Failed to ingest message %s in chat %s", message.message_id, message.chat.id)
            return


async def _handle_digest(message: Message, bot: Bot, session_factory, settings: Settings) -> None:
    if message.from_user is None:
        return
    logger.info(
        "Digest requested: chat_id=%s message_id=%s user_id=%s text=%r",
        message.chat.id,
        message.message_id,
        message.from_user.id,
        (message.text or "")[:160],
    )
    async with session_factory() as session:
        llm = build_llm_provider(settings)
        transcription = build_transcription_provider(settings)
        media_transcriber = TelegramMediaTranscriber(bot, transcription)
        message_repo = MessageRepository(session)
        run_repo = AgentRunRepository(session)
        tools = AgentTools(
            message_repository=message_repo,
            llm_provider=llm,
            transcription_provider=transcription,
            media_transcriber=media_transcriber,
            llm_summary_timeout_seconds=settings.llm_summary_timeout_seconds,
            llm_topics_timeout_seconds=settings.llm_topics_timeout_seconds,
            llm_extraction_timeout_seconds=settings.llm_extraction_timeout_seconds,
        )
        evaluator = DigestEvaluator(llm)
        user_repo = UserRepository(session)
        chat_repo = ChatRepository(session)
        user = await user_repo.get_or_create_from_payload(message.from_user)
        chat = await chat_repo.get_or_create_from_payload(message.chat)
        await session.flush()
        start = await message_repo.get_last_user_message_before(chat.id, user.id, message.message_id)
        start_message_id = start.telegram_message_id if start else 0
        lowered_text = (message.text or "").lower()
        mode = "baseline" if "baseline" in lowered_text else "agent"
        logger.info(
            "Digest window resolved: chat_db_id=%s chat_telegram_id=%s user_db_id=%s mode=%s start_message_id=%s end_message_id=%s",
            chat.id,
            chat.telegram_chat_id,
            user.id,
            mode,
            start_message_id,
            message.message_id,
        )
        if mode == "agent":
            runner = AgentRunner(session=session, tools=tools, run_repository=run_repo, evaluator=evaluator)
        else:
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
            objective="Generate a digest of the conversation",
            start_message_id=start_message_id,
            end_message_id=message.message_id,
        )
        await session.commit()
        logger.info(
            "Digest completed: run_id=%s status=%s stop_reason=%s digest_len=%s",
            run.id,
            run.status,
            run.stop_reason,
            len(run.final_digest or ""),
        )
        await message.answer(run.final_digest or "Дайджест не удалось сформировать.")


async def _handle_clarification(message: Message, session_factory, settings: Settings) -> None:
    if message.chat is None:
        return
    question = _extract_command_arguments(message.text or "")
    if not question:
        await message.answer("Напиши вопрос после команды, например: /ask кто что предложил?")
        return
    logger.info(
        "Clarification requested: chat_id=%s message_id=%s question=%r",
        message.chat.id,
        message.message_id,
        question[:160],
    )
    async with session_factory() as session:
        run_repo = AgentRunRepository(session)
        run = await run_repo.get_latest_completed(message.chat.id)
        if run is None or not run.final_digest:
            await message.answer("Сначала сформируй дайджест командой /digest.")
            return
        llm = build_llm_provider(settings)
        prompt = build_clarification_prompt(
            digest=run.final_digest,
            question=question,
            messages=run.collected_messages or [],
        )
        try:
            response = await llm.generate_text(
                system=(
                    "You answer clarification questions about a Telegram chat digest. "
                    "Use only the provided digest and messages."
                ),
                prompt=prompt,
            )
            answer = (response.text or "").strip()
        except Exception as exc:
            logger.exception("Failed to generate clarification answer: %s", exc)
            answer = ""
        if not answer:
            answer = (
                "Не удалось получить уточнение от модели. "
                f"Последний дайджест:\n{run.final_digest}"
            )
        logger.info(
            "Clarification answered: chat_id=%s run_id=%s answer_len=%s",
            message.chat.id,
            run.id,
            len(answer),
        )
        await message.answer(answer)


async def _handle_tasks(message: Message, session_factory) -> None:
    if message.chat is None:
        return
    logger.info("Tasks requested: chat_id=%s message_id=%s", message.chat.id, message.message_id)
    async with session_factory() as session:
        run_repo = AgentRunRepository(session)
        run = await run_repo.get_latest_completed(message.chat.id)
        if run is None or not run.tasks:
            await message.answer("Задачи пока не найдены.")
            return
        logger.info("Tasks returned: chat_id=%s run_id=%s tasks_count=%s", message.chat.id, run.id, len(run.tasks or []))
        lines = []
        for idx, task in enumerate(run.tasks, start=1):
            owner = task.get("who") or task.get("owner") or "unknown"
            what = task.get("what") or task.get("task") or str(task)
            deadline = task.get("deadline") or task.get("when") or "no deadline"
            if not str(what).strip():
                continue
            if not str(owner).strip() and str(what).strip() in {"unknown", str(task).strip()}:
                continue
            lines.append(f"{idx}. {owner}: {what} ({deadline})")
        await message.answer("\n".join(lines) if lines else "Задачи пока не найдены.")


async def _handle_decisions(message: Message, session_factory) -> None:
    if message.chat is None:
        return
    logger.info("Decisions requested: chat_id=%s message_id=%s", message.chat.id, message.message_id)
    async with session_factory() as session:
        run_repo = AgentRunRepository(session)
        run = await run_repo.get_latest_completed(message.chat.id)
        if run is None or not run.decisions:
            await message.answer("Решения пока не найдены.")
            return
        logger.info(
            "Decisions returned: chat_id=%s run_id=%s decisions_count=%s",
            message.chat.id,
            run.id,
            len(run.decisions or []),
        )
        lines = []
        for idx, decision in enumerate(run.decisions, start=1):
            title = decision.get("title") or decision.get("decision") or str(decision)
            if not str(title).strip():
                continue
            lines.append(f"{idx}. {title}")
        await message.answer("\n".join(lines) if lines else "Решения пока не найдены.")


def _extract_command_arguments(text: str) -> str:
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()
