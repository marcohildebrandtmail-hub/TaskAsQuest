"""PocketBase API client for QuestAsTask."""

import logging
from datetime import datetime, timedelta

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

    async def authenticate(self, email: str, password: str) -> bool:
        """Login with email/password. Returns True on success."""
        session = await self._get_session()
        url = f"{self.base_url}/api/collections/taq_users/auth-with-password"
        try:
            async with session.post(
                url,
                json={"identity": email, "password": password},
                headers={"Content-Type": "application/json"},
            ) as resp:
                if resp.status != 200:
                    _LOGGER.error("PocketBase auth failed: %s", resp.status)
                    return False
                data = await resp.json()
                self.token = data.get("token")
                record = data.get("record", {})
                self.user_id = record.get("id")
                _LOGGER.info("PocketBase auth OK, user_id=%s", self.user_id)
                return True
        except aiohttp.ClientError as err:
            _LOGGER.error("PocketBase connection error: %s", err)
            return False

    async def authenticate_with_token(self, token: str, user_id: str) -> bool:
        """Re-authenticate with stored token."""
        self.token = token
        self.user_id = user_id
        session = await self._get_session()
        url = f"{self.base_url}/api/collections/taq_users/auth-refresh"
        try:
            async with session.post(url, headers=self._headers()) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self.token = data.get("token", token)
                    return True
                _LOGGER.warning("Token refresh failed (%s), re-auth needed", resp.status)
                return False
        except aiohttp.ClientError:
            return False

    async def get_open_tasks(self) -> list[dict]:
        """Get all open tasks for user."""
        if not self.user_id:
            return []
        session = await self._get_session()
        url = f"{self.base_url}/api/collections/taq_tasks/records"
        params = {
            "filter": f'user="{self.user_id}" && status="open"',
            "perPage": 500,
        }
        try:
            async with session.get(url, params=params, headers=self._headers()) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("items", [])
        except aiohttp.ClientError:
            return []

    async def find_task_by_title(self, title: str) -> dict | None:
        """Find open task with exact title."""
        if not self.user_id:
            return None
        session = await self._get_session()
        url = f"{self.base_url}/api/collections/taq_tasks/records"
        params = {
            "filter": f'user="{self.user_id}" && status="open" && title="{title}"',
            "perPage": 1,
        }
        try:
            async with session.get(url, params=params, headers=self._headers()) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                items = data.get("items", [])
                return items[0] if items else None
        except aiohttp.ClientError:
            return None

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
        session = await self._get_session()
        url = f"{self.base_url}/api/collections/taq_tasks/records"
        payload: dict = {
            "user": self.user_id,
            "title": title,
            "difficulty": difficulty,
            "status": "open",
            "is_recurring": False,
        }
        if description:
            payload["description"] = description
        if due_date:
            payload["due_date"] = due_date
        else:
            # Faellig heute
            payload["due_date"] = datetime.now().strftime("%Y-%m-%d 12:00:00.000Z")
        try:
            async with session.post(url, json=payload, headers=self._headers()) as resp:
                if resp.status == 200:
                    task = await resp.json()
                    _LOGGER.info("Task created: %s", title)
                    return task
                _LOGGER.error("Task creation failed: %s", resp.status)
                return None
        except aiohttp.ClientError as err:
            _LOGGER.error("Task creation error: %s", err)
            return None

    async def close(self) -> None:
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()
