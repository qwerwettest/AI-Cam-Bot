from __future__ import annotations

import logging
from datetime import date, datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from pydantic import ValidationError

from app.config import Settings
from app.keyboards.menus import (
    duration_keyboard,
    floor_keyboard,
    location_keyboard,
    hold_actions_keyboard,
    result_actions_keyboard,
)
from app.models import FindRoomQuery
from app.services.formatter import extract_free_rooms, format_room_details, format_search_result
from app.services.java_client import JavaClient, JavaClientError
from app.storage.user_storage import UserStorage
from app.utils.validation import parse_time_input


logger = logging.getLogger(__name__)
router = Router()


class FindRoomStates(StatesGroup):
    choosing_location = State()
    choosing_floor = State()
    choosing_duration = State()


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
        "Шаг 1/3. Выберите корпус." + hint,
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
    await message.answer("Шаг 2/3. Выберите этаж:", reply_markup=floor_keyboard(floors))



#: Шаг сетки времени в минутах.
TIME_SLOT_MINUTES = 15


def _get_auto_time() -> str:
    """Текущее время, округлённое ВНИЗ до сетки в 15 минут.

    Раньше округляли вверх до целого часа: в 10:05 ближайшим слотом было
    11:00, и кабинет нельзя было занять прямо сейчас. Теперь 10:05 даёт
    10:00, 10:20 — 10:15 и так далее.
    """
    now = datetime.now()
    slot_minute = (now.minute // TIME_SLOT_MINUTES) * TIME_SLOT_MINUTES
    return now.replace(minute=slot_minute, second=0, microsecond=0).strftime("%H:%M")


async def _ask_duration(message: Message, state: FSMContext, settings: Settings) -> None:
    await state.set_state(FindRoomStates.choosing_duration)
    await message.answer(
        "Шаг 3/3. Выберите длительность:",
        reply_markup=duration_keyboard(settings.duration_options),
    )




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
    await _ask_duration(callback.message, state, settings)


@router.callback_query(FindRoomStates.choosing_floor, F.data.startswith("findfloor:"))
async def callback_find_floor(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
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
        await _ask_duration(callback.message, state, settings)


@router.callback_query(FindRoomStates.choosing_duration, F.data.startswith("finddur:"))
async def callback_find_duration(
    callback: CallbackQuery,
    state: FSMContext,
    java_client: JavaClient,
    user_storage: UserStorage,
) -> None:
    raw = callback.data.split(":", maxsplit=1)[1]
    if not raw.isdigit():
        await callback.answer("Некорректная длительность.", show_alert=True)
        return
    await state.update_data(duration_minutes=int(raw))
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
            # Дата и время больше не спрашиваются: C++ всё равно работает
            # с текущим днём недели, поэтому берём сегодня и ближайший час.
            date=date.today(),
            time=parse_time_input(_get_auto_time()),
            duration_minutes=int(data.get("duration_minutes", 0)),
            min_capacity=None,
            need_projector=None,
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

    # Кабинет найден и удержан, но бронью станет только после подтверждения.
    hold_id = free_rooms[0].get("hold_id") if free_rooms else None
    if hold_id is not None:
        await message.answer(text, reply_markup=hold_actions_keyboard(int(hold_id)))
    else:
        await message.answer(text, reply_markup=result_actions_keyboard(free_rooms))


@router.callback_query(F.data.startswith("holdok:"))
async def callback_confirm_hold(callback: CallbackQuery, java_client: JavaClient) -> None:
    raw = callback.data.split(":", maxsplit=1)[1]
    if not raw.isdigit():
        await callback.answer("Некорректный резерв.", show_alert=True)
        return

    try:
        await java_client.confirm_booking(int(raw), callback.from_user.id)
    except JavaClientError as exc:
        if exc.status_code == 404:
            await callback.answer(
                "Резерв истёк или уже обработан. Запустите /find заново.", show_alert=True
            )
        else:
            logger.error("hold_confirm_failed: %s", exc)
            await callback.answer("Не удалось подтвердить. Попробуйте позже.", show_alert=True)
        return

    await callback.answer("Забронировано.")
    if callback.message:
        await callback.message.edit_text(
            callback.message.html_text + "\n\n✅ <b>Бронь подтверждена.</b> Посмотреть все — /my"
        )


@router.callback_query(F.data.startswith("holdno:"))
async def callback_release_hold(callback: CallbackQuery, java_client: JavaClient) -> None:
    raw = callback.data.split(":", maxsplit=1)[1]
    if not raw.isdigit():
        await callback.answer("Некорректный резерв.", show_alert=True)
        return

    try:
        await java_client.cancel_booking(int(raw), callback.from_user.id)
    except JavaClientError as exc:
        if exc.status_code != 404:
            logger.error("hold_release_failed: %s", exc)

    await callback.answer("Кабинет освобождён.")
    if callback.message:
        await callback.message.edit_text(
            callback.message.html_text + "\n\n❌ <b>Вы отказались.</b> Новый поиск — /find"
        )


@router.callback_query(F.data.startswith("holdnext:"))
async def callback_next_room(
    callback: CallbackQuery,
    java_client: JavaClient,
    user_storage: UserStorage,
) -> None:
    """Отказ от текущего кабинета и повтор поиска: следующий свободный."""
    raw = callback.data.split(":", maxsplit=1)[1]

    # Сначала освобождаем текущий, иначе он же и найдётся снова.
    if raw.isdigit():
        try:
            await java_client.cancel_booking(int(raw), callback.from_user.id)
        except JavaClientError:
            pass

    payload = await user_storage.get_last_request(callback.from_user.id)
    if payload is None:
        await callback.answer("Нет предыдущего запроса. Запустите /find.", show_alert=True)
        return

    await callback.answer("Ищу другой кабинет...")
    try:
        response = await java_client.bridge(payload=payload)
    except JavaClientError as exc:
        logger.error("next_room_failed: %s", exc)
        if callback.message:
            await callback.message.answer("Сервис поиска недоступен. Попробуйте позже.")
        return

    await user_storage.save_last_response(callback.from_user.id, response)
    free_rooms = extract_free_rooms(response)
    text = format_search_result(response)
    hold_id = free_rooms[0].get("hold_id") if free_rooms else None

    if callback.message:
        if hold_id is not None:
            await callback.message.answer(text, reply_markup=hold_actions_keyboard(int(hold_id)))
        else:
            await callback.message.answer(text)


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
