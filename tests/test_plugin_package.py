from __future__ import annotations

import json
import os
from pathlib import Path
import types

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "ai-visit-website"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_packaged_launcher() -> types.ModuleType:
    module = types.ModuleType("ai_visit_website_packaged_launcher")
    module.__file__ = str(PLUGIN / "bin" / "ai-visit-website-mcp")
    source = Path(module.__file__).read_text(encoding="utf-8")
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def test_codex_plugin_manifest_and_marketplace_are_complete() -> None:
    manifest = read_json(PLUGIN / ".codex-plugin" / "plugin.json")
    mcp = read_json(PLUGIN / ".mcp.json")
    marketplace = read_json(ROOT / ".agents" / "plugins" / "marketplace.json")

    assert manifest["name"] == "ai-visit-website"
    assert manifest["version"].startswith("1.2.1+codex.")
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
    assert openclaw["version"] == portable["version"] == npm["version"] == "1.2.1"
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
    assert (
        PLUGIN / "skills" / "ai-visit-website" / "agents" / "openai.yaml"
    ).read_bytes() == (
        ROOT / "skills" / "ai-visit-website" / "agents" / "openai.yaml"
    ).read_bytes()


def test_packaged_launcher_upgrades_a_stale_runtime(tmp_path: Path, monkeypatch) -> None:
    launcher = load_packaged_launcher()
    root = tmp_path / "plugin-data"
    venv = root / "venv"
    server = launcher.venv_executable(venv, "agentictools-mcp")
    server.parent.mkdir(parents=True)
    server.write_text("stale", encoding="utf-8")
    versions = iter(["1.0.1", "1.2.1"])
    bootstraps: list[tuple[Path, Path, bool]] = []

    monkeypatch.setenv("AI_VISIT_WEBSITE_AUTO_SETUP", "1")
    monkeypatch.setenv("AI_VISIT_WEBSITE_AUTO_SETUP_BROWSER", "0")
    monkeypatch.setattr(launcher, "installed_runtime_version", lambda _venv: next(versions))
    monkeypatch.setattr(
        launcher,
        "bootstrap",
        lambda actual_root, actual_venv, *, with_browser: bootstraps.append(
            (actual_root, actual_venv, with_browser)
        ),
    )
    monkeypatch.setattr(
        launcher.os,
        "execve",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("execve called")),
    )

    with pytest.raises(RuntimeError, match="execve called"):
        launcher.launch(root, venv)

    assert launcher.bundled_runtime_version() == "1.2.1"
    assert bootstraps == [(root, venv, False)]


def test_packaged_launcher_rejects_a_stale_runtime_when_auto_setup_is_disabled(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_packaged_launcher()
    root = tmp_path / "plugin-data"
    venv = root / "venv"
    server = launcher.venv_executable(venv, "agentictools-mcp")
    server.parent.mkdir(parents=True)
    server.write_text("stale", encoding="utf-8")

    monkeypatch.setenv("AI_VISIT_WEBSITE_AUTO_SETUP", "0")
    monkeypatch.setattr(launcher, "installed_runtime_version", lambda _venv: "1.0.1")

    with pytest.raises(SystemExit, match="runtime 1.0.1 does not match bundled version 1.2.1"):
        launcher.launch(root, venv)


def test_packaged_launcher_keeps_setup_output_off_mcp_stdout(tmp_path: Path, monkeypatch) -> None:
    launcher = load_packaged_launcher()
    calls: list[dict] = []

    monkeypatch.setattr(launcher.shutil, "which", lambda _name: "/usr/bin/python3.12")
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *_args, **kwargs: calls.append(kwargs),
    )

    launcher.bootstrap(tmp_path / "plugin-data", tmp_path / "venv", with_browser=True)

    assert len(calls) == 3
    assert all(call["stdout"] is launcher.sys.stderr for call in calls)


@pytest.mark.asyncio
async def test_packaged_launcher_exposes_public_archive_and_browser_tools(tmp_path: Path) -> None:
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
            initialized = await session.initialize()
            listing = await session.list_tools()

    assert initialized.server_info.version == "1.2.1"
    assert {tool.name for tool in listing.tools} == {
        "site_discover",
        "article_list",
        "page_read",
        "browser_status",
        "browser_page_read",
        "browser_cancel",
        "browser_batch_start",
        "browser_batch_status",
        "browser_batch_cancel",
        "page_save",
        "archive_search",
    }
