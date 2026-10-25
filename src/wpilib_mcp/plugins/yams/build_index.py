#!/usr/bin/env python3
"""
Build the YAMS documentation index.

The docs moved from yagsl.gitbook.io/yams to yams.yassrobotics.com (GitBook).
Pages come from its llms.txt, using each page's Markdown copy. The generated
Java and C++ API reference pages are skipped; the guides link to them.

Usage:
    python -m wpilib_mcp.plugins.yams.build_index
"""

import argparse
import asyncio
import logging
from pathlib import Path

from wpilib_mcp.utils.static_docs import build_index_from_llms_txt, default_client


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BASE_URL = "https://yams.yassrobotics.com"
LLMS_URL = f"{BASE_URL}/llms.txt"
SKIP = ("/api-reference/java-reference", "/api-reference/c++-reference")


def keep(url: str) -> bool:
    return url.startswith(BASE_URL) and not any(s in url for s in SKIP)


def section_for(url: str) -> str:
    path = url.removeprefix(BASE_URL + "/")
    if path.startswith("documentation/tutorials"):
        return "Tutorials"
    if path.startswith("documentation/how-to"):
        return "How To"
    if path.startswith("documentation/understanding"):
        return "Understanding YAMS"
    if path.startswith("api-reference/guides"):
        return "API Guides"
    if path.startswith("documentation"):
        return "Documentation"
    return "General"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Build YAMS documentation index")
    parser.add_argument("--output", type=Path, help="Output file (default: data/index.json)")
    args = parser.parse_args()
    output = args.output or Path(__file__).parent / "data" / "index.json"
    async with default_client("yams") as client:
        count = await build_index_from_llms_txt(
            "yams", LLMS_URL, keep, section_for, output, client
        )
    print(f"\n✓ YAMS index saved to {output}\n  Pages indexed: {count}")


if __name__ == "__main__":
    asyncio.run(main())
