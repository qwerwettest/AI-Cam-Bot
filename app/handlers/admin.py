from __future__ import annotations

import json
import logging
from collections import deque
from html import escape
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message

from app.config import Settings
from app.services.java_client import JavaClient, JavaClientError


logger = logging.getLogger(__name__)
router = Router()


def _is_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.admin_telegram_ids


async def _reject_non_admin(message: Message) -> None:
    await message.answer("Команда доступна только администраторам.")


def _tail(path: str, limit: int) -> list[str]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    with file_path.open("r", encoding="utf-8") as file:
        return list(deque(file, maxlen=limit))


@router.message(Command("status"))
async def cmd_status(message: Message, settings: Settings, java_client: JavaClient) -> None:
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id, settings):
        await _reject_non_admin(message)
        return

    try:
        result = await java_client.bridge()
    except JavaClientError as exc:
        logger.error(
            "admin_status_failed",
            extra={"status_code": exc.status_code, "details": exc.details},
        )
        await message.answer(
            "Java API недоступен.\n"
            f"Ошибка: {escape(str(exc))}\n"
            f"HTTP: {exc.status_code or 'n/a'}"
        )
        return

    body = escape(json.dumps(result, ensure_ascii=False, indent=2))
    await message.answer(f"Java API доступен.\n<code>{body[:3500]}</code>")


@router.message(Command("logs"))
async def cmd_logs(message: Message, command: CommandObject, settings: Settings) -> None:
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id, settings):
        await _reject_non_admin(message)
        return

    limit = 20
    if command and command.args:
        raw = command.args.strip()
        if raw.isdigit():
            limit = max(1, min(100, int(raw)))

    lines = _tail(settings.log_path, limit)
    if not lines:
        await message.answer("Логи пока отсутствуют.")
        return

    body = escape("".join(lines)[-3900:])
    await message.answer(f"<b>Последние логи ({limit}):</b>\n<code>{body}</code>")

