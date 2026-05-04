from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "ITTopDostavka"

    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    DB_NAME: str = "dostavka"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    ORDER_SERVICE_HOST: str = "localhost"
    ORDER_SERVICE_PORT: int = 8001
    COURIER_SERVICE_HOST: str = "localhost"
    COURIER_SERVICE_PORT: int = 8002

    COURIER_CONFIRM_TIMEOUT: int = 10
    NUM_COURIERS: int = 10

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()


def get_db_url(service: str = "order") -> str:
    if service == "order":
        return f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/dostavka_order"
    return f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/dostavka_courier"


def get_redis_url() -> str:
    return f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
