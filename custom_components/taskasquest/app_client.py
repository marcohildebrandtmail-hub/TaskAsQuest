"""Task as Quest service API client."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp

from .protected_fields import ProtectedFields, ProtectedFieldsError

_LOGGER = logging.getLogger(__name__)

_LOGIN_PATH = "api/taq/login-bn"
_TASKS_PATH = "api/collections/taq_tasks/records"
_ASSIGNEES_PATH = "api/collections/taq_task_assignees/records"
_COMPANIONS_PATH = "api/collections/taq_party_members/records"
_ACCOUNTS_PATH = "api/collections/taq_users/records"


class TaskAsQuestClient:
    """Async client for the app service."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None
        self.user_id: str | None = None
        self.protection_version: int = 0
        self.user_record: dict | None = None
        self.protected_fields: ProtectedFields | None = None
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = self.token
        return headers

    @staticmethod
    def _escape_filter_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    async def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict | None:
        session = await self._get_session()
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            async with session.request(
                method, url, json=json, params=params, headers=self._headers()
            ) as resp:
                if resp.status == 204:
                    return {}
                if resp.status in {200, 201}:
                    return await resp.json()
                _LOGGER.error("Task as Quest request failed (%s)", resp.status)
                return None
        except aiohttp.ClientError as err:
            _LOGGER.error("Task as Quest connection error: %s", err)
            return None

    async def authenticate(
        self,
        login_name: str,
        password: str,
        totp_code: str | None = None,
    ) -> tuple[bool, str]:
        """Login with the app account identifier."""
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

        session = await self._get_session()
        url = f"{self.base_url}/{_LOGIN_PATH}"
        try:
            async with session.request("POST", url, json=payload, headers=self._headers()) as resp:
                if resp.status in {200, 201}:
                    data = await resp.json()
                    if data and data.get("token") and data.get("record"):
                        self.token = data.get("token")
                        record = data.get("record", {})
                        self.user_record = record
                        self.user_id = record.get("id")
                        self.protection_version = int(record.get("crypto_version") or 0)
                        _LOGGER.info("Task as Quest login OK")
                        return True, ""

                try:
                    err_data = await resp.json()
                    err_msg = err_data.get("message", "").lower()
                    if "totp" in err_msg or "2fa" in err_msg:
                        return False, "totp_required"
                    if "invalid" in err_msg or "failed" in err_msg:
                        return False, "auth_failed"
                    return False, err_data.get("message", "auth_failed")
                except Exception:  # noqa: BLE001 - provider error bodies are not guaranteed.
                    return False, "auth_failed"
        except aiohttp.ClientError as err:
            _LOGGER.error("Task as Quest connection error: %s", err)
            return False, "cannot_connect"

    def unlock_protected_fields(self, recovery_code: str | None) -> bool:
        """Unlock protected task fields when the account requires it."""
        if self.protection_version != 1:
            self.protected_fields = None
            return True
        if not self.user_record or not recovery_code:
            return False
        try:
            self.protected_fields = ProtectedFields.from_user_record(
                self.user_record,
                recovery_code,
            )
        except ProtectedFieldsError as err:
            _LOGGER.error("Task as Quest protected fields unlock failed: %s", err)
            self.protected_fields = None
            return False
        return True

    async def get_open_tasks(self) -> list[dict]:
        """Get all open tasks for the current account."""
        if not self.user_id:
            return []
        user_id = self._escape_filter_value(self.user_id)
        data = await self._request(
            "GET",
            _TASKS_PATH,
            params={
                "filter": f'user="{user_id}" && status="open"',
                "perPage": 500,
            },
        )
        tasks = data.get("items", []) if data else []
        if self.protection_version == 1 and self.protected_fields:
            return [self.protected_fields.decrypt_task_read(task) for task in tasks]
        return tasks

    async def find_task_by_title(self, title: str) -> dict | None:
        """Find an open task with an exact title."""
        if not self.user_id:
            return None
        if self.protection_version == 1:
            for task in await self.get_open_tasks():
                if task.get("title") == title:
                    return task
            return None
        user_id = self._escape_filter_value(self.user_id)
        escaped_title = self._escape_filter_value(title)
        data = await self._request(
            "GET",
            _TASKS_PATH,
            params={
                "filter": f'user="{user_id}" && status="open" && title="{escaped_title}"',
                "perPage": 1,
            },
        )
        items = data.get("items", []) if data else []
        return items[0] if items else None

    async def get_companions(self) -> dict[str, str]:
        """Get companion ids and display names."""
        if not self.user_id:
            return {}
        user_id = self._escape_filter_value(self.user_id)
        companions = set()

        data1 = await self._request(
            "GET",
            _COMPANIONS_PATH,
            params={"filter": f'user="{user_id}"', "expand": "party"},
        )
        for item in (data1.get("items", []) if data1 else []):
            owner = item.get("expand", {}).get("party", {}).get("owner")
            if owner and owner != self.user_id:
                companions.add(owner)

        data2 = await self._request(
            "GET",
            _COMPANIONS_PATH,
            params={"filter": f'party.owner="{user_id}"'},
        )
        for item in (data2.get("items", []) if data2 else []):
            if item.get("user") and item["user"] != self.user_id:
                companions.add(item["user"])

        if not companions:
            return {}

        filter_str = " || ".join([f'id="{cid}"' for cid in companions])
        user_data = await self._request("GET", _ACCOUNTS_PATH, params={"filter": filter_str})

        result = {}
        for item in (user_data.get("items", []) if user_data else []):
            name = item.get("display_base", item.get("username", "Unknown"))
            number = item.get("display_number")
            if number:
                name = f"{name}#{str(number).zfill(4)}"
            result[item["id"]] = name

        return result

    async def create_task(
        self,
        title: str,
        difficulty: str = "medium",
        description: str | None = None,
        due_date: str | None = None,
        assignees: list[str] | None = None,
        notify_app: bool = False,
    ) -> dict | None:
        """Create a new task."""
        if not self.user_id:
            return None
        quest_key = None
        if self.protection_version == 1:
            if not self.protected_fields:
                _LOGGER.error("Task as Quest protected fields are locked")
                return None
            payload_enc, quest_key = self.protected_fields.encrypt_task_write(
                {
                    "title": title,
                    "description": description,
                    "original_task": title,
                    "user_description": description,
                }
            )
            payload: dict = {
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
                "user_description": description,
                "difficulty": difficulty,
                "status": "open",
                "is_recurring": False,
                "recurrence_rule": None,
                "has_time": bool(due_date and "T" in due_date),
                "due_date": due_date,
            }
            if description:
                payload["description"] = description

        task_data = await self._request("POST", _TASKS_PATH, json=payload)
        if not task_data:
            return None

        task_id = task_data.get("id")
        if not task_id:
            return task_data

        assigned_users = set()
        if notify_app:
            await self._request(
                "POST",
                _ASSIGNEES_PATH,
                json={"task": task_id, "user": self.user_id, "role": "ha"},
            )
            assigned_users.add(self.user_id)

        if assignees:
            assignee_keys = {}
            if self.protection_version == 1 and self.protected_fields and quest_key:
                filter_str = " || ".join([f'id="{cid}"' for cid in assignees])
                users_data = await self._request("GET", _ACCOUNTS_PATH, params={"filter": filter_str})
                if users_data and "items" in users_data:
                    for user in users_data["items"]:
                        if user.get("pub_key"):
                            assignee_keys[user["id"]] = user["pub_key"]

            for companion_id in assignees:
                if companion_id in assigned_users:
                    continue
                assignee_payload = {"task": task_id, "user": companion_id}
                if (
                    self.protection_version == 1
                    and self.protected_fields
                    and quest_key
                    and companion_id in assignee_keys
                ):
                    try:
                        assignee_payload["quest_key_wrapped"] = (
                            self.protected_fields.wrap_task_key_for_b64_pub(
                                quest_key,
                                assignee_keys[companion_id],
                            )
                        )
                    except ProtectedFieldsError as err:
                        _LOGGER.error("Could not prepare assignee access: %s", err)

                await self._request("POST", _ASSIGNEES_PATH, json=assignee_payload)
                assigned_users.add(companion_id)

        return task_data

    async def update_task_status(self, task_id: str, status: str) -> bool:
        """Update the status of a task."""
        payload: dict = {"status": status}
        if status == "completed":
            payload["completed_at"] = (
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            )
        elif status == "open":
            payload["completed_at"] = None

        data = await self._request("PATCH", f"{_TASKS_PATH}/{task_id}", json=payload)
        return data is not None

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        data = await self._request("DELETE", f"{_TASKS_PATH}/{task_id}")
        return data is not None

    async def close(self) -> None:
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()
