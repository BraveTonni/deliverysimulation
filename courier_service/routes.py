import asyncio
import os
import httpx

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from sqlalchemy.ext.asyncio import AsyncSession

from courier_service.courier_service import CourierService
from courier_service.database import get_session
from courier_service.redis_client import redis_client
from courier_service.ws_manager import ws_manager
from shared.graph import generate_city_graph
from shared.schemas import (
    CourierAcceptRequest,
    CourierCreate,
    CourierResponse,
    WSCoordinateMessage,
)

router = APIRouter(prefix="/api/couriers", tags=["couriers"])
graph_router = APIRouter(prefix="/api/graph", tags=["graph"])

graph = generate_city_graph(50, seed=42)


@graph_router.get("/nodes")
async def get_graph_nodes():
    """Отдаём координаты всех нод графа фронтенду"""
    CENTER_LAT, CENTER_LNG = 55.75, 37.61
    SCALE = 0.004  # 1 единица = ~0.004 градуса (~440м)
    OFFSET = 500  # центр пространства графа

    nodes = {}
    for node_id, node in graph.nodes.items():
        lat = CENTER_LAT + (node.y - OFFSET) * SCALE
        lng = CENTER_LNG + (node.x - OFFSET) * SCALE
        nodes[str(node_id)] = {"lat": lat, "lng": lng}
    return nodes


async def location_callback(courier_id: int, node_id: int, x: float, y: float, order_id: int | None):
    message = WSCoordinateMessage(
        type="coordinate", courier_id=courier_id, node_id=node_id, x=x, y=y, order_id=order_id
    )
    await ws_manager.broadcast_coordinate(message)


async def delivery_complete_callback(courier_id: int, order_id: int | None = None):
    """Callback при завершении доставки - обновляем статус заказа и шлём WS"""
    await redis_client.set_courier_status(courier_id, "idle")
    await redis_client.clear_courier_route(courier_id)

    if order_id:
        # Уведомляем order service об успешной доставке
        order_service_url = os.getenv("ORDER_SERVICE_URL", "http://localhost:8001")
        delivered_marked = False
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        f"{order_service_url}/api/orders/{order_id}/delivered",
                        json={"courier_id": courier_id},
                    )
                    if resp.status_code == 200:
                        delivered_marked = True
                        break
                    print(
                        f"Failed to mark order {order_id} delivered (attempt {attempt}/3): "
                        f"status={resp.status_code}, body={resp.text}"
                    )
            except Exception as e:
                print(f"Failed to notify order service about delivery (attempt {attempt}/3): {e}")
            await asyncio.sleep(1)

        if not delivered_marked:
            print(f"Order {order_id} delivery confirmation failed after retries")

    # Бродкастим WS-событие фронту

    message = {
        "type": "order_delivered",
        "courier_id": courier_id,
        "order_id": order_id,
    }
    for client_id, websocket in list(ws_manager.active_connections.items()):
        try:
            await websocket.send_json(message)
        except Exception:
            pass


@router.post("/", response_model=CourierResponse)
async def create_courier(courier_data: CourierCreate, session: AsyncSession = Depends(get_session)):
    service = CourierService(session, graph, redis_client)
    courier = await service.create_courier(courier_data)
    await service.register_emulator(courier.id, location_callback, delivery_complete_callback)
    return CourierResponse(
        id=courier.id,
        name=courier.name,
        current_node_id=courier.current_node_id,
        current_x=courier.current_x,
        current_y=courier.current_y,
        status=courier.status,
        current_order_id=courier.current_order_id,
        color=courier.color,
    )


@router.post("/clear")
async def clear_couriers(session: AsyncSession = Depends(get_session)):
    """Очистить всех курьеров"""
    from sqlalchemy import delete
    from shared.models import Courier

    await session.execute(delete(Courier))
    await session.commit()

    # Очищаем Redis
    await redis_client.clear_all()

    return {"status": "cleared"}


@router.post("/simulate")
async def simulate_couriers(count: int = 5, session: AsyncSession = Depends(get_session)):
    """Создать несколько тестовых курьеров для эмуляции"""
    service = CourierService(session, graph, redis_client)
    created = []

    for i in range(count):
        courier = await service.create_courier(CourierCreate(name=f"Курьер_{i + 1}", start_node_id=i % 50))
        await service.register_emulator(courier.id, location_callback, delivery_complete_callback)
        created.append(courier)

    return {
        "status": "simulated",
        "created": len(created),
        "couriers": [{"id": c.id, "name": c.name, "status": c.status} for c in created],
    }


@router.post("/simulate-full")
async def simulate_full(courier_count: int = 5, order_count: int = 20, session: AsyncSession = Depends(get_session)):
    """Полная эмуляция: создать курьеров, заказы и назначить их"""
    import httpx

    print(f"=== SIMULATE-FULL: courier_count={courier_count}, order_count={order_count} ===")

    service = CourierService(session, graph, redis_client)
    service.set_default_callbacks(location_callback, delivery_complete_callback)

    couriers = []
    for i in range(courier_count):
        courier = await service.create_courier(CourierCreate(name=f"Курьер_{i + 1}", start_node_id=(i * 10) % 50))
        # Эмулятор держит курьера "живым" и шлёт координаты в WS
        await service.register_emulator(courier.id, location_callback, delivery_complete_callback)
        couriers.append(courier)

    await asyncio.sleep(1)

    order_service_url = os.getenv("ORDER_SERVICE_URL", "http://localhost:8001")
    assigned_orders = []

    print(f"Создаём {order_count} заказов...")

    async with httpx.AsyncClient() as client:
        for i in range(order_count):
            restaurant_node = (i * 17) % 50
            customer_node = ((i * 23) + 7) % 50

            order_resp = await client.post(
                f"{order_service_url}/api/orders/",
                json={
                    "restaurant_node_id": restaurant_node,
                    "customer_node_id": customer_node,
                    "customer_id": f"customer_{i + 1}",
                },
            )
            print(
                f"Создан заказ {i + 1}: ресторан={restaurant_node}, клиент={customer_node}, статус={order_resp.status_code}"
            )
            if order_resp.status_code == 200:
                order_data = order_resp.json()
                order_id = order_data["id"]

                route_restaurant_to_customer, dist = graph.astar(restaurant_node, customer_node)
                print(f"Маршрут A*: {restaurant_node} -> {customer_node} = {route_restaurant_to_customer}, dist={dist}")

                # A* может вернуть None (граф несвязный). Для симуляции делаем безопасный fallback.
                if not route_restaurant_to_customer or len(route_restaurant_to_customer) < 2:
                    route_restaurant_to_customer = [restaurant_node, customer_node]

                assign_resp = await client.post(
                    f"{order_service_url}/api/orders/{order_id}/assign", json={"route": route_restaurant_to_customer}
                )
                print(f"Назначение заказа {order_id}: {assign_resp.status_code} - {assign_resp.text}")

                if assign_resp.status_code == 200:
                    assign_data = assign_resp.json()
                    print(f"[simulate-full] assign_data for order {order_id}: {assign_data}")
                    if assign_data.get("status") == "assigned":
                        assigned_orders.append(
                            {
                                "order_id": order_id,
                                "restaurant_node": restaurant_node,
                                "customer_node": customer_node,
                                "route": assign_data.get("route", route_restaurant_to_customer),
                            }
                        )
                    else:
                        print(f"Не удалось назначить курьера на заказ {order_id}: {assign_data}")
                else:
                    print(f"Ошибка назначения заказа {order_id}: {assign_resp.status_code}")

    print(f"Создано курьеров: {len(couriers)}, заказов: {len(assigned_orders)}")

    return {
        "status": "simulated_full",
        "couriers_created": len(couriers),
        "orders_created": len(assigned_orders),
        "couriers": [{"id": c.id, "name": c.name, "color": c.color} for c in couriers],
        "orders": assigned_orders,
    }


@router.get("/{courier_id}", response_model=CourierResponse)
async def get_courier(courier_id: int, session: AsyncSession = Depends(get_session)):
    service = CourierService(session, graph, redis_client)
    courier = await service.get_courier(courier_id)
    if not courier:
        raise HTTPException(status_code=404, detail="Courier not found")
    return CourierResponse(
        id=courier.id,
        name=courier.name,
        current_node_id=courier.current_node_id,
        current_x=courier.current_x,
        current_y=courier.current_y,
        status=courier.status,
        current_order_id=courier.current_order_id,
        color=courier.color,
    )


@router.get("/", response_model=list[CourierResponse])
async def list_couriers(session: AsyncSession = Depends(get_session)):
    service = CourierService(session, graph, redis_client)
    couriers = await service.get_all_couriers()
    return [
        CourierResponse(
            id=c.id,
            name=c.name,
            current_node_id=c.current_node_id,
            current_x=c.current_x,
            current_y=c.current_y,
            status=c.status,
            current_order_id=c.current_order_id,
            color=c.color,
        )
        for c in couriers
    ]


@router.post("/accept")
async def accept_order(data: CourierAcceptRequest, session: AsyncSession = Depends(get_session)):
    service = CourierService(session, graph, redis_client)
    success = await service.accept_assignment(data.order_id, data.courier_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to accept assignment")
    return {"status": "accepted", "order_id": data.order_id, "courier_id": data.courier_id}


@router.post("/assign")
async def assign_order(
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    body = await request.json()
    order_id = body.get("order_id")
    restaurant_node_id = body.get("restaurant_node_id")
    customer_node_id = body.get("customer_node_id")
    route = body.get("route", [])
    print(
        f"[assign_order] Received order_id={order_id}, restaurant={restaurant_node_id}, customer={customer_node_id}, route={route}"
    )

    from shared.models import Courier
    from sqlalchemy import select

    result = await session.execute(select(Courier))
    all_couriers = list(result.scalars().all())

    print(f"Всего курьеров в БД: {len(all_couriers)}")
    for c in all_couriers:
        print(f"  Курьер {c.id}: {c.name}, status={c.status}, current_order_id={c.current_order_id}")

    if not all_couriers:
        return {"status": "no_couriers_available"}

    service = CourierService(session, graph, redis_client)
    service.set_default_callbacks(location_callback, delivery_complete_callback)

    for courier in all_couriers:
        print(f"Пытаемся назначить заказ {order_id} курьеру {courier.id}")
        # После завершения доставки курьер должен подождать 3 сек перед новым заказом.
        can_take_now = await redis_client.can_take_order(courier.id)
        if not can_take_now:
            print(f"Курьер {courier.id} в cooldown, пропускаем")
            continue

        # Полный маршрут для движения: от текущей позиции курьера -> ресторан -> клиент.
        # Если курьер не на маршруте, он сначала "подъезжает" к старту маршрута (ресторану).
        # Always rebuild canonical restaurant -> customer path.
        # External payload route can be stale/incomplete and may end at restaurant.
        route_restaurant_to_customer, _ = graph.astar(restaurant_node_id, customer_node_id)
        if not route_restaurant_to_customer or len(route_restaurant_to_customer) < 2:
            route_restaurant_to_customer = [restaurant_node_id, customer_node_id]

        # Нормализуем, чтобы маршрут явно начинался в ресторане
        if route_restaurant_to_customer[0] != restaurant_node_id:
            if restaurant_node_id in route_restaurant_to_customer:
                idx = route_restaurant_to_customer.index(restaurant_node_id)
                route_restaurant_to_customer = route_restaurant_to_customer[idx:]
            else:
                route_restaurant_to_customer = [restaurant_node_id] + route_restaurant_to_customer

        # Доезжаем до ресторана, если курьер не там
        if courier.current_node_id == restaurant_node_id:
            route_to_restaurant = [restaurant_node_id]
        else:
            route_to_restaurant, _ = graph.astar(courier.current_node_id, restaurant_node_id)
            if not route_to_restaurant or len(route_to_restaurant) < 2:
                route_to_restaurant = [courier.current_node_id, restaurant_node_id]

        # Склеиваем без дубля ресторана
        if route_to_restaurant and route_restaurant_to_customer and route_to_restaurant[-1] == route_restaurant_to_customer[0]:
            full_route = route_to_restaurant + route_restaurant_to_customer[1:]
        else:
            full_route = route_to_restaurant + route_restaurant_to_customer

        # Safety: route must end at customer.
        if not full_route or full_route[-1] != customer_node_id:
            full_route.append(customer_node_id)

        print(f"Маршрут для курьера {courier.id}: {full_route}")

        success = await service.assign_order(order_id, courier.id, full_route)
        if success:
            print(f"Успешно назначили курьера {courier.id} на заказ {order_id}")
            return {"status": "assigned", "courier_id": courier.id, "order_id": order_id, "route": full_route}

    retry_data = {
        "order_id": order_id,
        "restaurant_node_id": restaurant_node_id,
        "customer_node_id": customer_node_id,
        "route": route,
    }
    await redis_client.push_to_retry_queue(retry_data)
    return {"status": "queued_for_retry"}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_id = f"client_{id(websocket)}"
    ws_manager.active_connections[client_id] = websocket
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        del ws_manager.active_connections[client_id]
