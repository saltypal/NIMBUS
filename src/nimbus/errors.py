"""Domain errors carry stable codes across CLI and HTTP boundaries."""


class NimbusError(Exception):
    def __init__(self, code: str, message: str, status: int = 422, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


class Conflict(NimbusError):
    def __init__(
        self, code="revision_conflict", message="The record changed. Refresh and review again."
    ):
        super().__init__(code, message, 409)
