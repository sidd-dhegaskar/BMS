from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://ticketing:ticketing@localhost:5432/ticketing"

    class Config:
        env_file = ".env"


settings = Settings()
