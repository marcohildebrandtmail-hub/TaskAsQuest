"""Tests for Task as Quest HTTP failure classification."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.taskasquest.app_client import TaskAsQuestClient
from custom_components.taskasquest.exceptions import (
    TaskAsQuestAuthenticationError,
    TaskAsQuestCannotConnectError,
    TaskAsQuestRateLimitError,
    TaskAsQuestTotpRequiredError,
)

BASE_URL = "https://example.test"


async def _run_executor_job(func, *args):
    """Execute an executor callback inline while recording the async handoff."""
    return func(*args)


@pytest.mark.asyncio
async def test_authenticate_success() -> None:
    """A valid login response populates the reusable token and account."""
    async with aiohttp.ClientSession() as session:
        client = TaskAsQuestClient(BASE_URL, session)
        with aioresponses() as mocked:
            mocked.post(
                f"{BASE_URL}/api/taq/login-bn",
                status=200,
                payload={
                    "token": "token",
                    "record": {"id": "user", "crypto_version": 0},
                },
            )
            await client.authenticate("Hero#1", "password")

    assert client.token == "token"
    assert client.user_id == "user"


@pytest.mark.asyncio
async def test_authenticate_totp_is_not_generic_auth_failure() -> None:
    """The config flow can route TOTP challenges to their own step."""
    async with aiohttp.ClientSession() as session:
        client = TaskAsQuestClient(BASE_URL, session)
        with aioresponses() as mocked:
            mocked.post(
                f"{BASE_URL}/api/taq/login-bn",
                status=400,
                payload={"message": "TOTP required"},
            )
            with pytest.raises(TaskAsQuestTotpRequiredError):
                await client.authenticate("Hero#1", "password")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "exception", "headers"),
    [
        (401, TaskAsQuestAuthenticationError, {}),
        (429, TaskAsQuestRateLimitError, {"Retry-After": "120"}),
        (503, TaskAsQuestCannotConnectError, {}),
    ],
)
async def test_request_preserves_failure_category(
    status: int,
    exception: type[Exception],
    headers: dict[str, str],
) -> None:
    """Coordinator decisions receive the real failure category."""
    async with aiohttp.ClientSession() as session:
        client = TaskAsQuestClient(BASE_URL, session)
        client.restore_session("token", "user")
        with aioresponses() as mocked:
            mocked.post(
                f"{BASE_URL}/api/collections/taq_users/auth-refresh",
                status=status,
                headers=headers,
                payload={"message": "failure"},
            )
            with pytest.raises(exception):
                await client.refresh_auth(force=True)


@pytest.mark.asyncio
async def test_unlock_protected_fields_uses_executor() -> None:
    """PBKDF2 and private-key loading never run on the event loop."""
    executor_job = AsyncMock(side_effect=_run_executor_job)
    unlocked = MagicMock()
    async with aiohttp.ClientSession() as session:
        client = TaskAsQuestClient(BASE_URL, session, executor_job)
        client.protection_version = 1
        client.user_record = {"id": "user"}
        with patch(
            "custom_components.taskasquest.app_client.ProtectedFields.from_user_record",
            return_value=unlocked,
        ) as from_user_record:
            await client.async_unlock_protected_fields("password")

    executor_job.assert_awaited_once()
    from_user_record.assert_called_once_with({"id": "user"}, "password")
    assert client.protected_fields is unlocked


@pytest.mark.asyncio
async def test_open_task_batch_decryption_uses_one_executor_job() -> None:
    """A poll decrypts its complete task batch in one executor handoff."""
    executor_job = AsyncMock(side_effect=_run_executor_job)
    protected_fields = MagicMock()
    protected_fields.decrypt_task_read.side_effect = lambda task: {
        **task,
        "title": "decrypted",
    }
    async with aiohttp.ClientSession() as session:
        client = TaskAsQuestClient(BASE_URL, session, executor_job)
        client.user_id = "user"
        client.protection_version = 1
        client.protected_fields = protected_fields
        with patch.object(
            client,
            "_get_all",
            AsyncMock(return_value=[{"id": "one"}, {"id": "two"}]),
        ):
            tasks = await client.get_open_tasks()

    executor_job.assert_awaited_once()
    assert [task["title"] for task in tasks] == ["decrypted", "decrypted"]
    assert protected_fields.decrypt_task_read.call_count == 2
