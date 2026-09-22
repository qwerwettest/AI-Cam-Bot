from __future__ import annotations

from html import escape
from typing import Any


def _extract_list(payload: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def extract_free_rooms(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_list(payload, ("free_rooms", "rooms", "available_rooms"))


def extract_alternatives(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_list(payload, ("alternatives", "nearest_alternatives", "suggested_rooms"))


def _room_name(room: dict[str, Any]) -> str:
    return str(
        room.get("name")
        or room.get("room_name")
        or room.get("room")
        or room.get("id")
        or room.get("number")
        or "Без имени"
    )


def _bool_label(value: Any) -> str:
    if value is True:
        return "да"
    if value is False:
        return "нет"
    return "н/д"


def _room_line(room: dict[str, Any], index: int) -> str:
    name = escape(_room_name(room))
    location = escape(str(room.get("location_name") or room.get("location_id") or room.get("location") or ""))
    floor = room.get("floor")
    capacity = room.get("capacity")
    schedule_free = room.get("schedule_free", room.get("is_free_by_schedule"))
    camera_free = room.get("camera_free", room.get("is_free_by_camera"))
    camera_status = room.get("camera_status")
    access_code = room.get("access_code") or room.get("key") or room.get("code")

    booking_start = room.get("booking_start")
    booking_end = room.get("booking_end")
    duration = room.get("duration_minutes")
    category = room.get("category")

    lines = [f"{index}. <b>{name}</b>"]

    place = []
    if location:
        place.append(location)
    if floor is not None:
        place.append(f"{floor} этаж")
    if place:
        lines.append("📍 " + escape(" · ".join(str(p) for p in place)))

    # Кабинет удержан, но бронью станет только после подтверждения,
    # поэтому формулировка зависит от наличия hold_id.
    if booking_start and booking_end:
        when = f"{escape(str(booking_start))}–{escape(str(booking_end))}"
        if duration:
            when += f" ({duration} мин)"
        label = "Время" if room.get("hold_id") is not None else "Забронирован"
        lines.append(f"🕒 {label}: <b>{when}</b>")

    if category:
        lines.append(f"🏷 {escape(str(category))}")

    # Предупреждения, если пришлось отступить от запроса.
    if room.get("corpus_matched") is False:
        lines.append("⚠️ В выбранном корпусе свободных не было — это другой корпус")
    if room.get("floor_matched") is False:
        lines.append("⚠️ На выбранном этаже свободных не было — это другой этаж")

    chunks = []
    if capacity is not None:
        chunks.append(f"вместимость: {capacity}")
    chunks.append(f"расписание: {_bool_label(schedule_free)}")
    if camera_status:
        chunks.append(f"камера: {escape(str(camera_status))}")
    else:
        chunks.append(f"камера занятость: {_bool_label(camera_free)}")
    if access_code:
        chunks.append(f"код доступа: <code>{escape(str(access_code))}</code>")

    lines.append(" | ".join(chunks))

    if room.get("hold_id") is not None:
        lines.append("<i>Кабинет удержан за вами. Подтвердите бронь ниже.</i>")

    return "\n".join(lines)


def format_search_result(payload: dict[str, Any]) -> str:
    free_rooms = extract_free_rooms(payload)
    alternatives = extract_alternatives(payload)
    reason = str(payload.get("reason") or payload.get("message") or payload.get("error") or "").strip()

    parts: list[str] = []
    if free_rooms:
        parts.append("<b>Свободные кабинеты:</b>")
        for index, room in enumerate(free_rooms[:10], start=1):
            parts.append(_room_line(room, index))
        if len(free_rooms) > 10:
            parts.append(f"Показаны первые 10 из {len(free_rooms)}.")
    else:
        parts.append("<b>Свободные кабинеты не найдены.</b>")

    if alternatives:
        parts.append("")
        parts.append("<b>Ближайшие альтернативы:</b>")
        for index, room in enumerate(alternatives[:5], start=1):
            parts.append(_room_line(room, index))

    if reason and not free_rooms:
        parts.append("")
        parts.append(f"<i>Причина отказа: {escape(reason)}</i>")

    return "\n".join(parts)


def format_room_details(payload: dict[str, Any], room_index: int) -> str:
    rooms = extract_free_rooms(payload)
    if room_index < 0 or room_index >= len(rooms):
        return "Детали недоступны: кабинет не найден в последнем ответе."

    room = rooms[room_index]
    lines = ["<b>Детали кабинета</b>"]
    lines.append(f"Название: <b>{escape(_room_name(room))}</b>")
    for label, keys in (
        ("Локация", ("location_name", "location_id", "location")),
        ("Этаж", ("floor",)),
        ("Вместимость", ("capacity",)),
        ("Свободен по расписанию", ("schedule_free", "is_free_by_schedule")),
        ("Свободен по камере", ("camera_free", "is_free_by_camera")),
        ("Статус камеры", ("camera_status",)),
        ("Код доступа", ("access_code", "key", "code")),
    ):
        value = None
        for key in keys:
            if key in room and room[key] is not None:
                value = room[key]
                break
        if value is not None:
            lines.append(f"{label}: {escape(str(value))}")
    return "\n".join(lines)

