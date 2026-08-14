from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

from agentictools.models import (
    ArchiveSearchMatch,
    ArchiveSearchResult,
    FailureDetail,
    PageSaveRequest,
    PageSaveResult,
)
from agentictools.url_policy import PublicURLPolicy, URLPolicyError


DOCUMENT_ID = re.compile(r"^[0-9a-f]{64}$")
INDEX_VERSION = 1


class ArchiveError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def default_archive_root() -> Path:
    configured = os.environ.get("AGENTICTOOLS_ARCHIVE_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.name == "posix" and Path.home().joinpath("Library").exists():
        return Path.home() / "Library" / "Application Support" / "AgenticTools" / "archive"
    data_home = os.environ.get("XDG_DATA_HOME")
    return (Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share") / "agentictools" / "archive"


class MarkdownArchive:
    """File-backed Markdown archive with atomic index updates and hash deduplication."""

    def __init__(
        self,
        root: Path | str | None = None,
        url_policy: PublicURLPolicy | None = None,
        clock: Any | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else default_archive_root()
        self.documents_dir = self.root / "documents"
        self.index_path = self.root / "index.json"
        self.lock_path = self.root / ".archive.lock"
        self.url_policy = url_policy or PublicURLPolicy()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._thread_lock = threading.RLock()

    async def save(self, request: PageSaveRequest) -> PageSaveResult:
        markdown = request.markdown.strip()
        if not markdown:
            return self._save_failure("empty_content", "The approved Markdown is empty.")
        try:
            source_url = await self.url_policy.validate(request.source_url)
        except URLPolicyError as exc:
            return self._save_failure(exc.code, str(exc))

        digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        content_hash = f"sha256:{digest}"
        if request.expected_content_hash and request.expected_content_hash != content_hash:
            return self._save_failure(
                "content_hash_mismatch",
                "The Markdown does not match the expected page_read content hash.",
            )

        captured_at = self._format_datetime(self.clock())
        tags = self._normalize_tags(request.tags)
        with self._exclusive_lock():
            try:
                index = self._load_index()
            except ArchiveError as exc:
                return self._save_failure(exc.code, str(exc))

            existing_id = index["hashes"].get(content_hash)
            if existing_id:
                existing = index["documents"].get(existing_id)
                if not existing:
                    return self._save_failure(
                        "archive_corrupt", "The archive hash index references a missing record."
                    )
                return self._result(existing, status="duplicate")

            document_id = digest
            sequence = int(index.get("next_sequence", 1))
            record = {
                "document_id": document_id,
                "resource_uri": f"archive://document/{document_id}",
                "title": request.title.strip(),
                "source_url": source_url,
                "published_at": self._optional_text(request.published_at),
                "captured_at": captured_at,
                "author": self._optional_text(request.author),
                "tags": tags,
                "task_id": self._optional_text(request.task_id),
                "content_hash": content_hash,
                "sequence": sequence,
                "filename": f"{document_id}.md",
            }
            document = self._render_document(record, markdown)
            self.documents_dir.mkdir(parents=True, exist_ok=True)
            document_path = self.documents_dir / record["filename"]
            if document_path.exists():
                return self._save_failure(
                    "archive_corrupt",
                    "An unindexed document already exists for this content hash.",
                )
            try:
                self._atomic_create(document_path, document)
            except FileExistsError:
                return self._save_failure(
                    "archive_corrupt",
                    "An unindexed document already exists for this content hash.",
                )
            except OSError:
                return self._save_failure(
                    "archive_write_failed", "The Markdown document could not be written."
                )

            index["documents"][document_id] = record
            index["hashes"][content_hash] = document_id
            index["next_sequence"] = sequence + 1
            try:
                self._write_index(index)
            except OSError:
                document_path.unlink(missing_ok=True)
                return self._save_failure("archive_write_failed", "The archive index could not be updated.")
            return self._result(record, status="saved")

    def search(
        self,
        *,
        query: str | None = None,
        source: str | None = None,
        tags: list[str] | None = None,
        captured_after: str | None = None,
        captured_before: str | None = None,
        content_hash: str | None = None,
        limit: int = 20,
    ) -> ArchiveSearchResult:
        if limit < 1 or limit > 100:
            return self._search_failure("invalid_limit", "limit must be between 1 and 100.")
        try:
            after = self._parse_datetime(captured_after) if captured_after else None
            before = self._parse_datetime(captured_before) if captured_before else None
        except ValueError:
            return self._search_failure(
                "invalid_time", "Capture time filters must be ISO 8601 timestamps with a timezone."
            )
        if after and before and after > before:
            return self._search_failure(
                "invalid_time_range", "captured_after must not be later than captured_before."
            )
        if content_hash and not re.fullmatch(r"sha256:[0-9a-f]{64}", content_hash):
            return self._search_failure(
                "invalid_content_hash", "content_hash must be a lowercase SHA-256 value."
            )

        with self._exclusive_lock():
            try:
                index = self._load_index()
            except ArchiveError as exc:
                return self._search_failure(exc.code, str(exc))
            records = list(index["documents"].values())

        query_folded = (query or "").strip().casefold()
        source_folded = (source or "").strip().casefold()
        tag_filters = {tag.strip().casefold() for tag in tags or [] if tag.strip()}
        matches: list[tuple[dict[str, Any], str]] = []
        for record in records:
            captured = self._parse_datetime(record["captured_at"])
            if after and captured < after:
                continue
            if before and captured > before:
                continue
            if source_folded and source_folded not in record["source_url"].casefold():
                continue
            if content_hash and record["content_hash"] != content_hash:
                continue
            record_tags = {tag.casefold() for tag in record.get("tags", [])}
            if tag_filters and not tag_filters.issubset(record_tags):
                continue
            try:
                body = self._document_body(self.read_document(record["document_id"]))
            except (KeyError, OSError):
                continue
            haystack = f"{record['title']}\n{body}".casefold()
            if query_folded and query_folded not in haystack:
                continue
            matches.append((record, body))

        matches.sort(
            key=lambda item: (self._parse_datetime(item[0]["captured_at"]), item[0]["sequence"]),
            reverse=True,
        )
        total = len(matches)
        result_matches = [self._search_match(record, body, query_folded) for record, body in matches[:limit]]
        return ArchiveSearchResult(success=True, total=total, matches=result_matches)

    def read_document(self, document_id: str) -> str:
        if not DOCUMENT_ID.fullmatch(document_id):
            raise KeyError(document_id)
        path = self.documents_dir / f"{document_id}.md"
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise KeyError(document_id) from exc

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._thread_lock:
            with self.lock_path.open("a+b") as lock_file:
                try:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                except ImportError:  # pragma: no cover - Windows fallback uses process-local lock
                    fcntl = None  # type: ignore[assignment]
                try:
                    yield
                finally:
                    if fcntl is not None:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _load_index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {"version": INDEX_VERSION, "next_sequence": 1, "documents": {}, "hashes": {}}
        try:
            index = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArchiveError("archive_corrupt", "The archive index is unreadable.") from exc
        if (
            index.get("version") != INDEX_VERSION
            or not isinstance(index.get("documents"), dict)
            or not isinstance(index.get("hashes"), dict)
        ):
            raise ArchiveError("archive_corrupt", "The archive index has an unsupported shape.")
        return index

    def _write_index(self, index: dict[str, Any]) -> None:
        self._atomic_write(
            self.index_path,
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _atomic_create(path: Path, content: str) -> None:
        """Create a durable document without ever replacing an existing path."""

        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _render_document(record: dict[str, Any], markdown: str) -> str:
        metadata = {
            "title": record["title"],
            "source": record["source_url"],
            "published_at": record["published_at"],
            "captured_at": record["captured_at"],
            "author": record["author"],
            "task_id": record["task_id"],
            "content_hash": record["content_hash"],
            "tags": record["tags"],
            "generator": "ai-visit-website",
        }
        metadata = {key: value for key, value in metadata.items() if value is not None}
        frontmatter = yaml.safe_dump(
            metadata,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ).rstrip()
        return f"---\n{frontmatter}\n---\n\n{markdown}\n"

    @staticmethod
    def _document_body(document: str) -> str:
        if not document.startswith("---\n"):
            return document.strip()
        marker = document.find("\n---\n", 4)
        return document[marker + 5 :].strip() if marker >= 0 else document.strip()

    @classmethod
    def _search_match(
        cls, record: dict[str, Any], body: str, query: str
    ) -> ArchiveSearchMatch:
        compact = " ".join(body.split())
        if query:
            position = compact.casefold().find(query)
            start = max(0, position - 80) if position >= 0 else 0
        else:
            start = 0
        excerpt = compact[start : start + 240]
        if start:
            excerpt = "…" + excerpt
        if start + 240 < len(compact):
            excerpt += "…"
        return ArchiveSearchMatch(
            document_id=record["document_id"],
            resource_uri=record["resource_uri"],
            title=record["title"],
            source_url=record["source_url"],
            published_at=record.get("published_at"),
            captured_at=record["captured_at"],
            tags=record.get("tags", []),
            content_hash=record["content_hash"],
            excerpt=excerpt,
        )

    @staticmethod
    def _normalize_tags(tags: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in tags:
            tag = " ".join(raw.split())[:100]
            folded = tag.casefold()
            if tag and folded not in seen:
                seen.add(folded)
                result.append(tag)
        return result

    @staticmethod
    def _optional_text(value: str | None) -> str | None:
        stripped = value.strip() if value else ""
        return stripped or None

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _format_datetime(cls, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _result(record: dict[str, Any], *, status: str) -> PageSaveResult:
        return PageSaveResult(
            success=True,
            status=status,
            document_id=record["document_id"],
            resource_uri=record["resource_uri"],
            source_url=record["source_url"],
            title=record["title"],
            captured_at=record["captured_at"],
            content_hash=record["content_hash"],
            tags=record.get("tags", []),
        )

    @staticmethod
    def _save_failure(code: str, message: str) -> PageSaveResult:
        return PageSaveResult(
            success=False,
            status="failed",
            failure=FailureDetail(code=code, message=message, retryable=False),
        )

    @staticmethod
    def _search_failure(code: str, message: str) -> ArchiveSearchResult:
        return ArchiveSearchResult(
            success=False,
            failure=FailureDetail(code=code, message=message, retryable=False),
        )
