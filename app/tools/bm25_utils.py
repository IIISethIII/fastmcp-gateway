import re
from typing import Any
from rank_bm25 import BM25Okapi


def tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase alphanumeric tokens."""
    return re.findall(r"\w+", text.lower())


def rank_documents_bm25(
    query: str,
    documents: list[dict[str, Any]],
    text_key: str = "content",
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Rank documents using BM25 Okapi against a query string.
    
    If fewer documents exist than top_k, returns all ranked.
    If query is empty or no valid tokens, returns the first top_k documents.
    """
    if not documents:
        return []

    corpus = [doc.get(text_key, "") or "" for doc in documents]
    tokenized_corpus = [tokenize(doc) for doc in corpus]

    query_tokens = tokenize(query)
    if not query_tokens or not any(tokenized_corpus):
        return documents[:top_k]

    try:
        bm25 = BM25Okapi(tokenized_corpus)
        scores = bm25.get_scores(query_tokens)

        # Pair each document with its score
        scored_docs = list(zip(documents, scores))
        # Sort descending by score
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        ranked = []
        for doc, score in scored_docs[:top_k]:
            doc_copy = dict(doc)
            doc_copy["_bm25_score"] = round(float(score), 4)
            ranked.append(doc_copy)
        return ranked
    except Exception:
        return documents[:top_k]
