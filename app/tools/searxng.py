import logging
from typing import Any
import httpx
from app.config import settings
from app.tools.bm25_utils import rank_documents_bm25

logger = logging.getLogger("gateway.searxng")


async def searxng_search(
    query: str,
    categories: str = "general",
    time_range: str | None = None,
    max_results: int = 5,
) -> str:
    """Search the web using the local SearXNG engine with BM25 relevance ranking.

    Args:
        query: The search term or question.
        categories: Comma-separated categories (e.g. 'general', 'it', 'science').
        time_range: Filter by recency ('day', 'week', 'month', 'year') or None.
        max_results: Number of ranked results to return (default 5).

    Returns:
        Clean, markdown-formatted search results.
    """
    params: dict[str, Any] = {
        "q": query,
        "format": "json",
        "categories": categories,
    }
    if time_range:
        params["time_range"] = time_range

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{settings.searxng_url}/search", params=params)
            resp.raise_for_status()
            data = resp.json()

        raw_results = data.get("results", [])
        if not raw_results:
            return f"No results found for query: '{query}'"

        # Apply BM25 ranking to ensure high-relevance snippets come first
        ranked = rank_documents_bm25(
            query=query,
            documents=raw_results,
            text_key="content",
            top_k=max_results,
        )

        output_lines = [f"### SearXNG Results for: `{query}`\n"]
        for i, item in enumerate(ranked, 1):
            title = item.get("title", "Untitled")
            url = item.get("url", "")
            content = item.get("content", "").strip()
            score = item.get("_bm25_score", 0.0)
            output_lines.append(f"**{i}. [{title}]({url})** (relevance: {score})")
            if content:
                output_lines.append(f"> {content}")
            output_lines.append("")

        return "\n".join(output_lines)
    except httpx.ConnectError:
        logger.error(f"Failed to connect to SearXNG at {settings.searxng_url}")
        return f"Error: Unable to connect to SearXNG at {settings.searxng_url}. Verify container status."
    except Exception as e:
        logger.error(f"SearXNG query failed: {e}")
        return f"Error querying SearXNG: {str(e)}"
