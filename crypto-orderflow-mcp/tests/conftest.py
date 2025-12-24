"""
Pytest configuration and fixtures.
"""

import sys
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def sample_trades():
    """Sample trade data for testing."""
    from decimal import Decimal
    from src.data.trade_aggregator import AggregatedTrade
    from src.utils.time_utils import get_utc_now_ms
    
    now = get_utc_now_ms()
    return [
        AggregatedTrade(
            agg_trade_id=1,
            price=Decimal("50000"),
            quantity=Decimal("1.0"),
            first_trade_id=1,
            last_trade_id=1,
            timestamp=now,
            is_buyer_maker=False,
        ),
        AggregatedTrade(
            agg_trade_id=2,
            price=Decimal("50100"),
            quantity=Decimal("2.0"),
            first_trade_id=2,
            last_trade_id=2,
            timestamp=now + 1000,
            is_buyer_maker=True,
        ),
        AggregatedTrade(
            agg_trade_id=3,
            price=Decimal("49900"),
            quantity=Decimal("1.5"),
            first_trade_id=3,
            last_trade_id=3,
            timestamp=now + 2000,
            is_buyer_maker=False,
        ),
    ]


@pytest.fixture
def sample_orderbook_snapshot():
    """Sample orderbook snapshot for testing."""
    return {
        "lastUpdateId": 1000,
        "bids": [
            ["50000.0", "10.0"],
            ["49999.0", "20.0"],
            ["49998.0", "30.0"],
            ["49997.0", "40.0"],
            ["49996.0", "50.0"],
        ],
        "asks": [
            ["50001.0", "10.0"],
            ["50002.0", "20.0"],
            ["50003.0", "30.0"],
            ["50004.0", "40.0"],
            ["50005.0", "50.0"],
        ],
    }


@pytest.fixture
def sample_depth_update():
    """Sample orderbook depth update for testing."""
    return {
        "e": "depthUpdate",
        "E": 1234567890123,
        "T": 1234567890123,
        "s": "BTCUSDT",
        "U": 1001,
        "u": 1001,
        "pu": 1000,
        "b": [
            ["50000.0", "15.0"],  # Update existing
            ["49995.0", "25.0"],  # Add new
        ],
        "a": [
            ["50001.0", "0"],     # Remove
            ["50006.0", "60.0"],  # Add new
        ],
    }
