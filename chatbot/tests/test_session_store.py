from __future__ import annotations

import pytest

from config import Settings
from session.state import ConversationState
from session.store import SessionStore


class ExpireFailureRedis:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.get_calls = 0
        self.expire_calls = 0

    async def get(self, key: str) -> str:
        del key
        self.get_calls += 1
        return self.raw

    async def expire(self, key: str, ttl: int) -> bool:
        del key, ttl
        self.expire_calls += 1
        raise TimeoutError("TTL refresh timed out")


class ReadFailureAfterWriteRedis:
    async def set(self, key: str, raw: str, *, ex: int) -> bool:
        del key, raw, ex
        return True

    async def get(self, key: str) -> str:
        del key
        raise TimeoutError("Redis read timed out")


class MissingThenFailureRedis:
    def __init__(self, raw: str) -> None:
        self.responses: list[str | None | Exception] = [
            raw,
            None,
            TimeoutError("Redis read timed out"),
        ]

    async def get(self, key: str) -> str | None:
        del key
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    async def expire(self, key: str, ttl: int) -> bool:
        del key, ttl
        return True


class ClaimRedis:
    def __init__(self) -> None:
        self.keys: set[str] = set()

    async def set(
        self,
        key: str,
        raw: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool:
        del raw, ex
        if nx and key in self.keys:
            return False
        self.keys.add(key)
        return True


@pytest.mark.asyncio
async def test_ttl_refresh_failure_preserves_read_state_in_memory_fallback() -> None:
    expected = ConversationState(session_id="ttl-failure")
    expected.focus.university = "uni-lpu"
    expected.focus.category = "mba"
    expected.focus.entity_id = "course-lpu-mba"
    redis = ExpireFailureRedis(expected.model_dump_json())
    store = SessionStore(
        redis_client=redis,
        settings=Settings(redis_url=None),
    )

    first = await store.get("ttl-failure")
    second = await store.get("ttl-failure")

    assert first is not None and first.focus.entity_id == "course-lpu-mba"
    assert second is not None and second.focus.entity_id == "course-lpu-mba"
    assert store.using_memory
    assert redis.get_calls == 1
    assert redis.expire_calls == 1


@pytest.mark.asyncio
async def test_successful_redis_write_is_mirrored_before_later_read_failure() -> None:
    expected = ConversationState(session_id="read-failure")
    expected.focus.entity_id = "course-lpu-mba"
    store = SessionStore(
        redis_client=ReadFailureAfterWriteRedis(),
        settings=Settings(redis_url=None),
    )

    await store.set(expected)
    loaded = await store.get("read-failure")

    assert loaded is not None and loaded.focus.entity_id == "course-lpu-mba"
    assert store.using_memory


@pytest.mark.asyncio
async def test_authoritative_redis_miss_evicts_mirror_before_later_outage() -> None:
    stale = ConversationState(session_id="evicted-session")
    stale.focus.entity_id = "course-lpu-mba"
    store = SessionStore(
        redis_client=MissingThenFailureRedis(stale.model_dump_json()),
        settings=Settings(redis_url=None),
    )

    first = await store.get("evicted-session")
    missing = await store.get("evicted-session")
    after_outage = await store.get("evicted-session")

    assert first is not None and first.focus.entity_id == "course-lpu-mba"
    assert missing is None
    assert after_outage is None
    assert store.using_memory


@pytest.mark.asyncio
async def test_one_time_claim_is_hashed_and_shared_across_store_instances() -> None:
    redis = ClaimRedis()
    first = SessionStore(redis_client=redis, settings=Settings(redis_url=None))
    second = SessionStore(redis_client=redis, settings=Settings(redis_url=None))

    assert await first.claim_once("scholarship", "9876543210")
    assert not await first.claim_once("scholarship", "9876543210")
    assert not await second.claim_once("scholarship", "9876543210")
    assert all("9876543210" not in key for key in redis.keys)
