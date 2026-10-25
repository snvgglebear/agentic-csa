#!/usr/bin/env python3
"""
Build the PathPlanner documentation index.

Usage:
    python -m wpilib_mcp.plugins.pathplanner.build_index
"""

import argparse
import asyncio
import logging
from pathlib import Path
from urllib.parse import urljoin

from wpilib_mcp.utils.static_docs import build_index_from_urls, default_client


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

TOC_URL = "https://pathplanner.dev/HelpTOC.json"


async def list_urls(client) -> list[str]:
    """Guide pages from the Writerside table of contents (skips the API reference)."""
    resp = await client.get(TOC_URL)
    resp.raise_for_status()
    pages = resp.json()["entities"]["pages"].values()
    return [
        urljoin("https://pathplanner.dev/", p["url"])
        for p in pages
        if p.get("url", "").endswith(".html")
    ]


def section_for(url: str) -> str:
    name = url.rsplit("/", 1)[-1]
    if name.startswith("pplib") or name == "pathplannerlib.html":
        return "PathPlannerLib"
    if name.startswith("gui") or name == "pathplanner-gui.html":
        return "PathPlanner GUI"
    return "General"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Build PathPlanner documentation index")
    parser.add_argument("--output", type=Path, help="Output file (default: data/index.json)")
    args = parser.parse_args()
    output = args.output or Path(__file__).parent / "data" / "index.json"
    async with default_client("pathplanner") as client:
        count = await build_index_from_urls("pathplanner", await list_urls(client), section_for, output, client)
    print(f"\n✓ PathPlanner index saved to {output}\n  Pages indexed: {count}")


if __name__ == "__main__":
    asyncio.run(main())
