from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import Settings


logger = logging.getLogger(__name__)


class JavaClientError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        details: Any = None,
        retriable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details
        self.retriable = retriable


class JavaClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        timeout = httpx.Timeout(
            timeout=settings.request_timeout_seconds,
            connect=max(1.0, settings.request_timeout_seconds / 2),
        )
        self._client = httpx.AsyncClient(
            base_url=settings.java_base_url.rstrip("/"),
            timeout=timeout,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        secret = self.settings.java_auth_secret
        scheme = self.settings.java_auth_scheme
        if not secret or scheme == "none":
            return headers
        if scheme == "api_key":
            headers[self.settings.java_api_key_header] = secret
            return headers
        if scheme == "bearer":
            headers["Authorization"] = f"Bearer {secret}"
            return headers
        if scheme == "basic":
            headers["Authorization"] = f"Basic {secret}"
            return headers
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        retries = max(1, self.settings.max_retries)

        for attempt in range(1, retries + 1):
            try:
                full_url = f"{self._client.base_url}{path}"
                logger.info(
                    "java_request: %s %s attempt=%d payload=%s",
                    method, full_url, attempt, payload,
                )
                response = await self._client.request(
                    method=method,
                    url=path,
                    json=payload,
                    headers=self._auth_headers(),
                )
                logger.info(
                    "java_response: %s %s status=%d",
                    method, full_url, response.status_code,
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if attempt == retries:
                    break
                backoff = self.settings.retry_backoff_base * (2 ** (attempt - 1))
                logger.warning(
                    "java_request_retry_network",
                    extra={"attempt": attempt, "sleep_seconds": backoff, "path": path},
                )
                await asyncio.sleep(backoff)
                continue

            if response.status_code in {429, 500, 502, 503, 504} and attempt < retries:
                backoff = self.settings.retry_backoff_base * (2 ** (attempt - 1))
                logger.warning(
                    "java_request_retry_status",
                    extra={
                        "attempt": attempt,
                        "sleep_seconds": backoff,
                        "status_code": response.status_code,
                        "path": path,
                    },
                )
                await asyncio.sleep(backoff)
                continue

            if response.status_code >= 400:
                details: Any
                try:
                    details = response.json()
                except ValueError:
                    details = response.text[:500]
                logger.error(
                    "java_api_error",
                    extra={
                        "status_code": response.status_code,
                        "path": path,
                        "details": details,
                    },
                )
                raise JavaClientError(
                    "Java API returned an error response.",
                    status_code=response.status_code,
                    details=details,
                    retriable=response.status_code >= 500,
                )

            try:
                body = response.json()
            except ValueError as exc:
                logger.error(
                    "java_non_json_response",
                    extra={"status_code": response.status_code, "path": path},
                )
                raise JavaClientError(
                    "Java API returned non-JSON body.",
                    status_code=response.status_code,
                    details=response.text[:500],
                ) from exc

            if not isinstance(body, dict):
                raise JavaClientError(
                    "Java API returned unexpected JSON format.",
                    status_code=response.status_code,
                    details=body,
                )
            return body

        logger.error(
            "java_unavailable_after_retries",
            extra={"path": path, "retries": retries, "error": str(last_error)},
        )
        raise JavaClientError(
            "Java API is unavailable after retries.",
            details=str(last_error) if last_error else None,
            retriable=True,
        )

    async def bridge(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if payload is not None:
            return await self._request("POST", self.settings.bridge_path, payload=payload)
        return await self._request("GET", self.settings.bridge_path)

    async def close(self) -> None:
        await self._client.aclose()

