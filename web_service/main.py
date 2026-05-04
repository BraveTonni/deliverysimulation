import os
import os.path
import asyncio
import logging
import uvicorn
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import httpx
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LOG_DIR = os.getenv("LOG_DIR", "/app/logs")
os.makedirs(LOG_DIR, exist_ok=True)

file_handler = logging.FileHandler(f"{LOG_DIR}/web_service.log")
file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logging.getLogger().addHandler(file_handler)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent

courier_ws_connections = []
order_ws_connections = []
browser_clients: list = []  # WebSocket соединения браузеров


async def broadcast_to_browsers(data):
    """Разослать данные всем подключённым браузерным клиентам"""
    for ws in list(browser_clients):
        try:
            await ws.send_json(data)
        except Exception:
            if ws in browser_clients:
                browser_clients.remove(ws)

def _safe_json_from_httpx_response(resp: httpx.Response):
    """
    Some upstream services may return empty bodies or non-JSON error pages.
    Web service should proxy those safely instead of crashing on resp.json().
    """
    try:
        return resp.json()
    except Exception:
        text = (resp.text or "").strip()
        return {"error": "upstream_non_json_response", "status_code": resp.status_code, "body": text[:1000]}


async def forward_to_courier_ws(data):
    if courier_ws_connections:
        await asyncio.gather(*[conn.send_json(data) for conn in courier_ws_connections], return_exceptions=True)


async def forward_to_order_ws(data):
    if order_ws_connections:
        await asyncio.gather(*[conn.send_json(data) for conn in order_ws_connections], return_exceptions=True)


async def listen_to_courier_service():
    while True:
        try:
            async with httpx.AsyncClient() as client:
                async with client.ws_connect(f"{COURIER_SERVICE_URL}/api/couriers/ws") as ws:
                    courier_ws_connections.append(ws)
                    try:
                        async for msg in ws:
                            try:
                                data = msg.json()
                                # Форвардим и во внутренний order WS и браузерам
                                await forward_to_order_ws(data)
                                await broadcast_to_browsers(data)
                            except Exception:
                                pass
                    finally:
                        if ws in courier_ws_connections:
                            courier_ws_connections.remove(ws)
        except Exception:
            await asyncio.sleep(3)


async def listen_to_order_service():
    while True:
        try:
            async with httpx.AsyncClient() as client:
                async with client.ws_connect(f"{ORDER_SERVICE_URL}/api/orders/ws/test") as ws:
                    order_ws_connections.append(ws)
                    try:
                        async for msg in ws:
                            try:
                                data = msg.json()
                                await forward_to_courier_ws(data)
                                await broadcast_to_browsers(data)
                            except Exception:
                                pass
                    finally:
                        if ws in order_ws_connections:
                            order_ws_connections.remove(ws)
        except Exception:
            await asyncio.sleep(3)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(listen_to_courier_service())
    asyncio.create_task(listen_to_order_service())
    yield


app = FastAPI(title="ITTopDostavka Web", lifespan=lifespan)


@app.on_event("startup")
async def startup_event():
    await wait_for_services()

    # Очищаем данные при старте после ожидания сервисов
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            await client.post(f"{ORDER_SERVICE_URL}/api/orders/clear")
            await client.post(f"{COURIER_SERVICE_URL}/api/couriers/clear")
            logger.info("Cleared old data on startup")
    except Exception as e:
        logger.warning(f"Could not clear data on startup: {e}")


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")

ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://localhost:8001")
COURIER_SERVICE_URL = os.getenv("COURIER_SERVICE_URL", "http://localhost:8002")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"request": request})


async def wait_for_services():
    """Wait for services to be available on startup"""
    logger.info("Waiting for services to be available...")
    max_retries = 30
    retry_delay = 2

    async with httpx.AsyncClient(timeout=10.0) as client:
        for i in range(max_retries):
            try:
                resp = await client.get(f"{ORDER_SERVICE_URL}/health")
                if resp.status_code == 200:
                    logger.info("Order service is available")
                    break
            except Exception as e:
                logger.warning(f"Retry {i + 1}/{max_retries}: Order service not ready: {e}")
                await asyncio.sleep(retry_delay)

        for i in range(max_retries):
            try:
                resp = await client.get(f"{COURIER_SERVICE_URL}/health")
                if resp.status_code == 200:
                    logger.info("Courier service is available")
                    break
            except Exception as e:
                logger.warning(f"Retry {i + 1}/{max_retries}: Courier service not ready: {e}")
                await asyncio.sleep(retry_delay)


@app.get("/health")
async def health():
    services_status = {}

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{ORDER_SERVICE_URL}/health")
            services_status["order"] = "ok" if resp.status_code == 200 else "error"
        except Exception as e:
            services_status["order"] = f"unavailable: {e}"

        try:
            resp = await client.get(f"{COURIER_SERVICE_URL}/health")
            services_status["courier"] = "ok" if resp.status_code == 200 else "error"
        except Exception as e:
            services_status["courier"] = f"unavailable: {e}"

    return {"status": "ok", "services": services_status}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    browser_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # держим соединение живым
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in browser_clients:
            browser_clients.remove(websocket)


@app.get("/api/graph/nodes")
async def get_graph_nodes():
    """Прокси к courier service — координаты нод графа"""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(f"{COURIER_SERVICE_URL}/api/graph/nodes")
            return JSONResponse(content=_safe_json_from_httpx_response(resp), status_code=resp.status_code)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Cannot fetch graph nodes: {e}")


@app.get("/api/orders")
@app.get("/api/orders/")
async def list_orders():
    logger.info(f"Fetching orders from {ORDER_SERVICE_URL}/api/orders/")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(f"{ORDER_SERVICE_URL}/api/orders/")
            logger.info(f"Orders response: {resp.status_code}")
            return JSONResponse(content=_safe_json_from_httpx_response(resp), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code}: {e.response.text}")
        return JSONResponse(content={"error": str(e), "response": e.response.text}, status_code=e.response.status_code)
    except httpx.ConnectError as e:
        logger.error(f"Connection error: {e}")
        raise HTTPException(status_code=503, detail=f"Cannot connect to order service: {e}")
    except httpx.TimeoutException as e:
        logger.error(f"Timeout: {e}")
        raise HTTPException(status_code=503, detail=f"Order service timeout: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=503, detail=f"Order service error: {e}")


@app.post("/api/orders")
@app.post("/api/orders/")
async def create_order(data: dict):
    logger.info(f"Creating order: {data}")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.post(f"{ORDER_SERVICE_URL}/api/orders/", json=data)
            logger.info(f"Create order response: {resp.status_code}")
            return JSONResponse(content=_safe_json_from_httpx_response(resp), status_code=resp.status_code)
    except httpx.ConnectError as e:
        logger.error(f"Connection error: {e}")
        raise HTTPException(status_code=503, detail=f"Cannot connect to order service: {e}")
    except httpx.TimeoutException as e:
        logger.error(f"Timeout: {e}")
        raise HTTPException(status_code=503, detail=f"Order service timeout: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e}")
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=503, detail=f"Order service error: {e}")


@app.get("/api/orders/{order_id}")
@app.get("/api/orders/{order_id}/")
async def get_order(order_id: int):
    logger.info(f"Fetching order {order_id}")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(f"{ORDER_SERVICE_URL}/api/orders/{order_id}")
            return JSONResponse(content=_safe_json_from_httpx_response(resp), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code}: {e.response.text}")
        return JSONResponse(content={"error": str(e)}, status_code=e.response.status_code)
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=503, detail=f"Order service error: {e}")


@app.post("/api/orders/{order_id}/cancel")
@app.post("/api/orders/{order_id}/cancel/")
async def cancel_order(order_id: int):
    logger.info(f"Cancelling order {order_id}")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.post(f"{ORDER_SERVICE_URL}/api/orders/{order_id}/cancel")
            return JSONResponse(content=_safe_json_from_httpx_response(resp), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code}: {e.response.text}")
        return JSONResponse(content={"error": str(e)}, status_code=e.response.status_code)
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=503, detail=f"Order service error: {e}")


@app.get("/api/couriers")
@app.get("/api/couriers/")
async def list_couriers():
    logger.info(f"Fetching couriers from {COURIER_SERVICE_URL}/api/couriers/")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(f"{COURIER_SERVICE_URL}/api/couriers/")
            logger.info(f"Couriers response: {resp.status_code}")
            return JSONResponse(content=_safe_json_from_httpx_response(resp), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code}: {e.response.text}")
        return JSONResponse(content={"error": str(e), "response": e.response.text}, status_code=e.response.status_code)
    except httpx.ConnectError as e:
        logger.error(f"Connection error: {e}")
        raise HTTPException(status_code=503, detail=f"Cannot connect to courier service: {e}")
    except httpx.TimeoutException as e:
        logger.error(f"Timeout: {e}")
        raise HTTPException(status_code=503, detail=f"Courier service timeout: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=503, detail=f"Courier service error: {e}")


@app.post("/api/couriers/simulate")
async def simulate_couriers(data: dict = {"count": 5}):
    """Запустить симуляцию курьеров"""
    count = data.get("count", 5)
    logger.info(f"Simulating {count} couriers")
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.post(f"{COURIER_SERVICE_URL}/api/couriers/simulate?count={count}")
            logger.info(f"Simulate response: {resp.status_code}")
            return JSONResponse(content=_safe_json_from_httpx_response(resp), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code}: {e.response.text}")
        return JSONResponse(content={"error": str(e)}, status_code=e.response.status_code)
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=503, detail=f"Simulate error: {e}")


@app.post("/api/couriers")
@app.post("/api/couriers/")
async def create_courier(data: dict):
    logger.info(f"Creating courier: {data}")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.post(f"{COURIER_SERVICE_URL}/api/couriers/", json=data)
            logger.info(f"Create courier response: {resp.status_code}")
            return JSONResponse(content=_safe_json_from_httpx_response(resp), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code}: {e.response.text}")
        return JSONResponse(content={"error": str(e), "response": e.response.text}, status_code=e.response.status_code)
    except httpx.ConnectError as e:
        logger.error(f"Connection error: {e}")
        raise HTTPException(status_code=503, detail=f"Cannot connect to courier service: {e}")
    except httpx.TimeoutException as e:
        logger.error(f"Timeout: {e}")
        raise HTTPException(status_code=503, detail=f"Courier service timeout: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=503, detail=f"Courier service error: {e}")


@app.get("/api/couriers/{courier_id}")
async def get_courier(courier_id: int):
    logger.info(f"Fetching courier {courier_id}")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(f"{COURIER_SERVICE_URL}/api/couriers/{courier_id}")
            return JSONResponse(content=_safe_json_from_httpx_response(resp), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code}: {e.response.text}")
        return JSONResponse(content={"error": str(e)}, status_code=e.response.status_code)
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=503, detail=f"Courier service error: {e}")


class SimulateRequest(BaseModel):
    courier_count: int = 5
    order_count: int = 20


@app.post("/api/simulate-full")
async def simulate_full(request: SimulateRequest):
    """Полная эмуляция: курьеры + заказы + маршруты"""
    courier_count = request.courier_count
    order_count = request.order_count
    logger.info(f"Full simulation: {courier_count} couriers, {order_count} orders")

    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            # Очищаем перед симуляцией
            await client.post(f"{ORDER_SERVICE_URL}/api/orders/clear")
            await client.post(f"{COURIER_SERVICE_URL}/api/couriers/clear")

            resp = await client.post(
                f"{COURIER_SERVICE_URL}/api/couriers/simulate-full?courier_count={courier_count}&order_count={order_count}"
            )
            logger.info(f"Simulate-full response: {resp.status_code}")
            return JSONResponse(content=_safe_json_from_httpx_response(resp), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code}: {e.response.text}")
        return JSONResponse(content={"error": str(e)}, status_code=e.response.status_code)
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=503, detail=f"Simulate error: {e}")


@app.post("/api/clear")
async def clear_all():
    """Очистить все данные (заказы и курьеры)"""
    logger.info("Clearing all data...")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            await client.post(f"{ORDER_SERVICE_URL}/api/orders/clear")
            await client.post(f"{COURIER_SERVICE_URL}/api/couriers/clear")
        return {"status": "cleared"}
    except Exception as e:
        logger.error(f"Error clearing: {e}")
        raise HTTPException(status_code=500, detail=f"Clear error: {e}")


if __name__ == "__main__":
    uvicorn.run("web_service.main:app", host="0.0.0.0", port=5000, reload=True)
