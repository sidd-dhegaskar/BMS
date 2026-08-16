from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379"
    default_ttl_seconds: int = 60

    class Config:
        env_file = ".env"


settings = Settings()
