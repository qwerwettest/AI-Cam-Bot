from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import LocationOption


def location_keyboard(locations: list[LocationOption], callback_prefix: str = "findloc") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for location in locations:
        builder.button(text=location.name, callback_data=f"{callback_prefix}:{location.id}")
    builder.adjust(2)
    return builder.as_markup()


def floor_keyboard(floors: list[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for floor in floors:
        builder.button(text=f"{floor} этаж", callback_data=f"findfloor:{floor}")
    builder.button(text="Не важно", callback_data="findfloor:any")
    builder.adjust(3)
    return builder.as_markup()


def date_keyboard() -> InlineKeyboardMarkup:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Сегодня ({today.isoformat()})", callback_data=f"finddate:{today.isoformat()}")
    builder.button(
        text=f"Завтра ({tomorrow.isoformat()})",
        callback_data=f"finddate:{tomorrow.isoformat()}",
    )
    builder.adjust(1)
    return builder.as_markup()


def time_keyboard(common_times: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in common_times[:8]:
        builder.button(text=str(item), callback_data=f"findtime:{item}")
    builder.adjust(4)
    return builder.as_markup()


def duration_keyboard(options: list[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for minutes in options:
        builder.button(text=f"{minutes} мин", callback_data=f"finddur:{minutes}")
    builder.adjust(4)
    return builder.as_markup()


def capacity_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Пропустить", callback_data="findcap:skip")
    return builder.as_markup()


def projector_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Нужен проектор", callback_data="findproj:yes")
    builder.button(text="Без проектора", callback_data="findproj:no")
    builder.button(text="Не важно", callback_data="findproj:skip")
    builder.adjust(1)
    return builder.as_markup()


def result_actions_keyboard(free_rooms: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить", callback_data="refresh:last")
    for index, room in enumerate(free_rooms[:5]):
        room_name = str(
            room.get("name")
            or room.get("room_name")
            or room.get("id")
            or room.get("number")
            or f"Кабинет {index + 1}"
        )
        short_name = room_name[:20]
        builder.button(text=f"ℹ️ {short_name}", callback_data=f"detail:{index}")
    builder.adjust(1, 2)
    return builder.as_markup()


def set_default_location_keyboard(locations: list[LocationOption]) -> InlineKeyboardMarkup:
    return location_keyboard(locations, callback_prefix="setdef")

