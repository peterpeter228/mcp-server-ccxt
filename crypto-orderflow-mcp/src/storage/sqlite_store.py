"""
SQLite storage for trade aggregates and indicator data.
Stores footprint aggregates and key levels for historical analysis.
"""

import sys
from pathlib import Path
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
import asyncio
import json
import aiosqlite

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.config import Config
from src.utils.logging import get_logger
from src.utils.time_utils import get_utc_now_ms, get_day_start_ms

logger = get_logger(__name__)


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


@dataclass
class SQLiteStore:
    """SQLite storage for orderflow data."""
    
    db_path: str = "./data/orderflow_cache.db"
    retention_days: int = 7
    
    _db: aiosqlite.Connection | None = None
    _initialized: bool = False
    
    async def initialize(self) -> None:
        """Initialize database connection and tables."""
        if self._initialized:
            return
        
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        self._db = await aiosqlite.connect(self.db_path)
        await self._create_tables()
        self._initialized = True
        
        logger.info("SQLite store initialized", db_path=self.db_path)
    
    async def _create_tables(self) -> None:
        """Create database tables."""
        await self._db.executescript("""
            -- Footprint bars table
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
                price_levels TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(symbol, timeframe, open_time)
            );
            
            CREATE INDEX IF NOT EXISTS idx_footprint_symbol_tf_time 
            ON footprint_bars(symbol, timeframe, open_time);
            
            -- Daily levels table (VWAP, Volume Profile)
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
                trade_count INTEGER,
                data TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(symbol, date)
            );
            
            CREATE INDEX IF NOT EXISTS idx_daily_levels_symbol_date 
            ON daily_levels(symbol, date);
            
            -- Session levels table
            CREATE TABLE IF NOT EXISTS session_levels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                session_name TEXT NOT NULL,
                date TEXT NOT NULL,
                high TEXT,
                low TEXT,
                high_time INTEGER,
                low_time INTEGER,
                start_time INTEGER NOT NULL,
                end_time INTEGER NOT NULL,
                trade_count INTEGER,
                created_at INTEGER NOT NULL,
                UNIQUE(symbol, session_name, date)
            );
            
            CREATE INDEX IF NOT EXISTS idx_session_levels_symbol_session_date 
            ON session_levels(symbol, session_name, date);
            
            -- Liquidations table
            CREATE TABLE IF NOT EXISTS liquidations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price TEXT NOT NULL,
                quantity TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                trade_time INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_liquidations_symbol_time 
            ON liquidations(symbol, timestamp);
        """)
        await self._db.commit()
    
    async def save_footprint_bar(self, bar_data: dict) -> None:
        """Save a footprint bar to database."""
        if not self._initialized:
            await self.initialize()
        
        await self._db.execute("""
            INSERT OR REPLACE INTO footprint_bars 
            (symbol, timeframe, open_time, close_time, open, high, low, close,
             buy_volume, sell_volume, total_volume, delta, trade_count, price_levels, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            bar_data["symbol"],
            bar_data["timeframe"],
            bar_data["openTime"],
            bar_data["closeTime"],
            bar_data["open"],
            bar_data["high"],
            bar_data["low"],
            bar_data["close"],
            bar_data["buyVolume"],
            bar_data["sellVolume"],
            bar_data["totalVolume"],
            bar_data["delta"],
            bar_data["tradeCount"],
            json.dumps(bar_data.get("levels", []), cls=DecimalEncoder),
            get_utc_now_ms(),
        ))
        await self._db.commit()
    
    async def get_footprint_bars(
        self,
        symbol: str,
        timeframe: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get footprint bars from database."""
        if not self._initialized:
            await self.initialize()
        
        query = """
            SELECT symbol, timeframe, open_time, close_time, open, high, low, close,
                   buy_volume, sell_volume, total_volume, delta, trade_count, price_levels
            FROM footprint_bars
            WHERE symbol = ? AND timeframe = ?
        """
        params = [symbol, timeframe]
        
        if start_time:
            query += " AND open_time >= ?"
            params.append(start_time)
        if end_time:
            query += " AND close_time <= ?"
            params.append(end_time)
        
        query += " ORDER BY open_time DESC LIMIT ?"
        params.append(limit)
        
        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        
        result = []
        for row in rows:
            result.append({
                "symbol": row[0],
                "timeframe": row[1],
                "openTime": row[2],
                "closeTime": row[3],
                "open": row[4],
                "high": row[5],
                "low": row[6],
                "close": row[7],
                "buyVolume": row[8],
                "sellVolume": row[9],
                "totalVolume": row[10],
                "delta": row[11],
                "tradeCount": row[12],
                "levels": json.loads(row[13]),
            })
        
        return result
    
    async def save_daily_levels(self, symbol: str, date: str, levels: dict) -> None:
        """Save daily levels to database."""
        if not self._initialized:
            await self.initialize()
        
        await self._db.execute("""
            INSERT OR REPLACE INTO daily_levels 
            (symbol, date, vwap, poc, vah, val, high, low, volume, trade_count, data, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            levels.get("tradeCount"),
            json.dumps(levels, cls=DecimalEncoder),
            get_utc_now_ms(),
        ))
        await self._db.commit()
    
    async def get_daily_levels(self, symbol: str, date: str) -> dict | None:
        """Get daily levels from database."""
        if not self._initialized:
            await self.initialize()
        
        cursor = await self._db.execute(
            "SELECT data FROM daily_levels WHERE symbol = ? AND date = ?",
            (symbol, date),
        )
        row = await cursor.fetchone()
        
        if row:
            return json.loads(row[0])
        return None
    
    async def save_session_level(self, symbol: str, session_name: str, date: str, level: dict) -> None:
        """Save session level to database."""
        if not self._initialized:
            await self.initialize()
        
        await self._db.execute("""
            INSERT OR REPLACE INTO session_levels 
            (symbol, session_name, date, high, low, high_time, low_time, 
             start_time, end_time, trade_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol,
            session_name,
            date,
            level.get("high"),
            level.get("low"),
            level.get("highTime"),
            level.get("lowTime"),
            level.get("startTime"),
            level.get("endTime"),
            level.get("tradeCount"),
            get_utc_now_ms(),
        ))
        await self._db.commit()
    
    async def get_session_levels(self, symbol: str, date: str) -> list[dict]:
        """Get session levels for a date."""
        if not self._initialized:
            await self.initialize()
        
        cursor = await self._db.execute(
            """SELECT session_name, high, low, high_time, low_time, start_time, end_time, trade_count
               FROM session_levels WHERE symbol = ? AND date = ?""",
            (symbol, date),
        )
        rows = await cursor.fetchall()
        
        result = []
        for row in rows:
            result.append({
                "sessionName": row[0],
                "high": row[1],
                "low": row[2],
                "highTime": row[3],
                "lowTime": row[4],
                "startTime": row[5],
                "endTime": row[6],
                "tradeCount": row[7],
            })
        
        return result
    
    async def save_liquidation(self, liquidation: dict) -> None:
        """Save a liquidation event."""
        if not self._initialized:
            await self.initialize()
        
        await self._db.execute("""
            INSERT INTO liquidations 
            (symbol, side, price, quantity, timestamp, trade_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            liquidation["symbol"],
            liquidation["side"],
            liquidation["price"],
            liquidation["quantity"],
            liquidation["timestamp"],
            liquidation.get("tradeTime", liquidation["timestamp"]),
            get_utc_now_ms(),
        ))
        await self._db.commit()
    
    async def get_liquidations(
        self,
        symbol: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get liquidation events."""
        if not self._initialized:
            await self.initialize()
        
        query = "SELECT symbol, side, price, quantity, timestamp, trade_time FROM liquidations WHERE 1=1"
        params = []
        
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        
        result = []
        for row in rows:
            result.append({
                "symbol": row[0],
                "side": row[1],
                "price": row[2],
                "quantity": row[3],
                "timestamp": row[4],
                "tradeTime": row[5],
            })
        
        return result
    
    async def cleanup_old_data(self) -> None:
        """Remove data older than retention period."""
        if not self._initialized:
            await self.initialize()
        
        cutoff_ms = get_utc_now_ms() - (self.retention_days * 24 * 60 * 60 * 1000)
        
        await self._db.execute(
            "DELETE FROM footprint_bars WHERE created_at < ?",
            (cutoff_ms,),
        )
        await self._db.execute(
            "DELETE FROM liquidations WHERE timestamp < ?",
            (cutoff_ms,),
        )
        await self._db.commit()
        
        logger.info("Cleaned up old data", retention_days=self.retention_days)
    
    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None
            self._initialized = False
