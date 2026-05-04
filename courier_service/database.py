from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker, NullPool
from courier_service.config import get_db_url
from shared.models import Base
from courier_service.redis_client import redis_client


engine = create_async_engine(
    get_db_url(),
    echo=False,
    poolclass=NullPool,
)
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():

    # Очищаем Redis при старте
    await redis_client.clear_all()
    # При старте БД создаем таблицы
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session():
    async with async_session_maker() as session:
        yield session
