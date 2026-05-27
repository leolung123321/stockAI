"""
futu_client.py - 富途 OpenD 即時行情封裝，yfinance 備援整合
"""
import logging
import socket
import threading
from typing import Optional, Dict, Any

import pandas as pd
import numpy as np


# ── 符號映射表 ──
def _yf_to_futu(symbol: str) -> Optional[str]:
    """
    Yahoo Finance 格式 → 富途格式
    0700.HK  → HK.00700
    AAPL     → US.AAPL
    2330.TW  → TW.2330
    9988.HK  → HK.09988
    """
    s = symbol.upper().strip()

    # 美股：純字母，無後綴
    if s.isalpha() and len(s) <= 5:
        return f"US.{s}"

    # 有後綴格式
    if "." in s:
        parts = s.split(".")
        code = parts[0]
        suffix = parts[1]

        if suffix == "HK":
            # 港股補 0 成 5 位
            padded = code.zfill(5)
            return f"HK.{padded}"
        elif suffix == "TW":
            return f"TW.{code}"
        elif suffix == "T":
            return f"JP.{code}"
        else:
            # 其他 fallback: US
            return f"US.{code}"

    # 純數字 → 港股
    if s.isdigit():
        padded = s.zfill(5)
        return f"HK.{padded}"

    return None


def _futu_to_yf(futu_code: str) -> str:
    """富途格式 → Yahoo Finance 格式（反向，用於 fallback 顯示）"""
    if not futu_code or "." not in futu_code:
        return futu_code

    market, code = futu_code.split(".", 1)
    if market == "HK":
        # HK.00700 → 0700.HK（保留 4 位，去除多餘前導 0）
        stripped = code.lstrip("0") or "0"
        return f"{stripped.zfill(4)}.HK"
    elif market == "US":
        return code  # US.AAPL → AAPL
    elif market == "TW":
        return f"{code}.TW"
    elif market == "JP":
        return f"{code}.T"
    return futu_code


# ── 欄位映射（富途 get_stock_quote DataFrame → 統一 dict） ──
_QUOTE_FIELDS = {
    "code": "code",
    "name": "name",
    "last_price": "current_price",
    "open_price": "open_price",
    "high_price": "day_high",
    "low_price": "day_low",
    "prev_close_price": "prev_close",
    "volume": "volume",
    "turnover": "turnover",
}


# ── 市場狀態判斷（用於決定是否 fallback） ──
_MARKET_OPEN_HOURS = {
    "HK": {"weekday": (0, 4), "hours": ((9, 30), (16, 0))},    # 港股
    "US": {"weekday": (0, 4), "hours": ((9, 30), (16, 0))},    # 美股（東部時間）
    "TW": {"weekday": (0, 4), "hours": ((9, 0), (13, 30))},    # 台股
}


# ── 全局單例 ──
_futu_instance: Optional["FutuClient"] = None
_futu_lock = threading.Lock()


class FutuClient:
    """富途 OpenD 客戶端封裝（單例模式）"""

    def __init__(self, host: str = "127.0.0.1", port: int = 11111):
        self.host = host
        self.port = port
        self._ctx = None
        self._connected = False

    def connect(self) -> bool:
        """連線 OpenD（先 socket probe 再建立連線）"""
        # precedence check: port 有無 listen
        try:
            s = socket.create_connection((self.host, self.port), timeout=2)
            s.close()
        except OSError:
            print(f"[futu_client] OpenD {self.host}:{self.port} 未啟動，跳過 futu 連線")
            self._connected = False
            return False

        from futu import OpenQuoteContext, RET_OK
        import futu

        # 抑制 futu SDK 內部 ws error print
        # FTLog 沒有 setLevel，改用 console_level / file_level 或 console_logger
        if hasattr(futu.logger, "console_logger") and futu.logger.console_logger:
            futu.logger.console_logger.setLevel(logging.WARNING)
        if hasattr(futu.logger, "file_logger") and futu.logger.file_logger:
            futu.logger.file_logger.setLevel(logging.WARNING)
        futu.logger.console_level = logging.WARNING
        futu.logger.file_level = logging.WARNING

        try:
            ctx = OpenQuoteContext(self.host, self.port)
            # 用簡單查詢驗證連線
            ret, _ = ctx.get_market_state(["HK.00700"])
            if ret == RET_OK:
                self._ctx = ctx
                self._connected = True
                print(f"[futu_client] 已連線 OpenD {self.host}:{self.port}")
                return True
            ctx.close()
        except Exception as e:
            print(f"[futu_client] 連線失敗: {e}")

        self._connected = False
        return False

    def close(self) -> None:
        """斷線"""
        if self._ctx:
            try:
                self._ctx.close()
            except Exception:
                pass
        self._ctx = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ════════════════════════════════════════════════════
    # 即時報價
    # ════════════════════════════════════════════════════

    def get_realtime_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        取得即時報價（需已 subscribe QUOTE）

        Returns:
            dict 或 None（失敗時）
        """
        from futu import RET_OK

        if not self._connected or not self._ctx:
            return None

        futu_code = _yf_to_futu(symbol)
        if not futu_code:
            return None

        try:
            # subscribe + get_quote
            ret, data = self._ctx.get_market_snapshot([futu_code])
            if ret != RET_OK or data is None or data.empty:
                # fallback: get_stock_quote（需先 subscribe）
                self._ctx.subscribe([futu_code], ["QUOTE"], subscribe_push=False)
                ret, data = self._ctx.get_stock_quote([futu_code])
                if ret != RET_OK or data is None or data.empty:
                    return None
            return _parse_quote(data, symbol)
        except Exception as e:
            print(f"[futu_client] get_realtime_quote({symbol}) 錯誤: {e}")
            return None

    # ════════════════════════════════════════════════════
    # K 線數據
    # ════════════════════════════════════════════════════

    def get_kline(self, symbol: str, ktype: str = "K_DAY", num: int = 100) -> Optional[pd.DataFrame]:
        """
        取得 K 線數據，格式兼容 yfinance（Open/High/Low/Close/Volume）。

        Args:
            symbol: Yahoo Finance 格式代號
            ktype: K_1M / K_5M / K_15M / K_30M / K_60M / K_DAY / K_WEEK / K_MON
            num: 最多取幾根

        Returns:
            DataFrame with columns: Open, High, Low, Close, Volume, Datetime(index)
            失敗時回傳 None
        """
        from futu import RET_OK

        if not self._connected or not self._ctx:
            return None

        futu_code = _yf_to_futu(symbol)
        if not futu_code:
            return None

        try:
            # get_cur_kline 前需要 subscribe
            self._ctx.subscribe([futu_code], [ktype], subscribe_push=False)
            ret, data = self._ctx.get_cur_kline(futu_code, num=num, ktype=ktype, autype="qfq")
            if ret != RET_OK or data is None or data.empty:
                return None

            # 統一成 yfinance 格式
            df = data.rename(columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            })
            df.index = pd.to_datetime(data["time_key"])
            return df[["Open", "High", "Low", "Close", "Volume"]]
        except Exception as e:
            print(f"[futu_client] get_kline({symbol}, {ktype}) 錯誤: {e}")
            return None

    def get_history_kline(
        self, symbol: str, ktype: str = "K_DAY",
        start: Optional[str] = None, end: Optional[str] = None,
        max_count: int = 1000,
    ) -> Optional[pd.DataFrame]:
        """
        取得歷史 K 線（request_history_kline），可指定起止日期。

        Returns: 同 get_kline 格式
        """
        from futu import RET_OK

        if not self._connected or not self._ctx:
            return None

        futu_code = _yf_to_futu(symbol)
        if not futu_code:
            return None

        try:
            # request_history_kline 回傳 (ret, data, page_key)
            ret, data, _ = self._ctx.request_history_kline(
                futu_code, start=start, end=end,
                ktype=ktype, autype="qfq", max_count=max_count,
            )
            if ret != RET_OK or data is None or data.empty:
                return None

            df = data.rename(columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            })
            df.index = pd.to_datetime(data["time_key"])
            return df[["Open", "High", "Low", "Close", "Volume"]]
        except Exception as e:
            print(f"[futu_client] get_history_kline({symbol}) 錯誤: {e}")
            return None


# ════════════════════════════════════════════════════
# 內部輔助
# ════════════════════════════════════════════════════

def _parse_quote(data: pd.DataFrame, original_symbol: str) -> Optional[Dict[str, Any]]:
    """將富途 quote DataFrame 第一行解析成統一 dict"""
    if data is None or data.empty:
        return None

    row = data.iloc[0]
    ret: Dict[str, Any] = {
        "symbol": original_symbol,
        "current_price": _safe_val(row.get("last_price")),
        "open_price": _safe_val(row.get("open_price")),
        "day_high": _safe_val(row.get("high_price")),
        "day_low": _safe_val(row.get("low_price")),
        "prev_close": _safe_val(row.get("prev_close_price")),
        "volume": int(row.get("volume", 0)) if not np.isnan(row.get("volume", np.nan)) else 0,
        "turnover": _safe_val(row.get("turnover")),
    }

    # 計算漲跌幅
    cp = ret["current_price"]
    pc = ret["prev_close"]
    if cp is not None and pc is not None and pc > 0:
        change = cp - pc
        ret["change"] = round(change, 2)
        ret["change_percent"] = round((change / pc) * 100, 2)
        ret["direction"] = "up" if change > 0 else ("down" if change < 0 else "flat")
    else:
        ret["change"] = None
        ret["change_percent"] = None
        ret["direction"] = None

    # 確保必要欄位
    for f in ["current_price", "open_price", "day_high", "day_low", "prev_close"]:
        if ret.get(f) is None:
            ret[f] = np.nan

    return ret


def _safe_val(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
    except (ValueError, TypeError):
        return None
    if np.isnan(f) or np.isinf(f) or f <= 0:
        return None
    return f


# ════════════════════════════════════════════════════
# 全局單例管理
# ════════════════════════════════════════════════════

def init_futu(host: str = "127.0.0.1", port: int = 11111) -> bool:
    """初始化富途 OpenD 連線（全域單例）。"""
    global _futu_instance
    with _futu_lock:
        if _futu_instance and _futu_instance.is_connected:
            return True
        client = FutuClient(host, port)
        ok = client.connect()
        if ok:
            _futu_instance = client
        return ok


def get_futu() -> FutuClient:
    """取得全局 FutuClient 實例。"""
    return _futu_instance


def close_futu() -> None:
    """關閉富途連線。"""
    global _futu_instance
    with _futu_lock:
        if _futu_instance:
            _futu_instance.close()
            _futu_instance = None