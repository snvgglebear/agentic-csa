#!/usr/bin/env python3
"""
Build the AdvantageScope documentation index.

Usage:
    python -m wpilib_mcp.plugins.advantagescope.build_index
"""

import argparse
import asyncio
import logging
from pathlib import Path

from wpilib_mcp.utils.static_docs import build_index_from_urls, default_client, sitemap_urls


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

SITEMAP_URL = "https://docs.advantagescope.org/sitemap.xml"
SKIP = ("/category/", "/search", "/legal")


async def list_urls(client) -> list[str]:
    """Docs pages from the Docusaurus sitemap, without index and legal pages."""
    return [
        u for u in await sitemap_urls(client, SITEMAP_URL)
        if u.rstrip("/") != "https://docs.advantagescope.org" and not any(s in u for s in SKIP)
    ]


def section_for(url: str) -> str:
    part = url.split("docs.advantagescope.org/", 1)[-1].split("/", 1)[0]
    return {
        "overview": "Overview",
        "tab-reference": "Tab Reference",
        "more-features": "More Features",
        "whats-new": "What's New",
    }.get(part, "General")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Build AdvantageScope documentation index")
    parser.add_argument("--output", type=Path, help="Output file (default: data/index.json)")
    args = parser.parse_args()
    output = args.output or Path(__file__).parent / "data" / "index.json"
    async with default_client("advantagescope") as client:
        count = await build_index_from_urls("advantagescope", await list_urls(client), section_for, output, client)
    print(f"\n✓ AdvantageScope index saved to {output}\n  Pages indexed: {count}")


if __name__ == "__main__":
    asyncio.run(main())
