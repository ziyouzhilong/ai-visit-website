# Changelog

## 1.2.2 - 2026-08-21

- Renamed and refocused Chrome extension 1.5.0 as **AI Visit website**.
- Removed manual snippet capture, tags/folders, import/export, shortcuts, context menus, and Reuters validation UI.
- Kept the production Reuters extractor for agent-authorized browser reads.
- Rebuilt the extension settings as an agent-first Bridge configuration and status page.
- Documented exact Pairing token commands and secrecy boundaries.
- Updated the Skill to require `browser_status` before Chrome reads, one bounded retry, and a clear stop condition.
- Added regression coverage for the agent-first extension contract.
- Added Chinese installation, usage, security, and troubleshooting documentation based on observed failures.

Known limitation: the local Bridge is still created lazily by an MCP process. A dedicated `--bridge-only` foreground mode is planned but is not included in 1.2.2.

## 1.2.1 - 2026-08-20

- Added public sitemap discovery fallback, user-authorized Chrome reads, bounded browser batches, cancellation, and structured status.
- Packaged shared Codex, OpenClaw, and Hermes Agent manifests around one MCP server and Skill.
- Completed a real Codex/Chrome Reuters reading workflow while preserving robots and access-control boundaries.
