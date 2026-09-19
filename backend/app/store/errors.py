"""Persistence failures are never silent.

Step 11's spec: "if a Supabase write fails, surface it to the user/dev console
immediately rather than letting a generation appear to succeed in the UI but
never get persisted". Every store method raises on failure; nothing returns a
falsy sentinel that a caller could accidentally ignore.
"""
from __future__ import annotations


class PersistenceError(RuntimeError):
    """Raised whenever a read or write against the store does not succeed."""

    def __init__(self, operation: str, detail: str, *, status: int | None = None):
        self.operation = operation
        self.detail = detail
        self.status = status
        suffix = f" (HTTP {status})" if status is not None else ""
        super().__init__(f"persistence {operation} failed{suffix}: {detail}")


class NotFoundError(PersistenceError):
    """A row that must exist does not."""

    def __init__(self, operation: str, detail: str):
        super().__init__(operation, detail, status=404)
