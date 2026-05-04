import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_health_endpoint():
    with patch("courier_service.redis_client.redis_client.connect", new_callable=AsyncMock):
        with patch("courier_service.redis_client.redis_client.close", new_callable=AsyncMock):
            from courier_service.main import app

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/health")
                assert response.status_code == 200


@pytest.mark.asyncio
async def test_graph_nodes():
    with patch("courier_service.redis_client.redis_client.connect", new_callable=AsyncMock):
        with patch("courier_service.redis_client.redis_client.close", new_callable=AsyncMock):
            from courier_service.main import app

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/graph/nodes")
                assert response.status_code == 200
                data = response.json()
                assert "nodes" in data
                assert len(data["nodes"]) == 50


@pytest.mark.asyncio
async def test_graph_edges():
    with patch("courier_service.redis_client.redis_client.connect", new_callable=AsyncMock):
        with patch("courier_service.redis_client.redis_client.close", new_callable=AsyncMock):
            from courier_service.main import app

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/graph/edges")
                assert response.status_code == 200
                data = response.json()
                assert "edges" in data
                assert len(data["edges"]) > 0


@pytest.mark.asyncio
async def test_metrics_endpoint():
    with patch("courier_service.redis_client.redis_client.connect", new_callable=AsyncMock):
        with patch("courier_service.redis_client.redis_client.close", new_callable=AsyncMock):
            from courier_service.main import app

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/metrics")
                assert response.status_code == 200
