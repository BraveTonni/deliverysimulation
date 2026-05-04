import pytest
import asyncio
from unittest.mock import AsyncMock
import fakeredis.aioredis


class TestConcurrentAssignment:
    @pytest.mark.asyncio
    async def test_concurrent_order_assignment_to_same_courier(self):
        from courier_service.redis_client import RedisClient

        client = RedisClient()
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        client.client = fake_redis

        courier_id = 1

        async def try_assign(order_id: int):
            lock_key = f"courier_lock:{courier_id}"
            lock_value = f"order_{order_id}"
            acquired = await client.acquire_lock(lock_key, lock_value, timeout=10)
            if acquired:
                await asyncio.sleep(0.1)
                await client.release_lock(lock_key, lock_value)
            return acquired

        results = await asyncio.gather(try_assign(1), try_assign(2), try_assign(3))

        assert sum(1 for r in results if r) == 1

    @pytest.mark.asyncio
    async def test_concurrent_assignment_different_couriers(self):
        from courier_service.redis_client import RedisClient

        client = RedisClient()
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        client.client = fake_redis

        async def try_assign(courier_id: int):
            lock_key = f"courier_lock:{courier_id}"
            lock_value = f"order_{courier_id}"
            return await client.acquire_lock(lock_key, lock_value, timeout=10)

        results = await asyncio.gather(try_assign(1), try_assign(2), try_assign(3))

        assert sum(1 for r in results if r) == 3


class TestRetryQueue:
    @pytest.mark.asyncio
    async def test_retry_queue_order(self):
        from courier_service.redis_client import RedisClient

        client = RedisClient()
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        client.client = fake_redis

        order1 = {"order_id": 1, "restaurant_node_id": 5, "customer_node_id": 10}
        order2 = {"order_id": 2, "restaurant_node_id": 3, "customer_node_id": 8}

        await client.push_to_retry_queue(order1)
        await client.push_to_retry_queue(order2)

        popped1 = await client.pop_from_retry_queue()
        popped2 = await client.pop_from_retry_queue()

        assert popped1 == order2
        assert popped2 == order1


class TestCourierEmulator:
    @pytest.mark.asyncio
    async def test_emulator_initialization(self):
        from shared.graph import RoadGraph
        from courier_service.courier_service import CourierEmulator

        graph = RoadGraph()
        graph.add_node(0, 0.0, 0.0)
        graph.add_node(1, 10.0, 0.0)
        graph.add_node(2, 20.0, 0.0)

        session = AsyncMock()
        on_update = AsyncMock()

        emulator = CourierEmulator(1, session, graph, on_update)
        emulator.current_node = 0

        assert emulator.current_node == 0
        assert emulator.status.value == "idle"

    @pytest.mark.asyncio
    async def test_emulator_assign_order(self):
        from shared.graph import RoadGraph
        from courier_service.courier_service import CourierEmulator

        graph = RoadGraph()
        graph.add_node(0, 0.0, 0.0)
        graph.add_node(1, 10.0, 0.0)
        graph.add_node(2, 20.0, 0.0)

        session = AsyncMock()
        on_update = AsyncMock()

        emulator = CourierEmulator(1, session, graph, on_update)
        emulator.assign_order(1, [0, 1, 2])

        assert emulator.current_order_id == 1
        assert emulator.route == [0, 1, 2]
        assert emulator.status.value == "delivering"
