"""
screener.py - 龍頭股異動篩選器
基於 ATR 判斷中大陽線，跨日掃描 + LLM 驅動事件摘要
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
from openai import OpenAI

from .futu_client import get_futu, _yf_to_futu

# ── Config (env overridable) ──
ATR_PERIOD = 14
ATR_MULTIPLIER = float(os.getenv("SCREENER_ATR_MULTIPLIER", "1.0"))
# 中大陽線 = 實體 > ATR × this (default 1.0, 可在 .env 設 SCREENER_ATR_MULTIPLIER=1.2 微調)
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")


def _get_watchlist_path() -> str:
    """取得 watchlist.json 路徑（支援 PyInstaller 打包環境）。"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包：優先找 exe 同目錄（可讓用戶自行編輯），
        # 找不到則用 _MEIPASS 內建的
        base = os.path.dirname(sys.executable)
        user_path = os.path.join(base, "watchlist.json")
        if os.path.isfile(user_path):
            return user_path
        # fallback: 打包內建檔案
        return os.path.join(sys._MEIPASS, "watchlist.json")
    else:
        # 一般 Python 腳本：watchlist.json 在專案根目錄
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "watchlist.json")


def _load_watchlist() -> Dict[str, Any]:
    """載入龍頭股配置。"""
    path = _get_watchlist_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[screener] 載入 watchlist 失敗 ({path}): {e}")
        return {}


def _calc_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> Optional[float]:
    """計算 ATR(14) 並回傳最新值。"""
    if df is None or len(df) < period + 1:
        return None
    df = df.copy()
    df["H_L"] = df["High"] - df["Low"]
    df["H_Cp"] = abs(df["High"] - df["Close"].shift(1))
    df["L_Cp"] = abs(df["Low"] - df["Close"].shift(1))
    df["TR"] = df[["H_L", "H_Cp", "L_Cp"]].max(axis=1)
    atr = df["TR"].rolling(window=period).mean().iloc[-1]
    return float(atr) if not np.isnan(atr) and atr > 0 else None


def _is_big_bullish(open_price: float, close_price: float, atr: float) -> bool:
    """
    判斷是否為中大陽線。
    條件1（基於波動率）：實體 > ATR × multiplier
    條件2（基於漲幅，備用）：漲幅百分比 >= 3%
    任一成立即為中大陽線 — 確保 adjusted price 場景不漏判。
    """
    if open_price is None or close_price is None or open_price <= 0 or close_price <= 0:
        return False
    body = close_price - open_price
    if body <= 0:
        return False

    # 條件1：實體 > ATR × multiplier
    if atr and atr > 0 and body > atr * ATR_MULTIPLIER:
        return True
    # 條件2：漲幅百分比 >= 3%
    change_pct = body / open_price * 100
    return change_pct >= 3.0


def _get_kline_for_date(
    symbol: str, target_date: str, num: int = 80
) -> Tuple[Optional[pd.DataFrame], Optional[float], Optional[Dict[str, float]]]:
    """
    取得目標日期的日K線及 ATR，同時回傳該日的 OHLC。
    
    Returns:
        (full_df, atr_value, day_ohlc_dict)
    """
    # ── 計算日期範圍 ──
    target_dt = pd.to_datetime(target_date).normalize()
    # 需要至少 ATR_PERIOD+1 根 K 線在 target_date 之前，再算上 target_date 本身
    lookback_days = int(num * 1.5)  # ~120 天確保資料充足
    start_dt = target_dt - timedelta(days=lookback_days)
    end_dt = target_dt + timedelta(days=1)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    df = None

    # ── 先試富途 ──
    futu = get_futu()
    if futu and futu.is_connected:
        try:
            futu_code = _yf_to_futu(symbol)
            if futu_code:
                print(f"[screener] 富途 request_history_kline: {symbol} -> {futu_code} ({start_str} ~ {end_str})")
                df = futu.get_history_kline(symbol, ktype="K_DAY", start=start_str, end=end_str, max_count=num)
        except Exception as e:
            print(f"[screener] 富途 get_history_kline({symbol}) 失敗: {e}")

    # ── fallback: yfinance ──
    if df is None or df.empty:
        try:
            print(f"[screener] yfinance fallback: {symbol} (period=6mo, raw)")
            ticker = yf.Ticker(symbol)
            # auto_adjust=False → Open/High/Low/Close 為原始未調整價格
            df = ticker.history(period="6mo", auto_adjust=False)
            # 若 Close 沒有有效資料，降級為 adjusted（極少數情況）
            if df is not None and not df.empty:
                close_series = df["Close"].dropna()
                if len(close_series) == 0 or close_series.iloc[-1] <= 0:
                    print(f"[screener] {symbol}: raw Close 無效, 改用 adjusted")
                    df = ticker.history(period="6mo", auto_adjust=True)
        except Exception as e:
            print(f"[screener] yfinance history({symbol}) 失敗: {e}")
            return None, None, None

    if df is None or df.empty:
        print(f"[screener] {symbol}: 無任何K線資料")
        return None, None, None

    # ── 統一 index ──
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    df.index = pd.to_datetime(df.index).normalize()
    # 去重（同名 index）
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()

    # ── 找 target_date 在 index 中的位置 ──
    if target_dt not in df.index:
        available = df.index[df.index <= target_dt]
        if len(available) == 0:
            print(f"[screener] {symbol}: target {target_date} 不在K線範圍, 最早資料 {df.index[0]}")
            # 試試看是否接近最新交易日
            latest = df.index[-1]
            print(f"[screener] {symbol}: 改用最新交易日 {latest} 代替")
            target_dt = latest
            actual_date = latest.strftime("%Y-%m-%d")
        else:
            actual = available[-1]
            target_dt = actual
            actual_date = actual.strftime("%Y-%m-%d")
    else:
        actual_date = target_date

    # ── 計算 ATR（截至 target_date 或之前） ──
    df_before = df[df.index <= target_dt]
    if len(df_before) < ATR_PERIOD + 1:
        print(f"[screener] {symbol}: target 前只有 {len(df_before)} 根K線, 不足 {ATR_PERIOD+1}")
        # 如果資料不夠，用全部數據計算 ATR（放寬限制）
        if len(df) >= ATR_PERIOD + 1:
            df_before = df
        else:
            return None, None, None

    atr = _calc_atr(df_before, ATR_PERIOD)
    if atr is None:
        print(f"[screener] {symbol}: ATR 計算失敗")
        return None, None, None

    # ── 取 target_dt 當天 OHLC ──
    if target_dt not in df.index:
        print(f"[screener] {symbol}: {actual_date} 不在K線中")
        return None, None, None

    row = df.loc[target_dt]
    day_ohlc = {
        "open": float(row["Open"]),
        "high": float(row["High"]),
        "low": float(row["Low"]),
        "close": float(row["Close"]),
        "volume": int(row.get("Volume", 0)),
    }

    # 檢查是否為有效交易日
    if day_ohlc["open"] <= 0 or day_ohlc["close"] <= 0:
        print(f"[screener] {symbol}: {actual_date} 當天數據無效 O={day_ohlc['open']} C={day_ohlc['close']}")
        return None, None, None

    return df, atr, day_ohlc


def _get_prev_trading_dates(
    df: pd.DataFrame, target_date: str, count: int = 3
) -> List[str]:
    """
    從歷史 K 線 DataFrame 中取得 target_date 之前的倒數 N 個交易日。
    """
    target_dt = pd.to_datetime(target_date).normalize()
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    df.index = pd.to_datetime(df.index).normalize()
    dates = sorted(df.index[df.index < target_dt].unique())
    # 取倒數 count 個
    prev_dates = dates[-count:] if len(dates) >= count else dates
    return [d.strftime("%Y-%m-%d") for d in prev_dates]


def _check_prev_no_bullish(
    symbol: str, df: pd.DataFrame, prev_dates: List[str]
) -> bool:
    """
    確認前 N 天都沒有中大陽線。
    返回 True 表示都沒有（符合條件）。
    """
    if not prev_dates:
        return True  # 無前日數據，視為符合

    df = df.copy()
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    df.index = pd.to_datetime(df.index).normalize()

    for d in prev_dates:
        dt = pd.to_datetime(d).normalize()
        if dt not in df.index:
            continue
        row = df.loc[dt]
        o = float(row["Open"])
        c = float(row["Close"])
        if o <= 0 or c <= 0:
            continue
        # 對每一天獨立計算 ATR（截至當天）
        df_before = df[df.index <= dt]
        atr = _calc_atr(df_before, ATR_PERIOD)
        if atr and _is_big_bullish(o, c, atr):
            return False  # 有中大陽線，不符合
    return True


def _summarize_driver_events(
    symbol: str,
    stock_name: str,
    headlines: List[str],
    date: str,
    change_pct: float,
) -> str:
    """
    使用 LLM 摘要驅動事件。
    若無新聞或 LLM 不可用，回傳簡單說明。
    """
    if not headlines:
        return "暫無相關新聞"

    if not os.getenv("LLM_API_KEY"):
        return f"相關新聞 {len(headlines)} 則（無 LLM 摘要）"

    joined = "\n".join([f"{i+1}. {h}" for i, h in enumerate(headlines[:10])])
    prompt = f"""你是財經分析師。以下是有關 {stock_name}（{symbol}）在 {date} 前後的新聞標題。該股當日漲幅 {change_pct:+.2f}%，出現中大陽線。

新聞標題：
{joined}

請用一段繁體中文（50-80字）摘要說明導致該股大漲最有可能的驅動事件是什麼。只回摘要，不要其他文字。"""

    try:
        client = OpenAI(
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url="https://api.deepseek.com",
        )
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[screener] LLM 驅動事件摘要失敗: {e}")
        return f"相關新聞 {len(headlines)} 則（摘要失敗）"


def _parse_date_from_message(message: str) -> Optional[str]:
    """
    從訊息中解析日期。
    支援格式：26/5, 2026-05-26, 5月26日, 5/26
    回傳 YYYY-MM-DD。
    """
    # 2026-05-26 / 2026/05/26
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", message)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # 26/5 或 26/05
    m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?", message)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        if m.group(3):
            year = int(m.group(3))
            if year < 100:
                year += 2000
        else:
            year = datetime.now().year
        return f"{year}-{month:02d}-{day:02d}"

    # 5月26日 / 5月26號
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日號]", message)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        year = datetime.now().year
        return f"{year}-{month:02d}-{day:02d}"

    return None


def run_screen(target_date: Optional[str] = None, market: Optional[str] = None) -> Dict[str, Any]:
    """
    執行龍頭股異動篩選。

    Args:
        target_date: 目標日期 YYYY-MM-DD，None 為當天
        market: 指定市場代碼（HK/US/TW），None 為掃描全部

    Returns:
        dict: {
            "date": str,
            "total_scanned": int,
            "hits": List[dict],  # 符合條件的股票
            "errors": List[str],
        }
    """
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")

    print(f"[screener] 開始掃描: {target_date}, ATR_MULTIPLIER={ATR_MULTIPLIER}")

    watchlist = _load_watchlist()
    if not watchlist:
        return {"date": target_date, "total_scanned": 0, "hits": [], "errors": ["無法載入 watchlist"]}

    # 若指定市場，只保留該市場
    if market:
        market_upper = market.upper()
        watchlist = {k: v for k, v in watchlist.items() if k == market_upper}
        if not watchlist:
            return {"date": target_date, "total_scanned": 0, "hits": [], "errors": [f"未找到市場 {market_upper}"]}

    # 收集所有股票
    all_stocks: List[Dict[str, str]] = []
    for market_code, market_data in watchlist.items():
        for s in market_data.get("stocks", []):
            s["market"] = market_code
            s["market_name"] = market_data.get("name", market_code)
            all_stocks.append(s)

    total = len(all_stocks)
    hits: List[Dict[str, Any]] = []
    errors: List[str] = []

    for idx, stock in enumerate(all_stocks, 1):
        symbol = stock["symbol"]
        name = stock.get("name", symbol)
        sector = stock.get("sector", "")
        market_name = stock.get("market_name", "")

        try:
            df, atr, day_ohlc = _get_kline_for_date(symbol, target_date, num=80)
            if df is None or atr is None or day_ohlc is None:
                errors.append(f"{symbol} ({name}): K線數據不足")
                continue

            o = day_ohlc["open"]
            c = day_ohlc["close"]

            if not _is_big_bullish(o, c, atr):
                # debug: 顯示為何不符合
                body = c - o
                atr_thresh = atr * ATR_MULTIPLIER
                if c > o:
                    change_pct = body / o * 100
                    print(f"  [skip] {name} ({symbol}): 陽線 {change_pct:+.2f}% 實體 ${body:.2f} <= ATR ${atr:.2f} × {ATR_MULTIPLIER} = ${atr_thresh:.2f}")
                else:
                    print(f"  [skip] {name} ({symbol}): 陰線/平盤 O=${o:.2f} C=${c:.2f}")
                continue  # 不滿足中大陽線

            # 取前3個交易日，檢查是否有中大陽線
            prev_dates = _get_prev_trading_dates(df, target_date, count=3)
            prev_has_bullish = not _check_prev_no_bullish(symbol, df, prev_dates)

            # 符合條件！
            change_pct = (c - o) / o * 100 if o > 0 else 0
            body = c - o
            atr_ratio = body / atr if atr > 0 else 0

            print(f"  ✅ {name} ({symbol}): 漲幅 {change_pct:+.2f}%, 實體 ${body:.2f}, ATR ${atr:.2f}, 比值 {atr_ratio:.2f}x")

            # 撈取新聞
            from .news_fetcher import get_recent_news

            headlines = get_recent_news(symbol, count=8)

            # 驅動事件摘要
            driver = _summarize_driver_events(symbol, name, headlines, target_date, change_pct)

            hits.append({
                "symbol": symbol,
                "name": name,
                "sector": sector,
                "market": market_name,
                "date": target_date,
                "open": round(o, 2),
                "close": round(c, 2),
                "high": round(day_ohlc["high"], 2),
                "low": round(day_ohlc["low"], 2),
                "change_pct": round(change_pct, 2),
                "body": round(body, 2),
                "atr": round(atr, 2),
                "atr_ratio": round(atr_ratio, 2),
                "prev_trading_dates": prev_dates,
                "prev_has_bullish": prev_has_bullish,
                "headlines": headlines[:5],
                "driver": driver,
                "volume": day_ohlc.get("volume", 0),
            })

        except Exception as e:
            errors.append(f"{symbol} ({name}): {e}")
            import traceback
            traceback.print_exc()

    print(f"[screener] 掃描完成: {len(hits)}/{total} 符合條件, {len(errors)} 錯誤")

    return {
        "date": target_date,
        "total_scanned": total,
        "hits": hits,
        "errors": errors,
    }