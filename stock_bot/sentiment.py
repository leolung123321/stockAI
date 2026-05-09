"""
sentiment.py - 使用 DeepSeek LLM 進行逐則新聞情緒分析與自然語言股票代號解析
"""
import os
import json
from typing import List, Optional, Dict, Any

from openai import OpenAI

# ---- DeepSeek 設定 ----
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """延遲初始化 OpenAI 客戶端（確保 .env 已載入）。"""
    global _client
    if _client is None:
        api_key = os.getenv("LLM_API_KEY", "")
        _client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
        )
    return _client


def analyze_sentiment(headlines: List[str], symbol: str = "") -> Optional[Dict[str, Any]]:
    """
    使用 DeepSeek 對新聞標題進行逐則情緒評分 (0-10)。

    Returns:
        dict: {
            "score": int,
            "label": str,
            "per_headline": [{headline, sentiment, reason}],
            "overall_reason": str,
        }
    """
    if not headlines:
        return None

    if not os.getenv("LLM_API_KEY"):
        return _detailed_simple_sentiment(headlines)

    joined_headlines = "\n".join([f"{i+1}. {h}" for i, h in enumerate(headlines)])

    prompt = f"""你是一個金融情緒分析專家。請對以下 {len(headlines)} 則關於股票 {symbol} 的新聞標題進行逐則分析，並以 JSON 格式回覆。

新聞標題：
{joined_headlines}

對每則標題，判斷其為「利好」、「利淡」或「中性」，並提供一句簡短理由。

最後給出 0-10 的整體情緒評分與一段綜合分析（50-100字）。

請回覆一個 JSON 物件（只回 JSON，不要其他文字）：
{{
    "score": <整數0-10>,
    "label": "<情緒描述: 極其負面/相當負面/輕微負面/中性/輕微正面/相當正面/極其正面>",
    "per_headline": [
        {{"headline": "<標題>", "sentiment": "<利好|利淡|中性>", "reason": "<理由>"}},
        ...
    ],
    "overall_reason": "<綜合分析，說明整體情緒傾向及原因>"
}}
"""
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是一個專業的金融情緒分析助手，始終以 JSON 格式回覆。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=800,
        )

        content = response.choices[0].message.content.strip()

        # 嘗試解析 JSON（可能有 markdown code block 包裝）
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        result = json.loads(content)
        score = int(result.get("score", 5))
        score = max(0, min(10, score))
        label = result.get("label", _score_to_label(score))
        per_headline = result.get("per_headline", [])
        overall_reason = result.get("overall_reason", "")

        return {
            "score": score,
            "label": label,
            "per_headline": per_headline,
            "overall_reason": overall_reason,
        }

    except Exception as e:
        print(f"[sentiment] DeepSeek 情緒分析失敗: {e}")
        return _detailed_simple_sentiment(headlines)


def _detailed_simple_sentiment(headlines: List[str]) -> Dict[str, Any]:
    """增強版簡易情緒規則（含逐則分析）。"""
    positive_words = ["漲", "升", "利好", "突破", "回購", "增長", "盈喜", "buy", "up", "bull", "gain", "positive", "rise", "upgrade", "surge", "rally", "outperform"]
    negative_words = ["跌", "降", "利淡", "下跌", "風險", "虧損", "盈警", "sell", "down", "bear", "loss", "negative", "fall", "downgrade", "drop", "plunge", "weak", "slow"]

    pos_count = 0
    neg_count = 0
    per_headline = []

    for h in headlines:
        h_lower = h.lower()
        p = sum(1 for w in positive_words if w.lower() in h_lower)
        n = sum(1 for w in negative_words if w.lower() in h_lower)

        if p > n:
            sentiment = "利好"
            pos_count += 1
            reason = f"標題含正面關鍵詞，如" + "、".join([w for w in positive_words if w.lower() in h_lower][:2])
        elif n > p:
            sentiment = "利淡"
            neg_count += 1
            reason = f"標題含負面關鍵詞，如" + "、".join([w for w in negative_words if w.lower() in h_lower][:2])
        else:
            sentiment = "中性"
            reason = "標題語氣中性，無明顯利好或利淡傾向"

        per_headline.append({
            "headline": h,
            "sentiment": sentiment,
            "reason": reason,
        })

    total = len(headlines)
    if pos_count > neg_count:
        score = min(10, 5 + round((pos_count / total) * 5))
    elif neg_count > pos_count:
        score = max(0, 5 - round((neg_count / total) * 5))
    else:
        score = 5

    label = _score_to_label(score)
    overall_reason = (
        f"{total}則新聞中，{pos_count}則利好、{neg_count}則利淡。"
        f"整體市場情緒{label}。"
        + ("利好因素主導。" if pos_count > neg_count else ("利淡因素較多。" if neg_count > pos_count else "多空訊息均衡。"))
    )

    return {
        "score": score,
        "label": label,
        "per_headline": per_headline,
        "overall_reason": overall_reason,
    }


def _score_to_label(score: int) -> str:
    if score <= 1:
        return "極其負面"
    elif score <= 3:
        return "相當負面"
    elif score <= 4:
        return "輕微負面"
    elif score == 5:
        return "中性"
    elif score <= 6:
        return "輕微正面"
    elif score <= 8:
        return "相當正面"
    else:
        return "極其正面"


def parse_stock_symbol(user_message: str) -> Optional[str]:
    """
    使用 DeepSeek 從自然語言訊息中解析股票代號。
    支援全球股票格式（美股、港股、台股等）。
    """
    if not os.getenv("LLM_API_KEY"):
        return _simple_symbol_parse(user_message)

    prompt = f"""你是一個股票代號解析助手。請從以下使用者訊息中，提取股票代號。

使用者訊息："{user_message}"

常見代號格式：
- 港股：0700.HK (=騰訊), 9988.HK (=阿里巴巴), 0005.HK (=匯豐)
- 美股：AAPL, MSFT, GOOGL, TSLA, NVDA, AMZN, META
- 台股：2330.TW (=台積電), 0050.TW
- 日股：7203.T (=Toyota)

若使用者用中文名稱提及（如「騰訊」、「蘋果」、「台積電」），請轉換為對應代號。
若無法確定是哪支股票，回覆 "UNKNOWN"。
請只回覆代號（如 "0700.HK"、"AAPL"）或 "UNKNOWN"，不要回其他文字。"""

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是一個股票代號解析助手，只回覆代號字串。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=30,
        )

        content = response.choices[0].message.content.strip()
        content = content.strip('"').strip("'").strip()

        if content.upper() == "UNKNOWN" or len(content) > 20:
            return None

        return content

    except Exception as e:
        print(f"[sentiment] 自然語言解析失敗: {e}")
        return _simple_symbol_parse(user_message)


def _simple_symbol_parse(message: str) -> Optional[str]:
    """簡易股票代號解析（無 LLM 時的 fallback）。"""
    import re

    pattern = r'\b([A-Z]{1,5}(?:\.[A-Z]{2,3})?|\d{4}\.[A-Z]{2,3})\b'
    matches = re.findall(pattern, message.upper())
    if matches:
        return matches[0]

    name_map = {
        "騰訊": "0700.HK",
        "阿里巴巴": "9988.HK", "阿里": "9988.HK",
        "美團": "3690.HK",
        "小米": "1810.HK",
        "快手": "1024.HK",
        "京東": "9618.HK",
        "網易": "9999.HK",
        "百度": "9888.HK",
        "比亞迪": "1211.HK",
        "匯豐": "0005.HK",
        "中移動": "0941.HK",
        "平安": "2318.HK",
        "友邦": "1299.HK",
        "港交所": "0388.HK",
        "中芯": "0981.HK", "中芯國際": "0981.HK",
        "蘋果": "AAPL",
        "微軟": "MSFT",
        "谷歌": "GOOGL",
        "特斯拉": "TSLA",
        "輝達": "NVDA", "英偉達": "NVDA",
        "亞馬遜": "AMZN",
        "台積電": "2330.TW",
        "台指": "0050.TW",
    }
    for name, code in name_map.items():
        if name in message:
            return code

    return None