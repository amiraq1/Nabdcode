from __future__ import annotations

from typing import Final

try:
    from duckduckgo_search.exceptions import DuckDuckGoSearchException
except ImportError:
    class DuckDuckGoSearchException(Exception):
        pass

from tools.base import BaseTool
from tools.models import ToolResult
from core.sanitize import sanitize


def _is_online(timeout: float = 1.5) -> bool:
    """Quick network reachability check."""
    import urllib.request
    try:
        urllib.request.urlopen(
            "https://api.duckduckgo.com",
            timeout=timeout,
        )
        return True
    except Exception:
        return False


class WebSearchTool(BaseTool):
    """
    Search the web using DuckDuckGo.

    Arguments
    ---------
    query : str
        Search query.

    max_results : int
        Number of search results.
        Default = 3
        Maximum = 10
    """

    name: Final[str] = "web_search"

    description: Final[str] = (
        "Search the web for documentation, tutorials, news, or general information."
    )

    DEFAULT_RESULTS: Final[int] = 3
    MAX_RESULTS: Final[int] = 10

    def execute(self, **kwargs) -> ToolResult:

        query = kwargs.get("query")
        max_results = kwargs.get(
            "max_results",
            self.DEFAULT_RESULTS,
        )

        #
        # Validation
        #

        if not isinstance(query, str):

            return ToolResult(
                success=False,
                stderr="Argument 'query' must be a string.",
            )

        query = query.strip()

        if not query:

            return ToolResult(
                success=False,
                stderr="Search query cannot be empty.",
            )

        try:
            max_results = int(max_results)
        except (TypeError, ValueError):

            return ToolResult(
                success=False,
                stderr="'max_results' must be an integer.",
            )

        max_results = max(
            1,
            min(
                max_results,
                self.MAX_RESULTS,
            ),
        )

        #
        # Lazy Import
        #

        try:
            from duckduckgo_search import DDGS

        except ImportError:
            return self._fallback_search(query, max_results)

        #
        # Search
        #

        # Offline check: fail fast instead of timing out
        if not _is_online():
            return ToolResult(
                success=True,
                stdout=(
                    "[Web search unavailable — no internet connection. "
                    "Use file_system or shell tools instead.]"
                ),
            )

        try:

            records: list[str] = []

            with DDGS() as ddgs:

                for index, result in enumerate(
                    ddgs.text(
                        query,
                        max_results=max_results,
                    ),
                    start=1,
                ):

                    title = sanitize(result.get("title") or "Untitled")
                    url = (
                        result.get("href")
                        or result.get("url")
                        or ""
                    )
                    snippet = sanitize(
                        result.get("body")
                        or result.get("snippet")
                        or "No description."
                    )

                    records.append(
                        (
                            f"[{index}] {title}\n"
                            f"URL: {url}\n"
                            f"{snippet}"
                        )
                    )

            if not records:

                return ToolResult(
                    success=True,
                    stdout=f"No results found for '{query}'.",
                )

            return ToolResult(
                success=True,
                stdout="\n\n".join(records),
            )

        except DuckDuckGoSearchException as exc:

            return ToolResult(
                success=False,
                stderr=f"DuckDuckGo error: {exc}",
            )

        except Exception as exc:

            return ToolResult(
                success=False,
                stderr=f"{type(exc).__name__}: {exc}",
            )

    def _fallback_search(self, query: str, max_results: int) -> ToolResult:
        import urllib.request
        import urllib.parse
        import json
        import re

        records: list[str] = []
        try:
            url_ddg = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
            req_ddg = urllib.request.Request(url_ddg, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_ddg, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                abstract = data.get("Abstract") or data.get("Heading")
                if abstract:
                    url = data.get("AbstractURL") or "https://duckduckgo.com"
                    records.append(f"[1] {data.get('Heading', 'Result')}\nURL: {url}\n{abstract}")
                for topic in data.get("RelatedTopics", [])[:max_results]:
                    if isinstance(topic, dict) and "Text" in topic:
                        records.append(f"[-] {topic.get('Text')}\nURL: {topic.get('FirstURL', '')}")
        except Exception:
            pass

        if len(records) < max_results:
            try:
                domain = "ar.wikipedia.org" if re.search(r"[\u0600-\u06FF]", query) else "en.wikipedia.org"
                url_wiki = f"https://{domain}/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&format=json"
                req_wiki = urllib.request.Request(url_wiki, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req_wiki, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                    for idx, item in enumerate(data.get("query", {}).get("search", [])[:max_results], start=len(records)+1):
                        snippet = re.sub(r"<.*?>", "", item.get("snippet", "")).strip()
                        title = item.get("title", "Untitled")
                        records.append(f"[{idx}] {title} (Wikipedia)\nURL: https://{domain}/wiki/{urllib.parse.quote(title)}\n{snippet}")
            except Exception:
                pass

        if not records:
            return ToolResult(
                success=True,
                stdout=f"No online results found for '{query}'. Notice: External search libraries are unavailable, but standard engineering tools remain active."
            )
        return ToolResult(success=True, stdout="\n\n".join(records))
