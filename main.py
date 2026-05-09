"""
main.py - StockAI 入口：啟動 Telegram Bot + Web Dashboard
"""
import os
import sys
import threading
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "5000"))

if not TELEGRAM_BOT_TOKEN:
    print("❌ 錯誤：未設定 TELEGRAM_BOT_TOKEN，請檢查 .env 檔案")
    sys.exit(1)

if not LLM_API_KEY:
    print("⚠️  警告：未設定 LLM_API_KEY，情緒分析與自然語言解析將使用簡易規則")

sys.path.insert(0, os.path.dirname(__file__))

from stock_bot.bot import run_bot
from web_app import run_web


if __name__ == "__main__":
    print("=" * 50)
    print("🤖 StockAI - Telegram 股票分析 Chatbot")
    print("=" * 50)
    print(f"   LLM Provider: {os.getenv('LLM_PROVIDER', 'deepseek')}")
    print(f"   Model: {os.getenv('LLM_MODEL', 'deepseek-chat')}")
    print(f"   Web Dashboard: http://{WEB_HOST}:{WEB_PORT}")
    print("=" * 50)

    # Flask 在獨立執行緒中執行
    web_thread = threading.Thread(
        target=run_web,
        args=(WEB_HOST, WEB_PORT),
        daemon=True,
    )
    web_thread.start()

    # Bot 在主執行緒中執行（asyncio event loop）
    run_bot(TELEGRAM_BOT_TOKEN)