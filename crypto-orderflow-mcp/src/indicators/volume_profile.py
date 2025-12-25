"""Volume Profile calculator (POC, VAH, VAL)."""

from typing import Any
from collections import defaultdict

from src.data.storage import DataStorage
from src.config import get_settings
from src.utils import get_logger, timestamp_ms, round_to_tick
from src.utils.helpers import get_day_start_ms, get_yesterday_range_ms


class VolumeProfileCalculator:
    """Calculate Volume Profile with POC, VAH, VAL."""
    
    def __init__(self, storage: DataStorage):
        self.storage = storage
        self.settings = get_settings()
        self.logger = get_logger("indicators.volume_profile")
        
        # In-memory volume by price level for current day
        self._profiles: dict[str, dict[float, float]] = {}  # symbol -> {price_level -> volume}
    
    async def update(
        self,
        symbol: str,
        price: float,
        volume: float,
        buy_volume: float,
        sell_volume: float,
        timestamp: int,
    ) -> None:
        """Update volume profile with new trade data.
        
        Args:
            symbol: Trading pair symbol
            price: Trade price
            volume: Total trade volume
            buy_volume: Buy volume
            sell_volume: Sell volume
            timestamp: Trade timestamp in milliseconds
        """
        symbol = symbol.upper()
        tick_size = self.settings.get_tick_size(symbol)
        price_level = round_to_tick(price, tick_size)
        date = get_day_start_ms(timestamp)
        
        # Update in-memory profile
        if symbol not in self._profiles:
            self._profiles[symbol] = defaultdict(float)
        
        self._profiles[symbol][price_level] += volume
        
        # Persist to storage
        notional = price * volume
        await self.storage.upsert_daily_trade(
            symbol=symbol,
            date=date,
            price_level=price_level,
            volume=volume,
            buy_volume=buy_volume,
            sell_volume=sell_volume,
            notional=notional,
        )
    
    def calculate_poc(self, profile: dict[float, float]) -> float | None:
        """Calculate Point of Control (price level with highest volume).
        
        Args:
            profile: Dict mapping price levels to volumes
        
        Returns:
            POC price level or None
        """
        if not profile:
            return None
        
        return max(profile.keys(), key=lambda p: profile[p])
    
    def calculate_value_area(
        self,
        profile: dict[float, float],
        percentage: float = 70.0,
    ) -> tuple[float | None, float | None, float | None]:
        """Calculate Value Area (VAH, VAL) containing given percentage of volume.
        
        Args:
            profile: Dict mapping price levels to volumes
            percentage: Percentage of volume to include (default 70%)
        
        Returns:
            Tuple of (POC, VAH, VAL) or (None, None, None)
        """
        if not profile:
            return None, None, None
        
        total_volume = sum(profile.values())
        target_volume = total_volume * (percentage / 100)
        
        # Get POC
        poc = self.calculate_poc(profile)
        if poc is None:
            return None, None, None
        
        # Sort price levels
        sorted_prices = sorted(profile.keys())
        poc_idx = sorted_prices.index(poc)
        
        # Expand from POC
        vah_idx = poc_idx
        val_idx = poc_idx
        current_volume = profile[poc]
        
        while current_volume < target_volume:
            # Check which direction to expand
            upper_vol = profile.get(sorted_prices[vah_idx + 1], 0) if vah_idx + 1 < len(sorted_prices) else 0
            lower_vol = profile.get(sorted_prices[val_idx - 1], 0) if val_idx > 0 else 0
            
            if upper_vol == 0 and lower_vol == 0:
                break
            
            if upper_vol >= lower_vol and vah_idx + 1 < len(sorted_prices):
                vah_idx += 1
                current_volume += profile[sorted_prices[vah_idx]]
            elif val_idx > 0:
                val_idx -= 1
                current_volume += profile[sorted_prices[val_idx]]
            elif vah_idx + 1 < len(sorted_prices):
                vah_idx += 1
                current_volume += profile[sorted_prices[vah_idx]]
            else:
                break
        
        vah = sorted_prices[vah_idx]
        val = sorted_prices[val_idx]
        
        return poc, vah, val
    
    async def get_today_profile(self, symbol: str) -> dict[float, float]:
        """Get today's volume profile from memory."""
        symbol = symbol.upper()
        return dict(self._profiles.get(symbol, {}))
    
    async def get_yesterday_profile(self, symbol: str) -> dict[float, float]:
        """Get yesterday's volume profile from storage."""
        symbol = symbol.upper()
        yesterday = get_day_start_ms(timestamp_ms()) - 86_400_000
        
        rows = await self.storage.get_daily_trades(symbol, yesterday)
        
        profile: dict[float, float] = {}
        for row in rows:
            profile[row["price_level"]] = row["volume"]
        
        return profile
    
    async def get_key_levels(self, symbol: str, date: int | None = None) -> dict[str, Any]:
        """Get volume profile key levels.
        
        Args:
            symbol: Trading pair symbol
            date: Date to calculate for (defaults to today)
        
        Returns:
            Dict with dPOC, dVAH, dVAL, pdPOC, pdVAH, pdVAL
        """
        symbol = symbol.upper()
        
        # Today's developing profile
        today_profile = await self.get_today_profile(symbol)
        d_poc, d_vah, d_val = self.calculate_value_area(today_profile)
        
        # Yesterday's profile
        yesterday_profile = await self.get_yesterday_profile(symbol)
        pd_poc, pd_vah, pd_val = self.calculate_value_area(yesterday_profile)
        
        return {
            "symbol": symbol,
            "timestamp": timestamp_ms(),
            "developing": {
                "POC": d_poc,
                "VAH": d_vah,
                "VAL": d_val,
                "totalVolume": sum(today_profile.values()) if today_profile else 0,
                "priceLevels": len(today_profile),
            },
            "previousDay": {
                "POC": pd_poc,
                "VAH": pd_vah,
                "VAL": pd_val,
                "totalVolume": sum(yesterday_profile.values()) if yesterday_profile else 0,
                "priceLevels": len(yesterday_profile),
            },
            "unit": "USDT",
        }
    
    def reset_day(self, symbol: str) -> None:
        """Reset daily profile (called at day rollover)."""
        symbol = symbol.upper()
        self._profiles[symbol] = defaultdict(float)
        self.logger.info("profile_reset", symbol=symbol)


def calculate_volume_profile(
    trades: list[dict[str, Any]],
    tick_size: float,
) -> dict[float, dict[str, float]]:
    """Calculate volume profile from trades.
    
    Args:
        trades: List of trade dicts with 'price', 'volume', 'buy_volume', 'sell_volume'
        tick_size: Price tick size for aggregation
    
    Returns:
        Dict mapping price levels to volume breakdown
    """
    profile: dict[float, dict[str, float]] = defaultdict(
        lambda: {"volume": 0, "buy_volume": 0, "sell_volume": 0, "delta": 0}
    )
    
    for trade in trades:
        price_level = round_to_tick(trade["price"], tick_size)
        buy_vol = trade.get("buy_volume", 0)
        sell_vol = trade.get("sell_volume", 0)
        
        profile[price_level]["volume"] += trade["volume"]
        profile[price_level]["buy_volume"] += buy_vol
        profile[price_level]["sell_volume"] += sell_vol
        profile[price_level]["delta"] += buy_vol - sell_vol
    
    return dict(profile)
