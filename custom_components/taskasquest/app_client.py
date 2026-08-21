"""Asynchronous client for the Task as Quest service API."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import aiohttp

from .const import DEFAULT_REQUEST_TIMEOUT
from .exceptions import (
    TaskAsQuestApiError,
    TaskAsQuestAuthenticationError,
    TaskAsQuestCannotConnectError,
    TaskAsQuestEncryptionError,
    TaskAsQuestError,
    TaskAsQuestRateLimitError,
    TaskAsQuestTotpRequiredError,
)
from .protected_fields import ProtectedFields, ProtectedFieldsError

_LOGGER = logging.getLogger(__name__)

_LOGIN_PATH = "api/taq/login-bn"
_REFRESH_PATH = "api/collections/taq_users/auth-refresh"
_TASKS_PATH = "api/collections/taq_tasks/records"
_ASSIGNEES_PATH = "api/collections/taq_task_assignees/records"
_COMPANIONS_PATH = "api/collections/taq_party_members/records"
_ACCOUNTS_PATH = "api/collections/taq_users/records"


class TaskAsQuestClient:
    """Async client for the Task as Quest service."""

    def __init__(
        self,
        base_url: str,
        session: aiohttp.ClientSession,
        executor_job: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        """Initialize the client with a Home Assistant managed web session."""
        self.base_url = base_url.rstrip("/")
        self._session = session
        self._executor_job = executor_job
        self._timeout = aiohttp.ClientTimeout(total=DEFAULT_REQUEST_TIMEOUT)
        self.token: str | None = None
        self.user_id: str | None = None
        self.protection_version = 0
        self.user_record: dict[str, Any] | None = None
        self.protected_fields: ProtectedFields | None = None
        self._last_token_refresh = 0.0

    async def _async_run_crypto(
        self,
        func: Callable[..., Any],
        *args: Any,
    ) -> Any:
        """Run CPU-bound cryptography outside the event loop."""
        if self._executor_job is not None:
            return await self._executor_job(func, *args)
        return await asyncio.to_thread(func, *args)

    def restore_session(self, token: str, user_id: str) -> None:
        """Restore persisted authentication data before refreshing it."""
        self.token = token
        self.user_id = user_id

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = self.token
        return headers

    @staticmethod
    def _escape_filter_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    async def _response_message(response: aiohttp.ClientResponse) -> str:
        """Extract a short, non-sensitive provider error message."""
        try:
            data = await response.json(content_type=None)
            if isinstance(data, dict):
                message = data.get("message") or data.get("error")
                if isinstance(message, str):
                    return message[:200]
        except (aiohttp.ClientError, ValueError, TypeError):
            pass
        return f"HTTP {response.status}"

    @staticmethod
    def _retry_after(response: aiohttp.ClientResponse) -> float:
        value = response.headers.get("Retry-After", "60")
        try:
            return float(value)
        except (TypeError, ValueError):
            return 60

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform one API request and preserve its failure category."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            async with self._session.request(
                method,
                url,
                json=json,
                params=params,
                headers=self._headers(),
                timeout=self._timeout,
            ) as response:
                if response.status == 204:
                    return {}
                if 200 <= response.status < 300:
                    if response.content_length == 0:
                        return {}
                    try:
                        data = await response.json(content_type=None)
                    except (aiohttp.ClientError, ValueError, TypeError) as err:
                        raise TaskAsQuestApiError(
                            "Task as Quest returned an invalid response"
                        ) from err
                    if not isinstance(data, dict):
                        raise TaskAsQuestApiError("Task as Quest returned an unexpected response")
                    return data

                if response.status in {401, 403}:
                    raise TaskAsQuestAuthenticationError("Task as Quest authentication is invalid")
                if response.status == 429:
                    raise TaskAsQuestRateLimitError(self._retry_after(response))

                message = await self._response_message(response)
                if response.status >= 500:
                    raise TaskAsQuestCannotConnectError(message)
                raise TaskAsQuestApiError(message)
        except TaskAsQuestApiError:
            raise
        except (TimeoutError, aiohttp.ClientConnectionError, aiohttp.ServerTimeoutError) as err:
            raise TaskAsQuestCannotConnectError("Could not connect to Task as Quest") from err
        except aiohttp.ClientError as err:
            raise TaskAsQuestCannotConnectError("Task as Quest request failed") from err

    async def authenticate(
        self,
        login_name: str,
        password: str,
        totp_code: str | None = None,
    ) -> None:
        """Authenticate with an account identifier and optional TOTP code."""
        login_name = login_name.strip()
        display_base = login_name
        display_number = ""
        if "#" in login_name:
            display_base, display_number = login_name.rsplit("#", 1)
        if display_number:
            display_number = display_number.zfill(4)

        payload = {
            "display_base": display_base.strip(),
            "display_number": display_number.strip(),
            "password": password,
        }
        if totp_code:
            payload["totp"] = totp_code.strip()

        url = f"{self.base_url}/{_LOGIN_PATH}"
        try:
            async with self._session.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self._timeout,
            ) as response:
                if response.status in {200, 201}:
                    try:
                        data = await response.json(content_type=None)
                    except (aiohttp.ClientError, ValueError, TypeError) as err:
                        raise TaskAsQuestApiError(
                            "Task as Quest returned an invalid login response"
                        ) from err
                    self._apply_auth_response(data)
                    return

                message = await self._response_message(response)
                message_lower = message.lower()
                if "totp" in message_lower or "2fa" in message_lower:
                    raise TaskAsQuestTotpRequiredError(message)
                if response.status == 429:
                    raise TaskAsQuestRateLimitError(self._retry_after(response))
                if response.status >= 500:
                    raise TaskAsQuestCannotConnectError(message)
                raise TaskAsQuestAuthenticationError(message)
        except (
            TaskAsQuestApiError,
            TaskAsQuestAuthenticationError,
            TaskAsQuestCannotConnectError,
            TaskAsQuestRateLimitError,
        ):
            raise
        except (
            TimeoutError,
            aiohttp.ClientConnectionError,
            aiohttp.ServerTimeoutError,
            aiohttp.ClientError,
        ) as err:
            raise TaskAsQuestCannotConnectError("Could not connect to Task as Quest") from err

    def _apply_auth_response(self, data: Any) -> None:
        """Validate and apply a login or refresh response."""
        if not isinstance(data, dict) or not data.get("token"):
            raise TaskAsQuestApiError("Login response did not contain a token")
        record = data.get("record")
        if not isinstance(record, dict) or not record.get("id"):
            raise TaskAsQuestApiError("Login response did not contain an account")
        self.token = data["token"]
        self.user_record = record
        self.user_id = record["id"]
        self.protection_version = int(record.get("crypto_version") or 0)
        self._last_token_refresh = time.monotonic()

    async def refresh_auth(self, *, force: bool = False) -> None:
        """Refresh the session token at most once per hour."""
        if not self.token or not self.user_id:
            raise TaskAsQuestAuthenticationError("No Task as Quest session available")
        now = time.monotonic()
        if not force and now - self._last_token_refresh < 3600:
            return
        data = await self._request("POST", _REFRESH_PATH)
        self._apply_auth_response(data)

    async def async_unlock_protected_fields(self, password: str) -> None:
        """Unlock protected task fields with the account password."""
        if self.protection_version != 1:
            self.protected_fields = None
            return
        if not self.user_record or not password:
            raise TaskAsQuestEncryptionError("Account encryption data is unavailable")
        try:
            self.protected_fields = await self._async_run_crypto(
                ProtectedFields.from_user_record,
                self.user_record,
                password,
            )
        except ProtectedFieldsError as err:
            self.protected_fields = None
            raise TaskAsQuestEncryptionError("Protected fields could not be unlocked") from err

    async def _get_all(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Read every page from a PocketBase-style collection endpoint."""
        query = dict(params or {})
        query.setdefault("perPage", 500)
        page = 1
        items: list[dict[str, Any]] = []
        while page <= 100:
            query["page"] = page
            data = await self._request("GET", path, params=query)
            page_items = data.get("items", [])
            if not isinstance(page_items, list):
                raise TaskAsQuestApiError("Collection response contains invalid items")
            items.extend(item for item in page_items if isinstance(item, dict))
            try:
                total_pages = int(data.get("totalPages") or 1)
            except (TypeError, ValueError) as err:
                raise TaskAsQuestApiError(
                    "Collection response contains an invalid page count"
                ) from err
            if page >= total_pages:
                return items
            page += 1
        raise TaskAsQuestApiError("Collection returned too many pages")

    async def get_open_tasks(self) -> list[dict[str, Any]]:
        """Get all open tasks for the current account."""
        if not self.user_id:
            raise TaskAsQuestAuthenticationError("No Task as Quest account available")
        user_id = self._escape_filter_value(self.user_id)
        tasks = await self._get_all(
            _TASKS_PATH,
            params={"filter": f'user="{user_id}" && status="open"'},
        )
        if self.protection_version == 1 and self.protected_fields:
            return await self._async_run_crypto(
                self._decrypt_tasks,
                self.protected_fields,
                tasks,
            )
        return tasks

    @staticmethod
    def _decrypt_tasks(
        protected_fields: ProtectedFields,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Decrypt a task batch in one executor job."""
        return [protected_fields.decrypt_task_read(task) for task in tasks]

    async def get_task(self, task_id: str) -> dict[str, Any]:
        """Get one task and decrypt its protected fields if necessary."""
        task = await self._request("GET", f"{_TASKS_PATH}/{task_id}")
        if self.protection_version == 1 and self.protected_fields:
            return await self._async_run_crypto(
                self.protected_fields.decrypt_task_read,
                task,
            )
        return task

    async def find_task_by_title(
        self,
        title: str,
        open_tasks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Find an open task with an exact title."""
        tasks = open_tasks if open_tasks is not None else await self.get_open_tasks()
        return next((task for task in tasks if task.get("title") == title), None)

    async def get_companions(self) -> dict[str, str]:
        """Get all companion ids and display names."""
        if not self.user_id:
            raise TaskAsQuestAuthenticationError("No Task as Quest account available")
        user_id = self._escape_filter_value(self.user_id)
        companion_ids: set[str] = set()

        memberships = await self._get_all(
            _COMPANIONS_PATH,
            params={"filter": f'user="{user_id}"', "expand": "party"},
        )
        for item in memberships:
            expand = item.get("expand")
            party = expand.get("party") if isinstance(expand, dict) else None
            owner = party.get("owner") if isinstance(party, dict) else None
            if isinstance(owner, str) and owner != self.user_id:
                companion_ids.add(owner)

        owned_memberships = await self._get_all(
            _COMPANIONS_PATH,
            params={"filter": f'party.owner="{user_id}"'},
        )
        for item in owned_memberships:
            companion_id = item.get("user")
            if isinstance(companion_id, str) and companion_id != self.user_id:
                companion_ids.add(companion_id)

        result: dict[str, str] = {}
        companion_list = sorted(companion_ids)
        for start in range(0, len(companion_list), 50):
            batch = companion_list[start : start + 50]
            filter_string = " || ".join(
                f'id="{self._escape_filter_value(companion_id)}"' for companion_id in batch
            )
            accounts = await self._get_all(
                _ACCOUNTS_PATH,
                params={"filter": filter_string},
            )
            for account in accounts:
                account_id = account.get("id")
                if not isinstance(account_id, str):
                    continue
                name = account.get("display_base") or account.get("username") or "Unknown"
                number = account.get("display_number")
                result[account_id] = f"{name}#{str(number).zfill(4)}" if number else str(name)
        return result

    async def _get_public_keys(self, account_ids: list[str]) -> dict[str, str]:
        """Return public encryption keys for a set of accounts."""
        keys: dict[str, str] = {}
        for start in range(0, len(account_ids), 50):
            batch = account_ids[start : start + 50]
            filter_string = " || ".join(
                f'id="{self._escape_filter_value(account_id)}"' for account_id in batch
            )
            accounts = await self._get_all(
                _ACCOUNTS_PATH,
                params={"filter": filter_string},
            )
            for account in accounts:
                if isinstance(account.get("id"), str) and isinstance(account.get("pub_key"), str):
                    keys[account["id"]] = account["pub_key"]
        return keys

    async def create_task(
        self,
        title: str,
        difficulty: str = "medium",
        description: str | None = None,
        due_date: str | None = None,
        assignees: list[str] | None = None,
        notify_app: bool = False,
    ) -> dict[str, Any]:
        """Create a new task and optionally assign it to companions."""
        if not self.user_id:
            raise TaskAsQuestAuthenticationError("No Task as Quest account available")
        quest_key: bytes | None = None
        if self.protection_version == 1:
            if not self.protected_fields:
                raise TaskAsQuestEncryptionError("Protected fields are locked")
            try:
                payload_enc, quest_key = await self._async_run_crypto(
                    self.protected_fields.encrypt_task_write,
                    {
                        "title": title,
                        "description": description,
                        "original_task": title,
                        "user_description": description,
                    },
                )
            except ProtectedFieldsError as err:
                raise TaskAsQuestEncryptionError("Task fields could not be encrypted") from err
            payload: dict[str, Any] = {
                "user": self.user_id,
                **payload_enc,
                "difficulty": difficulty,
                "status": "open",
                "is_recurring": False,
                "recurrence_rule": None,
                "due_date": due_date,
                "has_time": bool(due_date and "T" in due_date),
            }
        else:
            payload = {
                "user": self.user_id,
                "title": title,
                "original_task": title,
                "description": description,
                "user_description": description,
                "difficulty": difficulty,
                "status": "open",
                "is_recurring": False,
                "recurrence_rule": None,
                "has_time": bool(due_date and "T" in due_date),
                "due_date": due_date,
            }

        task = await self._request("POST", _TASKS_PATH, json=payload)
        task_id = task.get("id")
        if not isinstance(task_id, str):
            raise TaskAsQuestApiError("Created task did not contain an id")

        warnings: list[str] = []
        assigned_users: set[str] = set()
        if notify_app:
            try:
                await self._request(
                    "POST",
                    _ASSIGNEES_PATH,
                    json={"task": task_id, "user": self.user_id, "role": "ha"},
                )
                assigned_users.add(self.user_id)
            except TaskAsQuestAuthenticationError:
                raise
            except TaskAsQuestError as err:
                warnings.append(f"Could not enable owner notification: {err}")

        assignee_list = list(dict.fromkeys(assignees or []))
        public_keys: dict[str, str] = {}
        if self.protection_version == 1 and assignee_list:
            try:
                public_keys = await self._get_public_keys(assignee_list)
            except TaskAsQuestAuthenticationError:
                raise
            except TaskAsQuestError as err:
                warnings.append(f"Could not load assignee encryption keys: {err}")

        for companion_id in assignee_list:
            if companion_id in assigned_users:
                continue
            assignee_payload: dict[str, Any] = {
                "task": task_id,
                "user": companion_id,
                # The app editor preserves explicit functional roles for companions.
                "role": "shared",
            }
            if self.protection_version == 1:
                if not self.protected_fields or not quest_key or companion_id not in public_keys:
                    warnings.append(f"Missing encryption key for assignee {companion_id}")
                    continue
                try:
                    assignee_payload["quest_key_wrapped"] = await self._async_run_crypto(
                        self.protected_fields.wrap_task_key_for_b64_pub,
                        quest_key,
                        public_keys[companion_id],
                    )
                except ProtectedFieldsError as err:
                    warnings.append(f"Could not encrypt assignee access: {err}")
                    continue
            try:
                await self._request("POST", _ASSIGNEES_PATH, json=assignee_payload)
                assigned_users.add(companion_id)
            except TaskAsQuestAuthenticationError:
                raise
            except TaskAsQuestError as err:
                warnings.append(f"Could not assign {companion_id}: {err}")

        if warnings:
            task["warnings"] = warnings
            _LOGGER.warning("Task as Quest created a task with warnings: %s", warnings)
        return task

    async def update_task(
        self,
        task_id: str,
        *,
        title: str,
        description: str | None,
        status: str,
        due_date: str | None,
        current_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update all mutable fields of a task."""
        payload: dict[str, Any] = {
            "status": status,
            "due_date": due_date,
            "has_time": bool(due_date and "T" in due_date),
        }
        if status == "completed":
            payload["completed_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        elif status == "open":
            payload["completed_at"] = None

        if self.protection_version == 1:
            if not self.protected_fields:
                raise TaskAsQuestEncryptionError("Protected fields are locked")
            record = current_record or await self.get_task(task_id)
            try:
                payload.update(
                    await self._async_run_crypto(
                        self.protected_fields.encrypt_task_update,
                        record,
                        {
                            "title": title,
                            "description": description,
                            "original_task": title,
                            "user_description": description,
                        },
                    )
                )
            except ProtectedFieldsError as err:
                raise TaskAsQuestEncryptionError("Task fields could not be encrypted") from err
        else:
            payload.update(
                {
                    "title": title,
                    "description": description,
                    "original_task": title,
                    "user_description": description,
                }
            )
        return await self._request("PATCH", f"{_TASKS_PATH}/{task_id}", json=payload)

    async def update_task_status(self, task_id: str, status: str) -> bool:
        """Update only the status of a task for backward compatibility."""
        payload: dict[str, Any] = {"status": status}
        if status == "completed":
            payload["completed_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        elif status == "open":
            payload["completed_at"] = None
        await self._request("PATCH", f"{_TASKS_PATH}/{task_id}", json=payload)
        return True

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        await self._request("DELETE", f"{_TASKS_PATH}/{task_id}")
        return True

    async def close(self) -> None:
        """Keep compatibility; Home Assistant owns and closes the web session."""
