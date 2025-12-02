"""Centralized exception types for kqChecker.

Place API-specific error types here so they can be imported from a
single location by other modules (scheduler, inquiry, handlers...).
"""

from typing import Any, Dict, Optional


class API400Error(Exception):
    """Raised when an API returns a structured 400-like payload and alerts are enabled.

    Carries `subject`, `body`, and optional `context` (dict) for downstream handlers
    that may need to send notifications or persist debug information.
    """

    def __init__(
        self, subject: str, body: str, context: Optional[Dict[str, Any]] = None
    ):
        super().__init__(subject)
        self.subject = subject
        self.body = body
        self.context = context or {}
