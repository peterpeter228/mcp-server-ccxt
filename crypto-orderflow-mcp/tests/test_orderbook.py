"""
Tests for Orderbook management and reconstruction.
"""

import pytest
from decimal import Decimal

from src.data.orderbook import Orderbook, OrderbookManager


class TestOrderbook:
    """Test Orderbook data structure."""
    
    def test_orderbook_initialization(self):
        """Test orderbook initializes correctly."""
        ob = Orderbook(symbol="BTCUSDT")
        
        assert ob.symbol == "BTCUSDT"
        assert len(ob.bids) == 0
        assert len(ob.asks) == 0
        assert ob.last_update_id == 0
        assert ob.is_synced is False
    
    def test_apply_snapshot(self):
        """Test applying orderbook snapshot."""
        ob = Orderbook(symbol="BTCUSDT")
        
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [
                ["50000.0", "1.0"],
                ["49999.0", "2.0"],
                ["49998.0", "3.0"],
            ],
            "asks": [
                ["50001.0", "1.5"],
                ["50002.0", "2.5"],
                ["50003.0", "3.5"],
            ],
        }
        
        ob.apply_snapshot(snapshot)
        
        assert ob.last_update_id == 1000
        assert len(ob.bids) == 3
        assert len(ob.asks) == 3
    
    def test_get_best_bid(self):
        """Test getting best bid."""
        ob = Orderbook(symbol="BTCUSDT")
        
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [
                ["50000.0", "1.0"],
                ["49999.0", "2.0"],
            ],
            "asks": [],
        }
        
        ob.apply_snapshot(snapshot)
        
        best_bid = ob.get_best_bid()
        assert best_bid is not None
        assert best_bid[0] == Decimal("50000.0")
        assert best_bid[1] == Decimal("1.0")
    
    def test_get_best_ask(self):
        """Test getting best ask."""
        ob = Orderbook(symbol="BTCUSDT")
        
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [],
            "asks": [
                ["50001.0", "1.5"],
                ["50002.0", "2.5"],
            ],
        }
        
        ob.apply_snapshot(snapshot)
        
        best_ask = ob.get_best_ask()
        assert best_ask is not None
        assert best_ask[0] == Decimal("50001.0")
        assert best_ask[1] == Decimal("1.5")
    
    def test_get_mid_price(self):
        """Test mid price calculation."""
        ob = Orderbook(symbol="BTCUSDT")
        
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [["50000.0", "1.0"]],
            "asks": [["50002.0", "1.0"]],
        }
        
        ob.apply_snapshot(snapshot)
        
        mid = ob.get_mid_price()
        assert mid == Decimal("50001.0")
    
    def test_get_spread(self):
        """Test spread calculation."""
        ob = Orderbook(symbol="BTCUSDT")
        
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [["50000.0", "1.0"]],
            "asks": [["50002.0", "1.0"]],
        }
        
        ob.apply_snapshot(snapshot)
        
        spread = ob.get_spread()
        assert spread == Decimal("2.0")
    
    def test_apply_diff_add_levels(self):
        """Test applying diff that adds levels."""
        ob = Orderbook(symbol="BTCUSDT")
        
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [["50000.0", "1.0"]],
            "asks": [["50001.0", "1.0"]],
        }
        ob.apply_snapshot(snapshot)
        
        diff = {
            "U": 1001,  # First update ID
            "u": 1001,  # Final update ID
            "E": 1234567890,
            "b": [["49999.0", "2.0"]],  # Add bid
            "a": [["50002.0", "2.0"]],  # Add ask
        }
        
        result = ob.apply_diff(diff)
        assert result is True
        assert len(ob.bids) == 2
        assert len(ob.asks) == 2
    
    def test_apply_diff_remove_levels(self):
        """Test applying diff that removes levels (qty=0)."""
        ob = Orderbook(symbol="BTCUSDT")
        
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [["50000.0", "1.0"], ["49999.0", "2.0"]],
            "asks": [["50001.0", "1.0"]],
        }
        ob.apply_snapshot(snapshot)
        
        diff = {
            "U": 1001,
            "u": 1001,
            "E": 1234567890,
            "b": [["49999.0", "0"]],  # Remove level
            "a": [],
        }
        
        result = ob.apply_diff(diff)
        assert result is True
        assert len(ob.bids) == 1
    
    def test_apply_diff_update_levels(self):
        """Test applying diff that updates existing levels."""
        ob = Orderbook(symbol="BTCUSDT")
        
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [["50000.0", "1.0"]],
            "asks": [["50001.0", "1.0"]],
        }
        ob.apply_snapshot(snapshot)
        
        diff = {
            "U": 1001,
            "u": 1001,
            "E": 1234567890,
            "b": [["50000.0", "5.0"]],  # Update existing
            "a": [],
        }
        
        ob.apply_diff(diff)
        
        best_bid = ob.get_best_bid()
        assert best_bid is not None
        assert best_bid[1] == Decimal("5.0")
    
    def test_apply_diff_gap_detection(self):
        """Test gap detection in update sequence."""
        ob = Orderbook(symbol="BTCUSDT")
        
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [["50000.0", "1.0"]],
            "asks": [["50001.0", "1.0"]],
        }
        ob.apply_snapshot(snapshot)
        
        # First valid update
        diff1 = {
            "U": 1001,
            "u": 1001,
            "E": 1234567890,
            "b": [],
            "a": [],
        }
        ob.apply_diff(diff1)
        
        # Gap: skipping 1002
        diff_with_gap = {
            "U": 1003,
            "u": 1003,
            "E": 1234567890,
            "b": [],
            "a": [],
        }
        
        result = ob.apply_diff(diff_with_gap)
        assert result is False
        assert ob.is_synced is False
    
    def test_drop_old_events(self):
        """Test that old events are dropped."""
        ob = Orderbook(symbol="BTCUSDT")
        
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [["50000.0", "1.0"]],
            "asks": [],
        }
        ob.apply_snapshot(snapshot)
        
        # Old event should be dropped
        old_diff = {
            "U": 999,
            "u": 999,
            "E": 1234567890,
            "b": [["50000.0", "10.0"]],
            "a": [],
        }
        
        result = ob.apply_diff(old_diff)
        assert result is False
        
        # Verify bid wasn't changed
        best_bid = ob.get_best_bid()
        assert best_bid[1] == Decimal("1.0")


class TestOrderbookDepth:
    """Test orderbook depth calculations."""
    
    def test_get_depth_at_percent(self):
        """Test depth calculation within percent range."""
        ob = Orderbook(symbol="BTCUSDT")
        
        # Create orderbook with mid price around 50000
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [
                ["50000.0", "10.0"],  # Within 1%
                ["49900.0", "20.0"],  # Within 1%
                ["49500.0", "30.0"],  # Within 1%
                ["49000.0", "40.0"],  # Outside 1%
            ],
            "asks": [
                ["50001.0", "10.0"],  # Within 1%
                ["50100.0", "20.0"],  # Within 1%
                ["50500.0", "30.0"],  # Within 1%
                ["51000.0", "40.0"],  # Outside 1%
            ],
        }
        ob.apply_snapshot(snapshot)
        
        depth = ob.get_depth_at_percent(1.0)
        
        assert "bid_volume" in depth
        assert "ask_volume" in depth
        assert "net" in depth
        assert depth["bid_volume"] > 0
        assert depth["ask_volume"] > 0
    
    def test_get_bids_list(self):
        """Test getting bids as list."""
        ob = Orderbook(symbol="BTCUSDT")
        
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [
                ["50000.0", "1.0"],
                ["49999.0", "2.0"],
                ["49998.0", "3.0"],
            ],
            "asks": [],
        }
        ob.apply_snapshot(snapshot)
        
        bids = ob.get_bids_list(limit=2)
        
        assert len(bids) == 2
        # Should be sorted highest first
        assert bids[0][0] == Decimal("50000.0")
        assert bids[1][0] == Decimal("49999.0")
    
    def test_get_asks_list(self):
        """Test getting asks as list."""
        ob = Orderbook(symbol="BTCUSDT")
        
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [],
            "asks": [
                ["50001.0", "1.0"],
                ["50002.0", "2.0"],
                ["50003.0", "3.0"],
            ],
        }
        ob.apply_snapshot(snapshot)
        
        asks = ob.get_asks_list(limit=2)
        
        assert len(asks) == 2
        # Should be sorted lowest first
        assert asks[0][0] == Decimal("50001.0")
        assert asks[1][0] == Decimal("50002.0")
    
    def test_to_dict(self):
        """Test orderbook serialization."""
        ob = Orderbook(symbol="BTCUSDT")
        
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [["50000.0", "1.0"]],
            "asks": [["50001.0", "1.0"]],
        }
        ob.apply_snapshot(snapshot)
        
        data = ob.to_dict(limit=10)
        
        assert data["symbol"] == "BTCUSDT"
        assert data["lastUpdateId"] == 1000
        assert "bids" in data
        assert "asks" in data
        assert "bestBid" in data
        assert "bestAsk" in data
        assert "midPrice" in data
        assert "spread" in data


class TestOrderbookSync:
    """Test orderbook synchronization logic."""
    
    def test_first_sync_after_snapshot(self):
        """Test first sync event after snapshot."""
        ob = Orderbook(symbol="BTCUSDT")
        
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [["50000.0", "1.0"]],
            "asks": [["50001.0", "1.0"]],
        }
        ob.apply_snapshot(snapshot)
        
        # First update that bridges snapshot
        # U <= lastUpdateId+1 <= u
        diff = {
            "U": 1000,  # First update ID
            "u": 1002,  # Final update ID
            "E": 1234567890,
            "b": [],
            "a": [],
        }
        
        result = ob.apply_diff(diff)
        assert result is True
        assert ob.is_synced is True
    
    def test_sync_requires_bridge(self):
        """Test sync requires bridging update."""
        ob = Orderbook(symbol="BTCUSDT")
        
        snapshot = {
            "lastUpdateId": 1000,
            "bids": [["50000.0", "1.0"]],
            "asks": [],
        }
        ob.apply_snapshot(snapshot)
        
        # Update that doesn't bridge (starts too late)
        diff = {
            "U": 1005,  # First update ID too high
            "u": 1006,
            "E": 1234567890,
            "b": [],
            "a": [],
        }
        
        result = ob.apply_diff(diff)
        assert result is False
        assert ob.is_synced is False
