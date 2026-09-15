from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from pydantic import ValidationError

from app.config import Settings
from app.keyboards.menus import (
    capacity_keyboard,
    date_keyboard,
    duration_keyboard,
    floor_keyboard,
    location_keyboard,
    projector_keyboard,
    result_actions_keyboard,
)
from app.models import FindRoomQuery
from app.services.formatter import extract_free_rooms, format_room_details, format_search_result
from app.services.java_client import JavaClient, JavaClientError
from app.storage.user_storage import UserStorage
from app.utils.validation import parse_capacity_input, parse_date_input, parse_time_input


logger = logging.getLogger(__name__)
router = Router()


class FindRoomStates(StatesGroup):
    choosing_location = State()
    choosing_floor = State()
    entering_date = State()
    choosing_duration = State()
    entering_capacity = State()
    choosing_projector = State()


@router.message(Command("find"))
async def cmd_find(message: Message, state: FSMContext, settings: Settings, user_storage: UserStorage) -> None:
    if not settings.locations_list:
        await message.answer("Список локаций не настроен. Заполните LOCATIONS_LIST в .env.")
        return

    await state.clear()
    await state.set_state(FindRoomStates.choosing_location)
    user_id = message.from_user.id if message.from_user else 0
    default_location = await user_storage.get_default_location(user_id) if user_id else None

    hint = ""
    if default_location:
        location = settings.get_location(default_location)
        if location:
            hint = f"\nТекущая локация по умолчанию: <b>{location.name}</b> ({location.id})."
    await message.answer(
        "Шаг 1/5. Выберите локацию поиска кабинета." + hint,
        reply_markup=location_keyboard(settings.locations_list),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    active_state = await state.get_state()
    if not active_state:
        await message.answer("Активного диалога нет.")
        return
    await state.clear()
    await message.answer("Диалог поиска отменен.")


async def _ask_floor(message: Message, state: FSMContext, floors: list[int]) -> None:
    await state.set_state(FindRoomStates.choosing_floor)
    await message.answer("Шаг 2/5. Выберите этаж:", reply_markup=floor_keyboard(floors))


async def _ask_date(message: Message, state: FSMContext) -> None:
    await state.set_state(FindRoomStates.entering_date)
    await message.answer(
        "Шаг 3/5. Введите дату в формате YYYY-MM-DD или выберите кнопку:",
        reply_markup=date_keyboard(),
    )


def _get_auto_time() -> str:
    """Round current time up to the next full hour."""
    now = datetime.now()
    if now.minute == 0 and now.second == 0:
        return now.strftime("%H:%M")
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return next_hour.strftime("%H:%M")


async def _ask_duration(message: Message, state: FSMContext, settings: Settings) -> None:
    await state.set_state(FindRoomStates.choosing_duration)
    await message.answer(
        "Шаг 4/5. Выберите длительность:",
        reply_markup=duration_keyboard(settings.duration_options),
    )


async def _ask_capacity(message: Message, state: FSMContext) -> None:
    await state.set_state(FindRoomStates.entering_capacity)
    await message.answer(
        "Шаг 5/5. Минимальная вместимость (число) или пропустите:",
        reply_markup=capacity_keyboard(),
    )


async def _ask_projector(message: Message, state: FSMContext) -> None:
    await state.set_state(FindRoomStates.choosing_projector)
    await message.answer("Нужен ли проектор?", reply_markup=projector_keyboard())


@router.callback_query(FindRoomStates.choosing_location, F.data.startswith("findloc:"))
async def callback_find_location(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    location_id = callback.data.split(":", maxsplit=1)[1]
    location = settings.get_location(location_id)
    if location is None:
        await callback.answer("Локация не найдена.", show_alert=True)
        return

    await state.update_data(location_id=location.id, location_name=location.name)
    await callback.answer()
    if not callback.message:
        return
    if location.floors:
        await _ask_floor(callback.message, state, location.floors)
        return
    await state.update_data(floor=None)
    await _ask_date(callback.message, state)


@router.callback_query(FindRoomStates.choosing_floor, F.data.startswith("findfloor:"))
async def callback_find_floor(callback: CallbackQuery, state: FSMContext) -> None:
    floor_raw = callback.data.split(":", maxsplit=1)[1]
    if floor_raw == "any":
        floor = None
    else:
        try:
            floor = int(floor_raw)
        except ValueError:
            await callback.answer("Некорректный этаж.", show_alert=True)
            return
    await state.update_data(floor=floor)
    await callback.answer()
    if callback.message:
        await _ask_date(callback.message, state)


@router.callback_query(FindRoomStates.entering_date, F.data.startswith("finddate:"))
async def callback_find_date(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    date_raw = callback.data.split(":", maxsplit=1)[1]
    try:
        parsed = parse_date_input(date_raw)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    auto_time = _get_auto_time()
    await state.update_data(date=parsed.isoformat(), time=auto_time)
    await callback.answer()
    if callback.message:
        await callback.message.answer(f"Время определено автоматически: {auto_time}")
        await _ask_duration(callback.message, state, settings)


@router.message(FindRoomStates.entering_date)
async def message_find_date(message: Message, state: FSMContext, settings: Settings) -> None:
    raw = (message.text or "").strip()
    try:
        parsed = parse_date_input(raw)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    auto_time = _get_auto_time()
    await state.update_data(date=parsed.isoformat(), time=auto_time)
    await message.answer(f"Время определено автоматически: {auto_time}")
    await _ask_duration(message, state, settings)


@router.callback_query(FindRoomStates.choosing_duration, F.data.startswith("finddur:"))
async def callback_find_duration(callback: CallbackQuery, state: FSMContext) -> None:
    raw = callback.data.split(":", maxsplit=1)[1]
    if not raw.isdigit():
        await callback.answer("Некорректная длительность.", show_alert=True)
        return
    await state.update_data(duration_minutes=int(raw))
    await callback.answer()
    if callback.message:
        await _ask_capacity(callback.message, state)


@router.callback_query(FindRoomStates.entering_capacity, F.data == "findcap:skip")
async def callback_find_capacity_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(min_capacity=None)
    await callback.answer()
    if callback.message:
        await _ask_projector(callback.message, state)


@router.message(FindRoomStates.entering_capacity)
async def message_find_capacity(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if raw.lower() in {"skip", "пропустить", "-"}:
        await state.update_data(min_capacity=None)
        await _ask_projector(message, state)
        return
    try:
        capacity = parse_capacity_input(raw)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(min_capacity=capacity)
    await _ask_projector(message, state)


@router.callback_query(FindRoomStates.choosing_projector, F.data.startswith("findproj:"))
async def callback_find_projector(
    callback: CallbackQuery,
    state: FSMContext,
    java_client: JavaClient,
    user_storage: UserStorage,
) -> None:
    raw = callback.data.split(":", maxsplit=1)[1]
    if raw == "yes":
        value = True
    elif raw == "no":
        value = False
    else:
        value = None

    await state.update_data(need_projector=value)
    await callback.answer()
    if not callback.message:
        return
    await _execute_search(
        message=callback.message,
        state=state,
        java_client=java_client,
        user_storage=user_storage,
        user_id=callback.from_user.id,
    )


async def _execute_search(
    *,
    message: Message,
    state: FSMContext,
    java_client: JavaClient,
    user_storage: UserStorage,
    user_id: int,
) -> None:
    data = await state.get_data()
    try:
        query = FindRoomQuery(
            location_id=str(data.get("location_id", "")),
            floor=data.get("floor"),
            date=parse_date_input(str(data.get("date", ""))),
            time=parse_time_input(str(data.get("time", ""))),
            duration_minutes=int(data.get("duration_minutes", 0)),
            min_capacity=data.get("min_capacity"),
            need_projector=data.get("need_projector"),
            requested_by=user_id,
        )
    except (ValidationError, ValueError) as exc:
        await state.clear()
        await message.answer(
            "Не удалось собрать корректный запрос. Запустите /find заново.\n"
            f"Детали: {exc}"
        )
        return

    payload = query.to_java_payload()
    logger.info("_execute_search: payload=%s", payload)
    await message.answer("Отправляю запрос на Java API...")

    try:
        logger.info("_execute_search: calling java_client.bridge(POST)...")
        response = await java_client.bridge(payload=payload)
        logger.info("_execute_search: response=%s", response)
    except JavaClientError as exc:
        await state.clear()
        logger.error(
            "find_request_failed: status_code=%s details=%s",
            exc.status_code,
            exc.details,
        )
        await message.answer(
            "Сервис поиска временно недоступен. Попробуйте позже.\n"
            f"Техническая ошибка: {exc}"
        )
        return
    except Exception as exc:
        await state.clear()
        logger.exception("find_request_unexpected_error")
        await message.answer(
            "Неожиданная ошибка при запросе к Java API.\n"
            f"Детали: {exc}"
        )
        return

    await user_storage.save_last_request(user_id, payload)
    await user_storage.save_last_response(user_id, response)
    await state.clear()

    free_rooms = extract_free_rooms(response)
    text = format_search_result(response)
    await message.answer(text, reply_markup=result_actions_keyboard(free_rooms))


@router.callback_query(F.data == "refresh:last")
async def callback_refresh_last(
    callback: CallbackQuery,
    java_client: JavaClient,
    user_storage: UserStorage,
) -> None:
    user_id = callback.from_user.id
    last_request = await user_storage.get_last_request(user_id)
    if last_request is None:
        await callback.answer("Нет предыдущего запроса.", show_alert=True)
        return

    await callback.answer("Обновляю...")
    if callback.message:
        await callback.message.answer("Обновляю результат по последнему запросу...")

    try:
        response = await java_client.bridge(payload=last_request)
    except JavaClientError:
        if callback.message:
            await callback.message.answer("Не удалось обновить результат: Java API недоступен.")
        return

    await user_storage.save_last_response(user_id, response)
    free_rooms = extract_free_rooms(response)
    text = format_search_result(response)
    if callback.message:
        await callback.message.answer(text, reply_markup=result_actions_keyboard(free_rooms))


@router.callback_query(F.data.startswith("detail:"))
async def callback_room_detail(callback: CallbackQuery, user_storage: UserStorage) -> None:
    payload = await user_storage.get_last_response(callback.from_user.id)
    if payload is None:
        await callback.answer("Нет сохраненного ответа.", show_alert=True)
        return

    raw_index = callback.data.split(":", maxsplit=1)[1]
    if not raw_index.isdigit():
        await callback.answer("Некорректный номер.", show_alert=True)
        return

    details_text = format_room_details(payload, int(raw_index))
    await callback.answer()
    if callback.message:
        await callback.message.answer(details_text)
