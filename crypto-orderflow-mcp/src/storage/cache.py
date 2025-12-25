"""
In-memory cache for frequently accessed data.
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any
import asyncio
import time
from collections import OrderedDict

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CacheEntry:
    """A single cache entry with TTL."""
    value: Any
    expires_at: float
    
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


@dataclass
class DataCache:
    """In-memory LRU cache with TTL."""
    
    max_size: int = 1000
    default_ttl: int = 60
    
    _cache: OrderedDict = field(default_factory=OrderedDict, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    
    def __post_init__(self):
        self._cache = OrderedDict()
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Any | None:
        """Get value from cache."""
        async with self._lock:
            if key not in self._cache:
                return None
            
            entry = self._cache[key]
            if entry.is_expired():
                del self._cache[key]
                return None
            
            self._cache.move_to_end(key)
            return entry.value
    
    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set value in cache."""
        if ttl is None:
            ttl = self.default_ttl
        
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
            
            self._cache[key] = CacheEntry(
                value=value,
                expires_at=time.time() + ttl,
            )
            
            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)
    
    async def delete(self, key: str) -> None:
        """Delete value from cache."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
    
    async def clear(self) -> None:
        """Clear all cache entries."""
        async with self._lock:
            self._cache.clear()
    
    async def cleanup_expired(self) -> int:
        """Remove expired entries and return count removed."""
        async with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired()
            ]
            
            for key in expired_keys:
                del self._cache[key]
            
            return len(expired_keys)
    
    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)
    
    async def get_or_set(self, key: str, factory, ttl: int | None = None) -> Any:
        """Get value from cache or compute and set it."""
        value = await self.get(key)
        if value is not None:
            return value
        
        if asyncio.iscoroutinefunction(factory):
            value = await factory()
        else:
            value = factory()
        
        await self.set(key, value, ttl)
        return value
