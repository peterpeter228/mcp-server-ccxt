"""SQLite storage for trade data and aggregations."""

import asyncio
from pathlib import Path
from typing import Any

import aiosqlite

from src.config import get_settings
from src.utils import get_logger, timestamp_ms, get_day_start_ms


class DataStorage:
    """SQLite storage for historical trade data and aggregations."""
    
    def __init__(self):
        self.settings = get_settings()
        self.db_path = self.settings.ensure_data_dir()
        self.logger = get_logger("data.storage")
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """Initialize database and create tables."""
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        
        await self._db.executescript("""
            -- Aggregated trades (1-minute footprint data)
            CREATE TABLE IF NOT EXISTS footprint_1m (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,  -- Start of minute (ms)
                price_level REAL NOT NULL,   -- Price tick level
                buy_volume REAL NOT NULL DEFAULT 0,
                sell_volume REAL NOT NULL DEFAULT 0,
                trade_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(symbol, timestamp, price_level)
            );
            
            CREATE INDEX IF NOT EXISTS idx_footprint_1m_symbol_ts 
                ON footprint_1m(symbol, timestamp);
            
            -- Daily aggregated data for VWAP/Volume Profile
            CREATE TABLE IF NOT EXISTS daily_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                date INTEGER NOT NULL,       -- Day start timestamp (ms)
                price_level REAL NOT NULL,   -- Price tick level
                volume REAL NOT NULL DEFAULT 0,
                buy_volume REAL NOT NULL DEFAULT 0,
                sell_volume REAL NOT NULL DEFAULT 0,
                notional REAL NOT NULL DEFAULT 0,
                trade_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(symbol, date, price_level)
            );
            
            CREATE INDEX IF NOT EXISTS idx_daily_trades_symbol_date 
                ON daily_trades(symbol, date);
            
            -- Session high/low tracking
            CREATE TABLE IF NOT EXISTS session_levels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                date INTEGER NOT NULL,       -- Day start timestamp (ms)
                session TEXT NOT NULL,       -- 'tokyo', 'london', 'ny'
                high_price REAL NOT NULL,
                low_price REAL NOT NULL,
                high_time INTEGER NOT NULL,
                low_time INTEGER NOT NULL,
                volume REAL NOT NULL DEFAULT 0,
                UNIQUE(symbol, date, session)
            );
            
            CREATE INDEX IF NOT EXISTS idx_session_levels_symbol_date 
                ON session_levels(symbol, date);
            
            -- VWAP tracking
            CREATE TABLE IF NOT EXISTS vwap_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                date INTEGER NOT NULL,       -- Day start timestamp (ms)
                cumulative_pv REAL NOT NULL DEFAULT 0,  -- Price * Volume
                cumulative_volume REAL NOT NULL DEFAULT 0,
                last_update INTEGER NOT NULL,
                UNIQUE(symbol, date)
            );
            
            CREATE INDEX IF NOT EXISTS idx_vwap_data_symbol_date 
                ON vwap_data(symbol, date);
            
            -- Open Interest snapshots
            CREATE TABLE IF NOT EXISTS oi_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open_interest REAL NOT NULL,
                open_interest_notional REAL NOT NULL,
                UNIQUE(symbol, timestamp)
            );
            
            CREATE INDEX IF NOT EXISTS idx_oi_snapshots_symbol_ts 
                ON oi_snapshots(symbol, timestamp);
            
            -- Depth delta snapshots
            CREATE TABLE IF NOT EXISTS depth_delta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                bid_volume REAL NOT NULL,
                ask_volume REAL NOT NULL,
                net_volume REAL NOT NULL,
                percent_range REAL NOT NULL,
                mid_price REAL NOT NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_depth_delta_symbol_ts 
                ON depth_delta(symbol, timestamp);
        """)
        
        await self._db.commit()
        self.logger.info("database_initialized", path=str(self.db_path))
    
    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None
    
    async def cleanup_old_data(self) -> int:
        """Remove data older than retention period."""
        if not self._db:
            return 0
        
        cutoff = timestamp_ms() - (self.settings.data_retention_days * 86_400_000)
        
        async with self._lock:
            cursor = await self._db.execute(
                "DELETE FROM footprint_1m WHERE timestamp < ?", (cutoff,)
            )
            deleted_footprint = cursor.rowcount
            
            cursor = await self._db.execute(
                "DELETE FROM daily_trades WHERE date < ?", (cutoff,)
            )
            deleted_daily = cursor.rowcount
            
            cursor = await self._db.execute(
                "DELETE FROM session_levels WHERE date < ?", (cutoff,)
            )
            deleted_sessions = cursor.rowcount
            
            cursor = await self._db.execute(
                "DELETE FROM vwap_data WHERE date < ?", (cutoff,)
            )
            deleted_vwap = cursor.rowcount
            
            cursor = await self._db.execute(
                "DELETE FROM oi_snapshots WHERE timestamp < ?", (cutoff,)
            )
            deleted_oi = cursor.rowcount
            
            cursor = await self._db.execute(
                "DELETE FROM depth_delta WHERE timestamp < ?", (cutoff,)
            )
            deleted_depth = cursor.rowcount
            
            await self._db.commit()
        
        total_deleted = deleted_footprint + deleted_daily + deleted_sessions + deleted_vwap + deleted_oi + deleted_depth
        self.logger.info("cleanup_complete", deleted=total_deleted, cutoff_days=self.settings.data_retention_days)
        return total_deleted
    
    # Footprint operations
    async def upsert_footprint(
        self,
        symbol: str,
        timestamp: int,
        price_level: float,
        buy_volume: float,
        sell_volume: float,
        trade_count: int = 1,
    ) -> None:
        """Insert or update footprint data."""
        if not self._db:
            return
        
        async with self._lock:
            await self._db.execute("""
                INSERT INTO footprint_1m (symbol, timestamp, price_level, buy_volume, sell_volume, trade_count)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timestamp, price_level) DO UPDATE SET
                    buy_volume = buy_volume + excluded.buy_volume,
                    sell_volume = sell_volume + excluded.sell_volume,
                    trade_count = trade_count + excluded.trade_count
            """, (symbol, timestamp, price_level, buy_volume, sell_volume, trade_count))
            await self._db.commit()
    
    async def get_footprint_range(
        self,
        symbol: str,
        start_time: int,
        end_time: int,
    ) -> list[dict[str, Any]]:
        """Get footprint data for a time range."""
        if not self._db:
            return []
        
        cursor = await self._db.execute("""
            SELECT timestamp, price_level, buy_volume, sell_volume, trade_count
            FROM footprint_1m
            WHERE symbol = ? AND timestamp >= ? AND timestamp < ?
            ORDER BY timestamp, price_level
        """, (symbol, start_time, end_time))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    # Daily trades operations
    async def upsert_daily_trade(
        self,
        symbol: str,
        date: int,
        price_level: float,
        volume: float,
        buy_volume: float,
        sell_volume: float,
        notional: float,
        trade_count: int = 1,
    ) -> None:
        """Insert or update daily trade aggregation."""
        if not self._db:
            return
        
        async with self._lock:
            await self._db.execute("""
                INSERT INTO daily_trades (symbol, date, price_level, volume, buy_volume, sell_volume, notional, trade_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, date, price_level) DO UPDATE SET
                    volume = volume + excluded.volume,
                    buy_volume = buy_volume + excluded.buy_volume,
                    sell_volume = sell_volume + excluded.sell_volume,
                    notional = notional + excluded.notional,
                    trade_count = trade_count + excluded.trade_count
            """, (symbol, date, price_level, volume, buy_volume, sell_volume, notional, trade_count))
            await self._db.commit()
    
    async def get_daily_trades(self, symbol: str, date: int) -> list[dict[str, Any]]:
        """Get daily trade aggregation for volume profile."""
        if not self._db:
            return []
        
        cursor = await self._db.execute("""
            SELECT price_level, volume, buy_volume, sell_volume, notional, trade_count
            FROM daily_trades
            WHERE symbol = ? AND date = ?
            ORDER BY price_level
        """, (symbol, date))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    # VWAP operations
    async def update_vwap(
        self,
        symbol: str,
        date: int,
        price: float,
        volume: float,
    ) -> None:
        """Update VWAP cumulative values."""
        if not self._db:
            return
        
        pv = price * volume
        now = timestamp_ms()
        
        async with self._lock:
            await self._db.execute("""
                INSERT INTO vwap_data (symbol, date, cumulative_pv, cumulative_volume, last_update)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol, date) DO UPDATE SET
                    cumulative_pv = cumulative_pv + excluded.cumulative_pv,
                    cumulative_volume = cumulative_volume + excluded.cumulative_volume,
                    last_update = excluded.last_update
            """, (symbol, date, pv, volume, now))
            await self._db.commit()
    
    async def get_vwap(self, symbol: str, date: int) -> dict[str, float] | None:
        """Get VWAP data for a specific day."""
        if not self._db:
            return None
        
        cursor = await self._db.execute("""
            SELECT cumulative_pv, cumulative_volume, last_update
            FROM vwap_data
            WHERE symbol = ? AND date = ?
        """, (symbol, date))
        
        row = await cursor.fetchone()
        if not row:
            return None
        
        return {
            "cumulative_pv": row["cumulative_pv"],
            "cumulative_volume": row["cumulative_volume"],
            "last_update": row["last_update"],
        }
    
    # Session levels operations
    async def update_session_levels(
        self,
        symbol: str,
        date: int,
        session: str,
        price: float,
        timestamp: int,
        volume: float,
    ) -> None:
        """Update session high/low."""
        if not self._db:
            return
        
        async with self._lock:
            # Check existing record
            cursor = await self._db.execute("""
                SELECT high_price, low_price FROM session_levels
                WHERE symbol = ? AND date = ? AND session = ?
            """, (symbol, date, session))
            
            row = await cursor.fetchone()
            
            if row:
                # Update existing
                high_price = max(row["high_price"], price)
                low_price = min(row["low_price"], price)
                high_time = timestamp if price >= row["high_price"] else None
                low_time = timestamp if price <= row["low_price"] else None
                
                if high_time:
                    await self._db.execute("""
                        UPDATE session_levels SET high_price = ?, high_time = ?, volume = volume + ?
                        WHERE symbol = ? AND date = ? AND session = ?
                    """, (high_price, high_time, volume, symbol, date, session))
                
                if low_time:
                    await self._db.execute("""
                        UPDATE session_levels SET low_price = ?, low_time = ?, volume = volume + ?
                        WHERE symbol = ? AND date = ? AND session = ?
                    """, (low_price, low_time, volume, symbol, date, session))
                
                if not high_time and not low_time:
                    await self._db.execute("""
                        UPDATE session_levels SET volume = volume + ?
                        WHERE symbol = ? AND date = ? AND session = ?
                    """, (volume, symbol, date, session))
            else:
                # Insert new
                await self._db.execute("""
                    INSERT INTO session_levels (symbol, date, session, high_price, low_price, high_time, low_time, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (symbol, date, session, price, price, timestamp, timestamp, volume))
            
            await self._db.commit()
    
    async def get_session_levels(self, symbol: str, date: int) -> dict[str, dict[str, Any]]:
        """Get all session levels for a day."""
        if not self._db:
            return {}
        
        cursor = await self._db.execute("""
            SELECT session, high_price, low_price, high_time, low_time, volume
            FROM session_levels
            WHERE symbol = ? AND date = ?
        """, (symbol, date))
        
        rows = await cursor.fetchall()
        return {
            row["session"]: {
                "high": row["high_price"],
                "low": row["low_price"],
                "high_time": row["high_time"],
                "low_time": row["low_time"],
                "volume": row["volume"],
            }
            for row in rows
        }
    
    # Open Interest operations
    async def save_oi_snapshot(
        self,
        symbol: str,
        timestamp: int,
        open_interest: float,
        open_interest_notional: float,
    ) -> None:
        """Save OI snapshot."""
        if not self._db:
            return
        
        async with self._lock:
            await self._db.execute("""
                INSERT OR REPLACE INTO oi_snapshots (symbol, timestamp, open_interest, open_interest_notional)
                VALUES (?, ?, ?, ?)
            """, (symbol, timestamp, open_interest, open_interest_notional))
            await self._db.commit()
    
    async def get_oi_history(
        self,
        symbol: str,
        start_time: int,
        end_time: int,
    ) -> list[dict[str, Any]]:
        """Get OI history for a time range."""
        if not self._db:
            return []
        
        cursor = await self._db.execute("""
            SELECT timestamp, open_interest, open_interest_notional
            FROM oi_snapshots
            WHERE symbol = ? AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp
        """, (symbol, start_time, end_time))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    # Depth delta operations
    async def save_depth_delta(
        self,
        symbol: str,
        timestamp: int,
        bid_volume: float,
        ask_volume: float,
        percent_range: float,
        mid_price: float,
    ) -> None:
        """Save depth delta snapshot."""
        if not self._db:
            return
        
        net_volume = bid_volume - ask_volume
        
        async with self._lock:
            await self._db.execute("""
                INSERT INTO depth_delta (symbol, timestamp, bid_volume, ask_volume, net_volume, percent_range, mid_price)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (symbol, timestamp, bid_volume, ask_volume, net_volume, percent_range, mid_price))
            await self._db.commit()
    
    async def get_depth_delta_history(
        self,
        symbol: str,
        lookback_seconds: int,
    ) -> list[dict[str, Any]]:
        """Get depth delta history."""
        if not self._db:
            return []
        
        start_time = timestamp_ms() - (lookback_seconds * 1000)
        
        cursor = await self._db.execute("""
            SELECT timestamp, bid_volume, ask_volume, net_volume, percent_range, mid_price
            FROM depth_delta
            WHERE symbol = ? AND timestamp >= ?
            ORDER BY timestamp
        """, (symbol, start_time))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
