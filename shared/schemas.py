from enum import Enum
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class OrderStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class CourierStatus(str, Enum):
    IDLE = "idle"
    PENDING = "pending"
    DELIVERING = "delivering"
    BUSY = "busy"


class Coordinate(BaseModel):
    node_id: int
    x: float
    y: float


class OrderCreate(BaseModel):
    restaurant_node_id: int
    customer_node_id: int
    customer_id: str


class OrderResponse(BaseModel):
    id: int
    restaurant_node_id: int
    customer_node_id: int
    customer_id: str
    courier_id: Optional[int] = None
    status: OrderStatus
    created_at: datetime
    updated_at: datetime
    route: Optional[list[int]] = None


class CourierCreate(BaseModel):
    name: str
    start_node_id: int
    color: Optional[str] = None


class CourierResponse(BaseModel):
    id: int
    name: str
    current_node_id: int
    current_x: Optional[float] = None
    current_y: Optional[float] = None
    status: CourierStatus
    current_order_id: Optional[int] = None
    color: Optional[str] = "#22c55e"


class CourierLocationUpdate(BaseModel):
    courier_id: int
    node_id: int
    x: float
    y: float
    order_id: Optional[int] = None


class OrderAssignment(BaseModel):
    order_id: int
    courier_id: int
    route: list[int]


class CourierAcceptRequest(BaseModel):
    order_id: int
    courier_id: int


class WSCoordinateMessage(BaseModel):
    type: str = "coordinate"
    courier_id: int
    node_id: int
    x: float
    y: float
    order_id: Optional[int] = None


class WSOrderUpdate(BaseModel):
    type: str = "order_update"
    order_id: int
    status: OrderStatus
    courier_id: Optional[int] = None


class WSAssignmentRequest(BaseModel):
    type: str = "assignment_request"
    order_id: int
    restaurant_node_id: int
    customer_node_id: int
    route: list[int]
    estimated_time: float
