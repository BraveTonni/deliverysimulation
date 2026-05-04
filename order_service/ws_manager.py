from fastapi import WebSocket
from typing import Dict
from shared.schemas import WSCoordinateMessage, WSOrderUpdate


class WSManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def send_coordinate(self, client_id: str, message: WSCoordinateMessage):
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_json(message.model_dump())
            except Exception:
                pass

    async def send_order_update(self, client_id: str, message: WSOrderUpdate):
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_json(message.model_dump())
            except Exception:
                pass

    async def broadcast_order_update(self, message: WSOrderUpdate):
        for client_id in list(self.active_connections.keys()):
            await self.send_order_update(client_id, message)


ws_manager = WSManager()
