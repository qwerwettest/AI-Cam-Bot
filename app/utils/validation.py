from __future__ import annotations

from datetime import date, datetime, time


def parse_date_input(raw_value: str) -> date:
    value = raw_value.strip()
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Дата должна быть в формате YYYY-MM-DD.") from exc
    if parsed < date.today():
        raise ValueError("Дата не может быть в прошлом.")
    return parsed


def parse_time_input(raw_value: str) -> time:
    value = raw_value.strip()
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise ValueError("Время должно быть в формате HH:MM (например, 14:30).") from exc


def parse_capacity_input(raw_value: str) -> int:
    value = raw_value.strip()
    if not value.isdigit():
        raise ValueError("Вместимость должна быть целым числом.")
    capacity = int(value)
    if capacity < 1 or capacity > 500:
        raise ValueError("Вместимость должна быть в диапазоне от 1 до 500.")
    return capacity

