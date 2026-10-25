"""
Shared pieces for docs sites whose pages come from a fixed list.

A vendor using this needs only:
- plugin.py: a StaticDocsPlugin subclass that sets the class attributes
- build_index.py: code that lists the site's page URLs, then calls
  build_index_from_urls()
"""

import asyncio
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import httpx
from bs4 import BeautifulSoup

from ..plugins.base import DocSection, PageContent, PluginBase, PluginConfig, SearchResult
from .fetch import HttpFetcher
from .html import HtmlCleaner
from .indexer import PageData
from .search import BM25SearchIndex


logger = logging.getLogger(__name__)


@dataclass
class IndexPage:
    url: str
    title: str
    section: str
    language: str
    content: str
    content_preview: str


class StaticDocsPlugin(PluginBase):
    """Plugin for one docs site with a single prebuilt index.json."""

    NAME = ""
    DISPLAY_NAME = ""
    DESCRIPTION = ""
    BASE_URLS: list[str] = []
    LANGUAGES = ["Java", "C++", "Python"]

    def __init__(self):
        super().__init__()
        self._pages: list[IndexPage] = []
        self._search_index: BM25SearchIndex[IndexPage] = BM25SearchIndex()
        self._fetcher: Optional[HttpFetcher] = None
        self._html_cleaner = HtmlCleaner()

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def supported_versions(self) -> list[str]:
        return ["latest"]

    @property
    def supported_languages(self) -> list[str]:
        return list(self.LANGUAGES)

    @property
    def base_urls(self) -> list[str]:
        return list(self.BASE_URLS)

    async def initialize(self, config: PluginConfig) -> None:
        self._config = config
        self._fetcher = HttpFetcher(cache_ttl_seconds=3600)
        self._load_index()
        if self._pages:
            self._search_index.build(
                items=self._pages,
                text_extractor=lambda p: f"{p.title} {p.section} {p.content}",
            )
        self._initialized = True
        logger.info(f"{self.DISPLAY_NAME} plugin initialized with {len(self._pages)} pages")

    def _load_index(self) -> None:
        index_file = self.data_dir / "index.json"
        if not index_file.exists():
            logger.warning(f"Index file not found: {index_file}")
            return
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for p in data.get("pages", []):
                self._pages.append(IndexPage(
                    url=p["url"],
                    title=p["title"],
                    section=p.get("section", "General"),
                    language=p.get("language", "All"),
                    content=p.get("content", ""),
                    content_preview=p.get("content_preview", ""),
                ))
        except Exception as e:
            logger.error(f"Error loading index {index_file}: {e}")

    async def search(
        self,
        query: str,
        version: Optional[str] = None,
        language: Optional[str] = None,
        max_results: int = 10,
    ) -> list[SearchResult]:
        if not self._search_index.is_built:
            return []

        def filter_fn(page: IndexPage) -> bool:
            return not language or page.language in (language, "All")

        return [
            SearchResult(
                url=sr.item.url,
                title=sr.item.title,
                section=sr.item.section,
                vendor=self.DISPLAY_NAME,
                language=sr.item.language,
                version="latest",
                content_preview=sr.item.content_preview or sr.item.content[:300],
                score=sr.score,
            )
            for sr in self._search_index.search_with_filter(
                query=query, filter_fn=filter_fn, max_results=max_results
            )
        ]

    async def fetch_page(self, url: str) -> Optional[PageContent]:
        if self._fetcher is None:
            return None
        page_info = self._find_page_by_url(url)
        try:
            html = await self._fetcher.fetch(url)
            soup = BeautifulSoup(html, "lxml")
            content = extract_article_text(soup) or self._html_cleaner.extract_content(html, url)
            return PageContent(
                url=url,
                title=extract_page_title(soup) or self.DISPLAY_NAME,
                content=content,
                vendor=self.DISPLAY_NAME,
                language=page_info.language if page_info else None,
                section=page_info.section if page_info else None,
                last_fetched=datetime.now().isoformat(),
            )
        except Exception as e:
            logger.error(f"Error fetching page {url}: {e}")
            return None

    def _find_page_by_url(self, url: str) -> Optional[IndexPage]:
        target = url.lower().rstrip("/")
        for page in self._pages:
            if page.url.lower().rstrip("/") == target:
                return page
        return None

    async def list_sections(
        self, version: Optional[str] = None, language: Optional[str] = None
    ) -> list[DocSection]:
        sections: dict[str, DocSection] = {}
        for page in self._pages:
            if page.section not in sections:
                sections[page.section] = DocSection(name=page.section, vendor=self.name, page_count=0)
            sections[page.section].page_count += 1
        return list(sections.values())

    async def shutdown(self) -> None:
        if self._fetcher:
            await self._fetcher.close()
            self._fetcher = None
        self._pages.clear()
        await super().shutdown()


# --- Index building ---

BOILERPLATE = [
    "script", "style", "nav", "header", "footer", "aside", "button",
    ".theme-doc-toc-mobile", ".theme-doc-breadcrumbs", ".pagination-nav",
    ".theme-doc-footer", ".hash-link", ".article__bottom", ".navigation-links",
]


def extract_article_text(soup: BeautifulSoup) -> str:
    """Main text of a docs page, without navigation and page chrome."""
    main = soup.find("article") or soup.find("main")
    if main is None:
        return ""
    for selector in BOILERPLATE:
        for el in main.select(selector):
            el.decompose()
    return re.sub(r"\s+", " ", main.get_text(separator=" ", strip=True)).strip()


def extract_page_title(soup: BeautifulSoup) -> Optional[str]:
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    if soup.title and soup.title.string:
        return re.sub(r"\s+[|—\-·]\s+.*$", "", soup.title.string).strip()
    return None


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


async def sitemap_urls(client: httpx.AsyncClient, sitemap_url: str) -> list[str]:
    """Page URLs listed in a sitemap.xml."""
    resp = await client.get(sitemap_url)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    return [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]


async def build_index_from_urls(
    vendor: str,
    urls: list[str],
    section_for: Callable[[str], str],
    output_path: Path,
    client: httpx.AsyncClient,
    language: str = "All",
    rate_limit: float = 0.2,
) -> int:
    """Fetch each URL, keep its main text, and write index.json. Returns page count."""
    pages: list[PageData] = []
    for url in dict.fromkeys(urls):  # drop duplicates, keep order
        await asyncio.sleep(rate_limit)
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Skipping {url}: {e}")
            continue
        soup = BeautifulSoup(resp.text, "lxml")
        title = extract_page_title(soup)
        content = extract_article_text(soup)
        if not title or len(content) < 100:
            continue
        pages.append(PageData(
            url=url,
            title=title,
            section=section_for(url),
            language=language,
            content=content,
            content_preview=create_preview(content),
        ))
        logger.info(f"Indexed: {title}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "vendor": vendor,
            "version": "latest",
            "built_at": datetime.now().isoformat(),
            "pages": [asdict(p) for p in pages],
        }, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved {len(pages)} {vendor} pages to {output_path}")
    return len(pages)


def default_client(vendor: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": f"WPILib-MCP-{vendor}-Indexer/1.0"},
    )


# --- llms.txt sites (GitBook and similar) ---

LLMS_LINK = re.compile(r"\s*[-*]\s*\[([^\]]+)\]\((https?://[^)\s]+\.md)\)")
LLMS_NOTICE = re.compile(r"^>\s*For the complete documentation index.*$", re.M)


def parse_llms_txt(text: str) -> list[tuple[str, str]]:
    """(title, markdown URL) for each page linked from an llms.txt, without duplicates."""
    seen = set()
    pages = []
    for line in text.splitlines():
        match = LLMS_LINK.match(line)
        if match and match.group(2) not in seen:
            seen.add(match.group(2))
            pages.append((match.group(1), match.group(2)))
    return pages


def markdown_url(url: str) -> str:
    """GitBook's Markdown copy of a page: ".../page" -> ".../page.md", site root -> "/readme.md"."""
    if url.endswith(".md"):
        return url
    parts = url.split("/", 3)
    if len(parts) < 4 or not parts[3].strip("/"):
        return url.rstrip("/") + "/readme.md"
    return url.rstrip("/") + ".md"


def clean_page_text(text: str) -> str:
    """Strip markup that isn't content from fetched page text: the llms.txt notice and heading anchors."""
    text = LLMS_NOTICE.sub("", text)
    text = re.sub(r"^\s*For the complete documentation index, see llms\.txt\b[^\n]*\n?", "", text, flags=re.M)
    text = re.sub(r"[ \t]*\{#[\w.-]+\}", "", text)
    return text.strip()


def clean_llms_markdown(markdown: str) -> str:
    """Drop the "see llms.txt" notice GitBook puts at the top of each page."""
    return LLMS_NOTICE.sub("", markdown).strip()


async def build_index_from_llms_txt(
    vendor: str,
    llms_url: str,
    keep: Callable[[str], bool],
    section_for: Callable[[str], str],
    output_path: Path,
    client: httpx.AsyncClient,
    language: str = "All",
    rate_limit: float = 0.2,
) -> int:
    """Index every page an llms.txt links to, using its Markdown copy. Returns page count."""
    resp = await client.get(llms_url)
    resp.raise_for_status()
    pages: list[PageData] = []
    for llms_title, md_url in parse_llms_txt(resp.text):
        page_url = md_url.removesuffix(".md")
        if page_url.endswith("/readme"):
            page_url = page_url.removesuffix("readme")
        if not keep(page_url):
            continue
        await asyncio.sleep(rate_limit)
        try:
            md = await client.get(md_url)
            md.raise_for_status()
        except Exception as e:
            logger.warning(f"Skipping {md_url}: {e}")
            continue
        content = clean_llms_markdown(md.text)
        if len(content) < 100:
            continue
        heading = re.search(r"^#\s+(.+)$", content, re.M)
        title = heading.group(1).strip() if heading else llms_title
        pages.append(PageData(
            url=page_url,
            title=title,
            section=section_for(page_url),
            language=language,
            content=content,
            content_preview=create_preview(re.sub(r"\s+", " ", content)),
        ))
        logger.info(f"Indexed: {title}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "vendor": vendor,
            "version": "latest",
            "built_at": datetime.now().isoformat(),
            "pages": [asdict(p) for p in pages],
        }, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved {len(pages)} {vendor} pages to {output_path}")
    return len(pages)
