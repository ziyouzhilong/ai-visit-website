from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentictools.archive import MarkdownArchive
from agentictools.models import PageSaveRequest


class AllowExamplePolicy:
    async def validate(self, url: str) -> str:
        return url.split("#", 1)[0]


@pytest.fixture
def archive(tmp_path: Path) -> MarkdownArchive:
    return MarkdownArchive(
        root=tmp_path / "archive",
        url_policy=AllowExamplePolicy(),
        clock=lambda: datetime(2026, 8, 13, 10, 30, tzinfo=timezone.utc),
    )


def request(**updates: object) -> PageSaveRequest:
    values: dict[str, object] = {
        "source_url": "https://example.com/articles/one#top",
        "title": "Grid Storage Breakthrough",
        "markdown": "# Grid Storage Breakthrough\n\nA sodium battery stores renewable power.",
        "published_at": "2026-08-13T08:00:00Z",
        "author": "Example Reporter",
        "tags": ["Energy", "storage", "Energy"],
        "task_id": "watch_energy",
    }
    values.update(updates)
    return PageSaveRequest(**values)


@pytest.mark.asyncio
async def test_page_save_writes_stable_frontmatter_and_searchable_document(
    archive: MarkdownArchive,
) -> None:
    result = await archive.save(request())

    assert result.success is True
    assert result.status == "saved"
    assert result.document_id is not None
    assert result.resource_uri == f"archive://document/{result.document_id}"
    assert result.source_url == "https://example.com/articles/one"
    assert result.tags == ["Energy", "storage"]
    assert result.content_hash is not None
    assert result.content_hash.startswith("sha256:")

    files = list((archive.root / "documents").glob("*.md"))
    assert len(files) == 1
    stored = files[0].read_text(encoding="utf-8")
    assert stored.startswith("---\n")
    assert 'title: Grid Storage Breakthrough' in stored
    assert 'source: https://example.com/articles/one' in stored
    assert 'captured_at: \'2026-08-13T10:30:00Z\'' in stored
    assert 'content_hash: sha256:' in stored
    assert 'generator: ai-visit-website' in stored
    assert stored.endswith(request().markdown + "\n")

    document = archive.read_document(result.document_id)
    assert document == stored


@pytest.mark.asyncio
async def test_duplicate_content_returns_existing_document_without_rewrite(
    archive: MarkdownArchive,
) -> None:
    first = await archive.save(request())
    path = next((archive.root / "documents").glob("*.md"))
    original_mtime = path.stat().st_mtime_ns

    second = await archive.save(
        request(source_url="https://mirror.example/same", title="Mirrored title")
    )

    assert second.success is True
    assert second.status == "duplicate"
    assert second.document_id == first.document_id
    assert second.resource_uri == first.resource_uri
    assert path.stat().st_mtime_ns == original_mtime
    assert len(list((archive.root / "documents").glob("*.md"))) == 1


@pytest.mark.asyncio
async def test_same_url_with_changed_content_creates_a_new_version(
    archive: MarkdownArchive,
) -> None:
    first = await archive.save(request())
    second = await archive.save(
        request(markdown="# Grid Storage Breakthrough\n\nUpdated facts and figures.")
    )

    assert first.document_id != second.document_id
    assert second.status == "saved"
    assert len(list((archive.root / "documents").glob("*.md"))) == 2

    search = archive.search(source="example.com/articles/one", limit=10)
    assert search.success is True
    assert search.total == 2
    assert [item.document_id for item in search.matches] == [
        second.document_id,
        first.document_id,
    ]


@pytest.mark.asyncio
async def test_expected_hash_mismatch_rejects_write(archive: MarkdownArchive) -> None:
    result = await archive.save(
        request(expected_content_hash="sha256:" + "0" * 64)
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.code == "content_hash_mismatch"
    assert not list((archive.root / "documents").glob("*.md"))


@pytest.mark.asyncio
async def test_invalid_source_url_rejects_write(archive: MarkdownArchive) -> None:
    class BlockingPolicy:
        async def validate(self, _url: str) -> str:
            from agentictools.url_policy import URLPolicyError

            raise URLPolicyError("private_address", "Local targets are blocked.")

    blocked = MarkdownArchive(root=archive.root, url_policy=BlockingPolicy())
    result = await blocked.save(request(source_url="http://127.0.0.1/secret"))

    assert result.success is False
    assert result.failure is not None
    assert result.failure.code == "private_address"
    assert not list((archive.root / "documents").glob("*.md"))


@pytest.mark.asyncio
async def test_archive_search_combines_text_tag_time_and_hash_filters(
    archive: MarkdownArchive,
) -> None:
    energy = await archive.save(request())
    await archive.save(
        request(
            source_url="https://example.com/articles/ai",
            title="Agent Systems",
            markdown="# Agent Systems\n\nTool routing and evaluation.",
            tags=["AI"],
        )
    )

    result = archive.search(
        query="sodium battery",
        source="example.com",
        tags=["energy"],
        captured_after="2026-08-13T10:00:00Z",
        captured_before="2026-08-13T11:00:00Z",
        content_hash=energy.content_hash,
        limit=5,
    )

    assert result.success is True
    assert result.total == 1
    assert len(result.matches) == 1
    match = result.matches[0]
    assert match.document_id == energy.document_id
    assert match.title == "Grid Storage Breakthrough"
    assert match.tags == ["Energy", "storage"]
    assert "sodium battery" in match.excerpt
    assert match.resource_uri == energy.resource_uri


def test_archive_search_rejects_invalid_time_range(archive: MarkdownArchive) -> None:
    result = archive.search(
        captured_after="2026-08-14T00:00:00Z",
        captured_before="2026-08-13T00:00:00Z",
    )

    assert result.success is False
    assert result.failure is not None
    assert result.failure.code == "invalid_time_range"


def test_read_document_rejects_invalid_identifier(archive: MarkdownArchive) -> None:
    with pytest.raises(KeyError):
        archive.read_document("../../secret")


def test_save_request_rejects_blank_title() -> None:
    with pytest.raises(ValidationError):
        request(title="   ")


def test_search_reports_corrupt_index(archive: MarkdownArchive) -> None:
    archive.root.mkdir(parents=True)
    archive.index_path.write_text("not-json", encoding="utf-8")

    result = archive.search(query="anything")

    assert result.success is False
    assert result.failure is not None
    assert result.failure.code == "archive_corrupt"


@pytest.mark.asyncio
async def test_save_never_overwrites_orphaned_document(archive: MarkdownArchive) -> None:
    markdown = request().markdown.strip()
    import hashlib

    document_id = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    archive.documents_dir.mkdir(parents=True)
    orphan = archive.documents_dir / f"{document_id}.md"
    orphan.write_text("orphaned evidence\n", encoding="utf-8")

    result = await archive.save(request())

    assert result.success is False
    assert result.failure is not None
    assert result.failure.code == "archive_corrupt"
    assert orphan.read_text(encoding="utf-8") == "orphaned evidence\n"
    assert not archive.index_path.exists()


@pytest.mark.asyncio
async def test_document_write_error_returns_structured_failure(
    archive: MarkdownArchive, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_create(_path: Path, _content: str) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(archive, "_atomic_create", fail_create)

    result = await archive.save(request())

    assert result.success is False
    assert result.failure is not None
    assert result.failure.code == "archive_write_failed"
