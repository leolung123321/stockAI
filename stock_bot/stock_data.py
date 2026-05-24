"""
stock_data.py - 使用富途 OpenD 即時行情 + yfinance 備援，完整股價數據、多層級支撐阻力位、技術指標
數據源策略：富途優先 → yfinance fallback
"""
import yfinance as yf
import numpy as np
import pandas as pd
from typing import Optional, Dict, Any, List
from datetime import datetime

from .futu_client import get_futu


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
    """
    獲取股票完整技術分析數據。

    數據源策略：富途 OpenD 即時行情優先 → yfinance 備援
    """
    # ── 嘗試富途即時行情 ──
    futu_result = _get_futu_data(symbol)
    if futu_result is not None:
        print(f"[stock_data] 富途即時行情成功: {symbol}")
        return futu_result

    # ── Fallback: 原有 yfinance 邏輯 ──
    print(f"[stock_data] 富途不可用，轉為 yfinance fallback: {symbol}")
    return _get_yfinance_data(symbol)


def _get_futu_data(symbol: str) -> Optional[Dict[str, Any]]:
    """使用富途 OpenD 取得即時行情 + K 線技術分析。富途不通回傳 None。"""
    futu = get_futu()
    if not futu or not futu.is_connected:
        return None

    # 1) 即時報價
    quote = futu.get_realtime_quote(symbol)
    if quote is None:
        return None

    current_price = quote["current_price"]
    prev_close = quote.get("prev_close")
    open_price = quote.get("open_price")
    day_high = quote.get("day_high")
    day_low = quote.get("day_low")
    volume = quote.get("volume", 0)
    change = quote.get("change")
    change_percent = quote.get("change_percent")
    direction = quote.get("direction")
    name = symbol  # 富途報價有 name 欄位，但 get_market_snapshot 未必有，先用 symbol

    # 2) 日 K 線 → 技術指標計算
    hist = futu.get_kline(symbol, ktype="K_DAY", num=100)
    hist_5d = futu.get_kline(symbol, ktype="K_DAY", num=5)
    hist_1mo = futu.get_kline(symbol, ktype="K_DAY", num=30)

    # 若 K 線全失敗，仍可回傳基本的即時報價（無 TA）
    if hist is not None and len(hist) > 0:
        bollinger_upper, bollinger_mid, bollinger_lower = _calc_bollinger(hist, current_price)
        support_levels = _calc_support_levels(current_price, day_low or 0, bollinger_lower, 0, hist)
        resistance_levels = _calc_resistance_levels(current_price, day_high or 0, bollinger_upper, 0, hist)
        td_sequential = _calc_td_sequential(hist)
    else:
        bollinger_upper = round(current_price * 1.05, 2)
        bollinger_mid = round(current_price, 2)
        bollinger_lower = round(current_price * 0.95, 2)
        support_levels = _calc_support_levels(current_price, day_low or 0, bollinger_lower, 0, None)
        resistance_levels = _calc_resistance_levels(current_price, day_high or 0, bollinger_upper, 0, None)
        td_sequential = None

    # 3) 分時九轉（用富途 K 線）
    td_intraday = {}
    for lbl, kt in [("1m", "K_1M"), ("5m", "K_5M"), ("15m", "K_15M")]:
        try:
            k = futu.get_kline(symbol, ktype=kt, num=100)
            td_intraday[lbl] = _calc_td_sequential(k) if k is not None else None
        except Exception:
            td_intraday[lbl] = None

    # 4) yfinance 補充基本資料（PE、市值、分析師目標、52週高低）
    yf_extra = _get_yfinance_basic_info(symbol)

    # 5) 組合結果
    result = {
        "symbol": symbol,
        "data_source": "富途即時行情 (OpenD)",
        "name": yf_extra.get("name", symbol),
        "current_price": round(current_price, 2),
        "prev_close": round(prev_close, 2) if prev_close is not None else None,
        "open_price": round(open_price, 2) if open_price is not None else None,
        "day_high": round(day_high, 2) if day_high is not None else None,
        "day_low": round(day_low, 2) if day_low is not None else None,
        "change": round(change, 2) if change is not None else None,
        "change_percent": round(change_percent, 2) if change_percent is not None else None,
        "direction": direction,
        "week52_high": yf_extra.get("week52_high"),
        "week52_low": yf_extra.get("week52_low"),
        "pe_ratio": yf_extra.get("pe_ratio"),
        "market_cap": yf_extra.get("market_cap"),
        "analyst_target_mean": yf_extra.get("analyst_target_mean"),
        "analyst_target_low": yf_extra.get("analyst_target_low"),
        "analyst_target_high": yf_extra.get("analyst_target_high"),
        "analyst_target_median": yf_extra.get("analyst_target_median"),
        "analyst_count": yf_extra.get("analyst_count"),
        "earnings_date": yf_extra.get("earnings_date"),
        "volume": volume,
        "avg_volume_10d": int(hist_1mo["Volume"].dropna().tail(10).mean()) if hist_1mo is not None and not hist_1mo.empty and hist_1mo["Volume"].dropna().size >= 5 else volume,
        "bollinger_upper": bollinger_upper,
        "bollinger_mid": bollinger_mid,
        "bollinger_lower": bollinger_lower,
        "support_levels": support_levels,
        "resistance_levels": resistance_levels,
        "td_sequential": td_sequential,
        "td_intraday": td_intraday,
    }
    return result


def _get_yfinance_data(symbol: str) -> Optional[Dict[str, Any]]:
    """原有 yfinance 完整邏輯（完全保留）。"""
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

        # ── 現價 ──
        current_price = _safe_val(fast.get("last_price")) or _safe_val(fast.get("regular_market_previous_close"))
        if current_price is None:
            current_price = _safe_val(info.get("currentPrice")) or _safe_val(info.get("regularMarketPrice"))
        if current_price is None and not hist_5d.empty:
            current_price = _safe_val(hist_5d["Close"].iloc[-1])
        if current_price is None and not hist_1mo.empty:
            current_price = _safe_val(hist_1mo["Close"].iloc[-1])
        if current_price is None and prev_close is not None:
            current_price = prev_close
        if current_price is None:
            print(f"[stock_data] 無法取得 {symbol} 的現價及前收市價，放棄處理")
            return None
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

        change = (current_price - prev_close) if prev_close is not None else None
        change_percent = ((change / prev_close) * 100) if (prev_close is not None and prev_close != 0 and change is not None) else None

        direction = "up" if change is not None and change > 0 else ("down" if change is not None and change < 0 else ("flat" if change is not None else None))
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
        analyst_target_median = info.get("targetMedianPrice") or None
        analyst_count = info.get("numberOfAnalystOpinions") or None

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
        bollinger_upper, bollinger_mid, bollinger_lower = _calc_bollinger(hist, current_price)

        # ── 多層級支撐/阻力位 ──
        support_levels = _calc_support_levels(current_price, day_low, bollinger_lower, week52_low, hist)
        resistance_levels = _calc_resistance_levels(current_price, day_high, bollinger_upper, week52_high, hist)

        # ── TD Sequential（神奇九轉） ──
        td_sequential = _calc_td_sequential(hist)

        # ── 分時九轉（1m / 5m / 15m） ──
        td_intraday = _calc_intraday_td_sequential(ticker)

        return {
            "symbol": symbol,
            "data_source": "yfinance (延遲約15-20分鐘)",
            "name": name,
            "current_price": round(current_price, 2),
            "prev_close": round(prev_close, 2) if prev_close is not None else None,
            "open_price": round(open_price, 2),
            "day_high": round(day_high, 2),
            "day_low": round(day_low, 2),
            "change": round(change, 2) if change is not None else None,
            "change_percent": round(change_percent, 2) if change_percent is not None else None,
            "direction": direction,
            "week52_high": round(week52_high, 2),
            "week52_low": round(week52_low, 2),
            "pe_ratio": round(pe_ratio, 2) if pe_ratio else None,
            "market_cap": market_cap,
            "analyst_target_mean": round(analyst_target_mean, 2) if analyst_target_mean else None,
            "analyst_target_low": round(analyst_target_low, 2) if analyst_target_low else None,
            "analyst_target_high": round(analyst_target_high, 2) if analyst_target_high else None,
            "analyst_target_median": round(analyst_target_median, 2) if analyst_target_median else None,
            "analyst_count": int(analyst_count) if analyst_count else None,
            "earnings_date": earnings_date,
            "volume": volume,
            "avg_volume_10d": avg_volume_10d,
            "bollinger_upper": bollinger_upper,
            "bollinger_mid": bollinger_mid,
            "bollinger_lower": bollinger_lower,
            "support_levels": support_levels,
            "resistance_levels": resistance_levels,
            "td_sequential": td_sequential,
            "td_intraday": td_intraday,
        }

    except Exception as e:
        print(f"[stock_data] yfinance 獲取 {symbol} 數據失敗: {e}")
        return None


def _get_yfinance_basic_info(symbol: str) -> Dict[str, Any]:
    """僅從 yfinance 取得基本資料（PE、市值、分析師目標、52週高低等），不拉 K 線。"""
    out: Dict[str, Any] = {
        "name": symbol, "week52_high": None, "week52_low": None,
        "pe_ratio": None, "market_cap": None,
        "analyst_target_mean": None, "analyst_target_low": None,
        "analyst_target_high": None, "analyst_target_median": None,
        "analyst_count": None, "earnings_date": None,
    }
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        fast = ticker.fast_info or {}

        out["name"] = info.get("long_name") or info.get("short_name") or symbol
        out["week52_high"] = _safe_val(fast.get("year_high")) or _safe_val(info.get("fiftyTwoWeekHigh"))
        out["week52_low"] = _safe_val(fast.get("year_low")) or _safe_val(info.get("fiftyTwoWeekLow"))
        out["pe_ratio"] = info.get("trailingPE") or info.get("forwardPE") or None
        out["market_cap"] = info.get("marketCap") or None
        out["analyst_target_mean"] = info.get("targetMeanPrice") or None
        out["analyst_target_low"] = info.get("targetLowPrice") or None
        out["analyst_target_high"] = info.get("targetHighPrice") or None
        out["analyst_target_median"] = info.get("targetMedianPrice") or None
        out["analyst_count"] = int(info["numberOfAnalystOpinions"]) if info.get("numberOfAnalystOpinions") else None

        ed = info.get("earningsDate")
        if isinstance(ed, list) and ed:
            out["earnings_date"] = ed[0]
        elif isinstance(ed, (int, float)):
            out["earnings_date"] = datetime.fromtimestamp(ed).strftime("%Y-%m-%d")

        # 整理為 round / None
        for k in ["week52_high", "week52_low", "analyst_target_mean", "analyst_target_low", "analyst_target_high", "analyst_target_median"]:
            v = out.get(k)
            if v is not None:
                out[k] = round(float(v), 2)
    except Exception as e:
        print(f"[stock_data] yfinance 基本資訊補充失敗: {e}")

    return out


def _calc_bollinger(hist: Any, fallback_price: float) -> tuple:
    """計算布林帶（20日）。"""
    if hist is not None and len(hist) > 0:
        closes_raw = hist["Close"].dropna().values[-20:]
    else:
        closes_raw = np.array([])
    closes = closes_raw if len(closes_raw) >= 5 else np.array([fallback_price] * 20)

    sma_20 = float(np.mean(closes))
    std_20 = float(np.std(closes, ddof=1)) if len(closes) > 1 else 0.0
    upper = round(sma_20 + 2 * std_20, 2)
    mid = round(sma_20, 2)
    lower = round(sma_20 - 2 * std_20, 2)
    return upper, mid, lower


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


def _calc_td_sequential(hist: Any) -> Optional[Dict[str, Any]]:
    """
    TD Sequential（神奇九轉）Setup 階段計算。
    需要至少 60 根 K 線（取 6mo 歷史）以進行可靠計算。

    Returns:
        dict: {
            "count": int,          # 當前 Setup 計數 (1-9)
            "direction": str,      # "buy_setup" / "sell_setup"
            "label": str,          # 中文描述
            "bars_from_end": int,  # 從尾部算起的 bar 位置（0=最新）
            "completed": bool,     # 是否已完成 9 轉
            "signal": str,         # 交易信號
        }
        若數據不足則回傳 None
    """
    if hist is None or len(hist) < 30:
        return None

    closes = hist["Close"].dropna()
    if len(closes) < 30:
        return None

    closes = closes.tail(100)  # 取最近 100 根
    n = len(closes)

    # ── Buy Setup（上升趨勢反轉向下）：連續 9 根收盤 > 4 根前收盤 ──
    buy_setup_count = 0
    buy_setup_bars: List[int] = []
    for i in range(4, n):
        close_i = float(closes.iloc[i])
        close_4ago = float(closes.iloc[i - 4])
        if close_i > close_4ago:
            buy_setup_count += 1
            buy_setup_bars.append(i)
            if buy_setup_count >= 9:
                break
        else:
            # 中斷則重置（需連續）
            buy_setup_count = 0
            buy_setup_bars = []

    # ── Sell Setup（下跌趨勢反轉向上）：連續 9 根收盤 < 4 根前收盤 ──
    sell_setup_count = 0
    sell_setup_bars: List[int] = []
    for i in range(4, n):
        close_i = float(closes.iloc[i])
        close_4ago = float(closes.iloc[i - 4])
        if close_i < close_4ago:
            sell_setup_count += 1
            sell_setup_bars.append(i)
            if sell_setup_count >= 9:
                break
        else:
            sell_setup_count = 0
            sell_setup_bars = []

    # 決定當前有效的 Setup（取最近完成的或正在計數的）
    latest_buy_bar = buy_setup_bars[-1] if buy_setup_bars else -1
    latest_sell_bar = sell_setup_bars[-1] if sell_setup_bars else -1

    if latest_buy_bar > latest_sell_bar and buy_setup_count > 0:
        # 買入結構（上升趨勢中，預示可能反轉向下 → 賣出信號）
        completed = buy_setup_count >= 9
        latest_bar = buy_setup_bars[-1]
        bars_from_end = n - 1 - latest_bar

        if completed:
            signal = "⚠️ 9轉完成，上升趨勢可能衰竭，留意回調風險"
            label = f"🟡 賣出Setup 第{buy_setup_count}轉（已完成）"
        else:
            signal = f"上升趨勢中，目前第{buy_setup_count}轉，距9轉尚餘{9 - buy_setup_count}根"
            label = f"🟡 賣出Setup 第{buy_setup_count}/9轉"

        return {
            "count": buy_setup_count,
            "direction": "sell_setup",
            "label": label,
            "bars_from_end": bars_from_end,
            "completed": completed,
            "signal": signal,
        }

    elif latest_sell_bar > latest_buy_bar and sell_setup_count > 0:
        # 賣出結構（下跌趨勢中，預示可能反轉向上 → 買入信號）
        completed = sell_setup_count >= 9
        latest_bar = sell_setup_bars[-1]
        bars_from_end = n - 1 - latest_bar

        if completed:
            signal = "✅ 9轉完成，下跌趨勢可能衰竭，留意反彈機會"
            label = f"🟢 買入Setup 第{sell_setup_count}轉（已完成）"
        else:
            signal = f"下跌趨勢中，目前第{sell_setup_count}轉，距9轉尚餘{9 - sell_setup_count}根"
            label = f"🟢 買入Setup 第{sell_setup_count}/9轉"

        return {
            "count": sell_setup_count,
            "direction": "buy_setup",
            "label": label,
            "bars_from_end": bars_from_end,
            "completed": completed,
            "signal": signal,
        }

    return None


def _calc_intraday_td_sequential(ticker: Any) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    分時九轉：計算 1 分鐘、5 分鐘、15 分鐘 K 線嘅 TD Sequential。

    Args:
        ticker: yfinance Ticker 物件

    Returns:
        dict: {"1m": {...}, "5m": {...}, "15m": {...}}
        每個值係 _calc_td_sequential() 嘅回傳格式，數據不足則為 None
    """
    intervals = [
        ("1m", "7d"),
        ("5m", "2mo"),
        ("15m", "3mo"),
    ]

    result: Dict[str, Optional[Dict[str, Any]]] = {}
    for label, period in intervals:
        try:
            hist = ticker.history(period=period, interval=label)
            td = _calc_td_sequential(hist)
            result[label] = td
        except Exception as e:
            print(f"[stock_data] 分時九轉 {label} 計算失敗: {e}")
            result[label] = None

    return result


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

    # 過濾無效價格
    valid = [lv for lv in levels if lv.get("price") is not None and lv["price"] > 0]
    if not valid:
        return []

    sorted_levels = sorted(valid, key=lambda x: x["price"])
    merged: List[Dict[str, Any]] = []

    for lv in sorted_levels:
        if not merged:
            merged.append(dict(lv))
            continue

        last = merged[-1]
        denom = last["price"]
        gap_pct = abs(lv["price"] - denom) / denom * 100 if denom > 0 else 999

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