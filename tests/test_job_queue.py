from dobs.infrastructure.adapters.event_bus.store_event_bus import StoreEventBus
from dobs.infrastructure.adapters.jobs.memory_job_store import MemoryJobStore


async def test_memory_store_records_events_in_order():
    store = MemoryJobStore()
    await store.write_event("job1", {"event": "queued", "data": {}})
    await store.write_event("job1", {"event": "ingest_start", "data": {}})
    await store.write_result("job1", result=[{"x": 1}])

    received: list[dict] = []
    async for event in store.read_events("job1"):
        received.append(event)

    assert [e["event"] for e in received] == ["queued", "ingest_start", "done"]


async def test_memory_store_round_trips_result():
    store = MemoryJobStore()
    await store.write_event("job2", {"event": "queued", "data": {}})
    await store.write_result("job2", result=[{"foo": "bar"}])

    result, error, done = await store.read_result("job2")
    assert done is True
    assert error is None
    assert result == [{"foo": "bar"}]


async def test_memory_store_records_error():
    store = MemoryJobStore()
    await store.write_event("job3", {"event": "queued", "data": {}})
    await store.write_result("job3", error="boom")

    result, error, done = await store.read_result("job3")
    assert done is True
    assert error == "boom"
    assert result is None


async def test_unknown_job_id_returns_not_found():
    store = MemoryJobStore()
    result, error, done = await store.read_result("missing")
    assert result is None
    assert error == "Job not found"
    assert done is True


async def test_store_event_bus_publish_emits():
    store = MemoryJobStore()
    bus = StoreEventBus(store=store, job_id="job4")
    await bus.publish("tier_active", {"tier": "balanced"})
    await bus.publish("done", {})

    received = []
    async for event in store.read_events("job4"):
        received.append(event)

    assert received[0]["event"] == "tier_active"
    assert received[0]["data"]["tier"] == "balanced"
    assert received[-1]["event"] == "done"


async def test_exists_flag():
    store = MemoryJobStore()
    assert await store.exists("nope") is False
    await store.write_event("there", {"event": "queued", "data": {}})
    assert await store.exists("there") is True
