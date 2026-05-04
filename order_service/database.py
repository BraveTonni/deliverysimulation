from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from order_service.config import get_db_url
from shared.models import Base

engine = create_async_engine(get_db_url(), echo=False, pool_pre_ping=True)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        # Для учебной/демо симуляции проще пересоздавать схему,
        # чтобы изменения моделей (например удаление FK) реально применялись.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Очищаем данные в БД при старте
    from sqlalchemy import delete
    from shared.models import Order, OrderHistory
    from order_service.database import async_session_maker

    async with async_session_maker() as session:
        await session.execute(delete(OrderHistory))
        await session.execute(delete(Order))
        await session.commit()


async def get_session():
    async with async_session_maker() as session:
        yield session
