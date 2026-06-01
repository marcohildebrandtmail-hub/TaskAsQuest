"""PocketBase API client for QuestAsTask."""

import logging
from datetime import datetime, timezone

import aiohttp

from .task_crypto import TaskCrypto, TaskCryptoError

_LOGGER = logging.getLogger(__name__)


class PocketBaseClient:
    """Async PocketBase client."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None
        self.user_id: str | None = None
        self.crypto_version: int = 0
        self.user_record: dict | None = None
        self.task_crypto: TaskCrypto | None = None
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
        """Escape a value for PocketBase filter string literals."""
        return value.replace("\\", "\\\\").replace('"', '\\"')

    async def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict | None:
        """Central request handler."""
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
                _LOGGER.error("PocketBase request failed (%s): %s", resp.status, url)
                return None
        except aiohttp.ClientError as err:
            _LOGGER.error("PocketBase connection error: %s", err)
            return None

    async def authenticate(self, email: str, password: str) -> bool:
        """Login with email/password. Returns True on success."""
        normalized_email = email.strip().lower()
        data = await self._request(
            "POST",
            "api/collections/taq_users/auth-with-password",
            json={"identity": normalized_email, "password": password},
        )
        if data:
            self.token = data.get("token")
            record = data.get("record", {})
            self.user_record = record
            self.user_id = record.get("id")
            self.crypto_version = int(record.get("crypto_version") or 0)
            _LOGGER.info("PocketBase auth OK, user_id=%s", self.user_id)
            return True
        return False

    async def authenticate_login_name(
        self,
        login_name: str,
        password: str,
        totp_code: str | None = None,
    ) -> tuple[bool, str]:
        """Login with the app's username#number login identifier."""
        login_name = login_name.strip()
        if "@" in login_name:
            res = await self.authenticate(login_name, password)
            return (res, "auth_failed" if not res else "")

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
        url = f"{self.base_url}/api/taq/login-bn"
        try:
            async with session.request("POST", url, json=payload, headers=self._headers()) as resp:
                if resp.status in {200, 201}:
                    data = await resp.json()
                    if data and data.get("token") and data.get("record"):
                        self.token = data.get("token")
                        record = data.get("record", {})
                        self.user_record = record
                        self.user_id = record.get("id")
                        self.crypto_version = int(record.get("crypto_version") or 0)
                        _LOGGER.info("Task as Quest login OK, user_id=%s", self.user_id)
                        return True, ""
                
                try:
                    err_data = await resp.json()
                    err_msg = err_data.get("message", "").lower()
                    if "totp" in err_msg or "2fa" in err_msg:
                        return False, "totp_required"
                    elif "invalid" in err_msg or "failed" in err_msg:
                        return False, "auth_failed"
                    return False, err_data.get("message", "auth_failed")
                except Exception:
                    return False, "auth_failed"
        except Exception as err:
            _LOGGER.error("PocketBase connection error: %s", err)
            return False, "cannot_connect"
        
        return False, "auth_failed"

    async def authenticate_with_token(self, token: str, user_id: str) -> bool:
        """Re-authenticate with stored token."""
        self.token = token
        self.user_id = user_id
        data = await self._request("POST", "api/collections/taq_users/auth-refresh")
        if data:
            self.token = data.get("token", token)
            record = data.get("record", {})
            self.user_record = record
            self.user_id = record.get("id", user_id)
            self.crypto_version = int(record.get("crypto_version") or 0)
            return True
        _LOGGER.warning("Token refresh failed, re-auth needed")
        return False

    def unlock_task_crypto(self, recovery_code: str | None) -> bool:
        """Unlock encrypted task support with the user's recovery code."""
        if self.crypto_version != 1:
            self.task_crypto = None
            return True
        if not self.user_record or not recovery_code:
            return False
        try:
            self.task_crypto = TaskCrypto.from_user_record(self.user_record, recovery_code)
        except TaskCryptoError as err:
            _LOGGER.error("Task as Quest crypto unlock failed: %s", err)
            self.task_crypto = None
            return False
        return True

    async def get_open_tasks(self) -> list[dict]:
        """Get all open tasks for user."""
        if not self.user_id:
            return []
        user_id = self._escape_filter_value(self.user_id)
        data = await self._request(
            "GET",
            "api/collections/taq_tasks/records",
            params={
                "filter": f'user="{user_id}" && status="open"',
                "perPage": 500,
            },
        )
        tasks = data.get("items", []) if data else []
        if self.crypto_version == 1 and self.task_crypto:
            return [self.task_crypto.decrypt_task_read(task) for task in tasks]
        return tasks

    async def find_task_by_title(self, title: str) -> dict | None:
        """Find open task with exact title."""
        if not self.user_id:
            return None
        if self.crypto_version == 1:
            for task in await self.get_open_tasks():
                if task.get("title") == title:
                    return task
            return None
        user_id = self._escape_filter_value(self.user_id)
        escaped_title = self._escape_filter_value(title)
        data = await self._request(
            "GET",
            "api/collections/taq_tasks/records",
            params={
                "filter": f'user="{user_id}" && status="open" && title="{escaped_title}"',
                "perPage": 1,
            },
        )
        items = data.get("items", []) if data else []
        return items[0] if items else None

    async def get_companions(self) -> dict[str, str]:
        """Get all companions of the user (ID -> Name)."""
        if not self.user_id:
            return {}
        user_id = self._escape_filter_value(self.user_id)
        companions = set()
        
        data1 = await self._request("GET", "api/collections/taq_party_members/records", params={
            "filter": f'user="{user_id}"',
            "expand": "party"
        })
        for item in (data1.get("items", []) if data1 else []):
            owner = item.get("expand", {}).get("party", {}).get("owner")
            if owner and owner != self.user_id:
                companions.add(owner)
                
        data2 = await self._request("GET", "api/collections/taq_party_members/records", params={
            "filter": f'party.owner="{user_id}"'
        })
        for item in (data2.get("items", []) if data2 else []):
            if item.get("user") and item["user"] != self.user_id:
                companions.add(item["user"])
                
        if not companions:
            return {}

        filter_str = " || ".join([f'id="{cid}"' for cid in companions])
        user_data = await self._request("GET", "api/collections/taq_users/records", params={"filter": filter_str})
        
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
        """Create a new task. Returns the created record or None."""
        if not self.user_id:
            return None
        if self.crypto_version == 1:
            if not self.task_crypto:
                _LOGGER.error("Task as Quest crypto is locked; cannot create encrypted task")
                return None
            payload_enc, quest_key = self.task_crypto.encrypt_task_write(
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
            task_data = await self._request("POST", "api/collections/taq_tasks/records", json=payload)
        else:
            payload: dict = {
                "user": self.user_id,
                "title": title,
                "original_task": title,
                "user_description": description,
                "difficulty": difficulty,
                "status": "open",
                "is_recurring": False,
                "recurrence_rule": None,
                "has_time": bool(due_date and "T" in due_date),
            }
            if description:
                payload["description"] = description
            if due_date:
                payload["due_date"] = due_date
            else:
                payload["due_date"] = None
            
            task_data = await self._request("POST", "api/collections/taq_tasks/records", json=payload)

        if task_data:
            task_id = task_data.get("id")
            if task_id:
                assigned_users = set()
                
                if notify_app:
                    await self._request("POST", "api/collections/taq_task_assignees/records", json={
                        "task": task_id,
                        "user": self.user_id,
                        "role": "ha"
                    })
                    assigned_users.add(self.user_id)
                
                if assignees:
                    # Fetch public keys for all assignees if crypto is enabled
                    assignee_keys = {}
                    if self.crypto_version == 1 and self.task_crypto:
                        filter_str = " || ".join([f'id="{cid}"' for cid in assignees])
                        users_data = await self._request("GET", "api/collections/taq_users/records", params={"filter": filter_str})
                        if users_data and "items" in users_data:
                            for u in users_data["items"]:
                                if u.get("pub_key"):
                                    assignee_keys[u["id"]] = u["pub_key"]

                    for comp_id in assignees:
                        if comp_id not in assigned_users:
                            assignee_payload = {
                                "task": task_id,
                                "user": comp_id
                            }
                            # Wrap the quest key for this assignee
                            if self.crypto_version == 1 and self.task_crypto and comp_id in assignee_keys:
                                try:
                                    wrapped = self.task_crypto.wrap_quest_key_for_b64_pub(
                                        quest_key, assignee_keys[comp_id]
                                    )
                                    assignee_payload["quest_key_wrapped"] = wrapped
                                except Exception as err:
                                    _LOGGER.error("Failed to wrap quest key for assignee %s: %s", comp_id, err)
                            
                            await self._request("POST", "api/collections/taq_task_assignees/records", json=assignee_payload)
                            assigned_users.add(comp_id)
        
        return task_data

    async def update_task_status(self, task_id: str, status: str) -> bool:
        """Update the status of a task (e.g., 'completed')."""
        payload: dict = {"status": status}
        if status == "completed":
            payload["completed_at"] = (
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            )
        elif status == "open":
            payload["completed_at"] = None

        data = await self._request(
            "PATCH",
            f"api/collections/taq_tasks/records/{task_id}",
            json=payload,
        )
        return data is not None

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        data = await self._request(
            "DELETE",
            f"api/collections/taq_tasks/records/{task_id}",
        )
        return data is not None

    async def close(self) -> None:
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()
