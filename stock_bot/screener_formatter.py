"""
screener_formatter.py - 龍頭股異動篩選結果格式化（Telegram Markdown / Web HTML）
"""
from typing import Dict, Any, List


def format_screener_report(result: Dict[str, Any]) -> str:
    """
    格式化篩選結果為 Telegram Markdown 字串。
    
    Args:
        result: run_screen() 的回傳 dict
    
    Returns:
        str: 格式化後的輸出
    """
    date = result.get("date", "未知日期")
    total = result.get("total_scanned", 0)
    hits = result.get("hits", [])
    errors = result.get("errors", [])

    if total == 0:
        return "⚠️ 無法載入股票清單，請檢查 watchlist.json"

    lines: List[str] = []
    lines.append(f"📊 **龍頭股異動掃描 — {date}**")
    lines.append(f"🔍 掃描範圍：{total} 檔龍頭股 | 符合條件：{len(hits)} 檔")

    if not hits:
        lines.append("")
        lines.append("❌ 今日無龍頭股出現中大陽線異動。")
        if errors:
            lines.append("")
            lines.append("⚠️ 以下股票數據缺失：")
            for e in errors[:5]:
                lines.append(f"  • {e}")
        return "\n".join(lines)

    lines.append("")
    for i, h in enumerate(hits, 1):
        lines.append(f"**{i}. {h['name']} ({h['symbol']})** — [{h['market']}] {h['sector']}")
        lines.append(
            f"   📈 {h['date']}：開 ${h['open']} → 收 ${h['close']} "
            f"（**{h['change_pct']:+.2f}%**）"
        )
        lines.append(f"   實體：${h['body']} / ATR(14)：${h['atr']}（比值 {h['atr_ratio']:.2f}x）")
        prev_status = "有中大陽線 ⚠️" if h["prev_has_bullish"] else "無中大陽線 ✅"
        lines.append(f"   前 {len(h['prev_trading_dates'])} 日：{prev_status}")
        lines.append(f"   📰 **驅動事件**：{h['driver']}")
        lines.append("")

    # 錯誤摘要
    if errors:
        lines.append(f"⚠️ 數據缺失：{len(errors)}/{total} 檔")
        for e in errors[:3]:
            lines.append(f"  • {e}")

    lines.append("")
    lines.append("⚠️ 本篩選基於 ATR(14) 自動判斷中大陽線，僅供參考。")

    return "\n".join(lines)


def format_screener_html(result: Dict[str, Any]) -> str:
    """
    格式化篩選結果為 Web Dashboard 用的 HTML。
    
    Returns:
        str: HTML 片段（不含外層容器）
    """
    date = result.get("date", "未知日期")
    total = result.get("total_scanned", 0)
    hits = result.get("hits", [])
    errors = result.get("errors", [])

    parts: List[str] = []
    parts.append(
        f'<div class="screener-header">'
        f'📊 龍頭股異動掃描 — {date} | '
        f'掃描 {total} 檔 | 符合 {len(hits)} 檔'
        f'</div>'
    )

    if not hits:
        parts.append('<div class="screener-empty">❌ 今日無龍頭股出現中大陽線異動。</div>')
        if errors:
            parts.append('<div class="screener-errors"><small>⚠️ 數據缺失：')
            for e in errors[:5]:
                parts.append(f'<div>• {e}</div>')
            parts.append('</small></div>')
        return ''.join(parts)

    for h in hits:
        parts.append(
            f'<div class="screener-hit">'
            f'<div class="screener-hit-title">'
            f'<strong>{h["name"]} ({h["symbol"]})</strong>'
            f' <span class="screener-tag">[{h["market"]}]</span>'
            f' <span class="screener-sector">{h["sector"]}</span>'
            f'</div>'
            f'<div class="screener-price">'
            f'{h["date"]} 開 ${h["open"]} → 收 ${h["close"]} '
            f'<span class="screener-pct {"up" if h["change_pct"] > 0 else "down"}">'
            f'{h["change_pct"]:+.2f}%</span>'
            f'</div>'
            f'<div class="screener-meta">'
            f'實體 ${h["body"]} / ATR ${h["atr"]} ({h["atr_ratio"]:.2f}x)'
            f' · 前{len(h["prev_trading_dates"])}日{"有中大陽線 ⚠️" if h["prev_has_bullish"] else "無中大陽線 ✅"}'
            f'</div>'
            f'<div class="screener-driver">📰 {h["driver"]}</div>'
            f'</div>'
        )

    if errors:
        parts.append(f'<div class="screener-errors"><small>⚠️ {len(errors)}/{total} 數據缺失</small></div>')

    return ''.join(parts)