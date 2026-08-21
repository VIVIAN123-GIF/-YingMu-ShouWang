from typing import Any


class ServiceError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        debug: dict[str, Any] | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        # Only callers that deliberately construct a redacted diagnostic payload
        # may expose it to clients. Never put raw provider requests or secrets here.
        self.debug = debug
        super().__init__(message)
