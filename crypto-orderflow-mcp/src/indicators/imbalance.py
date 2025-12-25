"""
Stacked Imbalance detector.
Identifies areas where buy/sell imbalances stack at consecutive price levels.
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.data.trade_aggregator import FootprintBar, FootprintLevel
from src.utils.logging import get_logger
from src.utils.time_utils import get_utc_now_ms

logger = get_logger(__name__)


@dataclass
class Imbalance:
    """A detected imbalance."""
    
    price: Decimal
    buy_volume: Decimal
    sell_volume: Decimal
    ratio: Decimal
    is_buy_imbalance: bool
    
    def to_dict(self) -> dict:
        return {
            "price": str(self.price),
            "buyVolume": str(self.buy_volume),
            "sellVolume": str(self.sell_volume),
            "ratio": str(self.ratio),
            "type": "buy" if self.is_buy_imbalance else "sell",
        }


@dataclass
class StackedImbalance:
    """A stacked imbalance (consecutive imbalances at multiple levels)."""
    
    start_price: Decimal
    end_price: Decimal
    levels: list[Imbalance]
    is_buy_stack: bool
    timestamp: int
    
    def to_dict(self) -> dict:
        return {
            "startPrice": str(self.start_price),
            "endPrice": str(self.end_price),
            "levelCount": len(self.levels),
            "type": "buy" if self.is_buy_stack else "sell",
            "timestamp": self.timestamp,
            "levels": [level.to_dict() for level in self.levels],
            "totalBuyVolume": str(sum(l.buy_volume for l in self.levels)),
            "totalSellVolume": str(sum(l.sell_volume for l in self.levels)),
        }


@dataclass
class ImbalanceDetector:
    """Detector for stacked imbalances."""
    
    symbol: str
    min_ratio: Decimal = Decimal("3.0")
    min_stack_levels: int = 3
    min_volume: Decimal = Decimal("0.1")
    
    def detect_imbalances(self, bar: FootprintBar) -> list[Imbalance]:
        """Detect all imbalances in a footprint bar."""
        imbalances = []
        
        for price, level in bar.levels.items():
            if level.buy_volume < self.min_volume and level.sell_volume < self.min_volume:
                continue
            
            if level.sell_volume > 0 and level.buy_volume / level.sell_volume >= self.min_ratio:
                imbalances.append(Imbalance(
                    price=price,
                    buy_volume=level.buy_volume,
                    sell_volume=level.sell_volume,
                    ratio=level.buy_volume / level.sell_volume,
                    is_buy_imbalance=True,
                ))
            elif level.buy_volume > 0 and level.sell_volume / level.buy_volume >= self.min_ratio:
                imbalances.append(Imbalance(
                    price=price,
                    buy_volume=level.buy_volume,
                    sell_volume=level.sell_volume,
                    ratio=level.sell_volume / level.buy_volume,
                    is_buy_imbalance=False,
                ))
        
        return imbalances
    
    def detect_stacked_imbalances(self, bar: FootprintBar) -> list[StackedImbalance]:
        """Detect stacked imbalances (consecutive levels with same-direction imbalance)."""
        imbalances = self.detect_imbalances(bar)
        
        if len(imbalances) < self.min_stack_levels:
            return []
        
        imbalances.sort(key=lambda x: x.price)
        
        stacked = []
        
        buy_imbalances = [i for i in imbalances if i.is_buy_imbalance]
        sell_imbalances = [i for i in imbalances if not i.is_buy_imbalance]
        
        for imbalance_list, is_buy in [(buy_imbalances, True), (sell_imbalances, False)]:
            if len(imbalance_list) < self.min_stack_levels:
                continue
            
            current_stack = [imbalance_list[0]]
            
            for i in range(1, len(imbalance_list)):
                current = imbalance_list[i]
                previous = imbalance_list[i - 1]
                
                if self._is_consecutive(previous.price, current.price, bar):
                    current_stack.append(current)
                else:
                    if len(current_stack) >= self.min_stack_levels:
                        stacked.append(StackedImbalance(
                            start_price=current_stack[0].price,
                            end_price=current_stack[-1].price,
                            levels=current_stack.copy(),
                            is_buy_stack=is_buy,
                            timestamp=bar.close_time,
                        ))
                    current_stack = [current]
            
            if len(current_stack) >= self.min_stack_levels:
                stacked.append(StackedImbalance(
                    start_price=current_stack[0].price,
                    end_price=current_stack[-1].price,
                    levels=current_stack.copy(),
                    is_buy_stack=is_buy,
                    timestamp=bar.close_time,
                ))
        
        return stacked
    
    def _is_consecutive(self, price1: Decimal, price2: Decimal, bar: FootprintBar) -> bool:
        """Check if two prices are consecutive tick levels."""
        tick_size = bar.tick_size
        diff = abs(price2 - price1)
        
        return diff <= tick_size * Decimal("2")
    
    def analyze_bars(self, bars: list[FootprintBar]) -> dict:
        """Analyze multiple bars for imbalances."""
        all_stacked = []
        total_imbalances = 0
        buy_imbalances = 0
        sell_imbalances = 0
        
        for bar in bars:
            imbalances = self.detect_imbalances(bar)
            total_imbalances += len(imbalances)
            buy_imbalances += sum(1 for i in imbalances if i.is_buy_imbalance)
            sell_imbalances += sum(1 for i in imbalances if not i.is_buy_imbalance)
            
            stacked = self.detect_stacked_imbalances(bar)
            all_stacked.extend(stacked)
        
        return {
            "symbol": self.symbol,
            "timestamp": get_utc_now_ms(),
            "barsAnalyzed": len(bars),
            "totalImbalances": total_imbalances,
            "buyImbalances": buy_imbalances,
            "sellImbalances": sell_imbalances,
            "stackedImbalances": [s.to_dict() for s in all_stacked],
            "stackedCount": len(all_stacked),
            "buyStacks": sum(1 for s in all_stacked if s.is_buy_stack),
            "sellStacks": sum(1 for s in all_stacked if not s.is_buy_stack),
        }
