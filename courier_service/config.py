from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    DB_NAME: str = "dostavka_courier"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    ORDER_SERVICE_URL: str = "http://localhost:8001"

    COURIER_CONFIRM_TIMEOUT: int = 10
    NUM_COURIERS: int = 10
    MOVEMENT_INTERVAL: float = 1.0

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()


def get_db_url() -> str:
    return f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"


def get_redis_url() -> str:
    return f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
