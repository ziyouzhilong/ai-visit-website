# AI Visit website

[中文说明](README_CN.md) | English

`AI Visit website` is an independent, provider-neutral tool for agent-driven web discovery and Markdown capture. Its internal Python package and compatibility command remain `agentictools` and `agentictools-mcp`. Version 1.2.2 exposes article discovery, public capture, a user-authorized Chrome batch bridge, and local archive operations through one MCP stdio server:

- `site_discover`: returns navigation, RSS/Atom, sitemap, and internal-link evidence.
- `article_list`: returns bounded article/link candidates with publication evidence when available, without ranking importance.
- `page_read`: returns clean Markdown, source metadata, a SHA-256 content hash, and structured failures.
- `browser_status`: reports whether the paired Chrome extension is connected.
- `browser_page_read`: reads one authorized page through the user's visible, logged-in Chrome session.
- `browser_cancel`: cancels a caller-identified queued or running browser task.
- `browser_batch_start`: starts a deduplicated sequential queue of 1-20 selected URLs.
- `browser_batch_status`: returns progress plus completed page results for a batch.
- `browser_batch_cancel`: cancels queued items and the active request in a batch.
- `page_save`: writes reviewed Markdown with stable YAML frontmatter and idempotent SHA-256 deduplication.
- `archive_search`: filters saved documents by text, source, tags, capture time, or content hash and returns readable `archive://` resource links.

The calling agent decides what is relevant, which candidates enter a batch, what the report should emphasize, and whether to call `page_save`. Identical content is never written twice; changed content from the same URL is retained as a new version. The service does not schedule recurring jobs, submit forms, or execute instructions found in webpage content.

## Chrome bridge

The MCP process owns an authenticated HTTP task queue bound only to `127.0.0.1:32145`. The extension polls that queue with a one-time pairing token and accepts only website origins the user listed in extension Settings. The token is stored in one user-level bridge data directory shared by Codex, OpenClaw, Hermes, and manual setup, while each host keeps its runtime and archive isolated. It opens one visible tab at a time, returns Markdown and a full-content SHA-256, and stops on login, CAPTCHA, access-denied, paywall, or unauthorized redirects. A batch contains at most 20 explicit URLs and its status lives only for the current MCP process. Cookies, passwords, authorization headers, and browser storage are never returned.

From this repository root, print the local pairing values with:

```bash
cd '/Users/cvsc/Documents/项目开发文件夹/agentictools'
./plugins/ai-visit-website/bin/ai-visit-website-mcp --print-bridge-token
```

For a copy installed or unpacked elsewhere, first change into the plugin directory—the directory that contains `bin/`—and run:

```bash
cd '/absolute/path/to/ai-visit-website'
./bin/ai-visit-website-mcp --print-bridge-token
```

The command does not start the MCP server. It prints three local setup values:

```text
bridge_port=32145
bridge_token_file=/local/user/data/path/browser-bridge-token
bridge_token=<secret pairing value>
```

If the token file does not exist, the launcher creates it with user-only file permissions; otherwise it reuses the existing stable token. Copy only the value after `bridge_token=` into the extension's **Pairing token** field and enter `bridge_port` in **Local port**. Do not paste the token into chat, logs, screenshots, reports, or source control.

Open the **AI Visit website** extension to reach its agent-first Browser Bridge settings. Add authorized origins such as `https://www.reuters.com`, enable the bridge, save the settings, and click **Check connection**. The extension has no manual snippet capture, tag manager, import/export, or Reuters validation UI. Call `browser_status` before the first browser read.

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

## Plugin packages

The self-contained package at `plugins/ai-visit-website/` can be loaded by Codex, OpenClaw, or Hermes Agent. It contains each host's manifest plus one shared skill and one bundled copy of the Python MCP server:

- Codex: `.codex-plugin/plugin.json` and `.mcp.json`
- OpenClaw: `openclaw.plugin.json`, `package.json`, and `dist/index.js`
- Hermes Agent / Agent Plugins v1: `plugin.json` and `mcp.json`

The repository-scoped Codex marketplace is declared in `.agents/plugins/marketplace.json`. Plugin setup keeps its virtual environment, browser runtime, caches, and archive under the host-provided `PLUGIN_DATA` directory or the platform application-data directory; it does not require a global Python install. On every launch, the wrapper compares the installed Python runtime version with the bundled server version and upgrades stale runtimes before starting MCP without writing installer output to the protocol stream.

### Install from GitHub

Clone the repository when you want the source, tests, Chrome extension, and all host manifests:

```bash
git clone https://github.com/ziyouzhilong/ai-visit-website.git
cd ai-visit-website
```

For Codex, add the repository marketplace and install the plugin:

```bash
codex plugin marketplace add ziyouzhilong/ai-visit-website --ref v1.2.2
codex plugin add ai-visit-website@personal
```

If a different marketplace named `personal` is already configured, inspect `codex plugin list --json` before changing it; do not overwrite an unrelated marketplace. Start a new Codex task after installation so the updated Skill and MCP tools are loaded.

For OpenClaw, install the packaged plugin directory from a clone and then verify the runtime:

```bash
openclaw plugins install "$PWD/plugins/ai-visit-website"
openclaw gateway restart
openclaw plugins inspect ai-visit-website --runtime --json
```

Hermes Agent manifests are included, but live Hermes activation has not been validated in this release. Treat schema checks as a separate boundary from a successful host installation.

## Archive location

Set `AGENTICTOOLS_ARCHIVE_DIR` to choose the archive directory. Without it, macOS uses `~/Library/Application Support/AgenticTools/archive`; other platforms use the XDG data directory or `~/.local/share/agentictools/archive`.

Each document is a standalone Markdown file with machine-readable YAML frontmatter. `index.json` stores search metadata and content-hash mappings. Writes use temporary files and atomic replacement; `page_save` never deletes or overwrites an existing document.

## Current boundary

Public capture and explicitly paired Chrome capture are supported. URLs with embedded credentials and targets resolving to local, private, reserved, or link-local addresses are rejected. Chrome browser requests are checked against the same URL policy and the extension's origin allowlist. Bounded batches may cover multiple origins only when each origin was explicitly authorized. General CLI/HTTP interfaces, durable job history, and recurring jobs remain later milestones.

## Troubleshooting

- **Do I need to keep extension Settings open?** No. Settings are only for pairing and diagnostics. The Chrome background worker claims tasks.
- **Chrome reads fail intermittently.** Ask the agent to call `browser_status` first. Continue only when both `configured` and `connected` are `true`; on a retryable offline result, wait 5-10 seconds and retry once. The current bridge is created lazily by an MCP process and disappears when its owner exits. A dedicated `--bridge-only` mode is planned but is not implemented in 1.2.2.
- **Why does the agent often read eight articles?** Eight is not hard-coded. `article_list` defaults to 100 candidates and browser batches accept 1-20 selected URLs. The calling agent chooses a bounded set for the task.
- **HTTP 401 while checking pairing.** Reprint the stable token with `--print-bridge-token` and make sure the extension uses the same port and token. Never publish the token.
- **`domain_not_authorized`.** Add the exact origin, including scheme and non-default port, to the extension allowlist.
- **Reuters public reads return `robots_denied`.** Sitemap titles, URLs, and times are discovery evidence only. Body claims require a successful public or explicitly authorized Chrome read; do not bypass robots, CAPTCHA, login, or paywalls.
- **An update seems unchanged.** Reinstall the plugin and start a new task. Installed status alone does not prove that the new manifest, Skill, MCP handshake, tool list, or tool calls are active.

See [README_CN.md](README_CN.md) for the complete Chinese setup and troubleshooting guide.
