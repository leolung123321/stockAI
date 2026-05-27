"""
db.py - SQLite 記錄 Telegram 查詢歷史
"""
import sqlite3
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_PATH = "chat_log.db"
_lock = threading.Lock()


def init_db() -> None:
    """建立資料表（若不存在）。"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_id INTEGER,
                username TEXT,
                symbol TEXT NOT NULL,
                query TEXT,
                result TEXT NOT NULL,
                query_type TEXT DEFAULT 'analysis'
            )
        """)
        # 向後兼容：舊表若無 query_type 欄位則新增
        try:
            conn.execute("ALTER TABLE chat_log ADD COLUMN query_type TEXT DEFAULT 'analysis'")
        except sqlite3.OperationalError:
            pass  # 欄位已存在
        conn.commit()
        conn.close()


def insert_log(
    user_id: Optional[int],
    username: Optional[str],
    symbol: str,
    query: str,
    result: str,
    query_type: str = "analysis",
) -> None:
    """插入一筆查詢記錄。"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO chat_log (timestamp, user_id, username, symbol, query, result, query_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), user_id, username, symbol, query, result, query_type),
        )
        conn.commit()
        conn.close()


def query_logs(
    limit: int = 100,
    symbol: Optional[str] = None,
    search: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """查詢歷史記錄，支援按 symbol/search 過濾。"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM chat_log WHERE 1=1"
        params: list = []

        if symbol:
            sql += " AND symbol LIKE ?"
            params.append(f"%{symbol}%")
        if search:
            sql += " AND (query LIKE ? OR result LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])

        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_log_count() -> int:
    """回傳總筆數。"""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM chat_log").fetchone()[0]
        conn.close()
        return count