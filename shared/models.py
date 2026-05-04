from datetime import datetime
from sqlalchemy import Integer, String, Float, DateTime, Enum, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from shared.schemas import OrderStatus, CourierStatus


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    restaurant_node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_id: Mapped[str] = mapped_column(String(100), nullable=False)
    courier_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # No FK - different DBs
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING)
    route: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


COURIER_COLORS = [
    "#ef4444",
    "#f97316",
    "#f59e0b",
    "#84cc16",
    "#22c55e",
    "#14b8a6",
    "#06b6d4",
    "#3b82f6",
    "#6366f1",
    "#8b5cf6",
    "#a855f7",
    "#d946ef",
    "#ec4899",
    "#f43f5e",
]


class Courier(Base):
    __tablename__ = "couriers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    current_node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    current_x: Mapped[float] = mapped_column(Float, default=0.0)
    current_y: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[CourierStatus] = mapped_column(Enum(CourierStatus), default=CourierStatus.IDLE)
    color: Mapped[str] = mapped_column(String(20), default="#22c55e")
    current_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class OrderHistory(Base):
    __tablename__ = "order_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("orders.id"), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
