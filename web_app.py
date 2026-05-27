"""
web_app.py - Flask Web 界面，顯示 Telegram Bot 查詢記錄
"""
import os
from flask import Flask, request, jsonify

from stock_bot.db import query_logs, get_log_count, init_db

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
body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e1e4e8; min-height: 100vh; }
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
.table-wrapper { padding: 0 24px 24px; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 10px 12px; background: #161b22; border-bottom: 2px solid #30363d; color: #8b949e; font-weight: 600; position: sticky; top: 0; }
td { padding: 10px 12px; border-bottom: 1px solid #21262d; vertical-align: top; }
tr:hover td { background: #1a1d2e; }
.code-block { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 12px; font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px; white-space: pre-wrap; word-break: break-word; max-height: 300px; overflow-y: auto; line-height: 1.5; }
.expand-btn { background: none; border: 1px solid #30363d; color: #58a6ff; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; transition: all .2s; }
.expand-btn:hover { background: #1f2937; border-color: #58a6ff; }
.empty { text-align: center; padding: 60px 20px; color: #8b949e; font-size: 15px; }
.time { color: #6e7681; font-size: 12px; white-space: nowrap; }
@media (max-width: 768px) {
  .header { padding: 12px 16px; }
  .header h1 { font-size: 18px; }
  .toolbar { padding: 8px 16px; }
  .toolbar input { width: 140px; }
  .table-wrapper { padding: 0 12px 12px; }
  td, th { padding: 8px; font-size: 12px; }
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
      <tr><th>時間</th><th>用戶</th><th>股票</th><th>查詢</th><th>結果</th></tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
  <div class="empty" id="emptyMsg">尚無記錄</div>
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

  tbody.innerHTML = data.logs.map((log, i) => `
    <tr>
      <td class="time">${fmtTime(log.timestamp)}</td>
      <td>${esc(log.username || log.user_id || '-')}</td>
      <td><strong>${esc(log.symbol)}</strong></td>
      <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(log.query || '')}">${esc(log.query || '')}</td>
      <td>
        <button class="expand-btn" onclick="toggleResult(${i})">📋 展開</button>
        <div id="res-${i}" class="code-block" style="display:none;margin-top:6px;">${esc(log.result)}</div>
      </td>
    </tr>
  `).join('');
}

function toggleResult(i) {
  const el = document.getElementById('res-' + i);
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function fmtTime(ts) {
  try { const d = new Date(ts); return d.toLocaleString('zh-HK', {hour12:false}); } catch(e) { return ts; }
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


def run_web(host: str = "127.0.0.1", port: int = 5000, open_browser: bool = True) -> None:
    """在獨立執行緒中啟動 Flask。"""
    init_db()
    app.run(host=host, port=port, debug=False, use_reloader=False)
