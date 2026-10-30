import logging
from typing import Any
import httpx
from app.config import settings
from app.tools.bm25_utils import rank_documents_bm25

logger = logging.getLogger("gateway.context7")


async def context7_docs(
    library: str,
    topic: str,
    max_tokens_approx: int = 2500,
) -> str:
    """Retrieve documentation and code context for a library or API using Context7.

    Resolves library ID using Context7 search and fetches targeted documentation.
    If CONTEXT7_API_KEY is not configured or unavailable, automatically falls back
    to SearXNG IT engine.

    Args:
        library: The package, library, or framework name (e.g. 'fastmcp', 'traefik', 'pydantic').
        topic: The specific concept, function, or usage question.
        max_tokens_approx: Approximate context budget limit.

    Returns:
        Curated documentation markdown.
    """
    if settings.context7_api_key:
        headers = {
            "Authorization": f"Bearer {settings.context7_api_key}",
            "X-Context7-Source": "mcp-server",
        }
        base_url = settings.context7_api_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                # Step 1: Search and resolve library ID
                search_url = f"{base_url}/v2/libs/search"
                search_resp = await client.get(
                    search_url,
                    params={"query": topic, "libraryName": library},
                    headers=headers,
                )
                if search_resp.status_code == 200:
                    search_data = search_resp.json()
                    results = search_data.get("results", [])
                    if results:
                        library_id = results[0].get("id")
                        lib_title = results[0].get("title", library)
                        # Step 2: Fetch context for resolved library
                        context_url = f"{base_url}/v2/context"
                        ctx_resp = await client.get(
                            context_url,
                            params={"query": topic, "libraryId": library_id},
                            headers=headers,
                        )
                        if ctx_resp.status_code == 200 and ctx_resp.text.strip():
                            docs_text = ctx_resp.text.strip()
                            return f"### Context7 Documentation: `{lib_title}` (`{library_id}`)\n**Topic:** `{topic}`\n\n{docs_text}"
        except Exception as e:
            logger.warning(f"Context7 API call failed: {e}. Falling back to internal docs search.")

    # Graceful fallback: SearXNG query scoped to library and documentation
    query = f"{library} official documentation {topic}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{settings.searxng_url}/search",
                params={"q": query, "format": "json", "categories": "it"},
            )
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            return f"No documentation entries found for '{library}: {topic}'"

        ranked = rank_documents_bm25(query=topic, documents=results, text_key="content", top_k=3)
        lines = [
            f"### Context Documentation: `{library}` (Topic: `{topic}`)\n",
            "*(Retrieved via SearXNG IT Engine)*\n",
        ]
        for item in ranked:
            lines.append(f"**[{item.get('title')}]({item.get('url')})**")
            lines.append(f"> {item.get('content', '').strip()}\n")

        return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving documentation for {library}: {str(e)}"

