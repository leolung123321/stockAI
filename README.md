# StockAI — Telegram 股票分析 Chatbot

以 Telegram Bot 接收查詢，調用 yfinance 取股價、布林帶、新聞，DeepSeek 作情緒分析，
輸出多層級支撐阻力位。附 Web Dashboard 查閱歷史記錄。可打為單一 .exe 於 Windows 執行。

## 架構

```
main.py          → 入口，啟 Bot 線程 + Flask Web 線程
stock_bot/
  bot.py         → Telegram Handler（指令 / 自然語言）
  stock_data.py  → yfinance 股價 + 布林帶 + 多層級支撐阻力
  news_fetcher.py→ yfinance 新聞（過濾不相關者）
  sentiment.py   → DeepSeek 情緒分析（逐則）+ 代號解析
  formatter.py   → 藍本風格輸出
  db.py          → SQLite 記錄層
web_app.py       → Flask Web Dashboard（內嵌 HTML）
```

## 環境需求

- Python 3.10+
- Windows / macOS / Linux

## 安裝

```bash
# 1) 複製專案
git clone git@github.com:leolung123321/stockAI.git
cd stockAI

# 2) 安裝依賴
pip install -r requirements.txt

# 3) 設定 .env（API Keys）
cp .env.example .env
# 編輯 .env，填入 LLM_API_KEY、TELEGRAM_BOT_TOKEN
```

## .env 設定

```env
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-xxxxxxxx          # DeepSeek API Key
LLM_MODEL=deepseek-chat
TELEGRAM_BOT_TOKEN=xxxxxxxxxx    # @BotFather 取得
WEB_HOST=127.0.0.1               # Web 介面主機（可選）
WEB_PORT=5000                    # Web 介面埠號（可選）
```

## 啟動

```bash
python main.py
```

啟動後：
- Telegram Bot 開始 Polling
- 瀏覽器自動開啟 `http://127.0.0.1:5000` 顯示 Dashboard

## Telegram 使用

| 方式 | 示例 |
|------|------|
| 自然語言 | `幫我睇下騰訊` `蘋果點？` |
| 代號直輸 | `0700.HK` `AAPL` `NVDA` |
| 指令 | `/analyze 0700.HK` |
| 說明 | `/help` |

支援格式：港股 `0700.HK`、美股 `AAPL`、台股 `2330.TW`、日股 `7203.T`

## Web Dashboard

- 深色主題，暗色 UI
- 顯示所有 Telegram 查詢記錄（時間、用戶、股票、結果）
- 支援關鍵字搜尋
- 每 30 秒自動刷新
- 點 「📋 展開」 查看完整分析結果

## 打包為 .exe（Windows）

```bash
pip install pyinstaller

pyinstaller --onefile --name StockAI `
  --hidden-import flask `
  --hidden-import yfinance `
  --hidden-import openai `
  --hidden-import telegram `
  --hidden-import telegram.ext `
  --hidden-import numpy `
  --hidden-import requests `
  --hidden-import dotenv `
  --hidden-import stock_bot.db `
  --hidden-import stock_bot.stock_data `
  --hidden-import stock_bot.news_fetcher `
  --hidden-import stock_bot.sentiment `
  --hidden-import stock_bot.formatter `
  --hidden-import stock_bot.bot `
  --hidden-import web_app `
  main.py
```

產出：`dist/StockAI.exe` (~48MB)

將 `.env` 置於 `StockAI.exe` 同目錄，雙擊執行即可。

## 依賴

| 套件 | 用途 |
|------|------|
| yfinance | 股價、布林帶、新聞 |
| python-telegram-bot | Telegram Bot |
| openai | DeepSeek API（情緒分析 + NLP） |
| flask | Web Dashboard |
| numpy | 布林帶計算 |
| python-dotenv | .env 載入 |

## 授權

MIT