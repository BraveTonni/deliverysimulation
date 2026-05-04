import uvicorn
import os
import os.path
from fastapi import FastAPI
from contextlib import asynccontextmanager
from order_service.database import init_db
from order_service.routes import router as orders_router
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
import time

# Настройка логирования в файл
# В среде без контейнера путь `/app/...` может быть недоступен, поэтому по умолчанию пишем в локальную папку проекта.
LOG_FILE = os.getenv("LOG_FILE", "./logs/order_service.log")


class FileLogger:
    def __init__(self, filepath):
        self.filepath = filepath
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

    def write(self, msg):
        with open(self.filepath, "a") as f:
            f.write(msg + "\n")
        import sys

        sys.stdout.write(msg + "\n")
        sys.stdout.flush()

    def flush(self):
        pass


file_logger = FileLogger(LOG_FILE)
print = file_logger.write


REQUEST_COUNT = Counter("order_http_requests_total", "Total HTTP requests", ["method", "endpoint"])
REQUEST_DURATION = Histogram("order_http_request_duration_seconds", "HTTP request duration")
ORDER_ASSIGNMENTS = Counter("order_assignments_total", "Total order assignments")
DELIVERY_TIME = Histogram("order_delivery_time_seconds", "Delivery time")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Order Service", lifespan=lifespan)


@app.middleware("http")
async def prometheus_middleware(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path).inc()
    REQUEST_DURATION.observe(duration)
    return response


app.include_router(orders_router)


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("order_service.main:app", host="0.0.0.0", port=8001, reload=True)
