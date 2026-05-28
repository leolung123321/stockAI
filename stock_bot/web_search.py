"""
web_search.py - Tavily API 封裝，用於通用問題搜索
"""
import os
from typing import List, Dict, Optional


def search_tavily(query: str, max_results: int = 5) -> Optional[List[Dict[str, str]]]:
    """
    使用 Tavily API 搜索網路。

    Args:
        query: 搜索查詢
        max_results: 最大結果數

    Returns:
        List[dict]: [{title, url, content}] 或 None（失敗時）
    """
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        return None

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=api_key)
        response = client.search(query=query, max_results=max_results)

        results = response.get("results", [])
        out = []
        for r in results:
            out.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
            })
        return out

    except ImportError:
        print("[web_search] tavily-python 未安裝")
        return None
    except Exception as e:
        print(f"[web_search] Tavily 搜索失敗: {e}")
        return None