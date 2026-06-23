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
    if not config.RAG_API_URL:
        logger.info("RAG_API_URL 未設定，使用 Mock RAG")
        return rag_mock.query_mock_rag(rag_query)

    try:
        resp = requests.post(
            config.RAG_API_URL,
            json={"message": rag_query},
            timeout=RAG_TIMEOUT,
        )
        resp.raise_for_status()
        answer = resp.json().get("answer", "").strip()

        if not answer:
            logger.warning("RAG API 回傳空答案，fallback 到 Mock")
            return rag_mock.query_mock_rag(rag_query)

        logger.info("RAG API 回傳成功（%d 字）", len(answer))
        return [answer]

    except requests.exceptions.Timeout:
        logger.warning("RAG API 逾時（>%ds），fallback 到 Mock", RAG_TIMEOUT)
        return rag_mock.query_mock_rag(rag_query)

    except Exception as e:
        logger.warning("RAG API 失敗：%s，fallback 到 Mock", e)
        return rag_mock.query_mock_rag(rag_query)
