#!/usr/bin/env python3
"""
Build the YAGSL documentation index.

The docs moved from docs.yagsl.com to yagsl.yassrobotics.com (GitBook).
Pages come from its llms.txt, using each page's Markdown copy.

Usage:
    python -m wpilib_mcp.plugins.yagsl.build_index
"""

import argparse
import asyncio
import logging
from pathlib import Path

from wpilib_mcp.utils.static_docs import build_index_from_llms_txt, default_client


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BASE_URL = "https://yagsl.yassrobotics.com"
LLMS_URL = f"{BASE_URL}/llms.txt"


def keep(url: str) -> bool:
    return url.startswith(BASE_URL) and "/external-links" not in url


def section_for(url: str) -> str:
    part = url.removeprefix(BASE_URL + "/").split("/", 1)[0]
    return {
        "tutorial": "Tutorial",
        "how-to-guides": "How-To Guides",
        "reference": "Reference",
        "explanation": "Explanation",
        "resources": "Resources",
    }.get(part, "General")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Build YAGSL documentation index")
    parser.add_argument("--output", type=Path, help="Output file (default: data/index.json)")
    args = parser.parse_args()
    output = args.output or Path(__file__).parent / "data" / "index.json"
    async with default_client("yagsl") as client:
        count = await build_index_from_llms_txt(
            "yagsl", LLMS_URL, keep, section_for, output, client, language="Java"
        )
    print(f"\n✓ YAGSL index saved to {output}\n  Pages indexed: {count}")


if __name__ == "__main__":
    asyncio.run(main())
