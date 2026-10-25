"""Routes unified MCP tools to appropriate plugins."""

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

from .plugins.base import PluginBase, SearchResult, PageContent, DocSection
from .utils.search import BM25SearchIndex
from .utils.seasons import SeasonVersions


logger = logging.getLogger(__name__)


# Results scoring below this fraction of the best hit are dropped, so a
# search returns only relevant pages instead of one page from every vendor.
MIN_RELATIVE_SCORE = 0.5

# When no returned page holds this share of the query's words (weighted by
# how rare each word is), results are flagged as weak matches.
MIN_TERM_COVERAGE = 0.7

# Extra score for a page whose title holds all of the query's words
# (scaled by the share of words that appear)
TITLE_BONUS = 0.6

# How many top pages get re-ranked with the title, phrase, and vendor
# bonuses. Large enough that a page whose words are all common (such as
# "Followers" for "follower motor configuration") still gets considered.
CANDIDATE_POOL = 150

# Extra score for a page where all of the query's neighboring word pairs
# also appear side by side (scaled by the share that do)
PHRASE_BONUS = 0.6

# Score multiplier for a vendor the query names, directly or by product.
VENDOR_BOOST = 1.6

VENDOR_TERMS = {
    "wpilib": ["wpilib", "wpilibj", "glass", "shuffleboard", "sysid", "epilogue"],
    "rev": ["rev", "revlib", "sparkmax", "spark", "sparkflex", "neo", "vortex"],
    "ctre": ["ctre", "phoenix", "talonfx", "talon", "kraken", "falcon", "cancoder",
             "pigeon", "pigeon2", "candle", "candi", "canivore", "tuner"],
    "photonvision": ["photonvision", "photonlib", "photon"],
    "limelight": ["limelight", "limelightlib", "megatag", "megatag2"],
    "pathplanner": ["pathplanner", "pathplannerlib", "pplib", "autobuilder"],
    "advantagekit": ["advantagekit", "akit"],
    "advantagescope": ["advantagescope"],
    "yagsl": ["yagsl"],
    "yams": ["yams"],
    "redux": ["redux", "canandmag", "canandgyro", "canandcolor"],
}


# Vendor and hardware names. When a query names one, the vendor boost
# already favors that vendor, so these words count less in ranking than
# what the student asked about the product. Features students ask about
# (Epilogue, SysId, MegaTag) are deliberately not here.
PRODUCT_NAMES = [
    "wpilib", "rev", "revlib", "spark max", "spark flex", "sparkmax", "sparkflex", "neo", "vortex",
    "ctre", "phoenix", "talon fx", "talon fxs", "talonfx", "talon", "kraken", "falcon", "cancoder",
    "pigeon", "pigeon2", "candle", "candi", "canivore", "photonvision", "photonlib", "limelight",
    "pathplanner", "pathplannerlib", "advantagekit", "advantagescope", "yagsl", "yams", "redux",
    "x60", "x44",
]


@lru_cache(maxsize=4)
def _product_words(index: "BM25SearchIndex") -> frozenset[str]:
    """Stemmed vendor and hardware names."""
    words = set()
    for name in PRODUCT_NAMES:
        words.update(index.tokenize(name))
    return frozenset(words)


def _phrase_share(query_terms: list[str], page_terms: list[str]) -> float:
    """Share of the query's neighboring word pairs that also sit side by side in the page."""
    pairs = set(zip(query_terms, query_terms[1:], strict=False))
    if not pairs:
        return 0.0
    page_pairs = set(zip(page_terms, page_terms[1:], strict=False))
    return len(pairs & page_pairs) / len(pairs)


def vendors_named_in(query: str) -> set[str]:
    """Vendors whose name or products appear in the query."""
    words = set(re.findall(r"[a-z0-9]+", query.lower()))
    # Longer names also match with spaces removed ("Spark Max", "Talon FX")
    joined = re.sub(r"[^a-z0-9]", "", query.lower())
    named = set()
    for vendor, terms in VENDOR_TERMS.items():
        if any(term in words or (len(term) > 5 and term in joined) for term in terms):
            named.add(vendor)
    return named


TITLE_JUNK = [
    re.compile(r"\s*\{#[^}]*\}"),                         # Markdown anchors: "Logging {#logging}"
    re.compile(r"\s+[-|—]\s+PhotonVision Docs$"),           # site-name suffixes
    re.compile(r"\s+[-|—]\s+FIRST Robotics Competition documentation$"),
]


# Labels that don't help tell pages apart
GENERIC_LABELS = {"", "general", "docs", "documentation", "home", "index", "sw", "en", "stable", "latest"}

# Words that keep their capitals when a URL part becomes a label
LABEL_WORDS = {"ion": "ION", "api": "API", "rev": "REV", "revlib": "REVLib", "gui": "GUI",
               "frc": "FRC", "nt": "NT", "can": "CAN", "pid": "PID"}


def _words(slug: str) -> str:
    """"ion-control" -> "ION Control"."""
    return " ".join(LABEL_WORDS.get(w.lower(), w.capitalize()) for w in re.split(r"[-_]+", slug) if w)


def _url_parts(url: str) -> list[str]:
    return [p for p in url.split("?")[0].split("#")[0].split("/") if p]


def _folder_label(url: str) -> str:
    """The page's folder: ".../migration-guide/configuration-guide.html" -> "Migration Guide"."""
    parts = _url_parts(url)
    return _words(parts[-2]) if len(parts) >= 3 else ""


def _area_label(url: str) -> str:
    """The first folder after the site: "docs.revrobotics.com/ion-control/..." -> "ION Control"."""
    parts = _url_parts(url)
    return _words(parts[2]) if len(parts) > 3 else ""


def _file_label(url: str) -> str:
    """The page's file name: ".../shuffleboard-layouts.html" -> "Shuffleboard Layouts"."""
    parts = _url_parts(url)
    return _words(re.sub(r"\.(html?|md)$", "", parts[-1])) if len(parts) >= 2 else ""


LABEL_KINDS = (
    lambda p: p.section,
    lambda p: _area_label(p.url),
    lambda p: _folder_label(p.url),
    lambda p: _file_label(p.url),
)


def _labeled_titles(same: list, kind, allow_bare: bool) -> Optional[list[str]]:
    """Titles with one kind of label added, or None if they'd still clash."""
    titles = []
    for page in same:
        label = kind(page)
        useless = label.lower() in GENERIC_LABELS or label.lower() == page.title.lower()
        if useless:
            if not allow_bare:
                return None
            titles.append(page.title)
        else:
            titles.append(f"{page.title} ({label})")
    return titles if len(set(titles)) == len(same) else None


def clean_title(title: str) -> str:
    """A title without Markdown anchors or site-name suffixes."""
    for pattern in TITLE_JUNK:
        title = pattern.sub("", title)
    return title.strip()


def tidy_titles(pages: list) -> None:
    """
    Clean page titles in place: drop Markdown anchors and site-name
    suffixes, and tell apart pages that share a title within one season
    of one vendor's docs. The label is the first of section, docs area,
    folder, or file name that gives every page a distinct, meaningful
    label; failing that, some pages may keep their plain title.
    """
    for page in pages:
        page.title = clean_title(page.title)

    groups: dict[tuple, list] = {}
    for page in pages:
        groups.setdefault((getattr(page, "version", None), page.title), []).append(page)

    for same in groups.values():
        if len(same) < 2:
            continue
        for allow_bare in (False, True):
            titles = next(
                (t for kind in LABEL_KINDS if (t := _labeled_titles(same, kind, allow_bare))),
                None,
            )
            if titles:
                for page, title in zip(same, titles, strict=True):
                    page.title = title
                break


@dataclass
class _GlobalEntry:
    """A page in the cross-vendor search index."""
    vendor: str
    display_name: str
    page: Any


class ToolRouter:
    """
    Routes unified tool calls to the appropriate plugins.
    
    Provides the logic behind the 3 unified MCP tools:
    - search_frc_docs: Multi-vendor search with result merging
    - fetch_frc_doc_page: URL-based routing to correct plugin
    - list_frc_doc_sections: Aggregate sections from plugins
    """
    
    def __init__(self, plugins: dict[str, PluginBase]):
        """
        Initialize the router with loaded plugins.
        
        Args:
            plugins: Dictionary of plugin name -> plugin instance
        """
        self._plugins = plugins
        self._global_index: Optional[BM25SearchIndex] = None
        self._term_cache: dict[int, int] = {}
    
    def update_plugins(self, plugins: dict[str, PluginBase]) -> None:
        """Update the plugins dictionary."""
        self._plugins = plugins
        self._global_index: Optional[BM25SearchIndex] = None
        self._term_cache: dict[int, int] = {}
    
    @property
    def available_vendors(self) -> list[str]:
        """Get list of available vendor names."""
        return list(self._plugins.keys())
    
    def get_plugin_info(self) -> list[dict]:
        """Get information about all loaded plugins."""
        info = []
        for name, plugin in self._plugins.items():
            info.append({
                "name": name,
                "display_name": plugin.display_name,
                "description": plugin.description,
                "versions": plugin.supported_versions,
                "languages": plugin.supported_languages,
                "initialized": plugin.is_initialized
            })
        return info
    
    def _resolve_vendors(self, vendors: list[str]) -> list[str]:
        """
        Resolve vendor list, expanding 'all' to all available vendors.
        
        Args:
            vendors: List of vendor names or ["all"]
            
        Returns:
            List of actual vendor names to query
        """
        if not vendors or vendors == ["all"] or "all" in vendors:
            return list(self._plugins.keys())
        
        # Filter to only valid vendors
        valid = [v for v in vendors if v in self._plugins]
        if len(valid) < len(vendors):
            invalid = set(vendors) - set(valid)
            logger.warning(f"Unknown vendors ignored: {invalid}")
        
        return valid
    
    async def search(
        self,
        query: str,
        vendors: list[str] = None,
        version: Optional[str] = None,
        language: Optional[str] = None,
        max_results: int = 10
    ) -> list[SearchResult]:
        """
        Search across multiple vendors and merge results.
        
        Args:
            query: Search query string
            vendors: List of vendors to search (["all"] for all)
            version: Filter by version
            language: Filter by language (Java/Python/C++)
            max_results: Maximum results to return
            
        Returns:
            Merged and ranked list of SearchResult objects
        """
        if vendors is None:
            vendors = ["all"]

        target_vendors = set(self._resolve_vendors(vendors))
        if not target_vendors:
            logger.warning("No valid vendors to search")
            return []

        index = self._get_global_index()
        if not index.is_built:
            return []

        # Some vendors (WPILib, PhotonVision) keep one index per season;
        # map the requested version ("2027", "latest", ...) for each.
        season = {}
        for name in target_vendors:
            plugin = self._plugins[name]
            if isinstance(plugin, SeasonVersions):
                season[name] = plugin._resolve_version(version)

        def filter_fn(entry: _GlobalEntry) -> bool:
            if entry.vendor not in target_vendors:
                return False
            if language and entry.page.language not in (language, "All", None, ""):
                return False
            wanted = season.get(entry.vendor)
            if wanted:
                return getattr(entry.page, "version", None) == wanted
            return True

        # Rank more candidates than needed, then apply vendor boosts and cut weak hits.
        # When the query names a product, the vendor boost covers it, so the
        # product's name counts less than what was asked about it.
        boosted = vendors_named_in(query)
        light = _product_words(index) if boosted else frozenset()
        candidates = index.search_with_filter(
            query=query, filter_fn=filter_fn, max_results=max(max_results * 4, CANDIDATE_POOL),
            light_terms=light,
        )
        # Product names already get the vendor boost; leaving them out of the
        # title bonus stops "Talon FX" overview pages beating the page about
        # what was asked ("current limits")
        ordered_terms = [tok for tok in index.tokenize(query) if tok not in _product_words(index)]
        query_terms = set(ordered_terms)
        scored = []
        for sr in candidates:
            score = sr.score * (VENDOR_BOOST if sr.item.vendor in boosted else 1.0)
            # Favor pages whose title holds the query's words
            if query_terms:
                in_title = query_terms & set(index.tokenize(sr.item.page.title))
                score *= 1.0 + TITLE_BONUS * len(in_title) / len(query_terms)
            # Favor pages where the query's words sit together ("current limit")
            if len(ordered_terms) > 1:
                score *= 1.0 + PHRASE_BONUS * _phrase_share(ordered_terms, self._page_terms(index, sr.item))
            scored.append((score, sr.item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        if not scored:
            return []

        cutoff = scored[0][0] * MIN_RELATIVE_SCORE
        results = []
        for score, entry in scored:
            if score < cutoff or len(results) >= max_results:
                break
            page = entry.page
            results.append(SearchResult(
                url=page.url,
                title=page.title,
                section=page.section,
                vendor=entry.display_name,
                language=page.language,
                version=getattr(page, "version", None) or "latest",
                content_preview=page.content_preview or page.content[:300],
                score=float(score),
            ))

        # Weak only when none of the returned pages covers the question
        weak = not any(self._covers(index, query, entry.page) for _, entry in scored[:len(results)])
        for result in results:
            result.weak_match = weak
        return results

    @staticmethod
    def _covers(index: "BM25SearchIndex", query: str, page: Any) -> bool:
        """
        True when the page holds at least MIN_TERM_COVERAGE of the query's
        words. BM25 always returns its closest pages, even when the docs
        don't cover the topic (for example "sensorless homing").
        """
        text = f"{page.title} {page.section} {page.content}"
        return index.term_coverage(query, text) >= MIN_TERM_COVERAGE

    def _page_terms(self, index: "BM25SearchIndex", entry: "_GlobalEntry") -> list[str]:
        """A page's stemmed words in order, as the index stored them when it was built."""
        if not self._term_cache:
            self._term_cache = {id(item): i for i, item in enumerate(index._items)}
        return index._corpus[self._term_cache[id(entry)]]

    def _get_global_index(self) -> "BM25SearchIndex[_GlobalEntry]":
        """
        One search index over every vendor's pages.

        Each vendor's own index has different word statistics, so their
        scores can't be compared. A single index scores all pages alike.
        """
        if self._global_index is None:
            entries = []
            for name, plugin in self._plugins.items():
                if not plugin.is_initialized:
                    continue
                pages = getattr(plugin, "_pages", [])
                tidy_titles(pages)
                for page in pages:
                    entries.append(_GlobalEntry(name, plugin.display_name, page))
            index: BM25SearchIndex[_GlobalEntry] = BM25SearchIndex()
            if entries:
                # Repeating the title weights it above body text.
                index.build(
                    items=entries,
                    text_extractor=lambda e: (
                        f"{e.page.title} {e.page.title} {e.page.section} {e.page.content}"
                    ),
                )
                logger.info(f"Built global search index with {len(entries)} pages")
            self._global_index = index
        return self._global_index
    
    async def fetch_page(self, url: str) -> Optional[PageContent]:
        """
        Fetch a documentation page, routing to the correct plugin.
        
        Args:
            url: The page URL to fetch
            
        Returns:
            PageContent if successful, None if no plugin handles the URL
        """
        # Find the plugin that owns this URL
        for name, plugin in self._plugins.items():
            if plugin.owns_url(url):
                logger.debug(f"URL {url} routed to plugin {name}")
                try:
                    return await plugin.fetch_page(url)
                except Exception as e:
                    logger.error(f"Fetch error in plugin {name}: {e}")
                    return None
        
        logger.warning(f"No plugin found for URL: {url}")
        return None
    
    def find_plugin_for_url(self, url: str) -> Optional[str]:
        """
        Find which plugin handles a URL.
        
        Args:
            url: URL to check
            
        Returns:
            Plugin name if found, None otherwise
        """
        for name, plugin in self._plugins.items():
            if plugin.owns_url(url):
                return name
        return None
    
    async def list_sections(
        self,
        vendors: list[str] = None,
        version: Optional[str] = None,
        language: Optional[str] = None
    ) -> dict[str, list[DocSection]]:
        """
        List documentation sections from requested vendors.
        
        Args:
            vendors: List of vendors (["all"] for all)
            version: Filter by version
            language: Filter by language
            
        Returns:
            Dictionary of vendor name -> list of DocSection objects
        """
        if vendors is None:
            vendors = ["all"]
        
        target_vendors = self._resolve_vendors(vendors)
        result: dict[str, list[DocSection]] = {}
        
        for vendor_name in target_vendors:
            plugin = self._plugins.get(vendor_name)
            if plugin is None or not plugin.is_initialized:
                continue
            
            try:
                sections = await plugin.list_sections(
                    version=version,
                    language=language
                )
                result[vendor_name] = sections
                
            except Exception as e:
                logger.error(f"List sections error in plugin {vendor_name}: {e}")
                result[vendor_name] = []
        
        return result


def format_search_results(results: list[SearchResult]) -> str:
    """
    Format search results for MCP tool response.
    
    Args:
        results: List of SearchResult objects
        
    Returns:
        Formatted string suitable for LLM consumption
    """
    if not results:
        return "No results found."

    if results[0].weak_match:
        lines = [
            "No indexed page closely matches this search. These are the nearest "
            "pages; check that they cover the topic before citing them, or try "
            "other words or a web search.\n"
        ]
    else:
        lines = [f"Found {len(results)} result(s):\n"]
    
    for i, result in enumerate(results, 1):
        lines.append(f"## {i}. {result.title}")
        lines.append(f"**Vendor:** {result.vendor} | **Section:** {result.section}")
        if result.language:
            lines.append(f"**Language:** {result.language}")
        lines.append(f"**URL:** {result.url}")
        lines.append(f"\n{result.content_preview}\n")
        lines.append("---\n")
    
    return "\n".join(lines)


def format_page_content(page: PageContent) -> str:
    """
    Format page content for MCP tool response.
    
    Args:
        page: PageContent object
        
    Returns:
        Formatted string suitable for LLM consumption
    """
    lines = [
        f"# {page.title}",
        f"**Source:** {page.vendor}",
        f"**URL:** {page.url}",
    ]
    
    if page.language:
        lines.append(f"**Language:** {page.language}")
    if page.version:
        lines.append(f"**Version:** {page.version}")
    if page.section:
        lines.append(f"**Section:** {page.section}")
    
    lines.append("\n---\n")
    lines.append(page.content)
    
    return "\n".join(lines)


def format_sections(sections_by_vendor: dict[str, list[DocSection]]) -> str:
    """
    Format documentation sections for MCP tool response.
    
    Args:
        sections_by_vendor: Dictionary of vendor -> sections
        
    Returns:
        Formatted string suitable for LLM consumption
    """
    if not sections_by_vendor:
        return "No documentation sections available."
    
    lines = ["# Available Documentation Sections\n"]
    
    for vendor, sections in sections_by_vendor.items():
        lines.append(f"## {vendor.upper()}\n")
        
        if not sections:
            lines.append("No sections available.\n")
            continue
        
        for section in sections:
            lines.append(f"### {section.name}")
            if section.description:
                lines.append(f"{section.description}")
            if section.page_count > 0:
                lines.append(f"*{section.page_count} pages*")
            if section.url:
                lines.append(f"URL: {section.url}")
            
            if section.subsections:
                for sub in section.subsections:
                    lines.append(f"  - {sub.name}")
            
            lines.append("")
    
    return "\n".join(lines)




