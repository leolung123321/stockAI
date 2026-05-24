"""
formatter.py - 按藍本風格格式化股票技術分析輸出（多層級支撐阻力、詳細情緒、操作建議）
"""
from typing import Dict, Any, Optional, List


def format_analysis(
    stock_data: Dict[str, Any],
    sentiment: Optional[Dict[str, Any]] = None,
) -> str:
    """將完整技術分析數據格式化為藍本風格輸出。"""
    symbol = stock_data["symbol"]
    name = stock_data.get("name", symbol)

    lines: List[str] = []
    # ── 數據來源標示 ──
    data_source = stock_data.get("data_source", "")
    if "富途" in data_source:
        lines.append(f"📡 **數據來自富途即時行情**")
    lines.append("")

    # ── 標題 ──
    lines.append(f"## {name} ({symbol}) — 技術分析 💹")
    lines.append("")

    # ── 最新股價區塊 ──
    lines += _format_price_section(stock_data)

    # ── 阻力位 ──
    lines += _format_levels_section("🛑 關鍵阻力位（上方）", stock_data["resistance_levels"])

    # ── 支持位 ──
    lines += _format_levels_section("🟢 關鍵支持位（下方）", stock_data["support_levels"])

    # ── 技術指標 ──
    lines += _format_indicators(stock_data)

    # ── 市場情緒分析 ──
    lines += _format_sentiment_section(sentiment)

    # ── 操作建議 ──
    lines += _format_advice(stock_data, sentiment)

    lines.append("")
    lines.append("⚠️ 本分析僅供參考，不構成投資建議。投資涉及風險，請自行判斷。")
    lines.append("註：數據約有15分鐘延遲。以上由 AI 自動生成。")

    return "\n".join(lines)


def _format_price_section(d: Dict[str, Any]) -> List[str]:
    """最新股價區塊。"""
    lines = ["### 📈 最新股價"]

    # 若前收為 None，則相關欄位無法計算
    if d.get("prev_close") is None:
        lines.append(
            f"**現報：${d['current_price']}**（前收市價數據不可用）"
        )
        lines.append("")
        return lines

    direction = d.get("direction")
    change = d.get("change")
    change_pct = d.get("change_percent")
    prev_close = d["prev_close"]

    arrow = "▲" if direction == "up" else ("▼" if direction == "down" else "—")

    if change is not None and change_pct is not None:
        lines.append(
            f"**前收：${prev_close} → 開市：${d['open_price']} → 現報：${d['current_price']}"
            f"（{arrow} {change:+.2f} / {change_pct:+.2f}%）**"
        )
    else:
        lines.append(
            f"**前收：${prev_close} → 開市：${d['open_price']} → 現報：${d['current_price']}**"
        )

    if d["day_low"] != d["day_high"]:
        lines.append(f"今日波幅：${d['day_low']} - ${d['day_high']}")

    lines.append("")
    return lines


def _format_levels_section(title: str, levels: List[Dict[str, Any]]) -> List[str]:
    """格式化支撐/阻力位表格。"""
    lines = [f"### {title}", ""]
    lines.append("| 價位 | 級別 | 說明 |")
    lines.append("|------|------|------|")
    for lv in levels[:6]:  # 最多顯示 6 個
        price = lv["price"]
        level = lv["level"]
        desc = lv["description"]
        lines.append(f"| **${price}** | {level} | {desc} |")
    lines.append("")
    return lines


def _format_indicators(d: Dict[str, Any]) -> List[str]:
    """技術指標區塊。"""
    lines = ["### 📊 技術指標", ""]

    w52h = d["week52_high"]
    w52l = d["week52_low"]
    lines.append(f"- **52週波幅**：${w52l} - ${w52h}")

    pe = d.get("pe_ratio")
    if pe:
        pe_str = f"{pe:.1f}倍"
        if pe > 50:
            pe_str += " — 極高，反映市場用未來預期定價"
        elif pe > 25:
            pe_str += " — 偏高"
        elif pe > 15:
            pe_str += " — 合理"
        else:
            pe_str += " — 偏低"
        lines.append(f"- **PE（本益比）**：{pe_str}")

    target_mean = d.get("analyst_target_mean")
    if target_mean:
        target_low = d.get("analyst_target_low") or "N/A"
        target_high = d.get("analyst_target_high") or "N/A"
        target_median = d.get("analyst_target_median")
        analyst_count = d.get("analyst_count")

        target_line = f"- **分析師目標價**（{analyst_count}位分析師）：均價 **${target_mean}**"
        if target_median:
            target_line += f" / 中位數 **${target_median}**"
        target_line += f"（最低 ${target_low}，最高 ${target_high}）"
        lines.append(target_line)

    earnings = d.get("earnings_date")
    if earnings:
        lines.append(f"- **業績公佈**：**{earnings}** — 短期關鍵催化劑")

    vol = d.get("volume", 0)
    avg_vol = d.get("avg_volume_10d", 0)
    if vol and avg_vol:
        ratio = (vol / avg_vol * 100 - 100) if avg_vol > 0 else 0
        note = ""
        if ratio > 50:
            note = " — 成交量明顯放大，有心人活動跡象"
        elif ratio > 20:
            note = " — 成交略增"
        elif ratio < -30:
            note = " — 成交萎縮，觀望氣氛濃"
        lines.append(f"- **成交量**：{vol:,}（10日均量 {avg_vol:,}，{ratio:+.0f}%{note}）")

    boll_upper = d["bollinger_upper"]
    boll_mid = d["bollinger_mid"]
    boll_lower = d["bollinger_lower"]
    lines.append(f"- **20日布林帶**：上軌 ${boll_upper} / 中線 ${boll_mid} / 下軌 ${boll_lower}")

    # ── TD Sequential（神奇九轉） ──
    td = d.get("td_sequential")
    if td:
        lines.append(f"- **神奇九轉**：{td['label']}")
        lines.append(f"  → {td['signal']}")

    # ── 分時九轉（1m / 5m / 15m） ──
    td_intra = d.get("td_intraday")
    if td_intra:
        intra_labels = {
            "1m": "1分鐘線",
            "5m": "5分鐘線",
            "15m": "15分鐘線",
        }
        for interval, label in intra_labels.items():
            v = td_intra.get(interval)
            if v:
                lines.append(f"- **分時九轉（{label}）**：{v['label']}")
                lines.append(f"  → {v['signal']}")
            else:
                lines.append(f"- **分時九轉（{label}）**：數據不足")

    market_cap = d.get("market_cap")
    if market_cap:
        if market_cap >= 1e12:
            cap_str = f"${market_cap/1e12:.2f}兆"
        elif market_cap >= 1e8:
            cap_str = f"${market_cap/1e8:.2f}億"
        else:
            cap_str = f"${market_cap:,.0f}"
        lines.append(f"- **市值**：{cap_str}")

    lines.append("")
    return lines


def _format_sentiment_section(sentiment: Optional[Dict[str, Any]]) -> List[str]:
    """市場情緒分析區塊。"""
    lines = ["### 📰 市場情緒分析", ""]

    if not sentiment:
        lines.append("未能獲取新聞數據，無法進行情緒分析。")
        lines.append("")
        return lines

    score = sentiment["score"]
    label = sentiment["label"]

    # 每則新聞分析
    per_headline = sentiment.get("per_headline", [])
    if per_headline:
        for i, item in enumerate(per_headline, 1):
            hl = item.get("headline", "")
            s = item.get("sentiment", "中性")
            reason = item.get("reason", "")
            icon = "🟢" if "利好" in s else ("🔴" if "利淡" in s else "⚪")
            lines.append(f"{icon} **{i}. {hl}**")
            lines.append(f"   → {s}：{reason}")
        lines.append("")

    # 總體評分
    lines.append(f"**綜合情緒評分：{score}/10（{label}）**")
    overall = sentiment.get("overall_reason", "")
    if overall:
        lines.append(f"> {overall}")
    lines.append("")

    return lines


def _format_advice(d: Dict[str, Any], sentiment: Optional[Dict[str, Any]] = None) -> List[str]:
    """操作建議區塊。"""
    lines = ["### 💡 操作建議", ""]

    current = d["current_price"]
    supports = d.get("support_levels", [])
    resistances = d.get("resistance_levels", [])

    # 最近的買入位
    nearest_support = None
    for s in supports:
        sp = s["price"]
        if sp < current and (nearest_support is None or sp > nearest_support["price"]):
            nearest_support = s

    # 最近的賣出位
    nearest_resist = None
    for r in resistances:
        rp = r["price"]
        if rp > current and (nearest_resist is None or rp < nearest_resist["price"]):
            nearest_resist = r

    # 操作建議
    if nearest_support:
        lines.append(f"🔹 **買入觀察區**：約 **${nearest_support['price']}** — {nearest_support['description']}")
    if nearest_resist:
        lines.append(f"🔹 **賣出觀察區**：約 **${nearest_resist['price']}** — {nearest_resist['description']}")

    # 風險提示
    earnings = d.get("earnings_date")
    if earnings:
        lines.append(f"🔹 **業績催化**：業績公佈日 **{earnings}**，業績前後波動可能加大，請注意風險管理。")

    # 成交量警示
    vol = d.get("volume", 0)
    avg_vol = d.get("avg_volume_10d", 0)
    if avg_vol > 0 and vol > avg_vol * 1.5:
        lines.append("🔹 **成交量警示**：今日成交明顯放量，可能有聰明錢趁消息出貨，短線操作需謹慎。")

    # 情緒面建議
    if sentiment:
        score = sentiment["score"]
        if score <= 3:
            lines.append("🔹 **情緒面**：市場情緒極度負面，恐慌時可能是留意買入的時機，但需等待確認信號。")
        elif score >= 8:
            lines.append("🔹 **情緒面**：市場情緒極度樂觀，貪婪時考慮鎖定利潤，避免追高。")

    lines.append("")
    return lines


def format_error(symbol: str, reason: str = "無法獲取數據") -> str:
    """格式化錯誤訊息。"""
    return (
        f"❌ 分析失敗 ({symbol}): {reason}\n\n"
        f"請確認股票代號是否正確，並稍後再試。\n"
        f"支援格式: 0700.HK（港股）、AAPL（美股）、2330.TW（台股）\n"
        f"也可以使用中文名稱，如「騰訊」「蘋果」"
    )


def format_processing(symbol: str) -> str:
    """回傳「處理中」訊息。"""
    return f"⏳ 正在分析 **{symbol}**，獲取股價、新聞與技術指標中，請稍候..."