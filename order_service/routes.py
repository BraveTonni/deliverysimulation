import json

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from sqlalchemy.ext.asyncio import AsyncSession

from order_service.database import get_session
from order_service.order_service import OrderService
from order_service.ws_manager import ws_manager
from shared.schemas import OrderCreate, OrderResponse, OrderStatus

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.post("/clear")
async def clear_orders(session: AsyncSession = Depends(get_session)):
    """Очистить все заказы"""
    from sqlalchemy import delete
    from shared.models import Order, OrderHistory

    await session.execute(delete(OrderHistory))
    await session.execute(delete(Order))
    await session.commit()
    return {"status": "cleared"}


@router.post("/", response_model=OrderResponse)
async def create_order(order_data: OrderCreate, session: AsyncSession = Depends(get_session)):
    service = OrderService(session)
    order = await service.create_order(order_data)

    return OrderResponse(
        id=order.id,
        restaurant_node_id=order.restaurant_node_id,
        customer_node_id=order.customer_node_id,
        customer_id=order.customer_id,
        courier_id=order.courier_id,
        status=order.status,
        created_at=order.created_at,
        updated_at=order.updated_at,
        route=json.loads(order.route) if order.route else None,
    )


@router.get("/", response_model=list[OrderResponse])
async def list_orders(
    status: str | None = None, customer_id: str | None = None, session: AsyncSession = Depends(get_session)
):
    service = OrderService(session)
    orders = await service.get_all_orders(status, customer_id)
    return [
        OrderResponse(
            id=o.id,
            restaurant_node_id=o.restaurant_node_id,
            customer_node_id=o.customer_node_id,
            customer_id=o.customer_id,
            courier_id=o.courier_id,
            status=o.status,
            created_at=o.created_at,
            updated_at=o.updated_at,
            route=json.loads(o.route) if o.route else None,
        )
        for o in orders
    ]


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(order_id: int, session: AsyncSession = Depends(get_session)):
    service = OrderService(session)
    order = await service.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return OrderResponse(
        id=order.id,
        restaurant_node_id=order.restaurant_node_id,
        customer_node_id=order.customer_node_id,
        customer_id=order.customer_id,
        courier_id=order.courier_id,
        status=order.status,
        created_at=order.created_at,
        updated_at=order.updated_at,
        route=json.loads(order.route) if order.route else None,
    )


@router.post("/{order_id}/delivered")
async def mark_order_delivered(order_id: int, request: Request, session: AsyncSession = Depends(get_session)):
    """Пометить заказ как доставленный (вызывается courier service)"""
    body = await request.json()
    courier_id = body.get("courier_id")
    service = OrderService(session)
    order = await service.update_order_status(order_id, OrderStatus.DELIVERED, courier_id=courier_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    # Шлём WS-обновление всем подключённым клиентам
    from shared.schemas import WSOrderUpdate

    msg = WSOrderUpdate(type="order_delivered", order_id=order_id, status=OrderStatus.DELIVERED, courier_id=courier_id)
    await ws_manager.broadcast_order_update(msg)
    return {"status": "delivered", "order_id": order_id}


async def cancel_order(order_id: int, session: AsyncSession = Depends(get_session)):
    service = OrderService(session)
    order = await service.update_order_status(order_id, OrderStatus.CANCELLED)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"status": "cancelled", "order_id": order.id}


@router.post("/{order_id}/assign")
async def assign_order(order_id: int, request: Request, session: AsyncSession = Depends(get_session)):
    """Назначить курьера на заказ"""
    import httpx
    import os

    body = await request.json()
    route = body.get("route", [])
    print(f"[Order {order_id}] Received assign request: route={route}, type={type(route)}")

    courier_service_url = os.getenv("COURIER_SERVICE_URL", "http://localhost:8002")

    service = OrderService(session)
    order = await service.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{courier_service_url}/api/couriers/")
            if resp.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to get couriers")
            couriers = resp.json()

            print(f"[Order {order_id}] Found {len(couriers)} couriers")
            for c in couriers:
                print(f"  Courier {c.get('id')}: status={c.get('status')}")

            # Prefer idle couriers so a courier can finish and take the next order.
            idle = [c for c in couriers if (c.get("status") or "").lower() == "idle"]
            if not idle:
                print(f"[Order {order_id}] No idle couriers available")
                return {"status": "no_couriers_available"}

            for courier in idle:
                print(f"[Order {order_id}] Trying courier {courier.get('id')} (status={courier.get('status')})")
                assign_resp = await client.post(
                    f"{courier_service_url}/api/couriers/assign",
                    json={
                        "order_id": order_id,
                        "restaurant_node_id": order.restaurant_node_id,
                        "customer_node_id": order.customer_node_id,
                        "route": route,
                    },
                )
                print(f"[Order {order_id}] Assign response: {assign_resp.status_code} - {assign_resp.text}")
                if assign_resp.status_code == 200:
                    assign_data = assign_resp.json()
                    print(
                        f"[Order {order_id}] assign_data keys: {assign_data.keys()}, status: {assign_data.get('status')}"
                    )
                    if assign_data.get("status") == "assigned":
                        full_route = assign_data.get("route", route)
                        updated_order = await service.assign_courier(order_id, assign_data["courier_id"], full_route)
                        print(f"[Order {order_id}] Updated order with route: {full_route}")
                        route_to_return = (
                            json.loads(updated_order.route) if updated_order and updated_order.route else full_route
                        )
                        return {
                            "status": "assigned",
                            "courier_id": assign_data["courier_id"],
                            "route": route_to_return,
                        }

            print(f"[Order {order_id}] No couriers could be assigned")
            return {"status": "no_couriers_available"}
        except Exception as e:
            print(f"[Order {order_id}] Assignment error: {e}")
            raise HTTPException(status_code=500, detail=f"Assignment error: {e}")


@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await ws_manager.connect(websocket, client_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)
