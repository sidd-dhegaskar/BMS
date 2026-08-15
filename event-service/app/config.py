from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://ticketing:ticketing@localhost:5432/ticketing"
    lock_service_url: str = "http://localhost:8001"
    lock_ttl_seconds: int = 60

    class Config:
        env_file = ".env"


settings = Settings()
