#!/usr/bin/env python3
"""
Build documentation index for PhotonVision.

Lists every page from the site's Sphinx objects.inv, then fetches each
page's _sources/*.md.txt source for clean MyST Markdown content, falling
back to HTML extraction if the source file is unavailable.

--version latest (the default) indexes the development docs, which cover the
2027 season; --version stable indexes the newest full release instead.

Usage:
    python -m wpilib_mcp.plugins.photonvision.build_index

    # Or from the plugin directory:
    python build_index.py
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

# Handle both module and direct execution
try:
    from wpilib_mcp.utils.indexer import PageData
    from wpilib_mcp.utils.markdown import extract_md_title, detect_md_language
    from wpilib_mcp.utils.sphinx_inventory import sphinx_doc_urls
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    from wpilib_mcp.utils.indexer import PageData
    from wpilib_mcp.utils.markdown import extract_md_title, detect_md_language
    from wpilib_mcp.utils.sphinx_inventory import sphinx_doc_urls


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BASE_URL = "https://docs.photonvision.org"
RATE_LIMIT = 0.2
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
RELEASE = re.compile(r"/en/(v(\d{4})\.(\d+)\.(\d+))/$")


async def resolve_docs_path(client: httpx.AsyncClient, version: str) -> str:
    """
    The docs folder for a season: "latest" stays "latest" (next season's
    development docs); "stable" becomes the newest full release, such as
    "vYYYY.N.N". PhotonVision publishes no /en/stable/.
    """
    if version != "stable":
        return version
    resp = await client.get(SITEMAP_URL)
    resp.raise_for_status()
    releases = []
    for loc in re.findall(r"<loc>([^<]+)</loc>", resp.text):
        match = RELEASE.search(loc.strip())
        if match:
            releases.append((tuple(int(x) for x in match.groups()[1:]), match.group(1)))
    if not releases:
        raise RuntimeError("No PhotonVision releases found in the sitemap")
    return max(releases)[1]


def to_sources_url(url: str) -> str:
    """
    Convert a PhotonVision HTML page URL to its Sphinx _sources .md.txt URL.

    Example:
      .../en/latest/docs/programming/photonlib/index.html
      -> .../en/latest/_sources/docs/programming/photonlib/index.md.txt
    """
    parsed = urlparse(url)
    match = re.search(r"/en/[^/]+/", parsed.path)
    if not match:
        return ""
    marker = match.group(0)
    prefix, rest = parsed.path.split(marker, 1)
    rest = rest.rstrip("/")
    if rest.endswith(".html"):
        rest = rest[:-5]
    elif not rest:
        rest = "index"
    return parsed._replace(path=f"{prefix}{marker}_sources/{rest}.md.txt").geturl()


def should_index(url: str) -> bool:
    """Skip pages students don't need: the 404 page and developer docs."""
    exclude = [
        r"/404\.html$", r"/contributing/", r"/genindex", r"/search\.html",
        r"/en/[^/]+/index\.html$",  # the home page is only a table of contents
    ]
    return not any(re.search(p, url) for p in exclude)


def extract_section(url: str) -> str:
    """Determine documentation section from URL path."""
    u = url.lower()
    if "/quick-start/" in u or "/about" in u:
        return "Getting Started"
    elif "/hardware/" in u:
        return "Hardware Selection"
    elif "/installation/" in u:
        return "Installation"
    elif "/camera" in u and "config" in u:
        return "Camera Configuration"
    elif "/pipelines/" in u:
        return "Pipelines"
    elif "/apriltag" in u:
        return "AprilTag Detection"
    elif "/reflective" in u or "/shape" in u:
        return "Reflective & Shape Detection"
    elif "/objectdetection" in u:
        return "Object Detection"
    elif "/calibrat" in u:
        return "Camera Calibration"
    elif "/photonlib/" in u:
        return "PhotonLib"
    elif "/simulation/" in u:
        return "Simulation"
    elif "/integration/" in u:
        return "Robot Integration"
    elif "/examples/" in u:
        return "Code Examples"
    elif "/troubleshooting/" in u:
        return "Troubleshooting"
    elif "/contributing/" in u:
        return "Contributing"
    elif "/additional-resources/" in u or "/best-practices" in u:
        return "Additional Resources"
    return "General"


def create_preview(content: str, max_length: int = 300) -> str:
    if len(content) <= max_length:
        return content
    preview = content[:max_length]
    last_period = preview.rfind(". ")
    if last_period > max_length * 0.5:
        return preview[:last_period + 1]
    last_space = preview.rfind(" ")
    if last_space > max_length * 0.7:
        return preview[:last_space] + "..."
    return preview + "..."


def extract_html_content(soup: BeautifulSoup) -> str:
    """Fallback: extract plain text from HTML."""
    for selector in [
        "nav", "header", "footer", ".sidebar", ".sidebar-drawer",
        ".toc-drawer", ".mobile-header", "script", "style",
        ".edit-page", ".page-nav", ".prev-next-area", ".footer-article",
        ".bd-sidebar", ".bd-toc"
    ]:
        for elem in soup.select(selector):
            elem.decompose()

    main = (
        soup.find("article", class_="bd-article") or
        soup.find("main", id="main-content") or
        soup.find("div", class_="bd-content") or
        soup.find("main") or
        soup.find("article") or
        soup.body
    )
    if main is None:
        return ""
    text = main.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


async def build(version: str = "latest") -> dict:
    """List pages from objects.inv, then fetch each page's _sources/*.md.txt."""
    pages: list[PageData] = []

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "WPILib-MCP-photonvision-Indexer/1.0"}
    ) as client:
        docs_path = await resolve_docs_path(client, version)
        root = f"{BASE_URL}/en/{docs_path}/"
        logger.info(f"Indexing PhotonVision {version} from {root}")
        discovered = [u for u in await sphinx_doc_urls(client, root) if should_index(u)]
        logger.info(f"Found {len(discovered)} pages")

        # --- Phase 2: fetch _sources/*.md.txt for each page ---
        for html_url in discovered:
            await asyncio.sleep(RATE_LIMIT)
            sources_url = to_sources_url(html_url)

            markdown = None
            if sources_url:
                try:
                    resp = await client.get(sources_url)
                    resp.raise_for_status()
                    markdown = resp.text
                    logger.debug(f"Got markdown source: {sources_url}")
                except Exception:
                    pass

            if markdown and len(markdown.strip()) >= 100:
                title = extract_md_title(markdown) or html_url.split("/")[-1]
                language = detect_md_language(markdown)
                content = markdown
            else:
                # Fall back to HTML extraction
                try:
                    resp = await client.get(html_url)
                    resp.raise_for_status()
                    soup = BeautifulSoup(resp.text, "lxml")
                    content = extract_html_content(soup)
                    h1 = soup.find("h1")
                    title = (
                        (h1.get_text(strip=True).rstrip("#¶") if h1 else None) or
                        (re.sub(r"\s+-\s+PhotonVision Docs$", "", soup.title.string.strip())
                         if soup.title and soup.title.string else None) or
                        html_url.split("/")[-1]
                    )
                    language = "All"
                except Exception as e:
                    logger.warning(f"HTML fallback failed {html_url}: {e}")
                    continue

            if len(content) < 100:
                continue

            section = extract_section(html_url)
            pages.append(PageData(
                url=html_url,
                title=title,
                section=section,
                language=language,
                content=content,
                content_preview=create_preview(content),
            ))
            logger.info(f"Indexed: {title}")

    logger.info(f"Indexed {len(pages)} pages for photonvision")
    return {
        "vendor": "photonvision",
        "version": version,
        "docs_path": docs_path,
        "built_at": datetime.now().isoformat(),
        "pages": [asdict(p) for p in pages],
    }


async def main():
    parser = argparse.ArgumentParser(
        description="Build PhotonVision documentation index"
    )
    parser.add_argument("--version", default="latest", choices=["latest", "stable"],
                        help="latest = development docs (2027, the default), stable = newest full release")
    parser.add_argument("--output", type=Path,
                        help="Output file path (default: data/index_<version>.json)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    data_dir = Path(__file__).parent / "data"
    output_path = args.output or (data_dir / f"index_{args.version}.json")

    index = await build(args.version)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    print(f"\n✓ PhotonVision index saved to {output_path}")
    print(f"  Pages indexed: {len(index['pages'])}")


if __name__ == "__main__":
    asyncio.run(main())
