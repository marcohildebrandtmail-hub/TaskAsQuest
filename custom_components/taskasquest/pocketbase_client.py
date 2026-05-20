"""PocketBase API client for QuestAsTask."""

import logging
from datetime import datetime, timezone

import aiohttp

_LOGGER = logging.getLogger(__name__)


class PocketBaseClient:
    """Async PocketBase client."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None
        self.user_id: str | None = None
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
            self.user_id = record.get("id")
            _LOGGER.info("PocketBase auth OK, user_id=%s", self.user_id)
            return True
        return False

    async def authenticate_with_token(self, token: str, user_id: str) -> bool:
        """Re-authenticate with stored token."""
        self.token = token
        self.user_id = user_id
        data = await self._request("POST", "api/collections/taq_users/auth-refresh")
        if data:
            self.token = data.get("token", token)
            record = data.get("record", {})
            self.user_id = record.get("id", user_id)
            return True
        _LOGGER.warning("Token refresh failed, re-auth needed")
        return False

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
        return data.get("items", []) if data else []

    async def find_task_by_title(self, title: str) -> dict | None:
        """Find open task with exact title."""
        if not self.user_id:
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

    async def create_task(
        self,
        title: str,
        difficulty: str = "medium",
        description: str | None = None,
        due_date: str | None = None,
    ) -> dict | None:
        """Create a new task. Returns the created record or None."""
        if not self.user_id:
            return None
        payload: dict = {
            "user": self.user_id,
            "title": title,
            "original_task": title,
            "user_description": description,
            "difficulty": difficulty,
            "status": "open",
            "is_recurring": False,
            "recurrence_rule": None,
        }
        if description:
            payload["description"] = description
        if due_date:
            payload["due_date"] = due_date
        else:
            payload["due_date"] = None
        
        return await self._request("POST", "api/collections/taq_tasks/records", json=payload)

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
