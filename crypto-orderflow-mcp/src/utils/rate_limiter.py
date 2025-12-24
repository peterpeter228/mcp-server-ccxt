"""
Rate limiter implementation for API calls.
Uses a sliding window algorithm to track request counts and weights.
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from .logging import get_logger

logger = get_logger(__name__)


@dataclass
class RateLimitEntry:
    """Single rate limit entry."""
    timestamp: float
    weight: int = 1


@dataclass
class RateLimiter:
    """
    Sliding window rate limiter.
    
    Tracks both request count and request weight within a time window.
    """
    
    requests_per_minute: int = 1200
    weight_per_minute: int = 6000
    window_seconds: float = 60.0
    
    _entries: Deque[RateLimitEntry] = field(default_factory=deque)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    
    def _cleanup_old_entries(self) -> None:
        """Remove entries outside the window."""
        cutoff = time.monotonic() - self.window_seconds
        while self._entries and self._entries[0].timestamp < cutoff:
            self._entries.popleft()
    
    def _current_count(self) -> int:
        """Get current request count in window."""
        return len(self._entries)
    
    def _current_weight(self) -> int:
        """Get current total weight in window."""
        return sum(e.weight for e in self._entries)
    
    async def acquire(self, weight: int = 1) -> None:
        """
        Acquire permission to make a request.
        
        Waits if rate limit would be exceeded.
        
        Args:
            weight: Weight of this request (default 1)
        """
        async with self._lock:
            while True:
                self._cleanup_old_entries()
                
                current_count = self._current_count()
                current_weight = self._current_weight()
                
                # Check if we can proceed
                if (current_count < self.requests_per_minute and 
                    current_weight + weight <= self.weight_per_minute):
                    # Add entry and proceed
                    self._entries.append(RateLimitEntry(
                        timestamp=time.monotonic(),
                        weight=weight
                    ))
                    return
                
                # Calculate wait time
                if self._entries:
                    oldest = self._entries[0]
                    wait_time = oldest.timestamp + self.window_seconds - time.monotonic()
                    if wait_time > 0:
                        logger.debug(
                            "Rate limit reached, waiting",
                            wait_seconds=wait_time,
                            current_count=current_count,
                            current_weight=current_weight,
                        )
                        # Release lock while waiting
                        self._lock.release()
                        try:
                            await asyncio.sleep(min(wait_time, 1.0))
                        finally:
                            await self._lock.acquire()
                else:
                    # No entries but somehow still limited, brief wait
                    self._lock.release()
                    try:
                        await asyncio.sleep(0.1)
                    finally:
                        await self._lock.acquire()
    
    def get_status(self) -> dict:
        """Get current rate limiter status."""
        self._cleanup_old_entries()
        return {
            "requests_used": self._current_count(),
            "requests_limit": self.requests_per_minute,
            "weight_used": self._current_weight(),
            "weight_limit": self.weight_per_minute,
            "window_seconds": self.window_seconds,
        }
    
    async def reset(self) -> None:
        """Reset the rate limiter."""
        async with self._lock:
            self._entries.clear()
