"""Exceptions raised by the Task as Quest API client."""

from __future__ import annotations


class TaskAsQuestError(Exception):
    """Base exception for Task as Quest."""


class TaskAsQuestApiError(TaskAsQuestError):
    """The API rejected a request."""


class TaskAsQuestAuthenticationError(TaskAsQuestError):
    """Authentication is invalid or expired."""


class TaskAsQuestCannotConnectError(TaskAsQuestError):
    """The Task as Quest server cannot be reached."""


class TaskAsQuestEncryptionError(TaskAsQuestError):
    """Protected fields could not be unlocked or processed."""


class TaskAsQuestRateLimitError(TaskAsQuestError):
    """The Task as Quest server is rate limiting requests."""

    def __init__(self, retry_after: float = 60) -> None:
        """Initialize a rate limit error."""
        super().__init__("The Task as Quest server is rate limiting requests")
        self.retry_after = max(1, min(retry_after, 3600))


class TaskAsQuestTotpRequiredError(TaskAsQuestAuthenticationError):
    """A TOTP code is required to finish authentication."""
