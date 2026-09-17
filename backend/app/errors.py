"""HTTP-safe application errors."""

from __future__ import annotations

from typing import Any


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str, *, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            error["details"] = self.details
        return {"error": error}


