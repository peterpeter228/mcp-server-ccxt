"""Configuration management for Crypto Orderflow MCP Server."""

import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionTime:
    """Parse session time string like '00:00-09:00' into start/end hours."""
    
    def __init__(self, time_str: str):
        parts = time_str.split("-")
        start_parts = parts[0].split(":")
        end_parts = parts[1].split(":")
        self.start_hour = int(start_parts[0])
        self.start_minute = int(start_parts[1])
        self.end_hour = int(end_parts[0])
        self.end_minute = int(end_parts[1])
    
    @property
    def start_minutes(self) -> int:
        return self.start_hour * 60 + self.start_minute
    
    @property
    def end_minutes(self) -> int:
        return self.end_hour * 60 + self.end_minute


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Server Settings
    mcp_host: str = Field(default="0.0.0.0", description="MCP Server host")
    mcp_port: int = Field(default=8022, description="MCP Server port")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    debug: bool = Field(default=False)
    
    # Binance API
    binance_rest_url: str = Field(default="https://fapi.binance.com")
    binance_ws_url: str = Field(default="wss://fstream.binance.com")
    binance_api_key: str | None = Field(default=None)
    binance_api_secret: str | None = Field(default=None)
    
    # Symbols
    symbols: str = Field(default="BTCUSDT,ETHUSDT")
    
    # Database
    cache_db_path: str = Field(default="./data/orderflow_cache.db")
    data_retention_days: int = Field(default=7)
    
    # Session Times (UTC)
    tokyo_session: str = Field(default="00:00-09:00")
    london_session: str = Field(default="07:00-16:00")
    ny_session: str = Field(default="13:00-22:00")
    
    # Orderflow Configuration
    default_timeframe: str = Field(default="1m")
    footprint_tick_size_btc: float = Field(default=0.1)
    footprint_tick_size_eth: float = Field(default=0.01)
    imbalance_ratio_threshold: float = Field(default=3.0)
    imbalance_consecutive_levels: int = Field(default=3)
    
    # Orderbook Configuration
    orderbook_depth_percent: float = Field(default=1.0)
    orderbook_update_interval_sec: int = Field(default=5)
    orderbook_snapshot_limit: int = Field(default=1000)
    
    # Liquidation
    liquidation_cache_size: int = Field(default=1000)
    
    # Rate Limiting
    rest_rate_limit_per_min: int = Field(default=1200)
    ws_reconnect_delay_sec: int = Field(default=5)
    ws_max_reconnect_attempts: int = Field(default=10)
    
    @property
    def symbol_list(self) -> list[str]:
        """Get symbols as list."""
        return [s.strip().upper() for s in self.symbols.split(",")]
    
    @property
    def tokyo(self) -> SessionTime:
        return SessionTime(self.tokyo_session)
    
    @property
    def london(self) -> SessionTime:
        return SessionTime(self.london_session)
    
    @property
    def ny(self) -> SessionTime:
        return SessionTime(self.ny_session)
    
    def get_tick_size(self, symbol: str) -> float:
        """Get tick size for footprint aggregation based on symbol."""
        symbol = symbol.upper()
        if "BTC" in symbol:
            return self.footprint_tick_size_btc
        elif "ETH" in symbol:
            return self.footprint_tick_size_eth
        else:
            return 0.1  # Default
    
    def ensure_data_dir(self) -> Path:
        """Ensure data directory exists."""
        db_path = Path(self.cache_db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return db_path


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get settings instance."""
    return settings
