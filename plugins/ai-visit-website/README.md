# AI Visit website plugin

This is one self-contained source bundle for Codex, OpenClaw, and Hermes Agent. All three hosts load the same `ai-visit-website` skill and start the same local MCP stdio server.

## Included formats

- Codex: `.codex-plugin/plugin.json` and `.mcp.json`
- OpenClaw: `openclaw.plugin.json`, `package.json`, and `dist/index.js`
- Hermes Agent / Agent Plugins v1: `plugin.json` and `mcp.json`
- Shared runtime: `server/`, `bin/`, and `skills/`

The plugin needs Python 3.12. Its setup command creates a virtual environment and keeps Python packages, browser files, caches, and archived Markdown under the host-provided `PLUGIN_DATA` directory. When a host does not provide that variable, the launcher uses the current user's application-data directory.

## Prepare the local server

Run this once from the installed plugin directory:

```bash
./bin/ai-visit-website-setup
```

This installs the bundled Python package and the Crawl4AI browser runtime. For a lightweight archive-only check, use `--skip-browser`.

The MCP launcher can perform this setup automatically on first start. Set `AI_VISIT_WEBSITE_AUTO_SETUP=0` to require explicit setup instead, or `AI_VISIT_WEBSITE_AUTO_SETUP_BROWSER=0` to skip browser installation during automatic setup.

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

The server exposes `site_discover`, `page_read`, `page_save`, and `archive_search`. It only captures public HTTP(S) pages and rejects credential-bearing, local, private, reserved, and link-local targets. `page_save` writes only agent-approved Markdown and deduplicates identical content with SHA-256.
