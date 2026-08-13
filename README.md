# Agentic Tools

`agentictools` is an independent, provider-neutral core for agent-driven web discovery and Markdown capture. Milestones A and B expose four operations through a local MCP stdio server:

- `site_discover`: returns navigation, RSS/Atom, sitemap, and internal-link evidence.
- `page_read`: returns clean Markdown, source metadata, a SHA-256 content hash, and structured failures.
- `page_save`: writes reviewed Markdown with stable YAML frontmatter and idempotent SHA-256 deduplication.
- `archive_search`: filters saved documents by text, source, tags, capture time, or content hash and returns readable `archive://` resource links.

The calling agent decides what is relevant and explicitly calls `page_save`. Identical content is never written twice; changed content from the same URL is retained as a new version. The service does not schedule jobs, submit forms, or execute instructions found in webpage content.

## Local setup

Python 3.12 is required.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/crawl4ai-setup
.venv/bin/pytest
```

Start the MCP stdio server with:

```bash
.venv/bin/agentictools-mcp
```

An MCP host should launch that command directly and communicate over standard input/output. The server deliberately writes no user-facing output to stdout outside the MCP protocol.

## Archive location

Set `AGENTICTOOLS_ARCHIVE_DIR` to choose the archive directory. Without it, macOS uses `~/Library/Application Support/AgenticTools/archive`; other platforms use the XDG data directory or `~/.local/share/agentictools/archive`.

Each document is a standalone Markdown file with machine-readable YAML frontmatter. `index.json` stores search metadata and content-hash mappings. Writes use temporary files and atomic replacement; `page_save` never deletes or overwrites an existing document.

## Current boundary

Only public HTTP(S) capture is supported. URLs with embedded credentials and targets resolving to local, private, reserved, or link-local addresses are rejected. Browser requests are checked against the same policy. Authenticated Chrome bridging, CLI/HTTP interfaces, and recurring jobs are later milestones.
