from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class AdapterFailure(RuntimeError):
    """Sanitized adapter failure suitable for a structured tool result."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code


class CaptureDocument(BaseModel):
    requested_url: str
    final_url: str
    title: str | None = None
    markdown: str
    html: str
    status_code: int | None = None
    published_at: str | None = None
    author: str | None = None
    elapsed_ms: int
    adapter: str


class CaptureAdapter(Protocol):
    name: str

    async def read(self, url: str) -> CaptureDocument: ...
