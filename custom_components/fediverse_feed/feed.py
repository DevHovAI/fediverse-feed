"""Fetches feeds on demand for the card and keeps each one for CACHE_TTL."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from homeassistant.util import dt as dt_util

from .api import FeedClient, FeedError, Post, Query
from .const import CACHE_TTL

_LOGGER = logging.getLogger(__name__)


class FeedCache:
    def __init__(self, client: FeedClient) -> None:
        self.client = client
        self._entries: dict[tuple, tuple[datetime, list[Post]]] = {}
        self._locks: dict[tuple, asyncio.Lock] = {}

    async def posts(self, q: Query) -> list[Post]:
        key = q.key
        lock = self._locks.setdefault(key, asyncio.Lock())
        # One request per feed, even if several cards ask at the same moment.
        async with lock:
            cached = self._entries.get(key)
            if cached and dt_util.utcnow() - cached[0] < CACHE_TTL:
                return cached[1]
            try:
                posts = await self.client.posts(q)
            except FeedError:
                if cached:
                    # Keep showing the last good result while the server is unreachable.
                    _LOGGER.debug("Fetching %s failed, using the cached result", key, exc_info=True)
                    return cached[1]
                raise
            self._entries[key] = (dt_util.utcnow(), posts)
            return posts
