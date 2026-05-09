"""
main.py - StockAI Telegram Bot 入口
載入環境變數並啟動 Bot
"""
import os
import sys
from dotenv import load_dotenv

# 載入 .env
load_dotenv()

# 檢查必要環境變數
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

if not TELEGRAM_BOT_TOKEN:
    print("❌ 錯誤：未設定 TELEGRAM_BOT_TOKEN，請檢查 .env 檔案")
    sys.exit(1)

if not LLM_API_KEY:
    print("⚠️  警告：未設定 LLM_API_KEY，情緒分析與自然語言解析將使用簡易規則")

if not FINNHUB_API_KEY:
    print("⚠️  警告：未設定 FINNHUB_API_KEY，將無法獲取新聞數據")

# 將 stock_bot 目錄加入路徑
sys.path.insert(0, os.path.dirname(__file__))

from stock_bot.bot import run_bot

if __name__ == "__main__":
    print("=" * 50)
    print("🤖 StockAI - Telegram 股票分析 Chatbot")
    print("=" * 50)
    print(f"   LLM Provider: {os.getenv('LLM_PROVIDER', 'deepseek')}")
    print(f"   Model: {os.getenv('LLM_MODEL', 'deepseek-chat')}")
    print("=" * 50)
    run_bot(TELEGRAM_BOT_TOKEN)