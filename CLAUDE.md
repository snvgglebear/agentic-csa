# CLAUDE.md - Project Guide for AI Assistants

## Project Overview

**FIRST Agentic CSA** is an MCP (Model Context Protocol) server that provides intelligent documentation search across FIRST Robotics Competition (FRC) documentation. It aggregates docs from multiple vendors (WPILib, REV Robotics, CTRE Phoenix, Redux, PhotonVision) and enables natural language queries via AI assistants.

## Tech Stack

- **Language:** Python 3.11+
- **Package Manager:** uv (Astral's Rust-based manager)
- **Protocol:** MCP 2025-06-18 schema
- **Search:** BM25 ranking via `rank-bm25`, stemming via `snowballstemmer`
- **HTTP:** httpx with async support
- **HTML Parsing:** BeautifulSoup4 + lxml
- **Build:** Hatchling
- **Testing:** pytest with asyncio

## Project Structure

```
src/wpilib_mcp/
├── server.py           # MCP server entry point & tool registration
├── tool_router.py      # Routes tool calls to plugins
├── plugin_loader.py    # Plugin discovery & loading
├── plugins/            # Vendor plugin implementations
│   ├── base.py         # PluginBase abstract class
│   ├── wpilib/         # WPILib core docs
│   ├── rev/            # REV Robotics (SparkMax)
│   ├── ctre/           # CTRE Phoenix (TalonFX)
│   ├── redux/          # Redux Robotics
│   ├── photonvision/   # PhotonVision
│   ├── limelight/      # Limelight (StaticDocsPlugin)
│   ├── pathplanner/    # PathPlanner (StaticDocsPlugin)
│   ├── advantagescope/ # AdvantageScope (StaticDocsPlugin)
│   └── advantagekit/, yagsl/, yams/
├── config.json         # Runtime configuration (ships in the wheel)
└── utils/
    ├── search.py       # BM25 search indexing
    ├── fetch.py        # HTTP fetching with caching
    ├── html.py         # HTML cleaning & extraction
    ├── indexer.py      # Crawling index builder (uses seed_urls() when the site has a page list)
    ├── sphinx_inventory.py  # Lists every page of a Sphinx site from objects.inv
    └── static_docs.py  # Shared plugin + builder for sites with a fixed page list

tests/                  # pytest test suite
scripts/                # Utility scripts (index building)
server.json             # MCP server manifest
```

## Common Commands

```bash
# Install dependencies
uv sync --all-extras

# Run tests
uv run pytest tests/ -v

# Run server locally
uv run first-agentic-csa

# Build package
uv build

# Build documentation indexes
python scripts/build_index.py all
python scripts/build_index.py wpilib    # 2027 season (docs.wpilib.org/en/latest)
python scripts/build_index.py rev
```

## Architecture Patterns

### Plugin System
- Each vendor implements a Plugin class extending `PluginBase`
- Plugins are loaded dynamically based on `src/wpilib_mcp/config.json` (or the file in `FIRST_AGENTIC_CSA_CONFIG`)
- A new docs site with a sitemap or table of contents needs only a `StaticDocsPlugin` subclass and a `build_index.py` that lists its URLs (see `limelight/`)
- Lifecycle: load → initialize → search/fetch → shutdown

### Async Pattern
All I/O operations are async:
```python
async def search(query, version, language, max_results) -> list[SearchResult]
async def fetch_page(url) -> Optional[PageContent]
```

### Key Data Classes
```python
@dataclass
class SearchResult:
    url, title, section, vendor, language, version, content_preview, score

@dataclass
class PageContent:
    url, title, content, vendor, language, version, section, last_fetched
```

### MCP Tools Exposed
1. `search_frc_docs` - Multi-vendor search with filters. How results are ranked (`tool_router.py`, `utils/search.py`):
   - One BM25 index over every vendor, with stemmed words (`snowballstemmer`; `STEM_EXCEPTIONS` keeps FRC nouns like "follower" apart from common words)
   - Student phrasings rewritten to docs wording at full weight (`FRC_REWRITES`, e.g. "browns out" -> "brownout"); related terms at 40% (`FRC_SYNONYMS`)
   - Bonuses for query words in the title and for query words side by side ("current limit"); a boost for vendors the query names, whose product names then count less
   - With `auto_detect` (the default), `utils/context.py` skips vendor libraries the robot project lacks (`PROJECT_LIBRARIES`), keeps tools with no project trace (AdvantageScope, Limelight) and vendors the query names, and does nothing outside a robot project (`is_robot_project`)
   - Hits under half the best score are dropped; results are flagged `weak_match` when no page holds 70% of the query's words, weighted by rarity
2. `fetch_frc_doc_page` - Page content retrieval, cut off at `max_chars` (default 12,000, about 3,000 tokens)
3. `list_frc_doc_sections` - Browse available documentation

## Coding Conventions

- Use async/await for all I/O operations
- Type hints on all function signatures
- Dataclasses for structured data
- Graceful error handling (don't crash the server)
- Pre-built JSON indexes stored in each plugin's `data/` directory

## Configuration

`src/wpilib_mcp/config.json` controls:
- Plugin enable/disable
- Supported languages per vendor (Java, Python, C++)
- Season versions for WPILib and PhotonVision: only `latest` (2027) ships; `2027` works as an alias (see `utils/seasons.py`)
- Cache TTL and size limits
- Default search parameters

## Testing

```bash
# Run all tests
uv run pytest tests/ -v

# Measure search quality on student questions (run after changing ranking or indexes)
uv run python scripts/search_eval.py -v

# Run specific test file
uv run pytest tests/test_plugins.py -v
uv run pytest tests/test_search.py -v
```

## Entry Point

The package exposes `first-agentic-csa` command which runs `wpilib_mcp.server:main()`
