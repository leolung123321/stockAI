"""
bot.py - Telegram Bot Handler：接收訊息、協調分析模組、回傳結果
"""
import asyncio
import logging
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from .stock_data import get_stock_data
from .news_fetcher import get_recent_news
from .sentiment import analyze_sentiment, parse_stock_symbol, _get_client
from .formatter import format_analysis, format_error, format_processing
from .screener import run_screen, _parse_date_from_message, _get_kline_for_date, _is_big_bullish
from .screener_formatter import format_screener_report
from .web_search import search_tavily
from .db import insert_log, init_db
import yfinance as yf

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── 指數代號映射 ──
INDEX_MAP = {
    "恆生指數": "^HSI", "恆指": "^HSI", "恒生指數": "^HSI", "恒指": "^HSI",
    "道瓊": "^DJI", "道指": "^DJI", "道瓊斯": "^DJI",
    "納指": "^IXIC", "納斯達克": "^IXIC",
    "標普": "^GSPC", "標普500": "^GSPC", "S&P": "^GSPC",
    "日經": "^N225", "日經指數": "^N225",
    "台股加權": "^TWII", "加權指數": "^TWII", "台指加權": "^TWII",
    "上證": "^SSEC", "上證指數": "^SSEC",
    "深證": "^SZSC", "深證指數": "^SZSC",
}


# ────────────────────────── 指令處理器 ──────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 /start 指令。"""
    await update.message.reply_text(
        "👋 歡迎使用 StockAI 股票分析 Bot！\n\n"
        "你可以直接輸入股票代號或自然語言查詢，例如：\n"
        "• 0700.HK\n"
        "• AAPL\n"
        "• 幫我睇下騰訊\n"
        "• 蘋果股票怎麼了？\n\n"
        "也可以使用 /analyze 指令：\n"
        "• /analyze 0700.HK\n\n"
        "支援全球股票（港股、美股、台股、日股等）"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 /help 指令。"""
    await update.message.reply_text(
        "📖 StockAI 使用說明\n\n"
        "🔹 直接輸入查詢：\n"
        "   輸入股票代號或自然語言描述即可分析。\n\n"
        "🔹 /analyze <股票代號>：\n"
        "   精確分析指定股票。\n"
        "   例：/analyze 0700.HK\n\n"
        "支援格式：\n"
        "• 港股：0700.HK, 9988.HK\n"
        "• 美股：AAPL, MSFT, TSLA\n"
        "• 台股：2330.TW, 0050.TW\n"
        "• 日股：7203.T\n\n"
        "分析內容包含：現價、升跌、布林帶買賣位、市場情緒評分。"
    )


async def screener_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 /screener [date] 指令。"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""

    target_date = None
    if context.args:
        raw = " ".join(context.args)
        target_date = _parse_date_from_message(raw)
        if target_date is None:
            # 嘗試當作日期字串直接使用
            target_date = raw.strip()

    processing_msg = await update.message.reply_text("🔍 正在掃描龍頭股異動，請稍候...")

    try:
        result = await asyncio.to_thread(run_screen, target_date)
        formatted = format_screener_report(result)
        await processing_msg.edit_text(formatted)

        # 寫入 DB
        try:
            await asyncio.to_thread(
                insert_log, user_id, username,
                "screener",
                f"/screener {target_date or 'today'}",
                formatted,
                query_type="screener",
            )
        except Exception as e:
            logger.warning(f"[DB] screener 寫入失敗: {e}")
    except Exception as e:
        logger.error(f"[screener] 執行失敗: {e}")
        await processing_msg.edit_text(f"❌ 掃描失敗：{e}")


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 /analyze <symbol> 指令。"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""

    if not context.args:
        await update.message.reply_text(
            "請提供股票代號。\n例：/analyze 0700.HK"
        )
        return

    symbol = context.args[0].strip().upper()
    raw_query = f"/analyze {symbol}"
    logger.info(f"[/analyze] user={user_id}, symbol={symbol}")

    processing_msg = await update.message.reply_text(format_processing(symbol))
    result = await run_analysis(symbol, user_id, username, raw_query)
    await processing_msg.edit_text(result)


async def natural_language_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理自然語言訊息（非指令）。"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    message_text = update.message.text.strip()

    if not message_text:
        return

    logger.info(f"[NL] user={user_id}, message='{message_text[:50]}...'")

    # 傳送處理中訊息
    processing_msg = await update.message.reply_text("🔍 正在解析你的查詢...")

    # ── 偵測「龍頭股」關鍵字 → 觸發篩選（僅當無額外技術條件時）──
    if "龍頭" in message_text or "龍頭股" in message_text:
        # 若包含技術條件關鍵字，不走 screener，改走意圖分類
        tech_keywords = ["九轉", "神奇九轉", "TD", "連升", "連跌", "大陽竹", "大陽燭", "大陰竹", "大陰燭", "RSI", "MACD", "超買", "超賣", "支持位", "阻力位"]
        has_tech = any(kw in message_text for kw in tech_keywords)

        if not has_tech:
            target_date = _parse_date_from_message(message_text)

            # 解析市場關鍵字
            market = None
            msg_lower = message_text.lower()
            if "港" in msg_lower or "香港" in msg_lower:
                market = "HK"
            elif "美" in msg_lower or "美國" in msg_lower:
                market = "US"
            elif "台" in msg_lower or "台灣" in msg_lower or "臺灣" in msg_lower:
                market = "TW"

            market_label = {"HK": "港股", "US": "美股", "TW": "台股"}.get(market, "全部市場")
            await processing_msg.edit_text(f"🔍 正在掃描{market_label}龍頭股異動，請稍候...")
            try:
                result = await asyncio.to_thread(run_screen, target_date, market)
                formatted = format_screener_report(result)
                await processing_msg.edit_text(formatted)
                try:
                    await asyncio.to_thread(
                        insert_log, user_id, username,
                        "screener",
                        message_text,
                        formatted,
                        query_type="screener",
                    )
                except Exception as e:
                    logger.warning(f"[DB] screener 寫入失敗: {e}")
            except Exception as e:
                logger.error(f"[screener] 執行失敗: {e}")
                await processing_msg.edit_text(f"❌ 掃描失敗：{e}")
            return
        # 有技術條件 → 繼續往下走意圖分類

    # Step 1: 先用簡易規則快速匹配
    symbol = parse_stock_symbol_fast(message_text)

    # Step 2: 若匹配到代號 → 直接分析
    if symbol is not None:
        logger.info(f"[NL] 解析結果: symbol={symbol}")
        await processing_msg.edit_text(format_processing(symbol))
        result = await run_analysis(symbol, user_id, username, message_text)
        await processing_msg.edit_text(result)
        return

    # Step 3: 無代號 → LLM 分類意圖
    await processing_msg.edit_text("🤖 正在分析你的問題，請稍候...")
    intent = await asyncio.to_thread(_classify_intent, message_text)

    if intent is None:
        # LLM 分類失敗，fallback 到股票代號解析
        await processing_msg.edit_text("🤖 正在用 AI 解析股票代號，請稍候...")
        symbol = await asyncio.to_thread(parse_stock_symbol, message_text)
        if symbol is None:
            await processing_msg.edit_text(
                "❓ 抱歉，我無法從你的訊息中辨識出股票代號。\n\n"
                "請直接輸入股票代號，例如：\n"
                "• 0700.HK（騰訊）\n"
                "• AAPL（蘋果）\n"
                "• 2330.TW（台積電）\n\n"
                "或使用 /analyze <代號> 指令。"
            )
            return
        logger.info(f"[NL] 解析結果: symbol={symbol}")
        await processing_msg.edit_text(format_processing(symbol))
        result = await run_analysis(symbol, user_id, username, message_text)
        await processing_msg.edit_text(result)
        return

    # 根據意圖分流
    if intent["type"] == "analysis":
        symbol = intent.get("symbol", "")
        if not symbol:
            result = "❌ 無法識別股票代號。"
        else:
            await processing_msg.edit_text(format_processing(symbol))
            result = await run_analysis(symbol, user_id, username, message_text)
    elif intent["type"] == "index":
        result = await _handle_index_query(intent)
    elif intent["type"] == "candle":
        await processing_msg.edit_text(f"🔍 正在檢視 {intent.get('name', intent['symbol'])} 的K線走勢...")
        result = await _handle_candle_query(intent)
    elif intent["type"] == "screener":
        await processing_msg.edit_text("🔍 正在掃描龍頭股並篩選技術條件...")
        result = await _handle_screener_query(intent)
    elif intent["type"] == "general":
        await processing_msg.edit_text("🌐 正在搜索相關資訊，請稍候...")
        result = await _handle_general_question(intent, message_text)
    else:
        result = "❓ 抱歉，無法理解你的查詢。"

    await processing_msg.edit_text(result)

    # 寫入 DB log
    try:
        await asyncio.to_thread(
            insert_log, user_id, username,
            intent.get("type", "unknown"),
            message_text,
            result[:500],
        )
    except Exception as e:
        logger.warning(f"[DB] 寫入記錄失敗: {e}")


def parse_stock_symbol_fast(message: str) -> Optional[str]:
    """快速解析：只用正則匹配已知代號格式，不做中文名映射（交給 LLM 意圖分類處理）。"""
    import re

    msg_upper = message.upper()

    # 匹配股票代號格式：美股字母 / 港股台股數字+後綴
    pattern = r'\b([A-Z]{1,5}(?:\.[A-Z]{2,3})?|\d{4}\.[A-Z]{2,3})\b'
    matches = re.findall(pattern, msg_upper)
    if matches:
        return matches[0]

    return None


# ────────────────────────── 分析核心 ──────────────────────────

async def run_analysis(
    symbol: str,
    user_id: int = 0,
    username: str = "",
    raw_query: str = "",
) -> str:
    """
    協調各模組執行完整股票分析（非阻塞）。

    Args:
        symbol: 股票代號

    Returns:
        str: 格式化後的結果字串
    """
    # 並行獲取股價數據與新聞
    stock_task = asyncio.to_thread(get_stock_data, symbol)
    news_task = asyncio.to_thread(get_recent_news, symbol, 10)

    stock_data, headlines = await asyncio.gather(stock_task, news_task)

    # 檢查股價數據，失敗時嘗試建議修正代號
    if stock_data is None:
        suggestion = _try_suggest_symbol(symbol)
        if suggestion:
            return format_error(symbol, f"無法獲取股價數據，你想查的是 {suggestion} 嗎？")
        return format_error(symbol, "無法獲取股價數據，請確認代號是否正確")

    # 情緒分析
    sentiment = None
    if headlines:
        sentiment = await asyncio.to_thread(analyze_sentiment, headlines, symbol)

    result = format_analysis(stock_data, sentiment)

    # 寫入 SQLite 記錄
    try:
        await asyncio.to_thread(insert_log, user_id, username, symbol, raw_query, result)
    except Exception as e:
        logger.warning(f"[DB] 寫入記錄失敗: {e}")

    return result


# ────────────────────────── 意圖分類與通用查詢處理 ──────────────────────────

def _classify_intent(message: str) -> Optional[dict]:
    """
    使用 LLM 分類用戶查詢意圖。

    Returns:
        dict with keys:
          {"type": "analysis", "symbol": "0700.HK", "name": "騰訊"}
          {"type": "index", "symbol": "^HSI", "name": "恆生指數"}
          {"type": "candle", "symbol": "0700.HK", "name": "騰訊"}
          {"type": "general", "query": "..."}
        None 若分類失敗
    """
    import os, json
    api_key = os.getenv("LLM_API_KEY", "")
    if not api_key:
        return {"type": "general", "query": message}

    # 先試 INDEX_MAP 快速匹配
    for idx_name, yf_symbol in INDEX_MAP.items():
        if idx_name in message:
            return {"type": "index", "symbol": yf_symbol, "name": idx_name}

    prompt = f"""你是一個股票查詢意圖分類器。請分析以下用戶訊息，判斷屬於哪一類：

1. **analysis** — 查詢個股行情/技術分析（如「騰訊股價」、「蘋果股票怎麼了」、「TSLA睇下」、「幫我分析美團」）
2. **candle** — 查詢個股K線形態/大陽竹大陰竹（如「騰訊有無大陽竹」、「0700有無大陰竹」、「美團今日K線點樣」）
3. **index** — 查詢指數/大市行情（如恆生指數、道指、納指、上證等）
4. **screener** — 在龍頭股中按技術條件篩選（如「處於神奇九轉第九轉的港股龍頭股」、「連升5日的龍頭股」）
5. **general** — 其他一般財經問題（如「美國加息最新消息」、「今日金價」、「比特幣點睇」）

用戶訊息：「{message}」

請回覆 JSON（只回 JSON，不要其他文字）：
- 若是 analysis 類型：{{"type": "analysis", "symbol": "<股票代號>", "name": "<股票中文名>"}}
- 若是 candle 類型：{{"type": "candle", "symbol": "<股票代號>", "name": "<股票中文名>"}}
- 若是 index 類型：{{"type": "index", "symbol": "<yfinance指數代號>", "name": "<中文名稱>"}}
  常見指數：恆生指數→^HSI, 道瓊→^DJI, 納指→^IXIC, 標普→^GSPC, 日經→^N225, 上證→^SSEC, 台股加權→^TWII
- 若是 screener 類型：{{"type": "screener", "market": "<HK|US|TW|null>", "condition": "<技術條件描述>"}}
  例如「處於神奇九轉第九轉的港股龍頭股」→ {{"type": "screener", "market": "HK", "condition": "td_sequential:9"}}
- 若是 general 類型：{{"type": "general"}}

常見股票中英對照：
- 騰訊=0700.HK, 阿里巴巴=9988.HK, 美團=3690.HK, 小米=1810.HK, 比亞迪=1211.HK
- 蘋果=AAPL, 微軟=MSFT, 谷歌=GOOGL, 特斯拉=TSLA, 輝達=NVDA, 亞馬遜=AMZN, Meta=META
- 台積電=2330.TW, 聯發科=2454.TW
"""
    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            messages=[
                {"role": "system", "content": "你是一個股票查詢分類器，只回 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=100,
        )
        content = resp.choices[0].message.content.strip()
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        intent = json.loads(content)
        if intent.get("type") in ("analysis", "index", "candle", "screener", "general"):
            return intent
        return {"type": "general", "query": message}
    except Exception as e:
        print(f"[bot] 意圖分類失敗: {e}")
        return {"type": "general", "query": message}


async def _handle_index_query(intent: dict) -> str:
    """處理指數查詢。"""
    symbol = intent.get("symbol", "^HSI")
    name = intent.get("name", symbol)

    try:
        ticker = await asyncio.to_thread(lambda: yf.Ticker(symbol))
        hist = await asyncio.to_thread(lambda: ticker.history(period="5d"))
        info = await asyncio.to_thread(lambda: ticker.info or {})

        if hist is None or hist.empty:
            return f"❌ 無法獲取 {name} 的數據"

        latest = hist.iloc[-1]
        close = latest["Close"]
        prev_close = hist.iloc[-2]["Close"] if len(hist) >= 2 else close
        change = close - prev_close
        change_pct = (change / prev_close) * 100 if prev_close > 0 else 0
        high = latest["High"]
        low = latest["Low"]

        lines = [f"📊 **{name}**"]
        lines.append(f"   現價：{close:.2f}")
        if change >= 0:
            lines.append(f"   升跌：**+{change:.2f} (+{change_pct:.2f}%)** 📈")
        else:
            lines.append(f"   升跌：**{change:.2f} ({change_pct:.2f}%)** 📉")
        lines.append(f"   最高：{high:.2f} / 最低：{low:.2f}")
        lines.append(f"   前收市：{prev_close:.2f}")

        # 從 info 補充
        if info:
            name_cn = info.get("shortName") or info.get("longName") or name
            lines[0] = f"📊 **{name_cn}**"

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[index] {name} 查詢失敗: {e}")
        return f"❌ 查詢 {name} 失敗：{e}"


async def _handle_candle_query(intent: dict) -> str:
    """處理大陽竹/大陰竹查詢。"""
    symbol = intent.get("symbol", "")
    name = intent.get("name", symbol)

    if not symbol:
        return "❌ 無法識別股票代號"

    try:
        # 取近 20 個交易日的 K 線
        import pandas as pd
        from datetime import datetime, timedelta

        today = datetime.now().strftime("%Y-%m-%d")
        df_raw, atr, _ = await asyncio.to_thread(_get_kline_for_date, symbol, today, num=80)

        if df_raw is None or df_raw.empty:
            return f"❌ 無法獲取 {name} ({symbol}) 的 K 線數據"

        # 取倒數 20 根
        df = df_raw.tail(20).copy()
        if hasattr(df.index, "tz") and df.index.tz is not None:
            df.index = df.index.tz_convert(None)
        df.index = pd.to_datetime(df.index).normalize()

        lines = [f"🕯 **{name} ({symbol}) — 近 20 個交易日 K 線分析**"]
        lines.append("")

        bullish_count = 0
        bearish_count = 0
        details = []

        for idx in reversed(df.index):
            row = df.loc[idx]
            o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
            body = c - o
            upper_wick = h - max(o, c)
            lower_wick = min(o, c) - l
            change_pct = (c - o) / o * 100 if o > 0 else 0
            date_str = idx.strftime("%m/%d")

            # 判斷陰陽
            if body > 0:
                is_bullish = _is_big_bullish(o, c, atr)
                if is_bullish:
                    bullish_count += 1
                    details.append(f"   {date_str} **大陽竹** 🟢 +{change_pct:.1f}% (體${body:.2f})")
                else:
                    # 一般陽線
                    pass
            elif body < 0:
                body_abs = abs(body)
                # 大陰竹：實體 > ATR 或 跌幅 > 3%
                if atr and atr > 0 and body_abs > atr * 1.0:
                    bearish_count += 1
                    details.append(f"   {date_str} **大陰竹** 🔴 {change_pct:.1f}% (體${body_abs:.2f})")
                elif abs(change_pct) >= 3.0:
                    bearish_count += 1
                    details.append(f"   {date_str} **大陰竹** 🔴 {change_pct:.1f}%")

        lines.append(f"   ATR(14) = ${atr:.2f}" if atr else "")
        lines.append(f"   大陽竹出現：{bullish_count} 次")
        lines.append(f"   大陰竹出現：{bearish_count} 次")
        lines.append("")

        if details:
            lines.append("   **顯著K線**：")
            for d in details[:10]:
                lines.append(d)
        else:
            lines.append("   近 20 日無明顯大陽竹或大陰竹。")

        lines.append("")
        lines.append("⚠️ 大陽竹定義：實體 > ATR 或漲幅 >= 3%；大陰竹反之。")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[candle] {name} 查詢失敗: {e}")
        import traceback
        traceback.print_exc()
        return f"❌ 查詢 {name} K 線失敗：{e}"


def _calc_rsi(df, period: int = 14) -> Optional[float]:
    """計算 RSI(14)。"""
    if df is None or len(df) < period + 1:
        return None
    closes = df["Close"].dropna()
    if len(closes) < period + 1:
        return None
    delta = closes.diff().dropna()
    gains = delta.where(delta > 0, 0)
    losses = -delta.where(delta < 0, 0)
    avg_gain = gains.tail(period).mean()
    avg_loss = losses.tail(period).mean()
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


async def _handle_screener_query(intent: dict) -> str:
    """處理龍頭股+技術條件篩選。有指定條件時直接掃描所有 watchlist 股票。"""
    from datetime import datetime
    from .stock_data import _calc_td_sequential
    from .screener import _load_watchlist, _get_kline_for_date

    market = intent.get("market", None)
    condition = intent.get("condition", "")
    target_date = datetime.now().strftime("%Y-%m-%d")

    # ── 無條件 → 維持原始行為（跑 run_screen 中大陽線）──
    if not condition:
        result = await asyncio.to_thread(run_screen, target_date, market)
        hits = result.get("hits", [])
        total = result.get("total_scanned", 0)
        if not hits:
            return f"📊 **龍頭股異動掃描 — {target_date}**\n🔍 掃描範圍：{total} 檔 | 符合條件：0 檔\n\n❌ 今日無龍頭股出現中大陽線異動。"
        lines = [f"📊 **龍頭股異動掃描 — {target_date}**"]
        lines.append(f"🔍 掃描範圍：{total} 檔 | 符合條件：{len(hits)} 檔")
        for h in hits:
            lines.append(f"\n**{h['name']} ({h['symbol']})**")
            lines.append(f"   📈 漲幅：{h['change_pct']:+.2f}%")
        return "\n".join(lines)

    # ── 有技術條件 → 直接掃描所有 watchlist 股票 ──
    watchlist = _load_watchlist()
    if not watchlist:
        return f"📊 **龍頭股異動掃描 — {target_date}**【已篩選】\n❌ 無法載入 watchlist"

    if market:
        market_upper = market.upper()
        watchlist = {k: v for k, v in watchlist.items() if k == market_upper}
        if not watchlist:
            return f"📊 **龍頭股異動掃描 — {target_date}**【已篩選】\n🔍 掃描 0 檔\n\n❌ 未找到市場 {market_upper}"

    # 收集所有股票
    all_stocks = []
    for market_code, market_data in watchlist.items():
        for s in market_data.get("stocks", []):
            s["market"] = market_data.get("name", market_code)
            all_stocks.append(s)

    import re
    total = len(all_stocks)
    filtered = []
    errors = []
    cond_lower = condition.lower()

    for stock in all_stocks:
        symbol = stock["symbol"]
        name = stock.get("name", symbol)
        try:
            df_raw, atr, day_ohlc = await asyncio.to_thread(_get_kline_for_date, symbol, target_date, num=80)
            if df_raw is None or df_raw.empty:
                errors.append(name)
                continue

            entry = {"symbol": symbol, "name": name, "sector": stock.get("sector", ""), "market": stock.get("market", "")}
            matched = False

            # ── TD Sequential（神奇九轉）──
            if "td_sequential" in cond_lower or "九轉" in cond_lower:
                td = _calc_td_sequential(df_raw)
                if td:
                    target_count = 9
                    m = re.search(r'(?:td_sequential[:\s]*|第)(\d+)', condition)
                    if m:
                        target_count = int(m.group(1))
                    if td.get("count") == target_count:
                        entry["td"] = td
                        matched = True

            # ── 大陰竹 / 大陰燭（big bearish candle）──
            elif any(kw in cond_lower for kw in ["bearish", "大陰竹", "大陰燭"]):
                if day_ohlc and atr and atr > 0:
                    o, c = day_ohlc["open"], day_ohlc["close"]
                    body = o - c
                    if body > 0 and body > atr * 1.0:
                        entry["change_pct"] = round((c - o) / o * 100, 2)
                        matched = True

            # ── 超買（RSI >= 70）/ 超賣（RSI <= 30）──
            elif any(kw in cond_lower for kw in ["overbought", "oversold", "超買", "超賣"]):
                rsi = _calc_rsi(df_raw)
                if rsi is not None:
                    is_overbought = any(kw in cond_lower for kw in ["overbought", "超買"])
                    if is_overbought and rsi >= 70:
                        entry["rsi"] = round(rsi, 1)
                        matched = True
                    elif not is_overbought and rsi <= 30:
                        entry["rsi"] = round(rsi, 1)
                        matched = True

            # ── 連升 / 連跌 ──
            elif any(kw in cond_lower for kw in ["consecutive_up", "consecutive_down", "連升", "連跌"]):
                closes = df_raw["Close"].dropna()
                if len(closes) >= 5:
                    n = 3
                    m = re.search(r'(\d+)', condition)
                    if m:
                        n = int(m.group(1))
                    is_up = any(kw in cond_lower for kw in ["consecutive_up", "連升"])
                    count = 0
                    for i in range(1, min(n + 1, len(closes))):
                        if is_up and float(closes.iloc[-i]) > float(closes.iloc[-i - 1]):
                            count += 1
                        elif not is_up and float(closes.iloc[-i]) < float(closes.iloc[-i - 1]):
                            count += 1
                        else:
                            break
                    if count >= n:
                        matched = True

            if matched:
                filtered.append(entry)

        except Exception:
            errors.append(name)

    # ── 格式化結果 ──
    if not filtered:
        msg = f"📊 **龍頭股異動掃描 — {target_date}**【已篩選]\n🔍 掃描範圍：{total} 檔 | 符合條件：0 檔\n\n❌ 無龍頭股符合篩選條件。"
        if errors:
            msg += f"\n⚠️ {len(errors)} 檔數據獲取失敗"
        return msg

    lines = [f"📊 **龍頭股異動掃描 — {target_date}**【已篩選]"]
    lines.append(f"🔍 掃描範圍：{total} 檔 | 符合條件：{len(filtered)} 檔")
    lines.append("")
    for i, f in enumerate(filtered, 1):
        lines.append(f"**{i}. {f['name']} ({f['symbol']})** — [{f['market']}] {f['sector']}")
        td = f.get("td")
        if td:
            lines.append(f"   🔄 {td['label']}")
            lines.append(f"   💡 {td['signal']}")
        rsi = f.get("rsi")
        if rsi is not None:
            label = "超買" if rsi >= 70 else "超賣"
            lines.append(f"   📊 RSI(14) = {rsi}（{label}）")
        change_pct = f.get("change_pct")
        if change_pct is not None:
            lines.append(f"   📈 當日漲跌幅：{change_pct:+.2f}%")
        lines.append("")
    if errors:
        lines.append(f"⚠️ {len(errors)} 檔股票數據獲取失敗")
    return "\n".join(lines)


async def _handle_general_question(intent: dict, original_message: str) -> str:
    """處理一般問題：Tavily 搜索 + LLM 摘要。"""
    query = intent.get("query", original_message)

    # Tavily 搜索
    search_results = await asyncio.to_thread(search_tavily, query, 5)

    if not search_results:
        return "❌ 無法搜索到相關資訊，請稍後再試或換個問法。"

    # 用 LLM 摘要搜索結果
    import os, json

    api_key = os.getenv("LLM_API_KEY", "")
    if not api_key:
        # 無 LLM 時直接顯示搜尋結果
        lines = ["🌐 **搜索結果**", ""]
        for r in search_results[:3]:
            lines.append(f"🔹 {r['title']}")
            lines.append(f"   {r['content'][:100]}...")
            lines.append("")
        return "\n".join(lines)

    joined = "\n".join([f"{i+1}. {r['title']}\n   {r['content'][:300]}" for i, r in enumerate(search_results[:5])])

    prompt = f"""以下是用戶問題和網絡搜索結果，請用繁體中文回答。

用戶問題：{query}

搜索結果：
{joined}

請根據搜索結果，用繁體中文簡潔回答（100-200字）。如搜索結果不足以回答，請誠實說明。"""

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            messages=[
                {"role": "system", "content": "你是一個專業的財經助手，用繁體中文回答。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        answer = resp.choices[0].message.content.strip()

        # 附上來源
        sources = "\n".join([f"🔗 {r['url']}" for r in search_results[:3]])
        return f"🌐 **{answer}**\n\n{sources}"

    except Exception as e:
        print(f"[general] LLM 摘要失敗: {e}")
        lines = ["🌐 **搜索結果**", ""]
        for r in search_results[:3]:
            lines.append(f"🔹 {r['title']}")
            lines.append(f"   {r['content'][:150]}...")
            lines.append("")
        return "\n".join(lines)


# ────────────────────────── Bot 啟動 ──────────────────────────

def _try_suggest_symbol(symbol: str) -> Optional[str]:
    """當原始代號找不到時，嘗試補充常見後綴。"""
    import re

    # 已經有後綴的，不處理
    if "." in symbol:
        return None

    # 嘗試常見後綴
    candidates = []
    if symbol.isdigit() and len(symbol) <= 5:
        # 港股/台股/日股純數字 → 嘗試補 .HK / .TW / .T
        code_padded = symbol.zfill(4)
        candidates = [f"{code_padded}.HK", f"{code_padded}.TW", f"{code_padded}.T"]
    elif symbol.isalpha() and len(symbol) <= 5:
        candidates = [symbol]  # 美股不需後綴，原樣試一次
    else:
        candidates = [f"{symbol}.HK", f"{symbol}.TW", f"{symbol}.T", symbol]

    for candidate in candidates[:5]:
        try:
            ticker = yf.Ticker(candidate)
            info = ticker.info or {}
            fast = ticker.fast_info or {}

            # 多層 fallback 檢查是否有有效價格
            price = fast.get("last_price") or fast.get("regular_market_previous_close")
            if (price is None or (isinstance(price, float) and price <= 0)):
                price = info.get("previousClose") or info.get("regularMarketPreviousClose") or info.get("currentPrice")
            if price is not None and float(price) > 0:
                return candidate
        except Exception:
            continue

    return None


def run_bot(token: str) -> None:
    """
    啟動 Telegram Bot（Polling 模式）。

    Args:
        token: Telegram Bot Token
    """
    app = Application.builder().token(token).build()

    # 註冊指令處理器
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CommandHandler("screener", screener_command))

    # 註冊自然語言處理器（非指令訊息）
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, natural_language_handler)
    )

    # 初始化資料庫
    init_db()

    logger.info("🤖 StockAI Bot 啟動中...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
