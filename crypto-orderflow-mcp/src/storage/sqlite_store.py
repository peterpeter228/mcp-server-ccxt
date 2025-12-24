"""
SQLite storage for trade aggregates and indicator data.
Stores footprint aggregates and key levels for historical analysis.
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import aiosqlite

from ..config import get_config
from ..utils import get_logger, get_utc_now_ms, get_day_start_ms, ms_to_datetime

logger = get_logger(__name__)


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types."""
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


@dataclass
class SQLiteStore:
    """
    SQLite-based storage for orderflow data.
    
    Stores:
    - Footprint bar aggregates (1m resolution)
    - Daily key levels (VWAP, POC, etc.)
    - Liquidation events
    """
    
    db_path: str = field(default_factory=lambda: get_config().cache_db_path)
    retention_days: int = field(default_factory=lambda: get_config().trade_cache_days)
    
    _conn: aiosqlite.Connection | None = field(default=None, init=False)
    _initialized: bool = field(default=False, init=False)
    
    async def connect(self) -> None:
        """Connect to the database and initialize tables."""
        if self._conn is not None:
            return
        
        # Ensure directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            Path(db_dir).mkdir(parents=True, exist_ok=True)
        
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        
        await self._init_tables()
        self._initialized = True
        
        logger.info("SQLite store connected", path=self.db_path)
    
    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            self._initialized = False
        logger.info("SQLite store closed")
    
    async def _init_tables(self) -> None:
        """Initialize database tables."""
        assert self._conn is not None
        
        # Footprint bars table (1m aggregates)
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS footprint_bars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                open_time INTEGER NOT NULL,
                close_time INTEGER NOT NULL,
                open TEXT NOT NULL,
                high TEXT NOT NULL,
                low TEXT NOT NULL,
                close TEXT NOT NULL,
                buy_volume TEXT NOT NULL,
                sell_volume TEXT NOT NULL,
                total_volume TEXT NOT NULL,
                delta TEXT NOT NULL,
                trade_count INTEGER NOT NULL,
                levels_json TEXT,
                created_at INTEGER NOT NULL,
                UNIQUE(symbol, timeframe, open_time)
            )
        """)
        
        # Daily key levels table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_levels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                vwap TEXT,
                poc TEXT,
                vah TEXT,
                val TEXT,
                high TEXT,
                low TEXT,
                volume TEXT,
                data_json TEXT,
                created_at INTEGER NOT NULL,
                UNIQUE(symbol, date)
            )
        """)
        
        # Session levels table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS session_levels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                session_name TEXT NOT NULL,
                high TEXT,
                low TEXT,
                start_time INTEGER NOT NULL,
                end_time INTEGER NOT NULL,
                is_complete INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(symbol, date, session_name)
            )
        """)
        
        # Liquidations table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS liquidations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price TEXT NOT NULL,
                quantity TEXT NOT NULL,
                order_type TEXT,
                time_in_force TEXT,
                timestamp INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        
        # Create indexes
        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_footprint_symbol_time 
            ON footprint_bars(symbol, timeframe, open_time)
        """)
        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_daily_levels_symbol_date 
            ON daily_levels(symbol, date)
        """)
        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_liquidations_symbol_time 
            ON liquidations(symbol, timestamp)
        """)
        
        await self._conn.commit()
        logger.info("Database tables initialized")
    
    # ==================== Footprint Bars ====================
    
    async def save_footprint_bar(
        self,
        symbol: str,
        timeframe: str,
        bar_data: dict,
    ) -> None:
        """
        Save a footprint bar to the database.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Bar timeframe
            bar_data: Footprint bar dictionary
        """
        assert self._conn is not None
        
        levels_json = json.dumps(bar_data.get("levels", []), cls=DecimalEncoder)
        
        await self._conn.execute("""
            INSERT OR REPLACE INTO footprint_bars
            (symbol, timeframe, open_time, close_time, open, high, low, close,
             buy_volume, sell_volume, total_volume, delta, trade_count, levels_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol,
            timeframe,
            bar_data["openTime"],
            bar_data["closeTime"],
            bar_data["open"],
            bar_data["high"],
            bar_data["low"],
            bar_data["close"],
            bar_data["totalBuyVolume"],
            bar_data["totalSellVolume"],
            bar_data["totalVolume"],
            bar_data["delta"],
            bar_data["tradeCount"],
            levels_json,
            get_utc_now_ms(),
        ))
        await self._conn.commit()
    
    async def get_footprint_bars(
        self,
        symbol: str,
        timeframe: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """
        Get footprint bars from database.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Bar timeframe
            start_time: Start time filter (ms)
            end_time: End time filter (ms)
            limit: Max number of bars
            
        Returns:
            List of footprint bar dicts
        """
        assert self._conn is not None
        
        query = """
            SELECT * FROM footprint_bars
            WHERE symbol = ? AND timeframe = ?
        """
        params: list[Any] = [symbol, timeframe]
        
        if start_time:
            query += " AND open_time >= ?"
            params.append(start_time)
        if end_time:
            query += " AND open_time < ?"
            params.append(end_time)
        
        query += " ORDER BY open_time ASC"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        
        return [self._row_to_footprint(row) for row in rows]
    
    def _row_to_footprint(self, row: aiosqlite.Row) -> dict:
        """Convert database row to footprint dict."""
        return {
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "openTime": row["open_time"],
            "closeTime": row["close_time"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "totalBuyVolume": row["buy_volume"],
            "totalSellVolume": row["sell_volume"],
            "totalVolume": row["total_volume"],
            "delta": row["delta"],
            "tradeCount": row["trade_count"],
            "levels": json.loads(row["levels_json"]) if row["levels_json"] else [],
        }
    
    # ==================== Daily Levels ====================
    
    async def save_daily_levels(
        self,
        symbol: str,
        date: str,
        levels: dict,
    ) -> None:
        """
        Save daily key levels to database.
        
        Args:
            symbol: Trading pair symbol
            date: Date string (YYYY-MM-DD)
            levels: Levels dictionary
        """
        assert self._conn is not None
        
        data_json = json.dumps(levels, cls=DecimalEncoder)
        
        await self._conn.execute("""
            INSERT OR REPLACE INTO daily_levels
            (symbol, date, vwap, poc, vah, val, high, low, volume, data_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol,
            date,
            levels.get("vwap"),
            levels.get("poc"),
            levels.get("vah"),
            levels.get("val"),
            levels.get("high"),
            levels.get("low"),
            levels.get("volume"),
            data_json,
            get_utc_now_ms(),
        ))
        await self._conn.commit()
    
    async def get_daily_levels(
        self,
        symbol: str,
        date: str,
    ) -> dict | None:
        """
        Get daily levels for a specific date.
        
        Args:
            symbol: Trading pair symbol
            date: Date string (YYYY-MM-DD)
            
        Returns:
            Levels dict or None
        """
        assert self._conn is not None
        
        async with self._conn.execute("""
            SELECT * FROM daily_levels WHERE symbol = ? AND date = ?
        """, (symbol, date)) as cursor:
            row = await cursor.fetchone()
        
        if row:
            return json.loads(row["data_json"])
        return None
    
    # ==================== Session Levels ====================
    
    async def save_session_levels(
        self,
        symbol: str,
        date: str,
        session_name: str,
        levels: dict,
    ) -> None:
        """Save session high/low levels."""
        assert self._conn is not None
        
        await self._conn.execute("""
            INSERT OR REPLACE INTO session_levels
            (symbol, date, session_name, high, low, start_time, end_time, is_complete, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol,
            date,
            session_name,
            levels.get("high"),
            levels.get("low"),
            levels.get("startTime", 0),
            levels.get("endTime", 0),
            1 if levels.get("isComplete") else 0,
            get_utc_now_ms(),
        ))
        await self._conn.commit()
    
    async def get_session_levels(
        self,
        symbol: str,
        date: str,
        session_name: str | None = None,
    ) -> list[dict]:
        """Get session levels for a date."""
        assert self._conn is not None
        
        if session_name:
            query = """
                SELECT * FROM session_levels 
                WHERE symbol = ? AND date = ? AND session_name = ?
            """
            params = (symbol, date, session_name)
        else:
            query = """
                SELECT * FROM session_levels 
                WHERE symbol = ? AND date = ?
            """
            params = (symbol, date)
        
        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        
        return [
            {
                "sessionName": row["session_name"],
                "high": row["high"],
                "low": row["low"],
                "startTime": row["start_time"],
                "endTime": row["end_time"],
                "isComplete": bool(row["is_complete"]),
            }
            for row in rows
        ]
    
    # ==================== Liquidations ====================
    
    async def save_liquidation(
        self,
        symbol: str,
        side: str,
        price: str,
        quantity: str,
        timestamp: int,
        order_type: str | None = None,
        time_in_force: str | None = None,
    ) -> None:
        """Save a liquidation event."""
        assert self._conn is not None
        
        await self._conn.execute("""
            INSERT INTO liquidations
            (symbol, side, price, quantity, order_type, time_in_force, timestamp, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol,
            side,
            price,
            quantity,
            order_type,
            time_in_force,
            timestamp,
            get_utc_now_ms(),
        ))
        await self._conn.commit()
    
    async def get_liquidations(
        self,
        symbol: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Get liquidation events."""
        assert self._conn is not None
        
        query = "SELECT * FROM liquidations WHERE symbol = ?"
        params: list[Any] = [symbol]
        
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)
        if end_time:
            query += " AND timestamp < ?"
            params.append(end_time)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        
        return [
            {
                "symbol": row["symbol"],
                "side": row["side"],
                "price": row["price"],
                "quantity": row["quantity"],
                "orderType": row["order_type"],
                "timeInForce": row["time_in_force"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]
    
    # ==================== Maintenance ====================
    
    async def cleanup_old_data(self) -> int:
        """
        Remove data older than retention period.
        
        Returns:
            Number of rows deleted
        """
        assert self._conn is not None
        
        cutoff = get_utc_now_ms() - (self.retention_days * 24 * 60 * 60 * 1000)
        cutoff_date = ms_to_datetime(cutoff).strftime("%Y-%m-%d")
        
        total_deleted = 0
        
        # Clean footprint bars
        cursor = await self._conn.execute(
            "DELETE FROM footprint_bars WHERE open_time < ?",
            (cutoff,)
        )
        total_deleted += cursor.rowcount
        
        # Clean daily levels
        cursor = await self._conn.execute(
            "DELETE FROM daily_levels WHERE date < ?",
            (cutoff_date,)
        )
        total_deleted += cursor.rowcount
        
        # Clean session levels
        cursor = await self._conn.execute(
            "DELETE FROM session_levels WHERE date < ?",
            (cutoff_date,)
        )
        total_deleted += cursor.rowcount
        
        # Clean liquidations
        cursor = await self._conn.execute(
            "DELETE FROM liquidations WHERE timestamp < ?",
            (cutoff,)
        )
        total_deleted += cursor.rowcount
        
        await self._conn.commit()
        
        if total_deleted > 0:
            logger.info(
                "Cleaned old data",
                rows_deleted=total_deleted,
                cutoff_date=cutoff_date,
            )
        
        return total_deleted
    
    async def get_stats(self) -> dict:
        """Get storage statistics."""
        assert self._conn is not None
        
        stats = {}
        
        # Count rows in each table
        for table in ["footprint_bars", "daily_levels", "session_levels", "liquidations"]:
            async with self._conn.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                row = await cursor.fetchone()
                stats[f"{table}_count"] = row[0] if row else 0
        
        # Get database file size
        if os.path.exists(self.db_path):
            stats["db_size_bytes"] = os.path.getsize(self.db_path)
            stats["db_size_mb"] = round(stats["db_size_bytes"] / (1024 * 1024), 2)
        
        return stats
