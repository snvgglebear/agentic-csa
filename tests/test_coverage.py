"""Tests that every docs source ships, loads, and is found."""

import json
import zlib
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from wpilib_mcp.plugin_loader import PACKAGED_CONFIG, PluginLoader, get_default_config, load_config
from wpilib_mcp.plugins.rev.build_index import parse_llms_txt, should_crawl
from wpilib_mcp.plugins.wpilib.build_index import WPILibIndexBuilder
from wpilib_mcp.plugins.wpilib.plugin import Plugin as WPILibPlugin
from wpilib_mcp.utils.sphinx_inventory import sphinx_doc_urls


PLUGINS_DIR = Path(__file__).parent.parent / "src" / "wpilib_mcp" / "plugins"


def enabled_plugins() -> list[str]:
    config = get_default_config()
    return [name for name, conf in config["plugins"].items() if conf.get("enabled", True)]


class TestPackagedConfig:
    def test_config_ships_inside_package(self):
        # The wheel only packages src/wpilib_mcp, so the config must live there.
        assert PACKAGED_CONFIG.parent.name == "wpilib_mcp"
        assert PACKAGED_CONFIG.exists()

    def test_default_load_uses_packaged_config(self, monkeypatch):
        monkeypatch.delenv("FIRST_AGENTIC_CSA_CONFIG", raising=False)
        assert load_config() == json.loads(PACKAGED_CONFIG.read_text())

    def test_env_var_overrides_config(self, monkeypatch, tmp_path):
        custom = tmp_path / "config.json"
        custom.write_text(json.dumps({"plugins": {"ctre": {"enabled": True}}}))
        monkeypatch.setenv("FIRST_AGENTIC_CSA_CONFIG", str(custom))
        assert load_config() == {"plugins": {"ctre": {"enabled": True}}}

    def test_every_plugin_is_in_config(self):
        discovered = set(PluginLoader().discover_plugins())
        assert discovered <= set(get_default_config()["plugins"])

    @pytest.mark.parametrize("name", ["wpilib", "photonvision"])
    def test_loads_2027_season_only(self, name):
        config = get_default_config()
        assert config["plugins"][name]["versions"] == ["latest"]
        assert config["search"]["default_version"] == "latest"
        assert not (PLUGINS_DIR / name / "data" / "index_stable.json").exists()


@pytest.mark.parametrize("name", enabled_plugins())
def test_enabled_plugin_index_has_pages(name):
    data_dir = PLUGINS_DIR / name / "data"
    versions = get_default_config()["plugins"][name].get("versions")
    # Season plugins keep index_<version>.json; the rest keep index.json
    files = [data_dir / f"index_{v}.json" for v in versions] if versions else [data_dir / "index.json"]
    for f in files:
        pages = json.loads(f.read_text())["pages"]
        assert len(pages) >= 15, f"{f} has only {len(pages)} pages"


class TestRevLlmsTxt:
    def test_parses_absolute_and_relative_links(self):
        text = "\n".join([
            "- [Relative](/brushless/spark-max/overview.md)",
            "* [Star bullet](https://docs.revrobotics.com/revlib/spark/closed-loop.md)",
            "- [With note](https://docs.revrobotics.com/revlib/install.md): How to install",
            "- [Duplicate](/brushless/spark-max/overview.md)",
        ])
        assert parse_llms_txt(text) == [
            ("Relative", "https://docs.revrobotics.com/brushless/spark-max/overview.md"),
            ("Star bullet", "https://docs.revrobotics.com/revlib/spark/closed-loop.md"),
            ("With note", "https://docs.revrobotics.com/revlib/install.md"),
        ]

    def test_includes_revlib(self):
        assert should_crawl("https://docs.revrobotics.com/revlib/spark/closed-loop.md")
        assert not should_crawl("https://docs.revrobotics.com/duo-control/intro.md")


class TestWPILibVersions:
    def make_plugin(self, versions):
        plugin = WPILibPlugin()
        plugin._index_data = {v: {} for v in versions}
        return plugin

    def test_year_alias(self):
        plugin = self.make_plugin(["latest"])
        assert plugin._resolve_version("2027") == "latest"
        assert plugin._resolve_version("latest") == "latest"

    def test_missing_version_uses_first_loaded_season(self):
        # Searching every season would list the same page once per season.
        plugin = self.make_plugin(["latest", "stable"])
        assert plugin._resolve_version(None) == "latest"
        assert plugin._resolve_version("2026") == "latest"


def test_title_keeps_hyphenated_words():
    builder = WPILibIndexBuilder()
    soup = BeautifulSoup(
        "<title>Command-Based Programming — FIRST Robotics Competition documentation</title>",
        "lxml",
    )
    assert builder.extract_title(soup, "") == "Command-Based Programming"


async def test_sphinx_inventory_lists_pages():
    entries = (
        "docs/software/commandbased/index std:doc -1 docs/software/commandbased/index.html Command-Based\n"
        "docs/software/basic $ std:label -1 docs/software/basic.html#x Label\n"
        "docs/software/filters/debouncer std:doc -1 $.html Debouncer\n"
    )
    body = (
        b"# Sphinx inventory version 2\n# Project: X\n# Version: 2027\n"
        b"# The remainder of this file is compressed using zlib.\n"
        + zlib.compress(entries.encode())
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    async with httpx.AsyncClient(transport=transport) as client:
        urls = await sphinx_doc_urls(client, "https://docs.wpilib.org/en/stable/")
    assert urls == [
        "https://docs.wpilib.org/en/stable/docs/software/commandbased/index.html",
        "https://docs.wpilib.org/en/stable/docs/software/filters/debouncer.html",
    ]


class TestProjectDetection:
    def make_project(self, tmp_path, vendordeps, java=""):
        (tmp_path / "vendordeps").mkdir()
        for i, dep in enumerate(vendordeps):
            (tmp_path / "vendordeps" / f"dep{i}.json").write_text(json.dumps(dep))
        src = tmp_path / "src" / "main" / "java" / "frc" / "robot"
        src.mkdir(parents=True)
        (src / "Robot.java").write_text("import edu.wpi.first.wpilibj.TimedRobot;\n" + java)
        (tmp_path / "build.gradle").write_text('plugins { id "edu.wpi.first.GradleRIO" }\n')
        return tmp_path

    def test_detects_new_vendors(self, tmp_path):
        from wpilib_mcp.utils.context import ProjectContextDetector
        project = self.make_project(tmp_path, [
            {"name": "Phoenix6", "mavenUrls": ["https://maven.ctr-electronics.com/release/"]},
            {"name": "AdvantageKit", "javaDependencies": [{"groupId": "org.littletonrobotics.akit", "artifactId": "akit-java"}]},
            {"name": "YAGSL (Commands v2)", "mavenUrls": ["https://cdn.yassrobotics.com/"]},
            {"name": "Yet Another Mechanism System (Commands v2)", "mavenUrls": ["https://cdn.yassrobotics.com/"]},
        ], java="import frc.robot.LimelightHelpers;\n")
        vendors = ProjectContextDetector(project).detect().vendors
        assert {"ctre", "advantagekit", "yagsl", "yams", "limelight"} <= set(vendors)
        assert "rev" not in vendors

    def test_search_keeps_tools_and_skips_unused_libraries(self):
        from wpilib_mcp.utils.context import vendors_for_project
        available = ["wpilib", "rev", "ctre", "photonvision", "limelight", "advantagescope", "pathplanner"]
        kept = vendors_for_project(["ctre", "photonvision"], available)
        # Libraries the project lacks are skipped; tools with no trace in a project stay
        assert kept == ["wpilib", "ctre", "photonvision", "limelight", "advantagescope"]


class TestFetchCleanup:
    def test_markdown_urls(self):
        from wpilib_mcp.utils.static_docs import markdown_url
        assert markdown_url("https://yams.yassrobotics.com/a/b") == "https://yams.yassrobotics.com/a/b.md"
        assert markdown_url("https://yagsl.yassrobotics.com/") == "https://yagsl.yassrobotics.com/readme.md"

    def test_page_text_drops_notice_and_anchors(self):
        from wpilib_mcp.utils.static_docs import clean_page_text
        text = ("> For the complete documentation index, see [llms.txt](https://x/llms.txt).\n"
                "# Logging {#logging}\nBody text.")
        assert clean_page_text(text) == "# Logging\nBody text."


def test_no_detection_outside_robot_projects(tmp_path):
    from wpilib_mcp.utils.context import ProjectContextDetector
    # Python files that mention a vendor, but no robot-project markers
    (tmp_path / "tool.py").write_text("talonfx = 'TalonFX'\nimport phoenix6\n")
    context = ProjectContextDetector(tmp_path).detect()
    assert not context.has_context


def test_detection_skips_tool_folders(tmp_path):
    from wpilib_mcp.utils.context import iter_source_files
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Robot.java").write_text("")
    (tmp_path / "build" / "tmp").mkdir(parents=True)
    (tmp_path / "build" / "tmp" / "Generated.java").write_text("")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("")
    assert [p.name for p in iter_source_files(tmp_path, "*.java")] == ["Robot.java"]
    assert list(iter_source_files(tmp_path, "*.py")) == []
