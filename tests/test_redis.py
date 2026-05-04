import pytest
import asyncio
import fakeredis.aioredis


class TestRedisClient:
    @pytest.fixture
    def redis_client(self):
        from courier_service.redis_client import RedisClient

        client = RedisClient()
        return client

    @pytest.mark.asyncio
    async def test_acquire_lock_success(self, redis_client):
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        redis_client.client = fake_redis

        result = await redis_client.acquire_lock("test_key", "test_value", timeout=10)
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_lock_duplicate(self, redis_client):
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        redis_client.client = fake_redis

        await redis_client.acquire_lock("test_key", "value1", timeout=10)
        result = await redis_client.acquire_lock("test_key", "value2", timeout=10)
        assert result is False

    @pytest.mark.asyncio
    async def test_release_lock(self, redis_client):
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        redis_client.client = fake_redis

        await redis_client.acquire_lock("test_key", "test_value", timeout=10)
        result = await redis_client.release_lock("test_key", "test_value")
        assert result is True

    @pytest.mark.asyncio
    async def test_push_to_retry_queue(self, redis_client):
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        redis_client.client = fake_redis

        order_data = {"order_id": 1, "restaurant_node_id": 5, "customer_node_id": 10}
        result = await redis_client.push_to_retry_queue(order_data)
        assert result is True

    @pytest.mark.asyncio
    async def test_pop_from_retry_queue(self, redis_client):
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        redis_client.client = fake_redis

        order_data = {"order_id": 1, "restaurant_node_id": 5, "customer_node_id": 10}
        await redis_client.push_to_retry_queue(order_data)
        popped = await redis_client.pop_from_retry_queue()
        assert popped == order_data

    @pytest.mark.asyncio
    async def test_set_courier_status(self, redis_client):
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        redis_client.client = fake_redis

        await redis_client.set_courier_status(1, "idle")
        status = await redis_client.get_courier_status(1)
        assert status == "idle"

    @pytest.mark.asyncio
    async def test_get_available_couriers(self, redis_client):
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        redis_client.client = fake_redis

        await redis_client.set_courier_status(1, "idle")
        await redis_client.set_courier_status(2, "delivering")
        await redis_client.set_courier_status(3, "idle")

        available = await redis_client.get_available_couriers()
        assert 1 in available
        assert 3 in available
        assert 2 not in available


class TestRaceConditions:
    @pytest.mark.asyncio
    async def test_concurrent_lock_acquisition(self):
        from courier_service.redis_client import RedisClient

        client = RedisClient()
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        client.client = fake_redis

        async def try_acquire():
            return await client.acquire_lock("resource", "client1", timeout=5)

        results = await asyncio.gather(try_acquire(), try_acquire(), try_acquire())

        assert sum(1 for r in results if r) == 1

    @pytest.mark.asyncio
    async def test_concurrent_order_assignment(self):
        from courier_service.redis_client import RedisClient

        client = RedisClient()
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        client.client = fake_redis

        async def assign_order(courier_id: int):
            lock_key = f"courier_lock:{courier_id}"
            lock_value = f"order_{courier_id}"
            return await client.acquire_lock(lock_key, lock_value, timeout=5)

        results = await asyncio.gather(
            assign_order(1),
            assign_order(1),
        )

        assert sum(1 for r in results if r) == 1
