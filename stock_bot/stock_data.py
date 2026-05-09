"""
stock_data.py - 使用 yfinance 獲取完整股價數據、多層級支撐阻力位、技術指標
"""
import yfinance as yf
import numpy as np
from typing import Optional, Dict, Any, List
from datetime import datetime


def _safe_val(val: Any) -> float | None:
    """回傳有效數值，NaN/inf/None/<=0 視為無效。"""
    if val is None:
        return None
    try:
        f = float(val)
    except (ValueError, TypeError):
        return None
    if np.isnan(f) or np.isinf(f) or f <= 0:
        return None
    return f


def _safe_series_mean(series, tail: int = 50) -> float | None:
    """安全計算 Series tail 均值，自動過濾 NaN。"""
    s = series.dropna()
    if len(s) == 0:
        return None
    if tail and len(s) >= tail:
        s = s.tail(tail)
    v = float(s.mean())
    return v if not np.isnan(v) else None


def _safe_series_min(series, tail: int = 20) -> float | None:
    s = series.dropna()
    if len(s) == 0:
        return None
    if tail and len(s) >= tail:
        s = s.tail(tail)
    v = float(s.min())
    return v if not np.isnan(v) else None


def _safe_series_max(series, tail: int = 20) -> float | None:
    s = series.dropna()
    if len(s) == 0:
        return None
    if tail and len(s) >= tail:
        s = s.tail(tail)
    v = float(s.max())
    return v if not np.isnan(v) else None


def get_stock_data(symbol: str) -> Optional[Dict[str, Any]]:
    """獲取股票完整技術分析數據。"""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        fast = ticker.fast_info or {}

        hist_1mo = ticker.history(period="1mo")
        hist_5d = ticker.history(period="5d")

        # ── 前收市價 ──
        prev_close = None
        for key in ["previousClose", "regularMarketPreviousClose"]:
            v = _safe_val(info.get(key))
            if v:
                prev_close = v
                break
        if prev_close is None:
            prev_close = _safe_val(fast.get("previous_close")) or _safe_val(fast.get("regular_market_previous_close"))
        if prev_close is None and len(hist_5d) >= 2:
            prev_close = _safe_val(hist_5d["Close"].iloc[-2])
        if prev_close is None and len(hist_1mo) >= 2:
            prev_close = _safe_val(hist_1mo["Close"].iloc[-2])
        if prev_close is None:
            prev_close = 100.0

        # ── 現價 ──
        current_price = _safe_val(fast.get("last_price")) or _safe_val(fast.get("regular_market_previous_close"))
        if current_price is None:
            current_price = _safe_val(info.get("currentPrice")) or _safe_val(info.get("regularMarketPrice"))
        if current_price is None and not hist_5d.empty:
            current_price = _safe_val(hist_5d["Close"].iloc[-1])
        if current_price is None and not hist_1mo.empty:
            current_price = _safe_val(hist_1mo["Close"].iloc[-1])
        if current_price is None:
            current_price = prev_close
        current_price = float(current_price)

        # ── 開市價 ──
        open_price = _safe_val(fast.get("open")) or _safe_val(fast.get("regular_market_open")) or _safe_val(info.get("regularMarketOpen"))
        if open_price is None and not hist_5d.empty:
            open_price = _safe_val(hist_5d["Open"].iloc[-1])
        if open_price is None and not hist_1mo.empty:
            open_price = _safe_val(hist_1mo["Open"].iloc[-1])
        if open_price is None:
            open_price = current_price

        # ── 日內高低 ──
        day_high = _safe_val(fast.get("day_high")) or _safe_val(fast.get("regular_market_day_high")) or _safe_val(info.get("dayHigh"))
        day_low = _safe_val(fast.get("day_low")) or _safe_val(fast.get("regular_market_day_low")) or _safe_val(info.get("dayLow"))
        if day_high is None and not hist_5d.empty:
            day_high = _safe_val(hist_5d["High"].iloc[-1])
        if day_low is None and not hist_5d.empty:
            day_low = _safe_val(hist_5d["Low"].iloc[-1])
        if day_high is None:
            day_high = current_price
        if day_low is None:
            day_low = current_price

        change = current_price - prev_close
        change_percent = (change / prev_close) * 100 if prev_close != 0 else 0.0

        direction = "up" if change > 0 else ("down" if change < 0 else "flat")
        name = info.get("long_name") or info.get("short_name") or symbol

        # ── 52 週高低 ──
        week52_high = _safe_val(fast.get("year_high")) or _safe_val(info.get("fiftyTwoWeekHigh")) or day_high
        week52_low = _safe_val(fast.get("year_low")) or _safe_val(info.get("fiftyTwoWeekLow")) or day_low

        # ── PE / 市值 ──
        pe_ratio = info.get("trailingPE") or info.get("forwardPE") or None
        market_cap = info.get("marketCap") or None

        # ── 分析師目標價 ──
        analyst_target_mean = info.get("targetMeanPrice") or None
        analyst_target_low = info.get("targetLowPrice") or None
        analyst_target_high = info.get("targetHighPrice") or None

        # ── 業績日期 ──
        earnings_date = None
        ed = info.get("earningsDate")
        if isinstance(ed, list) and ed:
            earnings_date = ed[0]
        elif isinstance(ed, (int, float)):
            earnings_date = datetime.fromtimestamp(ed).strftime("%Y-%m-%d")

        # ── 成交量 ──
        volume = fast.get("last_volume") or info.get("volume") or 0
        volume = int(volume) if volume else 0
        avg_volume_10d = int(hist_1mo["Volume"].dropna().tail(10).mean()) if not hist_1mo.empty and hist_1mo["Volume"].dropna().size >= 5 else volume

        # ── 布林帶（20 日） ──
        hist = ticker.history(period="3mo")
        if len(hist) >= 20:
            closes_raw = hist["Close"].dropna().values[-20:]
        elif len(hist) > 0:
            closes_raw = hist["Close"].dropna().values
        else:
            closes_raw = np.array([])
        closes = closes_raw if len(closes_raw) >= 5 else np.array([current_price] * 20)

        sma_20 = float(np.mean(closes))
        std_20 = float(np.std(closes, ddof=1)) if len(closes) > 1 else 0.0
        bollinger_upper = round(sma_20 + 2 * std_20, 2)
        bollinger_mid = round(sma_20, 2)
        bollinger_lower = round(sma_20 - 2 * std_20, 2)

        # ── 多層級支撐/阻力位 ──
        support_levels = _calc_support_levels(current_price, day_low, bollinger_lower, week52_low, hist)
        resistance_levels = _calc_resistance_levels(current_price, day_high, bollinger_upper, week52_high, hist)

        return {
            "symbol": symbol,
            "name": name,
            "current_price": round(current_price, 2),
            "prev_close": round(prev_close, 2),
            "open_price": round(open_price, 2),
            "day_high": round(day_high, 2),
            "day_low": round(day_low, 2),
            "change": round(change, 2),
            "change_percent": round(change_percent, 2),
            "direction": direction,
            "week52_high": round(week52_high, 2),
            "week52_low": round(week52_low, 2),
            "pe_ratio": round(pe_ratio, 2) if pe_ratio else None,
            "market_cap": market_cap,
            "analyst_target_mean": round(analyst_target_mean, 2) if analyst_target_mean else None,
            "analyst_target_low": round(analyst_target_low, 2) if analyst_target_low else None,
            "analyst_target_high": round(analyst_target_high, 2) if analyst_target_high else None,
            "earnings_date": earnings_date,
            "volume": volume,
            "avg_volume_10d": avg_volume_10d,
            "bollinger_upper": bollinger_upper,
            "bollinger_mid": bollinger_mid,
            "bollinger_lower": bollinger_lower,
            "support_levels": support_levels,
            "resistance_levels": resistance_levels,
        }

    except Exception as e:
        print(f"[stock_data] 獲取 {symbol} 數據失敗: {e}")
        return None


def _calc_support_levels(
    current: float, day_low: float, bb_lower: float,
    week52_low: float, hist: Any
) -> List[Dict[str, Any]]:
    """計算多層級支持位。"""
    candidates: List[Dict[str, Any]] = []

    # 1) 近期低點（20日） — 安全取值
    recent_low = _safe_series_min(hist["Low"], 20) if hist is not None and len(hist) >= 5 else None
    if recent_low is None:
        recent_low = min(day_low, bb_lower)

    short_val = min(day_low, recent_low)
    if short_val < current:
        candidates.append({"price": round(short_val, 2), "level": "🟢 短線支持", "description": "近期低位 / 日內低位附近"})

    # 2) 布林帶下軌
    if bb_lower < current:
        candidates.append({"price": bb_lower, "level": "🟡 布林帶下軌", "description": "20日布林帶底線"})

    # 3) MA50
    if hist is not None and len(hist) >= 5:
        ma50 = _safe_series_mean(hist["Close"], 50)
        if ma50 and ma50 < current:
            candidates.append({"price": round(ma50, 2), "level": "🟡 MA50", "description": "50日移動平均線"})

    # 4) MA100
    if hist is not None and len(hist) >= 5:
        ma100 = _safe_series_mean(hist["Close"], 100 if len(hist) >= 100 else None)
        if ma100 and ma100 < current:
            candidates.append({"price": round(ma100, 2), "level": "🟡 MA100", "description": "100日移動平均線"})

    # 5) Fibonacci 回撤
    if hist is not None and len(hist) >= 20:
        hh = _safe_series_max(hist["High"], 60 if len(hist) >= 60 else None)
        ll = _safe_series_min(hist["Low"], 60 if len(hist) >= 60 else None)
        if hh and ll and hh > ll:
            diff = hh - ll
            for pct, label in [(0.382, "Fib 38.2%"), (0.500, "Fib 50%"), (0.618, "Fib 61.8%")]:
                fib_val = round(hh - diff * pct, 2)
                if fib_val < current:
                    candidates.append({"price": fib_val, "level": "🟡 " + label, "description": "Fibonacci 回撤支持位"})

    # 6) 52 週低位
    if week52_low < current:
        candidates.append({"price": week52_low, "level": "🔴 52週低位", "description": "52週最低點，跌破則技術面轉弱"})

    merged = _merge_nearby_levels(candidates)
    if not merged:
        merged.append({"price": round(current * 0.93, 2), "level": "🔴 推算支持", "description": "基於現價推算"})
    merged.sort(key=lambda x: x["price"], reverse=True)
    return merged


def _calc_resistance_levels(
    current: float, day_high: float, bb_upper: float,
    week52_high: float, hist: Any
) -> List[Dict[str, Any]]:
    """計算多層級阻力位。"""
    candidates: List[Dict[str, Any]] = []

    # 1) 近期高點（20日）
    recent_high = _safe_series_max(hist["High"], 20) if hist is not None and len(hist) >= 5 else None
    if recent_high is None:
        recent_high = max(day_high, bb_upper)

    short_val = max(day_high, recent_high)
    if short_val > current:
        candidates.append({"price": round(short_val, 2), "level": "⚪ 短線阻力", "description": "近期高位 / 日內高位"})

    # 2) 心理阻力
    psycho = round(current * 1.05, -1) if current > 100 else (round(current * 1.08, 0) if current > 10 else round(current * 1.1, 1))
    if psycho > current:
        candidates.append({"price": psycho, "level": "🟡 心理阻力", "description": "整數關口"})

    # 3) 布林帶上軌
    if bb_upper > current:
        candidates.append({"price": bb_upper, "level": "🟡 布林帶上軌", "description": "20日布林帶頂線"})

    # 4) MA50 / MA100（若在現價上方）
    if hist is not None and len(hist) >= 5:
        ma50 = _safe_series_mean(hist["Close"], 50)
        if ma50 and ma50 > current:
            candidates.append({"price": round(ma50, 2), "level": "🟡 MA50", "description": "50日移動平均線"})
        ma100 = _safe_series_mean(hist["Close"], 100 if len(hist) >= 100 else None)
        if ma100 and ma100 > current:
            candidates.append({"price": round(ma100, 2), "level": "🟡 MA100", "description": "100日移動平均線"})

    # 5) Fibonacci 反彈
    if hist is not None and len(hist) >= 20:
        hh = _safe_series_max(hist["High"], 60 if len(hist) >= 60 else None)
        ll = _safe_series_min(hist["Low"], 60 if len(hist) >= 60 else None)
        if hh and ll and hh > ll:
            diff = hh - ll
            for pct, label in [(0.382, "Fib 38.2%"), (0.500, "Fib 50%"), (0.618, "Fib 61.8%")]:
                fib_val = round(ll + diff * pct, 2)
                if fib_val > current:
                    candidates.append({"price": fib_val, "level": "🟡 " + label, "description": "Fibonacci 回撤阻力位"})

    # 6) 52 週高位
    if week52_high > current:
        candidates.append({"price": week52_high, "level": "🔴 52週高位", "description": "52週最高點，突破則轉強"})

    merged = _merge_nearby_levels(candidates)
    if not merged:
        merged.append({"price": round(current * 1.07, 2), "level": "🔴 推算阻力", "description": "基於現價推算"})
    merged.sort(key=lambda x: x["price"])
    return merged


def _merge_nearby_levels(levels: List[Dict[str, Any]], min_gap_pct: float = 2.0) -> List[Dict[str, Any]]:
    """合併間距 < min_gap_pct% 的相近價位。去重說明文字。"""
    if not levels:
        return []

    priority = {"🔴": 4, "🟡": 3, "🟢": 2, "⚪": 1}

    def _priority_of(lv: Dict) -> int:
        for k, v in priority.items():
            if k in lv["level"]:
                return v
        return 0

    sorted_levels = sorted(levels, key=lambda x: x["price"])
    merged: List[Dict[str, Any]] = []

    for lv in sorted_levels:
        if not merged:
            merged.append(dict(lv))
            continue

        last = merged[-1]
        gap_pct = abs(lv["price"] - last["price"]) / last["price"] * 100

        if gap_pct < min_gap_pct:
            p_last = _priority_of(last)
            p_lv = _priority_of(lv)
            # 取均值價格
            merged[-1]["price"] = round((last["price"] + lv["price"]) / 2, 2)
            # 保留較高等級，合併說明時去重
            if p_lv > p_last:
                merged[-1]["level"] = lv["level"]
            # 合併說明（去重）
            desc_set = set()
            for d in [last.get("description", ""), lv.get("description", "")]:
                for part in d.replace("；", ";").split(";"):
                    part = part.strip()
                    if part:
                        desc_set.add(part)
            merged[-1]["description"] = "；".join(desc_set)
        else:
            merged.append(dict(lv))

    return merged