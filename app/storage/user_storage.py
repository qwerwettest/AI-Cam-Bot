from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class UserStorage:
    def __init__(self, storage_path: str) -> None:
        self.path = Path(storage_path)
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    async def _read_all_locked(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8").strip()
            if not raw:
                return {}
            data = json.loads(raw)
            if not isinstance(data, dict):
                logger.warning("storage_invalid_format", extra={"path": str(self.path)})
                return {}
            return data
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            logger.error("storage_corrupted_json", extra={"path": str(self.path)})
            return {}

    async def _write_all_locked(self, data: dict[str, Any]) -> None:
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    async def get_user(self, user_id: int) -> dict[str, Any]:
        key = str(user_id)
        async with self._lock:
            data = await self._read_all_locked()
            value = data.get(key, {})
            return value if isinstance(value, dict) else {}

    async def update_user(self, user_id: int, payload: dict[str, Any]) -> None:
        key = str(user_id)
        async with self._lock:
            data = await self._read_all_locked()
            current = data.get(key, {})
            if not isinstance(current, dict):
                current = {}
            current.update(payload)
            data[key] = current
            await self._write_all_locked(data)

    async def set_default_location(self, user_id: int, location_id: str) -> None:
        await self.update_user(user_id, {"default_location": location_id})

    async def get_default_location(self, user_id: int) -> str | None:
        user_data = await self.get_user(user_id)
        value = user_data.get("default_location")
        return str(value) if value else None

    async def save_last_request(self, user_id: int, payload: dict[str, Any]) -> None:
        await self.update_user(user_id, {"last_request": payload})

    async def get_last_request(self, user_id: int) -> dict[str, Any] | None:
        user_data = await self.get_user(user_id)
        value = user_data.get("last_request")
        return value if isinstance(value, dict) else None

    async def save_last_response(self, user_id: int, payload: dict[str, Any]) -> None:
        await self.update_user(user_id, {"last_response": payload})

    async def get_last_response(self, user_id: int) -> dict[str, Any] | None:
        user_data = await self.get_user(user_id)
        value = user_data.get("last_response")
        return value if isinstance(value, dict) else None

