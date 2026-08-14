from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "ai-visit-website"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_codex_plugin_manifest_and_marketplace_are_complete() -> None:
    manifest = read_json(PLUGIN / ".codex-plugin" / "plugin.json")
    mcp = read_json(PLUGIN / ".mcp.json")
    marketplace = read_json(ROOT / ".agents" / "plugins" / "marketplace.json")

    assert manifest["name"] == "ai-visit-website"
    assert manifest["interface"]["displayName"] == "AI Visit website"
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert mcp["mcpServers"]["ai-visit-website"]["command"] == (
        "./bin/ai-visit-website-mcp"
    )
    assert marketplace["plugins"][0]["source"]["path"] == (
        "./plugins/ai-visit-website"
    )


def test_openclaw_and_agent_plugins_manifests_share_one_runtime() -> None:
    openclaw = read_json(PLUGIN / "openclaw.plugin.json")
    portable = read_json(PLUGIN / "plugin.json")
    portable_mcp = read_json(PLUGIN / "mcp.json")
    npm = read_json(PLUGIN / "package.json")

    assert openclaw["id"] == portable["name"] == npm["name"] == "ai-visit-website"
    assert openclaw["version"] == portable["version"] == npm["version"] == "0.2.0"
    assert openclaw["skills"] == ["./skills"]
    assert openclaw["mcpServers"]["ai-visit-website"]["command"] == (
        "./bin/ai-visit-website-mcp"
    )
    assert portable_mcp["mcpServers"]["ai-visit-website"]["command"] == (
        "./bin/ai-visit-website-mcp"
    )
    assert npm["openclaw"]["extensions"] == ["./dist/index.js"]
    assert npm["openclaw"]["compat"]["pluginApi"] == ">=2026.5.17"
    assert npm["openclaw"]["install"]["minHostVersion"] == ">=2026.5.17"


def test_bundled_server_and_skill_match_the_canonical_sources() -> None:
    assert (PLUGIN / "server" / "pyproject.toml").read_bytes() == (
        ROOT / "pyproject.toml"
    ).read_bytes()

    canonical_source = ROOT / "src" / "agentictools"
    bundled_source = PLUGIN / "server" / "src" / "agentictools"
    source_files = sorted(path.relative_to(canonical_source) for path in canonical_source.glob("*.py"))
    bundled_files = sorted(path.relative_to(bundled_source) for path in bundled_source.glob("*.py"))
    assert bundled_files == source_files
    for relative in source_files:
        assert (bundled_source / relative).read_bytes() == (canonical_source / relative).read_bytes()

    assert (PLUGIN / "skills" / "ai-visit-website" / "SKILL.md").read_bytes() == (
        ROOT / "skills" / "ai-visit-website" / "SKILL.md"
    ).read_bytes()


@pytest.mark.asyncio
async def test_packaged_launcher_exposes_the_four_mcp_tools(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["AI_VISIT_WEBSITE_DATA_DIR"] = str(tmp_path / "plugin-data")
    env["AI_VISIT_WEBSITE_VENV"] = str(ROOT / ".venv")
    env["AI_VISIT_WEBSITE_AUTO_SETUP"] = "0"
    parameters = StdioServerParameters(
        command=str(PLUGIN / "bin" / "ai-visit-website-mcp"),
        args=[],
        env=env,
        cwd=str(PLUGIN),
    )

    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listing = await session.list_tools()

    assert {tool.name for tool in listing.tools} == {
        "site_discover",
        "page_read",
        "page_save",
        "archive_search",
    }
