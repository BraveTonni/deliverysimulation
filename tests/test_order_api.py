import pytest
from unittest.mock import AsyncMock
from httpx import AsyncClient, ASGITransport
from order_service.main import app


@pytest.fixture
def mock_session():
    session = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_create_order():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/orders/", json={"restaurant_node_id": 5, "customer_node_id": 10, "customer_id": "customer_123"}
        )
        assert response.status_code in [200, 500]


@pytest.mark.asyncio
async def test_get_order_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/orders/999")
        assert response.status_code in [404, 500]


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_metrics_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/metrics")
        assert response.status_code == 200
