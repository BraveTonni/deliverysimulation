import asyncio
import threading
import time
import os
from typing import Optional, Callable
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from shared.models import Courier, COURIER_COLORS
from shared.schemas import CourierStatus, CourierCreate, CourierResponse
from shared.graph import RoadGraph
from courier_service.database import async_session_maker as courier_async_session_maker


class CourierEmulator:
    def __init__(
        self,
        courier_id: int,
        session_maker: async_sessionmaker[AsyncSession],
        graph: RoadGraph,
        on_location_update: Callable,
        on_delivery_complete: Callable | None = None,
    ):
        self.courier_id = courier_id
        self.session_maker = session_maker
        self.graph = graph
        self.on_location_update = on_location_update
        self.on_delivery_complete = on_delivery_complete

        self.current_node = 0
        self.current_x = 0.0
        self.current_y = 0.0
        self.status = CourierStatus.IDLE
        self.color = "#22c55e"
        self.current_order_id: Optional[int] = None
        self.route: list[int] = []
        self.route_index = 0

        try:
            self.speed_m_per_s = float(os.getenv("COURIER_SPEED_PER_TICK", "15"))
        except ValueError:
            self.speed_m_per_s = 15.0
        self._segment_from_node: int | None = None
        self._segment_to_node: int | None = None
        self._segment_remaining: float = 0.0

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._db_update_counter = 0
        self._db_update_interval = 5

    async def initialize(self):
        async with self.session_maker() as session:
            result = await session.execute(select(Courier).where(Courier.id == self.courier_id))
            courier = result.scalar_one_or_none()
            if courier:
                self.current_node = courier.current_node_id
                node = self.graph.nodes.get(self.current_node)
                if node:
                    self.current_x = node.x
                    self.current_y = node.y
                self.status = courier.status
                self.current_order_id = courier.current_order_id
                self.color = courier.color

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def assign_order(self, order_id: int, route: list[int]):
        with self._lock:
            self.current_order_id = order_id
            self.route = route
            try:
                idx = self.route.index(self.current_node)
                self.route_index = min(idx + 1, len(self.route))
            except ValueError:
                self.route_index = 0
            self.status = CourierStatus.DELIVERING
            self._segment_from_node = None
            self._segment_to_node = None
            self._segment_remaining = 0.0
            self._db_update_counter = 0

    def _run_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        print(f"[Courier {self.courier_id}] Emulator thread started")

        while self._running:
            try:
                loop.run_until_complete(self._move_along_route())
            except Exception as e:
                print(f"[CourierEmulator] move error for courier {self.courier_id}: {e}")
            time.sleep(1.0)

        loop.close()

    async def _move_along_route(self):
        if self.status != CourierStatus.DELIVERING or not self.route:
            return

        if self.route_index >= len(self.route):
            print(f"[Courier {self.courier_id}] Route complete, calling _complete_delivery")
            await self._complete_delivery()
            return

        next_node_id = self.route[self.route_index]
        next_node = self.graph.nodes.get(next_node_id)
        if not next_node:
            self.route_index += 1
            return

        step = max(self.speed_m_per_s, 0.1)
        dx = next_node.x - self.current_x
        dy = next_node.y - self.current_y
        dist = (dx * dx + dy * dy) ** 0.5

        if dist <= step:
            self.current_x = next_node.x
            self.current_y = next_node.y
            self.current_node = next_node_id
            self.route_index += 1
            print(
                f"[Courier {self.courier_id}] Arrived at node {next_node_id}, index now {self.route_index}/{len(self.route)}"
            )
        else:
            k = step / dist
            self.current_x += dx * k
            self.current_y += dy * k

        self._db_update_counter += 1
        if self._db_update_counter >= self._db_update_interval:
            self._db_update_counter = 0
            await self._update_position_in_db()

        if self.on_location_update:
            try:
                await self.on_location_update(
                    self.courier_id, self.current_node, self.current_x, self.current_y, self.current_order_id
                )
            except RuntimeError as e:
                if "attached to a different loop" in str(e):
                    pass
                else:
                    raise

    async def _complete_delivery(self):
        completed_order_id = self.current_order_id
        print(f"[Courier {self.courier_id}] Completing delivery for order {completed_order_id}")
        self.status = CourierStatus.IDLE
        self.current_order_id = None
        self.route = []
        self.route_index = 0
        self._db_update_counter = 0
        await self._update_status_in_db()

        if self.on_delivery_complete:
            try:
                await self.on_delivery_complete(self.courier_id, completed_order_id)
            except RuntimeError as e:
                if "attached to a different loop" in str(e):
                    pass
                else:
                    raise

    async def _update_position_in_db(self):
        async with self.session_maker() as session:
            await session.execute(
                update(Courier)
                .where(Courier.id == self.courier_id)
                .values(
                    current_node_id=self.current_node,
                    current_x=self.current_x,
                    current_y=self.current_y,
                    status=self.status,
                    current_order_id=self.current_order_id,
                )
            )
            await session.commit()

    async def _update_status_in_db(self):
        async with self.session_maker() as session:
            await session.execute(
                update(Courier)
                .where(Courier.id == self.courier_id)
                .values(status=self.status, current_order_id=self.current_order_id)
            )
            await session.commit()


def to_response(self) -> CourierResponse:
    return CourierResponse(
        id=self.courier_id,
        name=f"Courier {self.courier_id}",
        current_node_id=self.current_node,
        status=self.status,
        current_order_id=self.current_order_id,
        color=self.color,
    )


class CourierService:
    _shared_emulators: dict[int, CourierEmulator] = {}

    def __init__(self, session: AsyncSession, graph: RoadGraph, redis_client):
        self.session = session
        self.graph = graph
        self.redis = redis_client
        # IMPORTANT: service instances are short-lived (per request).
        # Emulators must be process-wide to avoid duplicate movement threads.
        self.emulators = CourierService._shared_emulators
        self._default_location_callback: Callable | None = None
        self._default_delivery_complete_callback: Callable | None = None

    def set_default_callbacks(
        self,
        on_location_update: Callable | None = None,
        on_delivery_complete: Callable | None = None,
    ) -> None:
        """
        Optional callbacks used when an emulator is created lazily during assignment.
        If not set, WS updates won't be emitted for those emulators.
        """
        self._default_location_callback = on_location_update
        self._default_delivery_complete_callback = on_delivery_complete

    async def create_courier(self, courier_data: CourierCreate) -> Courier:
        courier_count = await self._get_courier_count()
        color = courier_data.color or COURIER_COLORS[courier_count % len(COURIER_COLORS)]

        courier = Courier(
            name=courier_data.name,
            current_node_id=courier_data.start_node_id,
            current_x=self.graph.nodes[courier_data.start_node_id].x,
            current_y=self.graph.nodes[courier_data.start_node_id].y,
            status=CourierStatus.IDLE,
            color=color,
        )
        self.session.add(courier)
        await self.session.commit()
        await self.session.refresh(courier)
        return courier

    async def _get_courier_count(self) -> int:
        from sqlalchemy import select

        result = await self.session.execute(select(Courier))
        return len(list(result.scalars().all()))

    async def get_courier(self, courier_id: int) -> Optional[Courier]:
        result = await self.session.execute(select(Courier).where(Courier.id == courier_id))
        return result.scalar_one_or_none()

    async def assign_order(self, order_id: int, courier_id: int, route: list[int]) -> bool:
        lock_key = f"courier_lock:{courier_id}"
        lock_value = f"order_{order_id}"

        acquired = await self.redis.acquire_lock(lock_key, lock_value, timeout=15)
        if not acquired:
            return False

        courier = await self.get_courier(courier_id)
        if not courier:
            await self.redis.release_lock(lock_key, lock_value)
            return False

        # Assign only idle courier to prevent state races.
        if courier.status != CourierStatus.IDLE:
            print(f"[assign_order] Courier {courier_id} status={courier.status}, skip assign")
            await self.redis.release_lock(lock_key, lock_value)
            return False

        # Обновляем статус в БД
        await self.session.execute(
            update(Courier)
            .where(Courier.id == courier_id)
            .values(status=CourierStatus.DELIVERING, current_order_id=order_id)
        )
        await self.session.commit()

        # Обновляем статус в эмуляторе если есть, или создаём новый
        if courier_id in self.emulators:
            self.emulators[courier_id].assign_order(order_id, route)
        else:
            # Создаём эмулятор на лету для движения по маршруту
            print(f"[assign_order] Creating emulator for courier {courier_id} to run route")

            async def noop_loc(courier_id, node_id, x, y, order_id):
                return

            async def noop_deliv(courier_id, order_id):
                return

            on_loc = self._default_location_callback or noop_loc
            on_deliv = self._default_delivery_complete_callback or noop_deliv

            em = CourierEmulator(courier_id, courier_async_session_maker, self.graph, on_loc, on_deliv)
            await em.initialize()  # Загружаем данные курьера из БД
            # IMPORTANT: must set current_order_id via assign_order,
            # otherwise completion callback gets order_id=None.
            em.assign_order(order_id, route)
            em.start()
            self.emulators[courier_id] = em

        # Обновляем статус в Redis
        await self.redis.set_courier_status(courier_id, "delivering")
        await self.redis.release_lock(lock_key, lock_value)
        return True

    async def accept_assignment(self, order_id: int, courier_id: int) -> bool:
        lock_key = f"courier_lock:{courier_id}"
        lock_value = f"accept_{order_id}"
        acquired = await self.redis.acquire_lock(lock_key, lock_value, timeout=5)

        if not acquired:
            return False

        courier = await self.get_courier(courier_id)
        if courier and courier.current_order_id == order_id:
            await self.session.execute(
                update(Courier).where(Courier.id == courier_id).values(status=CourierStatus.DELIVERING)
            )
            await self.session.commit()
            await self.redis.set_courier_status(courier_id, "delivering")
            await self.redis.release_lock(lock_key, lock_value)
            return True

        await self.redis.release_lock(lock_key, lock_value)
        return False

    async def register_emulator(
        self, courier_id: int, on_location_update: Callable, on_delivery_complete: Callable | None = None
    ) -> CourierEmulator:
        existing = self.emulators.get(courier_id)
        if existing:
            # Refresh callbacks for existing emulator and reuse it.
            existing.on_location_update = on_location_update
            existing.on_delivery_complete = on_delivery_complete
            if not existing._running:
                existing.start()
            return existing

        emulator = CourierEmulator(
            courier_id,
            courier_async_session_maker,
            self.graph,
            on_location_update,
            on_delivery_complete,
        )
        await emulator.initialize()
        emulator.start()
        self.emulators[courier_id] = emulator

        # Регистрируем курьера как доступного в Redis
        if self.redis.client:
            # Initial idle on startup should not trigger delivery cooldown timer.
            await self.redis.set_courier_status(courier_id, "idle", mark_idle_since=False)
        else:
            print(f"WARNING: Redis not connected for courier {courier_id}")

        return emulator

    def get_emulator(self, courier_id: int) -> Optional[CourierEmulator]:
        return self.emulators.get(courier_id)

    async def update_courier_status(self, courier_id: int, status: CourierStatus, order_id: int | None = None):
        """Обновить статус курьера в БД и Redis"""
        await self.session.execute(
            update(Courier).where(Courier.id == courier_id).values(status=status, current_order_id=order_id)
        )
        await self.session.commit()

        status_str = "idle" if status == CourierStatus.IDLE else "delivering"
        await self.redis.set_courier_status(courier_id, status_str)

    async def get_all_couriers(self) -> list[Courier]:
        # Обновляем сессию чтобы видеть последние изменения
        await self.session.flush()
        result = await self.session.execute(select(Courier).execution_options(populate_existing=True))
        return list(result.scalars().all())
