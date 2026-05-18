from __future__ import annotations

import json
from typing import AsyncIterator


class RedisJobStore:
    def __init__(self, /, *, url: str, key_prefix: str = "dobs:job:") -> None:
        from redis.asyncio import Redis
        self._url = url
        self._prefix = key_prefix
        self._client: Redis = Redis.from_url(url, decode_responses=True)

    def _events_channel(self, job_id: str) -> str:
        return f"{self._prefix}{job_id}:events"

    def _result_key(self, job_id: str) -> str:
        return f"{self._prefix}{job_id}:result"

    async def write_event(self, job_id: str, event: dict) -> None:
        payload = json.dumps(event)
        await self._client.rpush(self._events_channel(job_id), payload)
        await self._client.expire(self._events_channel(job_id), 86400)
        await self._client.publish(self._events_channel(job_id), payload)

    async def read_events(self, job_id: str) -> AsyncIterator[dict]:
        existing = await self._client.lrange(self._events_channel(job_id), 0, -1)
        last_seen = 0
        for raw in existing:
            event = json.loads(raw)
            last_seen += 1
            yield event
            if event.get("event") == "done":
                return

        pubsub = self._client.pubsub()
        await pubsub.subscribe(self._events_channel(job_id))
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                event = json.loads(message["data"])
                yield event
                if event.get("event") == "done":
                    return
        finally:
            await pubsub.unsubscribe(self._events_channel(job_id))
            await pubsub.close()

    async def write_result(
        self,
        job_id: str,
        result: list[dict] | None = None,
        error: str | None = None,
    ) -> None:
        payload = json.dumps({"result": result, "error": error, "done": True})
        await self._client.set(self._result_key(job_id), payload, ex=86400)
        await self.write_event(job_id, {"event": "done", "data": {}})

    async def read_result(
        self,
        job_id: str,
    ) -> tuple[list[dict] | None, str | None, bool]:
        raw = await self._client.get(self._result_key(job_id))
        if raw is None:
            if not await self.exists(job_id):
                return None, "Job not found", True
            return None, None, False
        payload = json.loads(raw)
        return payload.get("result"), payload.get("error"), payload.get("done", False)

    async def exists(self, job_id: str) -> bool:
        if await self._client.exists(self._result_key(job_id)):
            return True
        if await self._client.exists(self._events_channel(job_id)):
            return True
        return False
