"""
Configuration management for Crypto Orderflow MCP Server.
All settings are loaded from environment variables with sensible defaults.
"""

import os
from dataclasses import dataclass, field
from datetime import time
from typing import Any
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()


def _get_env(key: str, default: str = "") -> str:
    """Get environment variable with default."""
    return os.getenv(key, default)


def _get_env_int(key: str, default: int) -> int:
    """Get integer environment variable."""
    return int(_get_env(key, str(default)))


def _get_env_float(key: str, default: float) -> float:
    """Get float environment variable."""
    return float(_get_env(key, str(default)))


def _get_env_bool(key: str, default: bool) -> bool:
    """Get boolean environment variable."""
    val = _get_env(key, str(default)).lower()
    return val in ("true", "1", "yes", "on")


def _get_env_list(key: str, default: list[str]) -> list[str]:
    """Get list environment variable (comma separated)."""
    val = _get_env(key, "")
    if not val:
        return default
    return [s.strip() for s in val.split(",") if s.strip()]


def _parse_time(time_str: str) -> time:
    """Parse HH:MM time string to datetime.time."""
    parts = time_str.split(":")
    return time(hour=int(parts[0]), minute=int(parts[1]))


@dataclass
class SessionConfig:
    """Trading session configuration."""
    name: str
    start: time
    end: time


@dataclass
class Config:
    """Main configuration class."""
    
    # Binance API
    binance_rest_url: str = field(
        default_factory=lambda: _get_env("BINANCE_REST_URL", "https://fapi.binance.com")
    )
    binance_ws_url: str = field(
        default_factory=lambda: _get_env("BINANCE_WS_URL", "wss://fstream.binance.com")
    )
    
    # Symbols
    symbols: list[str] = field(
        default_factory=lambda: _get_env_list("SYMBOLS", ["BTCUSDT", "ETHUSDT"])
    )
    
    # Server
    host: str = field(default_factory=lambda: _get_env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _get_env_int("PORT", 8000))
    
    # Database
    cache_db_path: str = field(
        default_factory=lambda: _get_env("CACHE_DB_PATH", "./data/orderflow_cache.db")
    )
    
    # Cache settings
    trade_cache_days: int = field(
        default_factory=lambda: _get_env_int("TRADE_CACHE_DAYS", 7)
    )
    footprint_aggregation_interval: int = field(
        default_factory=lambda: _get_env_int("FOOTPRINT_AGGREGATION_INTERVAL", 60)
    )
    
    # Orderbook
    orderbook_depth_levels: int = field(
        default_factory=lambda: _get_env_int("ORDERBOOK_DEPTH_LEVELS", 1000)
    )
    orderbook_sync_interval: int = field(
        default_factory=lambda: _get_env_int("ORDERBOOK_SYNC_INTERVAL", 300)
    )
    
    # Volume Profile
    value_area_percent: int = field(
        default_factory=lambda: _get_env_int("VALUE_AREA_PERCENT", 70)
    )
    
    # Tick sizes per symbol
    tick_sizes: dict[str, float] = field(default_factory=dict)
    
    # Imbalance
    imbalance_ratio_threshold: float = field(
        default_factory=lambda: _get_env_float("IMBALANCE_RATIO_THRESHOLD", 3.0)
    )
    imbalance_consecutive_count: int = field(
        default_factory=lambda: _get_env_int("IMBALANCE_CONSECUTIVE_COUNT", 3)
    )
    
    # Depth Delta
    depth_delta_percent: float = field(
        default_factory=lambda: _get_env_float("DEPTH_DELTA_PERCENT", 1.0)
    )
    depth_delta_interval_sec: int = field(
        default_factory=lambda: _get_env_int("DEPTH_DELTA_INTERVAL_SEC", 5)
    )
    
    # Rate Limiting
    rate_limit_requests_per_minute: int = field(
        default_factory=lambda: _get_env_int("RATE_LIMIT_REQUESTS_PER_MINUTE", 1200)
    )
    rate_limit_weight_per_minute: int = field(
        default_factory=lambda: _get_env_int("RATE_LIMIT_WEIGHT_PER_MINUTE", 6000)
    )
    
    # Logging
    log_level: str = field(default_factory=lambda: _get_env("LOG_LEVEL", "INFO"))
    log_format: str = field(default_factory=lambda: _get_env("LOG_FORMAT", "json"))
    
    # Order placement (disabled by default)
    enable_order_placement: bool = field(
        default_factory=lambda: _get_env_bool("ENABLE_ORDER_PLACEMENT", False)
    )
    binance_api_key: str = field(default_factory=lambda: _get_env("BINANCE_API_KEY", ""))
    binance_api_secret: str = field(default_factory=lambda: _get_env("BINANCE_API_SECRET", ""))
    
    # Sessions (parsed from env)
    sessions: list[SessionConfig] = field(default_factory=list)
    
    def __post_init__(self) -> None:
        """Initialize derived settings."""
        # Set tick sizes
        self.tick_sizes = {
            "BTCUSDT": _get_env_float("TICK_SIZE_BTCUSDT", 0.1),
            "ETHUSDT": _get_env_float("TICK_SIZE_ETHUSDT", 0.01),
        }
        
        # Initialize sessions
        self.sessions = [
            SessionConfig(
                name="Tokyo",
                start=_parse_time(_get_env("SESSION_TOKYO_START", "00:00")),
                end=_parse_time(_get_env("SESSION_TOKYO_END", "09:00")),
            ),
            SessionConfig(
                name="London",
                start=_parse_time(_get_env("SESSION_LONDON_START", "07:00")),
                end=_parse_time(_get_env("SESSION_LONDON_END", "16:00")),
            ),
            SessionConfig(
                name="NY",
                start=_parse_time(_get_env("SESSION_NY_START", "13:00")),
                end=_parse_time(_get_env("SESSION_NY_END", "22:00")),
            ),
        ]
    
    def get_tick_size(self, symbol: str) -> float:
        """Get tick size for symbol, default to 0.01."""
        return self.tick_sizes.get(symbol, 0.01)
    
    def get_session(self, name: str) -> SessionConfig | None:
        """Get session by name."""
        for session in self.sessions:
            if session.name.lower() == name.lower():
                return session
        return None


# Global config instance
_config: Config | None = None


def get_config() -> Config:
    """Get or create global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config() -> Config:
    """Reload configuration from environment."""
    global _config
    load_dotenv(override=True)
    _config = Config()
    return _config
