from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol

from agentictools.models import (
    BrowserBridgeStatusResult,
    BrowserCancelResult,
    FailureDetail,
    PageReadResult,
)


DEFAULT_BRIDGE_HOST = "127.0.0.1"
DEFAULT_BRIDGE_PORT = 32145
MAX_REQUEST_BODY = 6 * 1024 * 1024
REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_bridge_data_dir() -> Path:
    explicit = os.environ.get("AI_VISIT_WEBSITE_BRIDGE_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser()
    if os.name == "posix" and Path.home().joinpath("Library").exists():
        return Path.home() / "Library" / "Application Support" / "AI Visit website"
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base / "ai-visit-website"


def load_or_create_bridge_token(path: Path | None = None) -> str:
    configured = os.environ.get("AI_VISIT_WEBSITE_BRIDGE_TOKEN")
    if configured:
        return configured.strip()
    token_path = path or default_bridge_data_dir() / "browser-bridge-token"
    if token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
        raise RuntimeError("The browser bridge token file is invalid.")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(token_path, flags, 0o600)
    except FileExistsError:
        token = token_path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
        raise RuntimeError("The browser bridge token file is invalid.")
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    return token


@dataclass
class _BrowserTask:
    request_id: str
    url: str
    purpose: str | None
    timeout_seconds: int
    created_at: str
    state: str = "queued"
    claimed_at: str | None = None
    completed_at: str | None = None
    result: dict[str, Any] | None = None

    def public_request(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "type": "page_read",
            "url": self.url,
            "purpose": self.purpose,
            "timeoutSeconds": self.timeout_seconds,
            "createdAt": self.created_at,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "state": self.state,
            "created_at": self.created_at,
            "claimed_at": self.claimed_at,
            "completed_at": self.completed_at,
            "result": self.result,
        }


class BrowserTaskBroker:
    """Thread-safe queue shared by the MCP client and Chrome extension."""

    def __init__(self, *, heartbeat_ttl_seconds: int = 45, max_tasks: int = 20) -> None:
        self.heartbeat_ttl_seconds = heartbeat_ttl_seconds
        self.max_tasks = max_tasks
        self._condition = threading.Condition()
        self._tasks: dict[str, _BrowserTask] = {}
        self._queue: list[str] = []
        self._last_seen_monotonic: float | None = None
        self._last_seen_at: str | None = None
        self._extension_version: str | None = None

    def heartbeat(self, extension_version: str | None = None) -> dict[str, Any]:
        with self._condition:
            self._last_seen_monotonic = time.monotonic()
            self._last_seen_at = _utc_now()
            if extension_version:
                self._extension_version = extension_version[:100]
            self._condition.notify_all()
            return self.status()

    def status(self) -> dict[str, Any]:
        with self._condition:
            connected = (
                self._last_seen_monotonic is not None
                and time.monotonic() - self._last_seen_monotonic <= self.heartbeat_ttl_seconds
            )
            active = next(
                (task.request_id for task in self._tasks.values() if task.state == "running"),
                None,
            )
            return {
                "connected": connected,
                "extension_version": self._extension_version,
                "last_seen_at": self._last_seen_at,
                "queued_tasks": sum(task.state == "queued" for task in self._tasks.values()),
                "active_request_id": active,
            }

    def create_task(
        self,
        *,
        url: str,
        purpose: str | None,
        timeout_seconds: int,
        request_id: str | None = None,
    ) -> _BrowserTask:
        identifier = request_id or uuid.uuid4().hex
        if not REQUEST_ID.fullmatch(identifier):
            raise ValueError("request_id must contain only letters, numbers, dot, underscore, or dash")
        if not url:
            raise ValueError("url is required")
        if timeout_seconds < 15 or timeout_seconds > 120:
            raise ValueError("timeout_seconds must be between 15 and 120")
        if purpose is not None and not isinstance(purpose, str):
            raise ValueError("purpose must be a string")
        with self._condition:
            existing = self._tasks.get(identifier)
            if existing is not None:
                if existing.url == url:
                    return existing
                raise ValueError("request_id is already used for another URL")
            unfinished = sum(task.state in {"queued", "running"} for task in self._tasks.values())
            if unfinished >= self.max_tasks:
                raise OverflowError("browser task queue is full")
            task = _BrowserTask(
                request_id=identifier,
                url=url,
                purpose=purpose[:500] if purpose else None,
                timeout_seconds=timeout_seconds,
                created_at=_utc_now(),
            )
            self._tasks[identifier] = task
            self._queue.append(identifier)
            self._condition.notify_all()
            return task

    def claim_task(
        self,
        *,
        wait_seconds: float,
        extension_version: str | None,
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + max(0, min(wait_seconds, 30))
        self.heartbeat(extension_version)
        with self._condition:
            while True:
                while self._queue:
                    request_id = self._queue.pop(0)
                    task = self._tasks.get(request_id)
                    if task is None or task.state != "queued":
                        continue
                    task.state = "running"
                    task.claimed_at = _utc_now()
                    self._condition.notify_all()
                    return task.public_request()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
                self._last_seen_monotonic = time.monotonic()
                self._last_seen_at = _utc_now()

    def complete_task(self, request_id: str, result: dict[str, Any]) -> bool:
        with self._condition:
            task = self._tasks.get(request_id)
            if task is None or task.state in {"completed", "canceled"}:
                return False
            task.state = "completed"
            task.completed_at = _utc_now()
            task.result = result
            self._condition.notify_all()
            return True

    def wait_for_task(self, request_id: str, wait_seconds: float) -> dict[str, Any] | None:
        deadline = time.monotonic() + max(0, min(wait_seconds, 120))
        with self._condition:
            task = self._tasks.get(request_id)
            if task is None:
                return None
            while task.state not in {"completed", "canceled"}:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            return task.snapshot()

    def cancel_task(self, request_id: str) -> str:
        with self._condition:
            task = self._tasks.get(request_id)
            if task is None:
                return "not_found"
            if task.state in {"completed", "canceled"}:
                return "already_finished"
            task.state = "canceled"
            task.completed_at = _utc_now()
            self._condition.notify_all()
            return "canceled"


class _BridgeRequestHandler(BaseHTTPRequestHandler):
    server_version = "AIBrowserBridge/1.0"

    @property
    def broker(self) -> BrowserTaskBroker:
        return self.server.broker  # type: ignore[attr-defined]

    @property
    def token(self) -> str:
        return self.server.bridge_token  # type: ignore[attr-defined]

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            return self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/v1/agent/status":
            return self._write_json(HTTPStatus.OK, self.broker.status())
        match = re.fullmatch(r"/v1/agent/tasks/([A-Za-z0-9._-]+)", parsed.path)
        if match:
            query = urllib.parse.parse_qs(parsed.query)
            try:
                wait = float(query.get("wait", ["0"])[0])
            except ValueError:
                return self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_wait"})
            snapshot = self.broker.wait_for_task(match.group(1), wait)
            if snapshot is None:
                return self._write_json(HTTPStatus.NOT_FOUND, {"error": "task_not_found"})
            return self._write_json(HTTPStatus.OK, snapshot)
        return self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        try:
            payload = self._read_json()
        except ValueError as exc:
            return self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/v1/extension/heartbeat":
            status = self.broker.heartbeat(payload.get("extensionVersion"))
            return self._write_json(HTTPStatus.OK, status)
        if parsed.path == "/v1/extension/tasks/claim":
            try:
                wait = float(payload.get("waitSeconds", 20))
            except (TypeError, ValueError):
                return self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_wait"})
            task = self.broker.claim_task(
                wait_seconds=wait,
                extension_version=payload.get("extensionVersion"),
            )
            if task is None:
                self.send_response(HTTPStatus.NO_CONTENT)
                self._cors_headers()
                self.end_headers()
                return
            return self._write_json(HTTPStatus.OK, task)

        completion = re.fullmatch(
            r"/v1/extension/tasks/([A-Za-z0-9._-]+)/complete", parsed.path
        )
        if completion:
            result = payload.get("result")
            if not isinstance(result, dict):
                return self._write_json(HTTPStatus.BAD_REQUEST, {"error": "result_required"})
            accepted = self.broker.complete_task(completion.group(1), result)
            status = HTTPStatus.OK if accepted else HTTPStatus.CONFLICT
            return self._write_json(status, {"accepted": accepted})

        if parsed.path == "/v1/agent/tasks":
            try:
                task = self.broker.create_task(
                    url=str(payload.get("url") or ""),
                    purpose=payload.get("purpose"),
                    timeout_seconds=int(payload.get("timeout_seconds", 60)),
                    request_id=payload.get("request_id"),
                )
            except ValueError as exc:
                return self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except OverflowError as exc:
                return self._write_json(HTTPStatus.TOO_MANY_REQUESTS, {"error": str(exc)})
            return self._write_json(HTTPStatus.CREATED, task.snapshot())

        cancel = re.fullmatch(r"/v1/agent/tasks/([A-Za-z0-9._-]+)/cancel", parsed.path)
        if cancel:
            status = self.broker.cancel_task(cancel.group(1))
            return self._write_json(HTTPStatus.OK, {"request_id": cancel.group(1), "status": status})
        return self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        expected = f"Bearer {self.token}"
        return hmac.compare_digest(header, expected)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid_content_length") from exc
        if length < 0 or length > MAX_REQUEST_BODY:
            raise ValueError("request_body_too_large")
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            raise ValueError("invalid_json") from exc
        if not isinstance(value, dict):
            raise ValueError("json_object_required")
        return value

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "authorization, content-type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class BrowserBridgeHTTPServer:
    def __init__(
        self,
        *,
        host: str = DEFAULT_BRIDGE_HOST,
        port: int = DEFAULT_BRIDGE_PORT,
        token: str,
        broker: BrowserTaskBroker | None = None,
    ) -> None:
        if host != DEFAULT_BRIDGE_HOST:
            raise ValueError("The browser bridge may listen only on 127.0.0.1.")
        self.broker = broker or BrowserTaskBroker()
        self._server = ThreadingHTTPServer((host, port), _BridgeRequestHandler)
        self._server.daemon_threads = True
        self._server.broker = self.broker  # type: ignore[attr-defined]
        self._server.bridge_token = token  # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def endpoint(self) -> str:
        return f"http://{DEFAULT_BRIDGE_HOST}:{self.port}"

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="ai-visit-website-browser-bridge",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)


class BrowserBridge(Protocol):
    async def status(self) -> BrowserBridgeStatusResult: ...

    async def page_read(
        self,
        url: str,
        *,
        purpose: str | None,
        timeout_seconds: int,
        request_id: str | None,
    ) -> PageReadResult: ...

    async def cancel(self, request_id: str) -> BrowserCancelResult: ...


class LoopbackBrowserBridgeClient:
    def __init__(self, *, endpoint: str, token: str) -> None:
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname != DEFAULT_BRIDGE_HOST:
            raise ValueError("Browser bridge endpoint must be loopback HTTP on 127.0.0.1.")
        self.endpoint = endpoint.rstrip("/")
        self.token = token

    async def status(self) -> BrowserBridgeStatusResult:
        try:
            payload = await asyncio.to_thread(self._request, "GET", "/v1/agent/status", None, 3)
        except (OSError, ValueError) as exc:
            return BrowserBridgeStatusResult(
                success=False,
                configured=True,
                connected=False,
                endpoint=self.endpoint,
                failure=FailureDetail(
                    code="bridge_unavailable",
                    message="The local Chrome bridge is not available.",
                    retryable=True,
                ),
            )
        return BrowserBridgeStatusResult(
            success=True,
            configured=True,
            connected=bool(payload.get("connected")),
            endpoint=self.endpoint,
            extension_version=payload.get("extension_version"),
            last_seen_at=payload.get("last_seen_at"),
            queued_tasks=int(payload.get("queued_tasks", 0)),
            active_request_id=payload.get("active_request_id"),
        )

    async def page_read(
        self,
        url: str,
        *,
        purpose: str | None,
        timeout_seconds: int,
        request_id: str | None,
    ) -> PageReadResult:
        status = await self.status()
        if not status.success or not status.connected:
            return PageReadResult(
                success=False,
                original_url=url,
                request_id=request_id,
                adapter="chrome-extension",
                elapsed_ms=0,
                failure=FailureDetail(
                    code="bridge_offline",
                    message="Chrome is not connected to the local browser bridge.",
                    retryable=True,
                ),
            )
        started = time.perf_counter()
        try:
            created = await asyncio.to_thread(
                self._request,
                "POST",
                "/v1/agent/tasks",
                {
                    "url": url,
                    "purpose": purpose,
                    "timeout_seconds": timeout_seconds,
                    "request_id": request_id,
                },
                5,
            )
            identifier = str(created["request_id"])
            snapshot = await asyncio.to_thread(
                self._request,
                "GET",
                f"/v1/agent/tasks/{urllib.parse.quote(identifier)}?wait={timeout_seconds}",
                None,
                timeout_seconds + 5,
            )
        except (OSError, ValueError, KeyError):
            return PageReadResult(
                success=False,
                original_url=url,
                request_id=request_id,
                adapter="chrome-extension",
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                failure=FailureDetail(
                    code="bridge_unavailable",
                    message="The local Chrome bridge stopped responding.",
                    retryable=True,
                ),
            )
        if snapshot.get("state") != "completed" or not isinstance(snapshot.get("result"), dict):
            await self.cancel(identifier)
            return PageReadResult(
                success=False,
                original_url=url,
                request_id=identifier,
                adapter="chrome-extension",
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                failure=FailureDetail(
                    code="browser_read_timeout",
                    message="Chrome did not finish the page read before the timeout.",
                    retryable=True,
                ),
            )
        result = PageReadResult.model_validate(snapshot["result"])
        return result.model_copy(update={"request_id": identifier})

    async def cancel(self, request_id: str) -> BrowserCancelResult:
        try:
            payload = await asyncio.to_thread(
                self._request,
                "POST",
                f"/v1/agent/tasks/{urllib.parse.quote(request_id)}/cancel",
                {},
                5,
            )
        except (OSError, ValueError):
            return BrowserCancelResult(
                success=False,
                request_id=request_id,
                status="failed",
                failure=FailureDetail(
                    code="bridge_unavailable",
                    message="The local Chrome bridge is not available.",
                    retryable=True,
                ),
            )
        status = str(payload.get("status") or "failed")
        return BrowserCancelResult(
            success=status == "canceled",
            request_id=request_id,
            status=status,
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        timeout: int,
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"bridge_http_{exc.code}: {detail[:200]}") from exc
        if not body:
            return {}
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("The bridge returned an invalid response.")
        return value


_runtime_lock = threading.Lock()
_runtime_server: BrowserBridgeHTTPServer | None = None


def default_browser_bridge() -> LoopbackBrowserBridgeClient:
    global _runtime_server
    port = int(os.environ.get("AI_VISIT_WEBSITE_BRIDGE_PORT", DEFAULT_BRIDGE_PORT))
    token = load_or_create_bridge_token()
    endpoint = f"http://{DEFAULT_BRIDGE_HOST}:{port}"
    with _runtime_lock:
        if _runtime_server is None:
            try:
                server = BrowserBridgeHTTPServer(port=port, token=token)
                server.start()
                _runtime_server = server
            except OSError:
                # Another local plugin process may already own the shared bridge port.
                pass
    return LoopbackBrowserBridgeClient(endpoint=endpoint, token=token)


def verify_page_result_hash(result: PageReadResult) -> bool:
    if not result.success or not result.markdown or not result.content_hash:
        return False
    digest = hashlib.sha256(result.markdown.encode("utf-8")).hexdigest()
    return hmac.compare_digest(result.content_hash, f"sha256:{digest}")
