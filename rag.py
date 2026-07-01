"""
RAG 模組：呼叫隊友的 AnythingLLM API，取得知識庫答案。
若 API 無法連線，自動 fallback 到 rag_mock。
"""

import logging
import requests
import rag_mock
import config

logger = logging.getLogger(__name__)

RAG_TIMEOUT = 60  # 秒


def query_rag(rag_query: str) -> list[str]:
    """
    送出含脈絡的問題給 AnythingLLM，回傳知識片段列表。
    格式與 rag_mock.query_mock_rag() 相同，main.py 不需要改。
    """
    chunks, _ = query_rag_with_sources(rag_query)
    return chunks


def query_rag_with_sources(rag_query: str) -> tuple[list[str], list[dict]]:
    """Same as query_rag but also returns source metadata.

    Returns:
        (chunks, sources) where sources is a list of dicts with keys:
        'title' (str) and 'url' (str | None).
        Falls back to (mock_chunks, []) when RAG is unavailable.
    """
    if not config.RAG_API_URL:
        logger.info("RAG_API_URL 未設定，使用 Mock RAG")
        return rag_mock.query_mock_rag(rag_query), []

    try:
        resp = requests.post(
            config.RAG_API_URL,
            json={"message": rag_query},
            timeout=RAG_TIMEOUT,
        )
        resp.raise_for_status()
        data   = resp.json()
        answer = data.get("answer", "").strip()

        if not answer:
            logger.warning("RAG API 回傳空答案，fallback 到 Mock")
            return rag_mock.query_mock_rag(rag_query), []

        # AnythingLLM may return a 'sources' list alongside 'answer'
        raw_sources = data.get("sources") or []
        sources = [
            {
                "title": s.get("title") or s.get("name") or "政策文件",
                "url":   _clean_url(s.get("url") or s.get("docSource") or ""),
            }
            for s in raw_sources
            if isinstance(s, dict)
        ]
        # Deduplicate by URL, keep order
        seen: set[str] = set()
        unique_sources = []
        for s in sources:
            key = s["url"] or s["title"]
            if key not in seen:
                seen.add(key)
                unique_sources.append(s)

        logger.info("RAG API 回傳成功（%d 字，%d 個來源）", len(answer), len(unique_sources))
        return [answer], unique_sources

    except requests.exceptions.Timeout:
        logger.warning("RAG API 逾時（>%ds），fallback 到 Mock", RAG_TIMEOUT)
        return rag_mock.query_mock_rag(rag_query), []

    except Exception as e:
        logger.warning("RAG API 失敗：%s，fallback 到 Mock", e)
        return rag_mock.query_mock_rag(rag_query), []


def _clean_url(url: str) -> str:
    """Return url if it looks like a real http(s) URL, otherwise empty string."""
    url = url.strip()
    return url if url.startswith(("http://", "https://")) else ""
