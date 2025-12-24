"""
In-memory cache for frequently accessed data.
"""

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, TypeVar

from ..utils import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


@dataclass
class CacheEntry:
    """Single cache entry with TTL."""
    value: Any
    expires_at: float
    
    @property
    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at


@dataclass
class DataCache:
    """
    LRU cache with TTL support.
    
    Used for caching:
    - Market snapshots
    - Key levels
    - Computed indicators
    """
    
    max_size: int = 1000
    default_ttl: float = 60.0  # seconds
    
    _cache: OrderedDict[str, CacheEntry] = field(default_factory=OrderedDict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _hits: int = 0
    _misses: int = 0
    
    def _evict_expired(self) -> None:
        """Remove expired entries."""
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.is_expired
        ]
        for key in expired_keys:
            del self._cache[key]
    
    def _evict_lru(self) -> None:
        """Remove least recently used entries if over capacity."""
        while len(self._cache) > self.max_size:
            self._cache.popitem(last=False)
    
    async def get(self, key: str) -> Any | None:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        async with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._misses += 1
                return None
            
            if entry.is_expired:
                del self._cache[key]
                self._misses += 1
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            return entry.value
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (uses default if None)
        """
        async with self._lock:
            self._evict_expired()
            
            expires_at = time.monotonic() + (ttl or self.default_ttl)
            self._cache[key] = CacheEntry(value=value, expires_at=expires_at)
            self._cache.move_to_end(key)
            
            self._evict_lru()
    
    async def delete(self, key: str) -> bool:
        """
        Delete entry from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if entry was deleted, False if not found
        """
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    async def clear(self) -> None:
        """Clear all cache entries."""
        async with self._lock:
            self._cache.clear()
    
    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Coroutine[Any, Any, T]],
        ttl: float | None = None,
    ) -> T:
        """
        Get value from cache or compute and cache it.
        
        Args:
            key: Cache key
            factory: Async function to compute value if not cached
            ttl: Time to live in seconds
            
        Returns:
            Cached or computed value
        """
        value = await self.get(key)
        if value is not None:
            return value
        
        # Compute new value
        value = await factory()
        await self.set(key, value, ttl)
        return value
    
    def get_stats(self) -> dict:
        """Get cache statistics."""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0
        
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
        }
    
    async def cleanup(self) -> int:
        """
        Remove expired entries.
        
        Returns:
            Number of entries removed
        """
        async with self._lock:
            before = len(self._cache)
            self._evict_expired()
            return before - len(self._cache)


# Global cache instance
_global_cache: DataCache | None = None


def get_cache() -> DataCache:
    """Get or create global cache instance."""
    global _global_cache
    if _global_cache is None:
        _global_cache = DataCache()
    return _global_cache
