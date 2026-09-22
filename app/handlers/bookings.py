from __future__ import annotations

import logging
from html import escape
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.services.java_client import JavaClient, JavaClientError


logger = logging.getLogger(__name__)

router = Router(name="bookings")


def _booking_line(booking: dict[str, Any]) -> str:
    name = escape(str(booking.get("name") or booking.get("auditory_id") or "кабинет"))
    corpus = escape(str(booking.get("corpus") or ""))
    floor = booking.get("floor")
    day = escape(str(booking.get("day_name") or ""))
    start = booking.get("start_time")
    end = booking.get("end_time")
    duration = booking.get("duration_minutes")

    place = " · ".join(p for p in [corpus, f"{floor} этаж" if floor is not None else ""] if p)

    when = ""
    if start and end:
        when = f"{escape(str(start))}–{escape(str(end))}"
        if duration:
            when += f" ({duration} мин)"
    if day:
        when = f"{day}, {when}" if when else day

    lines = [f"<b>{name}</b>"]
    if place:
        lines.append(f"📍 {place}")
    if when:
        lines.append(f"🕒 {when}")
    return "\n".join(lines)


def _bookings_keyboard(bookings: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = []
    for booking in bookings:
        booking_id = booking.get("id")
        if booking_id is None:
            continue
        name = booking.get("name") or booking.get("auditory_id") or "бронь"
        start = booking.get("start_time") or ""
        label = f"❌ Отменить {name}"
        if start:
            label += f" в {start}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"cancelbk:{booking_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render(bookings: list[dict[str, Any]]) -> str:
    if not bookings:
        return "У вас нет активных броней.\n\nНайти кабинет — /find"
    parts = [f"<b>Ваши брони ({len(bookings)}):</b>"]
    parts.extend(_booking_line(b) for b in bookings)
    return "\n\n".join(parts)


@router.message(Command("my"))
async def cmd_my_bookings(message: Message, java_client: JavaClient) -> None:
    try:
        response = await java_client.list_bookings(message.from_user.id)
    except JavaClientError as exc:
        logger.error("bookings_list_failed: %s", exc)
        await message.answer("Не удалось получить список броней. Попробуйте позже.")
        return

    bookings = response.get("bookings") or []
    await message.answer(
        _render(bookings),
        reply_markup=_bookings_keyboard(bookings) if bookings else None,
    )


@router.callback_query(F.data.startswith("cancelbk:"))
async def callback_cancel_booking(callback: CallbackQuery, java_client: JavaClient) -> None:
    raw = callback.data.split(":", maxsplit=1)[1]
    if not raw.isdigit():
        await callback.answer("Некорректная бронь.", show_alert=True)
        return

    try:
        await java_client.cancel_booking(int(raw), callback.from_user.id)
    except JavaClientError as exc:
        # Java отдаёт 404, если бронь чужая или её уже нет.
        if exc.status_code == 404:
            await callback.answer("Бронь уже отменена или принадлежит другому пользователю.", show_alert=True)
        else:
            logger.error("booking_cancel_failed: %s", exc)
            await callback.answer("Не удалось отменить бронь. Попробуйте позже.", show_alert=True)
    else:
        await callback.answer("Бронь отменена.")

    # Перерисовываем список, чтобы он не остался устаревшим.
    try:
        response = await java_client.list_bookings(callback.from_user.id)
    except JavaClientError:
        return

    bookings = response.get("bookings") or []
    if callback.message:
        await callback.message.edit_text(
            _render(bookings),
            reply_markup=_bookings_keyboard(bookings) if bookings else None,
        )
