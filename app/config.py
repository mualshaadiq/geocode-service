from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db: str = "geocode_service"
    collection_name: str = "toponyms"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
