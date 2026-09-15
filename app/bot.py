from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent

from app.config import get_settings
from app.handlers import admin, common, find
from app.services.java_client import JavaClient
from app.storage.user_storage import UserStorage
from app.utils.logging import setup_logging


logger = logging.getLogger(__name__)


async def _set_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Приветствие"),
        BotCommand(command="help", description="Список команд"),
        BotCommand(command="find", description="Поиск свободного кабинета"),
        BotCommand(command="setdefault", description="Локация по умолчанию"),
        BotCommand(command="status", description="Проверка Java health (admin)"),
        BotCommand(command="logs", description="Логи приложения (admin)"),
        BotCommand(command="cancel", description="Отмена текущего диалога"),
    ]
    await bot.set_my_commands(commands)


async def run_bot() -> None:
    settings = get_settings()
    setup_logging(settings.log_path, settings.log_level)

    user_storage = UserStorage(settings.storage_path)
    await user_storage.init()
    java_client = JavaClient(settings)

    bot = Bot(
        token=settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp["settings"] = settings
    dp["user_storage"] = user_storage
    dp["java_client"] = java_client

    dp.include_router(common.router)
    dp.include_router(find.router)
    dp.include_router(admin.router)

    @dp.error()
    async def on_error(event: ErrorEvent) -> bool:
        logger.exception("unhandled_exception", exc_info=event.exception)
        message = event.update.message if event.update else None
        if message:
            await message.answer("Внутренняя ошибка. Попробуйте еще раз позже.")
        callback = event.update.callback_query if event.update else None
        if callback:
            try:
                await callback.answer("Внутренняя ошибка.", show_alert=True)
            except Exception:
                pass
        return True

    await _set_commands(bot)
    logger.info("bot_started")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        logger.info("bot_stopping")
        await java_client.close()
        await bot.session.close()
