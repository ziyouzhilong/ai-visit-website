# AI Visit website plugin

This is one self-contained source bundle for Codex, OpenClaw, and Hermes Agent. All three hosts load the same `ai-visit-website` skill and start the same local MCP stdio server.

## Included formats

- Codex: `.codex-plugin/plugin.json` and `.mcp.json`
- OpenClaw: `openclaw.plugin.json`, `package.json`, and `dist/index.js`
- Hermes Agent / Agent Plugins v1: `plugin.json` and `mcp.json`
- Shared runtime: `server/`, `bin/`, and `skills/`

The plugin needs Python 3.12. Its setup command creates a virtual environment and keeps Python packages, browser files, caches, and archived Markdown under the host-provided `PLUGIN_DATA` directory. When a host does not provide that variable, the launcher uses the current user's application-data directory. The Chrome pairing token is intentionally kept in a stable user-level bridge directory shared across hosts so the printed token and the running MCP server cannot diverge.

The packaged host manifests enable a guarded public-DNS fallback for transparent proxy environments that synthesize `198.18.0.0/15` addresses. The fallback accepts such a hostname only after public DNS independently resolves it exclusively to globally routable addresses. Literal benchmark-range URLs and all private, local, link-local, and other reserved targets remain blocked.

## Prepare the local server

Run this once from the installed plugin directory:

```bash
./bin/ai-visit-website-setup
```

This installs the bundled Python package and the Crawl4AI browser runtime. For a lightweight archive-only check, use `--skip-browser`.

The MCP launcher performs setup automatically on first start and upgrades an existing runtime whenever its installed version differs from the bundled server version. Installer output is redirected away from the MCP protocol stream. Set `AI_VISIT_WEBSITE_AUTO_SETUP=0` to require explicit setup instead, or `AI_VISIT_WEBSITE_AUTO_SETUP_BROWSER=0` to skip browser installation during automatic setup.

## Pair the Chrome extension

The pairing command must be run from this packaged plugin directory—the directory that contains `bin/`. It creates the local token if one does not exist and reuses the same token on later runs; it does not need to start the MCP server.

```bash
cd '/absolute/path/to/ai-visit-website'
./bin/ai-visit-website-mcp --print-bridge-token
```

When working directly from this repository, the equivalent complete command is:

```bash
cd '/Users/cvsc/Documents/项目开发文件夹/agentictools'
./plugins/ai-visit-website/bin/ai-visit-website-mcp --print-bridge-token
```

Expected output has this shape:

```text
bridge_port=32145
bridge_token_file=/local/user/data/path/browser-bridge-token
bridge_token=<secret pairing value>
```

Open the **AI Visit website** Chrome extension. Enter `bridge_port` under **Local port**, copy only the value after `bridge_token=` into **Pairing token**, and add each authorized website origin (for example `https://www.reuters.com`). Enable the bridge, save the settings, and click **Check connection**. Never paste the token into chat, logs, screenshots, reports, or source control.

The extension is agent-first and contains no manual snippet manager or Reuters validation page. The bridge listens only on `127.0.0.1`, opens one visible tab, never exports cookies or browser credentials, and stops on login, CAPTCHA, access-denied, paywall, or a redirect outside the allowlist.

## Codex

The source repository includes `.agents/plugins/marketplace.json`, so Codex can discover this package from the repository marketplace. Restart Codex, install `ai-visit-website`, start a new task, and invoke `$ai-visit-website`.

## OpenClaw

Install the package directory or an npm tarball, then reload the Gateway:

```bash
openclaw plugins install ./ai-visit-website
openclaw plugins inspect ai-visit-website --runtime --json
```

OpenClaw reads the native manifest and contributes the bundled skill and static MCP server while the plugin is enabled.

## Hermes Agent

Install the directory from its Git repository and enable it through the normal Hermes plugin workflow. Hermes reads the Agent Plugins v1 manifest, the namespaced skill, and the stdio MCP entry:

```bash
hermes plugins install owner/repository --no-enable
hermes plugins enable ai-visit-website
hermes plugins doctor ai-visit-website --ci
```

The repository placeholder must be replaced with the eventual Git hosting location. Local source validation can use `hermes plugins doctor <plugin-directory> --ci`.

## Tools and data

The server exposes `site_discover`, `article_list`, `page_read`, `browser_status`, `browser_page_read`, `browser_cancel`, `browser_batch_start`, `browser_batch_status`, `browser_batch_cancel`, `page_save`, and `archive_search`. `article_list` preserves discovery evidence without deciding importance. Browser batches accept 1-20 selected URLs, run one visible read at a time, expose progress/results, and can be canceled. Their status is retained only while the MCP process is running.

Public and Chrome reads both reject credential-bearing, local, private, reserved, and link-local targets. Every website origin used by Chrome must also be explicitly authorized in extension Settings. `page_save` writes only agent-approved Markdown and deduplicates identical content with SHA-256.

When a section page is blocked by robots policy or an automated-access challenge, `site_discover` may recover current link and title evidence from sitemaps declared by the site's public `robots.txt`. A successful result then uses adapter `robots-sitemap` and includes the original `robots_denied`, `bot_challenge`, or `access_denied` detail in `capture_warning`. This is discovery evidence, not proof that `page_read` accessed each article body.
