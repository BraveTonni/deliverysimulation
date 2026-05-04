import json
import httpx

from datetime import datetime
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from shared.models import Order, OrderHistory
from shared.schemas import OrderCreate, OrderStatus


class OrderService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_order(self, order_data: OrderCreate) -> Order:
        order = Order(
            restaurant_node_id=order_data.restaurant_node_id,
            customer_node_id=order_data.customer_node_id,
            customer_id=order_data.customer_id,
            status=OrderStatus.PENDING,
        )
        self.session.add(order)
        await self.session.commit()
        await self.session.refresh(order)

        history = OrderHistory(order_id=order.id, status=OrderStatus.PENDING, note="Order created")
        self.session.add(history)
        await self.session.commit()

        return order

    async def get_order(self, order_id: int) -> Optional[Order]:
        result = await self.session.execute(select(Order).where(Order.id == order_id))
        return result.scalar_one_or_none()

    async def update_order_status(
        self, order_id: int, status: OrderStatus, courier_id: Optional[int] = None, route: Optional[list[int]] = None
    ) -> Optional[Order]:
        order = await self.get_order(order_id)
        if not order:
            return None

        order.status = status
        order.updated_at = datetime.utcnow()

        if courier_id is not None:
            order.courier_id = courier_id
        if route is not None and len(route) > 0:
            order.route = json.dumps(route)

        history = OrderHistory(order_id=order.id, status=status, note=f"Status changed to {status.value}")
        self.session.add(history)

        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def get_pending_orders(self) -> list[Order]:
        result = await self.session.execute(select(Order).where(Order.status == OrderStatus.PENDING))
        return list(result.scalars().all())

    async def assign_courier(self, order_id: int, courier_id: int, route: list[int]) -> Optional[Order]:
        print(
            f"[OrderService] assign_courier called: order_id={order_id}, courier_id={courier_id}, route={route}, len={len(route) if route else 0}"
        )
        return await self.update_order_status(order_id, OrderStatus.ASSIGNED, courier_id=courier_id, route=route)

    async def get_order_history(self, order_id: int) -> list[OrderHistory]:
        result = await self.session.execute(
            select(OrderHistory).where(OrderHistory.order_id == order_id).order_by(OrderHistory.changed_at)
        )
        return list(result.scalars().all())

    async def get_all_orders(self, status: str | None = None, customer_id: str | None = None) -> list[Order]:
        query = select(Order)
        if status:
            query = query.where(Order.status == status)
        if customer_id:
            query = query.where(Order.customer_id == customer_id)
        result = await self.session.execute(query.order_by(Order.created_at.desc()))
        return list(result.scalars().all())


async def notify_courier_service(order: Order, route: list[int]) -> bool:
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{__import__('os').environ.get('COURIER_SERVICE_URL', 'http://localhost:8002')}/assign",
                json={
                    "order_id": order.id,
                    "restaurant_node_id": order.restaurant_node_id,
                    "customer_node_id": order.customer_node_id,
                    "route": route,
                },
                timeout=5.0,
            )
            return response.status_code == 200
        except Exception:
            return False
