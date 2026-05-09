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
from .sentiment import analyze_sentiment, parse_stock_symbol
from .formatter import format_analysis, format_error, format_processing

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


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


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 /analyze <symbol> 指令。"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text(
            "請提供股票代號。\n例：/analyze 0700.HK"
        )
        return

    symbol = context.args[0].strip().upper()
    logger.info(f"[/analyze] user={user_id}, symbol={symbol}")

    # 傳送處理中訊息
    processing_msg = await update.message.reply_text(format_processing(symbol))

    # 執行分析
    result = await run_analysis(symbol)

    # 編輯原訊息為最終結果
    await processing_msg.edit_text(result)


async def natural_language_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理自然語言訊息（非指令）。"""
    user_id = update.effective_user.id
    message_text = update.message.text.strip()

    if not message_text:
        return

    logger.info(f"[NL] user={user_id}, message='{message_text[:50]}...'")

    # 傳送處理中訊息
    processing_msg = await update.message.reply_text("🔍 正在解析你的查詢...")

    # Step 1: 先用簡易規則快速匹配
    symbol = parse_stock_symbol_fast(message_text)

    if symbol is None:
        # Step 2: 使用 LLM 解析
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

    # 更新處理中訊息
    await processing_msg.edit_text(format_processing(symbol))

    # 執行分析
    result = await run_analysis(symbol)

    # 編輯為最終結果
    await processing_msg.edit_text(result)


def parse_stock_symbol_fast(message: str) -> Optional[str]:
    """快速解析：先用正則匹配已知格式，再用中文名稱映射（免 LLM 延遲）。"""
    import re

    msg_upper = message.upper()

    # 匹配股票代號格式
    pattern = r'\b([A-Z]{1,5}(?:\.[A-Z]{2,3})?|\d{4}\.[A-Z]{2,3})\b'
    matches = re.findall(pattern, msg_upper)
    if matches:
        return matches[0]

    # 中文名稱映射
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
        "中芯國際": "0981.HK", "中芯": "0981.HK",
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


# ────────────────────────── 分析核心 ──────────────────────────

async def run_analysis(symbol: str) -> str:
    """
    協調各模組執行完整股票分析（非阻塞）。

    Args:
        symbol: 股票代號

    Returns:
        str: 格式化後的結果字串
    """
    # 並行獲取股價數據與新聞
    stock_task = asyncio.to_thread(get_stock_data, symbol)
    news_task = asyncio.to_thread(get_recent_news, symbol)

    stock_data, headlines = await asyncio.gather(stock_task, news_task)

    # 檢查股價數據
    if stock_data is None:
        return format_error(symbol, "無法獲取股價數據，請確認代號是否正確")

    # 情緒分析
    sentiment = None
    if headlines:
        sentiment = await asyncio.to_thread(analyze_sentiment, headlines, symbol)

    # 格式化輸出
    return format_analysis(stock_data, sentiment)


# ────────────────────────── Bot 啟動 ──────────────────────────

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

    # 註冊自然語言處理器（非指令訊息）
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, natural_language_handler)
    )

    logger.info("🤖 StockAI Bot 啟動中...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)