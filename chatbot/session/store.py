"""Redis-backed conversation state with a sliding in-process fallback."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from redis.asyncio import Redis

from config import Settings, get_settings

from .state import ConversationState

logger = logging.getLogger(__name__)


class SessionStore:
    """Persist session state in Redis and degrade safely to process memory.

    Redis keys and in-memory entries both use a sliding TTL: each successful read extends
    the lifetime. Once a configured Redis connection fails, this instance stays on the
    local fallback so a request does not alternate between two divergent state sources.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        *,
        ttl_seconds: int | None = None,
        key_prefix: str | None = None,
        timeout_seconds: float | None = None,
        redis_client: Any | None = None,
        settings: Settings | None = None,
    ) -> None:
        config = settings or get_settings()
        self.ttl_seconds = ttl_seconds or config.session_ttl_seconds
        self.key_prefix = key_prefix if key_prefix is not None else config.redis_key_prefix
        self.timeout_seconds = timeout_seconds or config.redis_timeout_seconds
        self._memory: dict[str, tuple[float, str]] = {}
        self._memory_lock = asyncio.Lock()
        self._redis_failed = False
        self._owns_redis = redis_client is None

        effective_url = redis_url if redis_url is not None else config.redis_url
        if redis_client is not None:
            self._redis: Any | None = redis_client
        elif effective_url:
            self._redis = Redis.from_url(
                effective_url,
                decode_responses=True,
                socket_connect_timeout=self.timeout_seconds,
                socket_timeout=self.timeout_seconds,
            )
        else:
            self._redis = None

    @property
    def using_memory(self) -> bool:
        return self._redis is None or self._redis_failed

    def _key(self, session_id: str) -> str:
        return f"{self.key_prefix}{session_id}"

    @staticmethod
    def _serialize(state: ConversationState) -> str:
        return state.model_dump_json()

    @staticmethod
    def _deserialize(raw: str | bytes) -> ConversationState:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return ConversationState.model_validate_json(raw)

    def _fall_back(self, operation: str, error: Exception) -> None:
        if not self._redis_failed:
            logger.warning(
                "Redis %s failed; using process-memory session storage: %s",
                operation,
                error,
            )
        self._redis_failed = True

    async def _memory_get(self, session_id: str) -> ConversationState | None:
        async with self._memory_lock:
            entry = self._memory.get(session_id)
            if entry is None:
                return None
            expires_at, raw = entry
            now = time.monotonic()
            if expires_at <= now:
                self._memory.pop(session_id, None)
                return None
            self._memory[session_id] = (now + self.ttl_seconds, raw)
        try:
            return self._deserialize(raw)
        except Exception as error:
            logger.warning("Discarding invalid in-memory session %s: %s", session_id, error)
            async with self._memory_lock:
                self._memory.pop(session_id, None)
            return None

    async def _memory_set(self, state: ConversationState) -> None:
        raw = self._serialize(state)
        async with self._memory_lock:
            self._memory[state.session_id] = (
                time.monotonic() + self.ttl_seconds,
                raw,
            )

    async def get(self, session_id: str) -> ConversationState | None:
        """Return state and refresh its TTL; missing/corrupt data returns ``None``."""

        if not session_id:
            return None
        if not self.using_memory:
            try:
                key = self._key(session_id)
                raw = await self._redis.get(key)
                if raw is None:
                    return None
                await self._redis.expire(key, self.ttl_seconds)
                return self._deserialize(raw)
            except Exception as error:
                self._fall_back("read", error)
        return await self._memory_get(session_id)

    async def get_or_create(self, session_id: str) -> ConversationState:
        state = await self.get(session_id)
        return state if state is not None else ConversationState(session_id=session_id)

    async def set(
        self,
        session_or_state: str | ConversationState,
        state: ConversationState | None = None,
    ) -> None:
        """Save state.

        Both ``set(state)`` and ``set(session_id, state)`` are supported. The latter guards
        against accidentally persisting a state under the wrong identifier.
        """

        if isinstance(session_or_state, ConversationState):
            value = session_or_state
        elif state is not None:
            value = state.model_copy(update={"session_id": session_or_state})
        else:
            raise TypeError("set() requires a ConversationState")

        if not self.using_memory:
            try:
                await self._redis.set(
                    self._key(value.session_id),
                    self._serialize(value),
                    ex=self.ttl_seconds,
                )
                return
            except Exception as error:
                self._fall_back("write", error)
        await self._memory_set(value)

    save = set

    async def delete(self, session_id: str) -> None:
        if not self.using_memory:
            try:
                await self._redis.delete(self._key(session_id))
            except Exception as error:
                self._fall_back("delete", error)
        async with self._memory_lock:
            self._memory.pop(session_id, None)

    async def ping(self) -> bool:
        if self.using_memory:
            return False
        try:
            return bool(await self._redis.ping())
        except Exception as error:
            self._fall_back("health check", error)
            return False

    async def health(self) -> bool:
        """Return Redis reachability; ``False`` means memory fallback is active."""

        return await self.ping()

    async def close(self) -> None:
        if self._redis is not None and self._owns_redis:
            try:
                await self._redis.aclose()
            except Exception:
                logger.debug("Redis close failed", exc_info=True)

    async def __aenter__(self) -> SessionStore:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


class MemorySessionStore(SessionStore):
    """Explicit process-memory variant, useful for tests and local development."""

    def __init__(self, *, ttl_seconds: int = 30 * 60) -> None:
        super().__init__(
            redis_url=None,
            redis_client=None,
            ttl_seconds=ttl_seconds,
            settings=Settings(redis_url=None),
        )


RedisSessionStore = SessionStore
StateStore = SessionStore
