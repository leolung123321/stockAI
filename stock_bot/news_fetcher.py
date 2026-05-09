"""
news_fetcher.py - 使用 yfinance 獲取最新 N 則新聞標題（支援全球股票）
"""
from typing import List
import yfinance as yf


def get_recent_news(symbol: str, count: int = 10) -> List[str]:
    """
    使用 yfinance 獲取指定股票最近新聞標題。

    Args:
        symbol: 股票代號，例如 "0700.HK", "AAPL", "0050.TW"
        count: 獲取新聞則數（預設 10)

    Returns:
        list[str]: 新聞標題列表，若失敗則回傳空列表
    """
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.news

        if not news or not isinstance(news, list):
            print(f"[news_fetcher] {symbol} 沒有 yfinance 新聞資料")
            return []

        headlines = []
        for item in news[:count]:
            title = item.get("title") or item.get("content", {}).get("title", "")
            title = str(title).strip()
            if title:
                headlines.append(title)

        if not headlines:
            print(f"[news_fetcher] {symbol} 新聞標題為空")
            return []

        return headlines

    except Exception as e:
        print(f"[news_fetcher] yfinance 新聞獲取失敗 ({symbol}): {e}")
        return []