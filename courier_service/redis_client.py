import json
import time
import redis.asyncio as redis

from courier_service.config import get_redis_url
from typing import Optional


class RedisClient:
    def __init__(self):
        self.client: Optional[redis.Redis] = None

    async def connect(self):
        self.client = redis.from_url(get_redis_url(), decode_responses=True)

    async def close(self):
        if self.client:
            await self.client.close()

    async def acquire_lock(self, key: str, value: str, timeout: int = 10) -> bool:
        if not self.client:
            return False
        
        result = await self.client.set(key, value, nx=True, ex=timeout)
        return bool(result)

    async def release_lock(self, key: str, value: str) -> bool:
        if not self.client:
            return False
        
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        result = await self.client.eval(script, 1, key, value)
        return bool(result)

    async def push_to_retry_queue(self, order_data: dict) -> bool:
        if not self.client:
            return False
        
        await self.client.lpush("retry_queue", json.dumps(order_data))
        return True

    async def pop_from_retry_queue(self, timeout: int = 0) -> Optional[dict]:
        if not self.client:
            return None
        
        if timeout > 0:
            result = await self.client.brpop("retry_queue", timeout=timeout)
            if result:
                return json.loads(result[1])
        else:
            result = await self.client.rpop("retry_queue")
            if result:
                return json.loads(result)
            
        return None

    async def set_courier_status(self, courier_id: int, status: str, mark_idle_since: bool = True) -> bool:
        if not self.client:
            return False
        
        await self.client.set(f"courier_status:{courier_id}", status)
        # Запоминаем время когда стал idle
        if status == "idle" and mark_idle_since:
            await self.client.set(f"courier_idle_since:{courier_id}", time.time())

        return True

    async def can_take_order(self, courier_id: int) -> bool:
        """Проверить может ли курьер взять новый заказ (прошло ли 3 сек после idle)"""
        if not self.client:
            return True
        status = await self.client.get(f"courier_status:{courier_id}")
        # If status key is missing (e.g. Redis restart), don't deadlock assignment.
        if status is None:
            return True
        
        if status != "idle":
            return False
        
        idle_since = await self.client.get(f"courier_idle_since:{courier_id}")
        if idle_since:
            elapsed = time.time() - float(idle_since)
            if elapsed < 3:
                return False
        return True

    async def get_courier_status(self, courier_id: int) -> Optional[str]:
        if not self.client:
            return None
        
        return await self.client.get(f"courier_status:{courier_id}")

    async def get_available_couriers(self) -> list[int]:
        if not self.client:
            return []
        
        keys = await self.client.keys("courier_status:*")
        available = []
        for key in keys:
            status = await self.client.get(key)
            if status == "idle":
                courier_id = int(key.split(":")[1])
                available.append(courier_id)
                
        return available

    async def clear_courier_route(self, courier_id: int) -> bool:
        """Очистить маршрут курьера"""
        if not self.client:
            return False
        
        await self.client.delete(f"courier_route:{courier_id}")
        return True

    async def set_courier_route(self, courier_id: int, route: list[int]) -> bool:
        """Сохранить маршрут курьера"""
        if not self.client:
            return False
        
        await self.client.set(f"courier_route:{courier_id}", json.dumps(route))
        return True

    async def get_courier_route(self, courier_id: int) -> Optional[list[int]]:
        """Получить маршрут курьера"""
        if not self.client:
            return None
        
        route = await self.client.get(f"courier_route:{courier_id}")
        if route:
            return json.loads(route)
        
        return None

    async def clear_all(self):
        """Очистить все данные Redis"""
        if not self.client:
            return
        
        await self.client.flushdb()


redis_client = RedisClient()
