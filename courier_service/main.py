import asyncio
import os
import os.path
import threading
import uvicorn
import time
import random
import httpx

from fastapi import FastAPI
from fastapi.responses import Response
from contextlib import asynccontextmanager
from courier_service.database import init_db
from courier_service.routes import router as couriers_router, graph_router, graph
from courier_service.redis_client import redis_client
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Настройка логирования в файл
LOG_FILE = os.getenv("LOG_FILE", "/app/logs/courier_service.log")


class FileLogger:
    def __init__(self, filepath):
        self.filepath = filepath
        # Создаём директорию если нет
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

    def write(self, msg):
        with open(self.filepath, "a") as f:
            f.write(msg + "\n")
        # Также выводим в stdout для docker logs
        import sys

        sys.stdout.write(msg + "\n")
        sys.stdout.flush()

    def flush(self):
        pass


REQUEST_COUNT = Counter("courier_http_requests_total", "Total HTTP requests", ["method", "endpoint"])
REQUEST_DURATION = Histogram("courier_http_request_duration_seconds", "HTTP request duration")
ORDER_ASSIGNMENTS = Counter("courier_order_assignments_total", "Total order assignments")
DELIVERY_TIME = Histogram("courier_delivery_time_seconds", "Delivery time")
ACTIVE_COURIERS = Counter("courier_active_total", "Total active couriers")

ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://localhost:8001")


def update_traffic():
    while True:
        time.sleep(30)
        edges = list(graph.edges.items())
        for node_id, edge_list in edges[:10]:
            for edge in edge_list[:2]:
                factor = random.uniform(0.8, 2.0)
                graph.set_traffic(edge.from_node, edge.to_node, factor)


async def auto_assign_orders():
    """Автоматическое назначение заказов курьерам каждые 2-3 секунды"""
    await asyncio.sleep(5)  # Ждём пока сервисы стартуют

    print(f"Автоназначение запущено, ORDER_SERVICE_URL={ORDER_SERVICE_URL}")

    while True:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                # Получаем список заказов со статусом pending
                resp = await client.get(f"{ORDER_SERVICE_URL}/api/orders/")
                if resp.status_code == 200:
                    orders = resp.json()

                    pending_orders = [
                        o for o in orders if not o.get("courier_id") and (o.get("status") or "").lower() == "pending"
                    ]
                    if pending_orders:
                        print(f"Найдено {len(pending_orders)} заказов без курьеров")

                    for order in pending_orders:
                        # Пробуем назначить курьера
                        restaurant_node = order["restaurant_node_id"]
                        customer_node = order["customer_node_id"]

                        # Рассчитываем маршрут (если нет связности — fallback на [start, end])
                        try:
                            route, _ = graph.astar(restaurant_node, customer_node)
                        except Exception:
                            route = None
                        if not route or len(route) < 2:
                            route = [restaurant_node, customer_node]
                        print(f"Маршрут для заказа {order['id']}: {restaurant_node} -> {customer_node} = {route}")

                        # Запрашиваем назначение
                        assign_resp = await client.post(
                            f"{ORDER_SERVICE_URL}/api/orders/{order['id']}/assign", json={"route": route}
                        )

                        print(f"Ответ assign для заказа {order['id']}: {assign_resp.status_code} - {assign_resp.text}")

                        if assign_resp.status_code == 200:
                            result = assign_resp.json()
                            if result.get("status") == "assigned":
                                print(
                                    f"Автоматически назначен курьер {result.get('courier_id')} на заказ {order['id']}"
                                )
                            elif result.get("status") == "no_courier_available":
                                print(f"Нет доступных курьеров для заказа {order['id']}")
        except Exception as e:
            print(f"Ошибка автоназначения: {e}")

        await asyncio.sleep(2)  # Проверяем каждые 2 секунды


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await redis_client.connect()

    traffic_thread = threading.Thread(target=update_traffic, daemon=True)
    traffic_thread.start()

    # Auto-assign next orders when couriers become idle after delivery.
    asyncio.create_task(auto_assign_orders())

    yield

    await redis_client.close()


app = FastAPI(title="Courier Service", lifespan=lifespan)


@app.middleware("http")
async def prometheus_middleware(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path).inc()
    REQUEST_DURATION.observe(duration)
    return response


app.include_router(couriers_router)
app.include_router(graph_router)


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/graph/nodes")
async def get_graph_nodes():
    return {"nodes": [{"id": n.id, "x": n.x, "y": n.y} for n in graph.nodes.values()]}


@app.get("/graph/edges")
async def get_graph_edges():
    edges = []
    for node_id, edge_list in graph.edges.items():
        for edge in edge_list:
            if edge.from_node <= edge.to_node:
                edges.append(
                    {
                        "from": edge.from_node,
                        "to": edge.to_node,
                        "distance": edge.distance,
                        "traffic_factor": edge.traffic_factor,
                    }
                )
    return {"edges": edges}


if __name__ == "__main__":
    uvicorn.run("courier_service.main:app", host="0.0.0.0", port=8002, reload=True)
