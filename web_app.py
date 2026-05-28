"""
web_app.py - Flask Web 界面，顯示 Telegram Bot 查詢記錄 + Chat 功能
"""
import os
import asyncio
from flask import Flask, request, jsonify

from stock_bot.db import query_logs, get_log_count, init_db, insert_log
from stock_bot.screener import run_screen, _parse_date_from_message
from stock_bot.screener_formatter import format_screener_html, format_screener_report
from stock_bot.bot import run_analysis, parse_stock_symbol_fast, _classify_intent
from stock_bot.bot import _handle_index_query, _handle_candle_query, _handle_screener_query, _handle_general_question
from stock_bot.sentiment import parse_stock_symbol

app = Flask(__name__)

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StockAI - Web</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e1e4e8; min-height: 100vh; display: flex; flex-direction: column; }
.header { background: linear-gradient(135deg, #1a1d2e 0%, #16191e 100%); border-bottom: 1px solid #2a2e3a; padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
.header h1 { font-size: 22px; font-weight: 700; background: linear-gradient(90deg, #58a6ff, #bc8cff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.status { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #8b949e; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: #3fb950; box-shadow: 0 0 8px #3fb950; animation: pulse 2s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
.toolbar { padding: 12px 24px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; border-bottom: 1px solid #21262d; }
.toolbar input { background: #161b22; border: 1px solid #30363d; color: #c9d1d9; padding: 8px 14px; border-radius: 6px; font-size: 14px; width: 220px; outline: none; transition: border .2s; }
.toolbar input:focus { border-color: #58a6ff; }
.toolbar button { background: #238636; color: #fff; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 600; transition: background .2s; }
.toolbar button:hover { background: #2ea043; }
.toolbar .refresh { background: #21262d; color: #c9d1d9; }
.toolbar .refresh:hover { background: #30363d; }
.count { font-size: 13px; color: #8b949e; margin-left: auto; }
.table-wrapper { padding: 0 24px; overflow-x: auto; flex: 1; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 10px 12px; background: #161b22; border-bottom: 2px solid #30363d; color: #8b949e; font-weight: 600; position: sticky; top: 0; }
td { padding: 10px 12px; border-bottom: 1px solid #21262d; vertical-align: top; }
tr:hover td { background: #1a1d2e; }
.code-block { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 12px; font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px; white-space: pre-wrap; word-break: break-word; max-height: 300px; overflow-y: auto; line-height: 1.5; }
.expand-btn { background: none; border: 1px solid #30363d; color: #58a6ff; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; transition: all .2s; }
.expand-btn:hover { background: #1f2937; border-color: #58a6ff; }
.empty { text-align: center; padding: 60px 20px; color: #8b949e; font-size: 15px; }
.time { color: #6e7681; font-size: 12px; white-space: nowrap; }

/* ── Chat UI ── */
.chat-section { border-top: 1px solid #2a2e3a; background: #0d1117; }
.chat-toggle { display: flex; align-items: center; gap: 8px; padding: 10px 24px; cursor: pointer; color: #58a6ff; font-size: 14px; font-weight: 600; border: none; background: none; width: 100%; text-align: left; transition: background .2s; }
.chat-toggle:hover { background: #161b22; }
.chat-toggle .arrow { transition: transform .2s; }
.chat-toggle.open .arrow { transform: rotate(90deg); }
.chat-body { display: none; flex-direction: column; max-height: 500px; }
.chat-body.open { display: flex; }
.chat-messages { flex: 1; overflow-y: auto; padding: 12px 24px; min-height: 0; max-height: 380px; }
.chat-msg { margin-bottom: 12px; display: flex; flex-direction: column; }
.chat-msg.user { align-items: flex-end; }
.chat-msg.bot { align-items: flex-start; }
.chat-bubble { max-width: 85%; padding: 10px 14px; border-radius: 12px; font-size: 13px; line-height: 1.5; word-break: break-word; white-space: pre-wrap; }
.chat-msg.user .chat-bubble { background: #1f6feb; color: #fff; border-bottom-right-radius: 4px; }
.chat-msg.bot .chat-bubble { background: #21262d; color: #c9d1d9; border-bottom-left-radius: 4px; }
.chat-msg.bot .chat-bubble.screener-result { background: #161b22; border: 1px solid #30363d; font-size: 12px; }
.chat-msg .chat-time { font-size: 10px; color: #6e7681; margin-top: 3px; padding: 0 4px; }
.chat-input-area { display: flex; gap: 8px; padding: 10px 24px 14px; border-top: 1px solid #21262d; }
.chat-input-area input { flex: 1; background: #161b22; border: 1px solid #30363d; color: #c9d1d9; padding: 10px 14px; border-radius: 8px; font-size: 14px; outline: none; transition: border .2s; }
.chat-input-area input:focus { border-color: #58a6ff; }
.chat-input-area button { background: #238636; color: #fff; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 600; transition: background .2s; white-space: nowrap; }
.chat-input-area button:hover { background: #2ea043; }
.chat-input-area button:disabled { background: #21262d; color: #6e7681; cursor: not-allowed; }
.chat-loading { display: inline-block; width: 14px; height: 14px; border: 2px solid #6e7681; border-top-color: #58a6ff; border-radius: 50%; animation: spin .6s linear infinite; margin-right: 6px; vertical-align: middle; }
@keyframes spin { to { transform: rotate(360deg); } }

/* screener 結果樣式 */
.screener-header { padding: 8px 0; font-size: 14px; font-weight: 600; color: #58a6ff; margin-bottom: 8px; }
.screener-empty { color: #8b949e; padding: 12px 0; }
.screener-hit { padding: 10px 0; border-bottom: 1px solid #21262d; }
.screener-hit:last-child { border-bottom: none; }
.screener-hit-title { font-size: 14px; margin-bottom: 4px; }
.screener-tag { color: #58a6ff; font-size: 11px; }
.screener-sector { color: #6e7681; font-size: 11px; }
.screener-price { font-size: 13px; color: #c9d1d9; margin-bottom: 3px; }
.screener-pct { font-weight: 600; }
.screener-pct.up { color: #3fb950; }
.screener-pct.down { color: #f85149; }
.screener-meta { font-size: 11px; color: #6e7681; margin-bottom: 4px; }
.screener-driver { font-size: 12px; color: #e1e4e8; background: #1a1d2e; padding: 6px 10px; border-radius: 6px; margin-top: 4px; }
.screener-errors { padding: 8px 0; color: #f85149; font-size: 12px; }

@media (max-width: 768px) {
  .header { padding: 12px 16px; }
  .header h1 { font-size: 18px; }
  .toolbar { padding: 8px 16px; }
  .toolbar input { width: 140px; }
  .table-wrapper { padding: 0 12px; }
  td, th { padding: 8px; font-size: 12px; }
  .chat-messages { padding: 12px 16px; }
  .chat-input-area { padding: 10px 16px 14px; }
}
</style>
</head>
<body>
<div class="header">
  <h1>📊 StockAI Dashboard</h1>
  <div class="status"><span class="dot"></span> Bot 運作中 · 自動刷新 30s</div>
</div>
<div class="toolbar">
  <input type="text" id="search" placeholder="搜尋股票或關鍵字..." onkeyup="debounceSearch()">
  <button class="refresh" onclick="loadLogs()">🔄 刷新</button>
  <span class="count" id="count">記錄: -</span>
</div>
<div class="table-wrapper">
  <table id="logTable">
    <thead>
      <tr><th>時間</th><th>用戶</th><th>類型</th><th>查詢</th><th>結果</th></tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
  <div class="empty" id="emptyMsg">尚無記錄</div>
</div>

<!-- Chat -->
<div class="chat-section">
  <button class="chat-toggle" onclick="toggleChat()">
    <span class="arrow">▶</span> 💬 AI 聊天查詢
  </button>
  <div class="chat-body" id="chatBody">
    <div class="chat-messages" id="chatMessages">
      <div class="chat-msg bot">
        <div class="chat-bubble">👋 你好！我可以幫你：<br>
• 分析個股：輸入股票代號或名稱（如「0700.HK」、「騰訊」、「AAPL」）<br>
• 龍頭股異動：輸入「龍頭股」或「幫我找出26/5龍頭股中大陽線」</div>
        <div class="chat-time">now</div>
      </div>
    </div>
    <div class="chat-input-area">
      <input type="text" id="chatInput" placeholder="輸入查詢..." onkeydown="if(event.key==='Enter') sendChat()">
      <button id="chatSendBtn" onclick="sendChat()">發送</button>
    </div>
  </div>
</div>

<script>
let debounceTimer;
function debounceSearch() { clearTimeout(debounceTimer); debounceTimer = setTimeout(loadLogs, 300); }

async function loadLogs() {
  const search = document.getElementById('search').value.trim();
  const url = `/api/logs?limit=100${search ? '&search=' + encodeURIComponent(search) : ''}`;
  const resp = await fetch(url);
  const data = await resp.json();
  const tbody = document.getElementById('tbody');
  const empty = document.getElementById('emptyMsg');
  document.getElementById('count').textContent = '記錄: ' + (data.total || 0);

  if (!data.logs || data.logs.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';

  tbody.innerHTML = data.logs.map((log, i) => {
    const typeIcon = log.query_type === 'screener' ? '📊' : '📈';
    return `<tr>
      <td class="time">${fmtTime(log.timestamp)}</td>
      <td>${esc(log.username || log.user_id || '-')}</td>
      <td><span title="${esc(log.query_type || 'analysis')}">${typeIcon}</span> ${esc(log.symbol)}</td>
      <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(log.query || '')}">${esc(log.query || '')}</td>
      <td>
        <button class="expand-btn" onclick="toggleResult(${i})">📋 展開</button>
        <div id="res-${i}" class="code-block" style="display:none;margin-top:6px;">${esc(log.result)}</div>
      </td>
    </tr>`;
  }).join('');
}

function toggleResult(i) {
  const el = document.getElementById('res-' + i);
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function esc(s) {
  if (s === null || s === undefined) return '';
  const d = document.createElement('div'); d.textContent = s; return d.innerHTML;
}

function fmtTime(ts) {
  try { const d = new Date(ts); return d.toLocaleString('zh-HK', {hour12:false}); } catch(e) { return ts; }
}

// Chat
function toggleChat() {
  const body = document.getElementById('chatBody');
  const toggle = document.querySelector('.chat-toggle');
  body.classList.toggle('open');
  toggle.classList.toggle('open');
  if (body.classList.contains('open')) {
    setTimeout(() => document.getElementById('chatInput').focus(), 100);
  }
}

function addChatMessage(text, role, isHtml) {
  const msgs = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = 'chat-msg ' + role;
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble' + (role === 'bot' && text.includes('📊') ? ' screener-result' : '');
  if (isHtml) {
    bubble.innerHTML = text;
  } else {
    bubble.textContent = text;
  }
  div.appendChild(bubble);
  const time = document.createElement('div');
  time.className = 'chat-time';
  const now = new Date();
  time.textContent = now.toLocaleTimeString('zh-HK', {hour12:false});
  div.appendChild(time);
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
}

async function sendChat() {
  const input = document.getElementById('chatInput');
  const btn = document.getElementById('chatSendBtn');
  const text = input.value.trim();
  if (!text) return;

  addChatMessage(text, 'user');
  input.value = '';
  btn.disabled = true;

  // loading indicator
  const msgs = document.getElementById('chatMessages');
  const loadingDiv = document.createElement('div');
  loadingDiv.className = 'chat-msg bot';
  loadingDiv.id = 'chatLoading';
  loadingDiv.innerHTML = '<div class="chat-bubble"><span class="chat-loading"></span> 處理中...</div>';
  msgs.appendChild(loadingDiv);
  msgs.scrollTop = msgs.scrollHeight;

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, username: 'web_user' }),
    });
    const data = await resp.json();
    document.getElementById('chatLoading').remove();

    if (data.type === 'screener') {
      addChatMessage(data.result_html || data.result, 'bot', true);
    } else {
      addChatMessage(data.result, 'bot');
    }

    // refresh log table
    loadLogs();
  } catch (err) {
    document.getElementById('chatLoading').remove();
    addChatMessage('❌ 請求失敗：' + err.message, 'bot');
  } finally {
    btn.disabled = false;
    document.getElementById('chatInput').focus();
  }
}

setInterval(loadLogs, 30000);
loadLogs();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return HTML_TEMPLATE


@app.route("/api/logs")
def api_logs():
    limit = request.args.get("limit", 100, type=int)
    search = request.args.get("search") or None
    symbol = request.args.get("symbol") or None
    logs = query_logs(limit=limit, symbol=symbol, search=search)
    total = get_log_count()
    return jsonify({"logs": logs, "total": total})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True)
    message = (data.get("message") or "").strip()
    username = data.get("username") or "web_user"

    if not message:
        return jsonify({"type": "error", "result": "請輸入查詢內容"})

    # ── 偵測龍頭股關鍵字 ──
    if "龍頭" in message or "龍頭股" in message:
        target_date = _parse_date_from_message(message)

        # 解析市場關鍵字（同 bot.py）
        market = None
        msg_lower = message.lower()
        if "港" in msg_lower or "香港" in msg_lower:
            market = "HK"
        elif "美" in msg_lower or "美國" in msg_lower:
            market = "US"
        elif "台" in msg_lower or "台灣" in msg_lower or "臺灣" in msg_lower:
            market = "TW"

        try:
            result = run_screen(target_date, market)
            html = format_screener_html(result)
            md = format_screener_report(result)
            insert_log(0, username, "screener", message, md, query_type="screener")
            return jsonify({
                "type": "screener",
                "result": md,
                "result_html": html,
                "hits": len(result.get("hits", [])),
            })
        except Exception as e:
            return jsonify({"type": "error", "result": f"掃描失敗：{e}"})

    # ── 先用規則匹配股票代號 ──
    symbol = parse_stock_symbol_fast(message)

    # ── 匹配到代號 → 直接分析 ──
    if symbol is not None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result_text = loop.run_until_complete(run_analysis(symbol, 0, username, message))
            finally:
                loop.close()
            return jsonify({"type": "analysis", "symbol": symbol, "result": result_text})
        except Exception as e:
            return jsonify({"type": "error", "result": f"分析失敗：{e}"})

    # ── 無代號 → 意圖分類 ──
    try:
        intent = _classify_intent(message)
    except Exception:
        intent = {"type": "general", "query": message}

    if intent is None:
        # fallback 到 LLM 解析代號
        try:
            symbol = parse_stock_symbol(message)
        except Exception:
            symbol = None
        if symbol:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result_text = loop.run_until_complete(run_analysis(symbol, 0, username, message))
                finally:
                    loop.close()
                return jsonify({"type": "analysis", "symbol": symbol, "result": result_text})
            except Exception as e:
                return jsonify({"type": "error", "result": f"分析失敗：{e}"})
        return jsonify({
            "type": "error",
            "result": "❌ 無法辨識股票代號。請輸入代號（如 0700.HK、AAPL）或中文名稱。"
        })

    # 根據意圖分流
    try:
        _run_event_loop = lambda coro: asyncio.run(coro) if hasattr(asyncio, 'run') else asyncio.new_event_loop().run_until_complete(coro)
        # 簡化：用 helper 統一處理 async
        def _sync_run(coro):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        if intent["type"] == "analysis":
            symbol = intent.get("symbol", "")
            if not symbol:
                result_text = "❌ 無法識別股票代號。"
            else:
                result_text = _sync_run(run_analysis(symbol, 0, username, message))
        elif intent["type"] == "index":
            result_text = _sync_run(_handle_index_query(intent))
        elif intent["type"] == "candle":
            result_text = _sync_run(_handle_candle_query(intent))
        elif intent["type"] == "screener":
            result_text = _sync_run(_handle_screener_query(intent))
        elif intent["type"] == "general":
            result_text = _sync_run(_handle_general_question(intent, message))
        else:
            result_text = "❓ 抱歉，無法理解你的查詢。"

        # 寫入 DB
        try:
            insert_log(0, username, intent.get("type", "unknown"), message, result_text[:500])
        except Exception:
            pass

        return jsonify({"type": intent.get("type", "general"), "result": result_text})
    except Exception as e:
        return jsonify({"type": "error", "result": f"處理失敗：{e}"})


def run_web(host: str = "127.0.0.1", port: int = 5000, open_browser: bool = True) -> None:
    """在獨立執行緒中啟動 Flask。"""
    init_db()
    app.run(host=host, port=port, debug=False, use_reloader=False)