import logging
from typing import Any
import httpx
from app.config import settings
from app.tools.bm25_utils import rank_documents_bm25

logger = logging.getLogger("gateway.firecrawl")


async def firecrawl_scrape(
    url: str,
    focus_query: str | None = None,
    max_length: int = 4000,
) -> str:
    """Scrape a webpage and convert it to clean markdown using Firecrawl.

    Applies BM25 Okapi chunk-filtering if focus_query is provided to extract only
    the most relevant sections, preventing LLM context window bloat.

    Args:
        url: The web URL to scrape.
        focus_query: Optional search query to filter and extract top-ranked sections.
        max_length: Maximum character length when no focus query is specified.

    Returns:
        Clean markdown representation of the target webpage.
    """
    if not settings.firecrawl_api_key:
        return (
            "Firecrawl API key is not configured. "
            "Please set FIRECRAWL_API_KEY in the gateway's .env."
        )

    headers = {
        "Authorization": f"Bearer {settings.firecrawl_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": url,
        "formats": ["markdown"],
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.firecrawl_api_url.rstrip('/')}/v1/scrape",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        markdown_content = (
            data.get("data", {}).get("markdown")
            or data.get("markdown")
            or ""
        )

        if not markdown_content:
            return f"Scrape completed for {url}, but no markdown content was returned."

        # If a focus query is specified, apply BM25 section extraction
        if focus_query:
            # Split by double newlines or headers into chunks
            raw_chunks = [c.strip() for c in markdown_content.split("\n\n") if len(c.strip()) > 30]
            chunk_docs = [{"content": c, "id": i} for i, c in enumerate(raw_chunks)]
            
            ranked_chunks = rank_documents_bm25(
                query=focus_query,
                documents=chunk_docs,
                text_key="content",
                top_k=4,
            )

            # Sort chunks back into original reading order
            ranked_chunks.sort(key=lambda x: x["id"])
            extracted = "\n\n---\n\n".join(c["content"] for c in ranked_chunks)

            return (
                f"### Firecrawl BM25-Extracted Sections for: `{focus_query}` from [{url}]({url})\n\n"
                f"{extracted}"
            )

        # Truncate if exceeds max_length without focus_query
        if len(markdown_content) > max_length:
            return (
                f"### Scraped Content from [{url}]({url}) (Truncated to {max_length} chars)\n\n"
                f"{markdown_content[:max_length]}\n\n"
                f"*...[Truncated {len(markdown_content) - max_length} additional characters. Provide `focus_query` to extract specific topics]*"
            )

        return f"### Scraped Content from [{url}]({url})\n\n{markdown_content}"

    except httpx.HTTPStatusError as e:
        logger.error(f"Firecrawl HTTP error: {e.response.status_code} - {e.response.text}")
        return f"Firecrawl API Error ({e.response.status_code}): {e.response.text}"
    except Exception as e:
        logger.error(f"Firecrawl scraping error: {e}")
        return f"Error executing Firecrawl scrape: {str(e)}"
