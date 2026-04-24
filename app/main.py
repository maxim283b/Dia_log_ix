from __future__ import annotations

import asyncio

from fastapi import FastAPI

from app.api.routes import api_router
from app.config import get_settings
from app.db.base import Base
from app.db.session import create_engine_and_session_factory
from app.models import agent_run, agent_trace, chat, digest_evaluation, message, user  # noqa: F401
from app.telegram.bot import setup_bot


def create_app() -> FastAPI:
    settings = get_settings()
    engine, session_factory = create_engine_and_session_factory(settings.database_url)
    app = FastAPI(title="Telegram Digest Agent", version="0.1.0")
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.engine = engine
    app.include_router(api_router)

    @app.on_event("startup")
    async def on_startup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        bot, dispatcher = await setup_bot(session_factory, settings)
        app.state.bot = bot
        app.state.dispatcher = dispatcher
        if settings.bot_mode.lower() == "webhook" and settings.webhook_url:
            await bot.set_webhook(settings.webhook_url)

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        bot = getattr(app.state, "bot", None)
        if bot is not None:
            await bot.session.close()

    return app


async def run_polling() -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session_factory(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    bot, dispatcher = await setup_bot(session_factory, settings)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    settings = get_settings()
    if settings.bot_mode.lower() == "polling":
        asyncio.run(run_polling())
    else:
        import uvicorn

        uvicorn.run("app.main:create_app", factory=True, host="0.0.0.0", port=8000, reload=False)
