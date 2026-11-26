from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Principal:
    """Created by trusted authentication layer, never from an HTTP request body."""
    user_id: UUID


class NotFound(LookupError):
    pass


class Forbidden(PermissionError):
    pass


class Conflict(ValueError):
    pass


class QuotaExceeded(ValueError):
    pass


class LeaseLost(RuntimeError):
    pass


class CancelRequested(RuntimeError):
    pass
