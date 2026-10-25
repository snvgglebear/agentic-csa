"""Tests for cross-vendor search ranking, page text extraction, and fetch limits."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from wpilib_mcp import server
from wpilib_mcp.plugins.base import PageContent
from wpilib_mcp.tool_router import tidy_titles, vendors_named_in
from wpilib_mcp.utils.html import HtmlCleaner


@pytest.fixture(scope="module")
async def router():
    await server.initialize_server()
    return server._router


@pytest.mark.parametrize("query, vendor", [
    ("PhotonVision pose estimation", "PhotonVision"),
    ("TalonFX current limit", "CTRE Phoenix"),
    ("SparkMax configure", "REV Robotics"),
    ("slew rate limiter", "WPILib"),
    ("register named commands", "PathPlanner"),
    ("MegaTag2 robot orientation", "Limelight"),
])
async def test_best_page_ranks_first(router, query, vendor):
    results = await router.search(query=query, vendors=["all"], language="Java", max_results=3)
    assert results and results[0].vendor == vendor


async def test_weak_vendors_are_not_padded_in(router):
    # The old merge gave every vendor's best page a perfect score, so a
    # search always returned one page per vendor however poor the match.
    results = await router.search(
        query="MegaTag2 robot orientation", vendors=["all"], language="Java", max_results=5
    )
    assert {r.vendor for r in results} == {"Limelight"}


@pytest.mark.parametrize("version", [None, "2027", "latest", "2026"])
async def test_wpilib_searches_2027_docs(router, version):
    results = await router.search(
        query="debouncer", vendors=["wpilib"], version=version, max_results=3
    )
    assert results and all("/en/latest/" in r.url for r in results)


@pytest.mark.parametrize("query, weak", [
    ("slew rate limiter", False),
    ("command based subsystem default command", False),
    ("sensorless homing stall current", True),
    ("how to bake a cake", True),
])
async def test_weak_matches_are_flagged(router, query, weak):
    results = await router.search(query=query, vendors=["all"], language="Java", max_results=3)
    assert results and results[0].weak_match is weak


async def test_photonvision_searches_2027_docs(router):
    results = await router.search(query="PhotonPoseEstimator", vendors=["photonvision"], max_results=10)
    assert results and all("/en/latest/" in r.url for r in results)
    assert len({r.url for r in results}) == len(results)


def test_vendor_names_and_products():
    assert vendors_named_in("Spark Max closed loop") == {"rev"}
    assert vendors_named_in("Talon FX config") == {"ctre"}
    assert vendors_named_in("reverse the motor") == set()


class TestHtmlCleaner:
    def test_read_the_docs_page_keeps_its_content(self):
        # The theme's body and wrapper classes contain "nav"; they used to
        # delete the whole page.
        html = """<html><head><title>Slew Rate Limiter</title></head>
        <body class="wy-body-for-nav"><div class="wy-nav-content">
        <div role="main" class="document"><section>
        <h1>Slew Rate Limiter<a class="headerlink" href="#x">¶</a></h1>
        <p>A common use for filters is to soften the behavior of control inputs,
        for example the joystick inputs from your drivers.</p>
        <div class="page-nav">Previous / Next</div>
        </section></div></div></body></html>"""
        text = HtmlCleaner().extract_content(html)
        assert "soften the behavior of control inputs" in text
        assert "¶" not in text
        assert "Previous / Next" not in text

    def test_short_patterns_match_whole_class_parts(self):
        # "ad" (advertisement) used to match inside "shadow"
        html = """<html><body><main><div class="shadow-box">
        <p>Shadow boxes hold real content and are long enough to count as the main text of this page.</p>
        </div></main></body></html>"""
        assert "real content" in HtmlCleaner().extract_content(html)

    def test_links_keep_their_spaces(self):
        html = """<html><body><main><p>AdvantageKit is a logging framework developed by
        <a href="#">Team 6328</a>. It records everything the robot does during a match, and more text here.</p>
        </main></body></html>"""
        assert "developed by Team 6328" in HtmlCleaner().extract_content(html)


async def test_fetch_is_cut_off_at_max_chars(router, monkeypatch):
    async def fake_fetch(url):
        return PageContent(url=url, title="Long", content="line of text\n" * 2000, vendor="WPILib")

    monkeypatch.setattr(router, "fetch_page", fake_fetch)
    text = (await server.handle_fetch({"url": "https://docs.wpilib.org/x", "max_chars": 1000}))[0].text
    assert "[Cut off at" in text
    assert len(text) < 1500


class TestTidyTitles:
    def page(self, title, url, section="General", version=None):
        return SimpleNamespace(title=title, url=url, section=section, version=version)

    def test_strips_anchors_and_site_names(self):
        pages = [
            self.page("Annotation Logging {#annotation-logging}", "https://a.org/x/one"),
            self.page("Code Examples - PhotonVision Docs", "https://b.org/en/v1/docs/examples/index.html"),
        ]
        tidy_titles(pages)
        assert [p.title for p in pages] == ["Annotation Logging", "Code Examples"]

    def test_tells_apart_shared_titles(self):
        pages = [
            self.page("Getting Started", "https://pathplanner.dev/gui-getting-started.html", "PathPlanner GUI"),
            self.page("Getting Started", "https://pathplanner.dev/pplib-getting-started.html", "PathPlannerLib"),
            self.page("Quick Links", "https://docs.revrobotics.com/ion-control/home/links"),
            self.page("Quick Links", "https://docs.revrobotics.com/brushless/home/links"),
        ]
        tidy_titles(pages)
        assert [p.title for p in pages] == [
            "Getting Started (PathPlanner GUI)",
            "Getting Started (PathPlannerLib)",
            "Quick Links (ION Control)",
            "Quick Links (Brushless)",
        ]

    def test_same_page_in_two_seasons_is_not_a_duplicate(self):
        pages = [
            self.page("Debouncer", "https://docs.wpilib.org/en/stable/x/debouncer.html", version="stable"),
            self.page("Debouncer", "https://docs.wpilib.org/en/latest/x/debouncer.html", version="latest"),
        ]
        tidy_titles(pages)
        assert [p.title for p in pages] == ["Debouncer", "Debouncer"]


async def test_search_quality_holds(router):
    """The student-question set in scripts/search_eval.py must not regress."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from search_eval import CASES, run

    top1, top3, weak_ok, answerable = await run(verbose=False, router=router)
    assert top3 == answerable, "every answerable question should have its page in the top 3"
    assert top1 >= answerable - 3
    assert weak_ok == len(CASES)


def test_stemming_matches_word_forms():
    from wpilib_mcp.utils.search import BM25SearchIndex
    index = BM25SearchIndex()
    assert index.tokenize("logs homing limits") == index.tokenize("log home limit")
    # FRC nouns keep their meaning instead of matching common words
    assert index.tokenize("followers") != index.tokenize("following")
    assert index.tokenize("controllers") != index.tokenize("control")


async def test_search_accepts_numbers_as_strings(router):
    text = (await server.handle_search({"query": "pid", "max_results": "3", "auto_detect": False}))[0].text
    assert text.startswith("Found 3 result(s)")


async def test_search_names_unknown_vendors(router):
    text = (await server.handle_search({"query": "pid", "vendors": ["nope"], "auto_detect": False}))[0].text
    assert text.startswith("Error: unknown vendor(s) nope") and "wpilib" in text


async def test_search_accepts_one_vendor_as_a_string(router):
    results_text = (await server.handle_search({"query": "pid", "vendors": "ctre", "auto_detect": False}))[0].text
    vendors = {line.split("**Vendor:** ")[1].split(" |")[0] for line in results_text.splitlines() if line.startswith("**Vendor")}
    assert vendors == {"CTRE Phoenix"}
