"""
news_fetcher.py - 使用 yfinance 獲取與股票相關的最新 N 則新聞標題
（合併 ticker.news + yf.Search 以獲取更多新聞）
"""
from typing import List, Set, Dict, Any
import yfinance as yf


def _extract_keywords(symbol: str, ticker: yf.Ticker) -> Set[str]:
    """從股票代號與公司名稱提取相關關鍵詞，用於新聞過濾。"""
    keywords: Set[str] = set()

    # 1) 代號本身（無後綴）
    clean = symbol.upper().replace(".HK", "").replace(".TW", "").replace(".T", "")
    keywords.add(clean.lower())

    # 2) 港股4位數字代號（如 0700 → 700）
    if clean.isdigit() and len(clean) == 4:
        keywords.add(clean.lstrip("0"))

    # 3) 公司名稱關鍵詞
    try:
        info = ticker.info or {}
        name = info.get("shortName") or info.get("longName") or ""
        # 提取名稱中的有意義詞彙（長度 > 2，非停用詞）
        stopwords = {"inc", "ltd", "limited", "corp", "corporation", "holdings", "holding", "group", "the", "and", "co", "company", "plc", "sehk", "class"}
        for word in name.replace(",", " ").replace(".", " ").split():
            w = word.strip().lower()
            if len(w) > 2 and w not in stopwords:
                keywords.add(w)
    except Exception:
        pass

    # 4) 常見中文名稱對應（港股）
    zh_map = {
        "0700": ["騰訊", "tencent"],
        "0998": ["阿里巴巴", "阿里", "alibaba"],
        "9988": ["阿里巴巴", "阿里", "alibaba"],
        "3690": ["美團", "meituan"],
        "1810": ["小米", "xiaomi"],
        "0005": ["匯豐", "hsbc"],
        "1299": ["友邦", "aia"],
        "2318": ["平安", "ping an"],
        "0388": ["港交所", "hkex"],
        "0981": ["中芯", "smic"],
        "0941": ["中移動", "china mobile"],
        "1211": ["比亞迪", "byd"],
        "9618": ["京東", "jd"],
        "1024": ["快手", "kuaishou"],
        "9999": ["網易", "netease"],
        "9888": ["百度", "baidu"],
    }
    if clean in zh_map:
        for w in zh_map[clean]:
            keywords.add(w.lower())

    return keywords


def _is_relevant(headline: str, keywords: Set[str]) -> bool:
    """檢查新聞標題是否與股票相關（含任一關鍵詞）。"""
    hl_lower = headline.lower()
    for kw in keywords:
        if kw in hl_lower:
            return True
    return False


def get_recent_news(symbol: str, count: int = 5) -> List[str]:
    """
    使用 yfinance 獲取指定股票最近相關新聞標題。
    會過濾掉與該股票無關的新聞，直到找到 count 則相關新聞為止。

    Args:
        symbol: 股票代號，例如 "0700.HK", "AAPL", "NVDA"
        count: 目標新聞則數（預設 10）

    Returns:
        list[str]: 相關新聞標題列表
    """
    try:
        ticker = yf.Ticker(symbol)
        keywords = _extract_keywords(symbol, ticker)
        news = ticker.news

        # 合併兩個新聞來源
        all_items: List[Dict[str, Any]] = []

        if isinstance(news, list):
            all_items.extend(news)

        # 嘗試用 yf.Search 獲取更多新聞
        try:
            search_results = yf.Search(symbol).news
            if isinstance(search_results, list):
                all_items.extend(search_results)
        except Exception:
            pass

        if not all_items:
            print(f"[news_fetcher] {symbol} 沒有 yfinance 新聞資料")
            return []

        # 只取與股票相關的新聞（上限 count 則），去重
        relevant: List[str] = []
        seen: Set[str] = set()

        for item in all_items:
            title = item.get("title") or item.get("content", {}).get("title", "")
            title = str(title).strip()
            if not title or title.lower() in seen:
                continue

            if _is_relevant(title, keywords):
                seen.add(title.lower())
                relevant.append(title)
                if len(relevant) >= count:
                    break

        if not relevant:
            print(f"[news_fetcher] {symbol} 沒有相關新聞")

        print(f"[news_fetcher] {symbol}: 總新聞 {len(all_items)}則，相關 {len(relevant)}則 (關鍵詞: {', '.join(sorted(keywords))})")

        return relevant

    except Exception as e:
        print(f"[news_fetcher] yfinance 新聞獲取失敗 ({symbol}): {e}")
        return []