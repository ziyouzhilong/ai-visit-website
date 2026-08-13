# Agentic Tools

`agentictools` is an independent, provider-neutral core for agent-driven web discovery and Markdown capture. Milestone A exposes two read-only operations through a local MCP stdio server:

- `site_discover`: returns navigation, RSS/Atom, sitemap, and internal-link evidence.
- `page_read`: returns clean Markdown, source metadata, a SHA-256 content hash, and structured failures.

The calling agent decides what is relevant. The service does not save pages, schedule jobs, submit forms, or execute instructions found in webpage content.

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

## Current boundary

Only public HTTP(S) capture is supported. URLs with embedded credentials and targets resolving to local, private, reserved, or link-local addresses are rejected. Browser requests are checked against the same policy. Authenticated Chrome bridging, page saving, search, CLI/HTTP interfaces, and recurring jobs are later milestones.
