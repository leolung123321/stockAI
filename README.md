# StockAI — Telegram 股票分析 Chatbot

以 Telegram Bot 接收查詢，**富途 OpenD 即時行情優先**，yfinance 備援（延遲約 15-20 分鐘）。
取股價、布林帶、多層級支撐阻力位、TD Sequential（神奇九轉），DeepSeek 作情緒分析。
附 Web Dashboard 查閱歷史記錄。可打包為單一 .exe 於 Windows 執行。

## 架構

```
main.py          → 入口，啟 Bot 線程 + Flask Web 線程 + 富途 OpenD 連線
stock_bot/
  bot.py         → Telegram Handler（指令 / 自然語言）
  stock_data.py  → 數據源：富途優先 → yfinance fallback
  futu_client.py → 富途 OpenD 封裝（即時報價、K 線、符號映射）
  news_fetcher.py→ yfinance 新聞（過濾不相關者）
  sentiment.py   → DeepSeek 情緒分析（逐則）+ 代號解析
  formatter.py   → 藍本風格輸出
  db.py          → SQLite 記錄層
web_app.py       → Flask Web Dashboard（內嵌 HTML）
```

## 環境需求

- Python 3.10+
- Windows / macOS / Linux
- （可選）富途 OpenD — 需先啟動，否則自動降級為 yfinance

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
FUTU_HOST=127.0.0.1              # 富途 OpenD 主機（可選）
FUTU_PORT=11111                  # 富途 OpenD 埠號（可選）
```

## 啟動富途 OpenD（可選，但建議）

若要使用即時行情，需先啟動富途 OpenD：

1. 從富途官網下載 OpenD
2. 執行 OpenD（預設監聽 127.0.0.1:11111）
3. 確認 `.env` 中 `FUTU_HOST` / `FUTU_PORT` 正確

若 OpenD 未啟動或連線失敗，程式會自動切換至 yfinance 備援。

## 啟動

```bash
python main.py
```

啟動後：
- Telegram Bot 開始 Polling
- 瀏覽器自動開啟 `http://127.0.0.1:5000` 顯示 Dashboard
- 主控台顯示富途連線狀態

## Telegram 使用

| 方式 | 示例 |
|------|------|
| 自然語言 | `幫我睇下騰訊` `蘋果點？` |
| 代號直輸 | `0700.HK` `AAPL` `NVDA` |
| 指令 | `/analyze 0700.HK` |
| 說明 | `/help` |

支援格式：港股 `0700.HK`、美股 `AAPL`、台股 `2330.TW`、日股 `7203.T`

> 若使用富途數據，回覆第一行會顯示「📡 數據來自富途即時行情」

## Web Dashboard

- 深色主題，暗色 UI
- 顯示所有 Telegram 查詢記錄（時間、用戶、股票、結果）
- 支援關鍵字搜尋
- 每 30 秒自動刷新
- 點 「📋 展開」 查看完整分析結果

## 打包為 .exe（Windows）

```bash
pip install pyinstaller

# 使用 .spec 檔案（自動處理富途 VERSION.txt 等非 Python 資源）
pyinstaller StockAI.spec
```

產出：`dist/StockAI.exe`

將 `.env` 置於 `StockAI.exe` 同目錄，雙擊執行即可。

## 依賴

| 套件 | 用途 |
|------|------|
| futu-api | 富途 OpenD 即時行情（優先數據源） |
| yfinance | 股價、布林帶、新聞（備援數據源） |
| python-telegram-bot | Telegram Bot |
| openai | DeepSeek API（情緒分析 + NLP） |
| flask | Web Dashboard |
| numpy | 布林帶計算 |
| python-dotenv | .env 載入 |

## 授權

MIT