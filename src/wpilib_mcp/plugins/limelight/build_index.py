#!/usr/bin/env python3
"""
Build the Limelight documentation index.

Usage:
    python -m wpilib_mcp.plugins.limelight.build_index
"""

import argparse
import asyncio
import logging
from pathlib import Path

from wpilib_mcp.utils.static_docs import build_index_from_urls, default_client, sitemap_urls


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

SITEMAP_URL = "https://docs.limelightvision.io/sitemap.xml"
SKIP = ("ftc", "software-change-log", "ask-a-question")


async def list_urls(client) -> list[str]:
    """FRC-relevant docs pages from the Docusaurus sitemap."""
    return [
        u for u in await sitemap_urls(client, SITEMAP_URL)
        if "/docs/docs-limelight/" in u and not any(s in u for s in SKIP)
    ]


def section_for(url: str) -> str:
    part = url.split("/docs/docs-limelight/", 1)[-1].split("/", 1)[0]
    return {
        "getting-started": "Getting Started",
        "apis": "Programming APIs",
        "pipeline-apriltag": "AprilTags and Localization",
        "pipeline-neural": "Neural Pipelines",
        "pipeline-retro": "Retroreflective Pipelines",
        "pipeline-python": "Python Pipelines",
        "pipeline-barcode": "Barcode Pipelines",
        "tutorials": "Tutorials",
    }.get(part, "General")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Build Limelight documentation index")
    parser.add_argument("--output", type=Path, help="Output file (default: data/index.json)")
    args = parser.parse_args()
    output = args.output or Path(__file__).parent / "data" / "index.json"
    async with default_client("limelight") as client:
        count = await build_index_from_urls("limelight", await list_urls(client), section_for, output, client)
    print(f"\n✓ Limelight index saved to {output}\n  Pages indexed: {count}")


if __name__ == "__main__":
    asyncio.run(main())
