from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./cvas_dev.db"
    media_root: str = "./uploads"

    auto_approve_threshold: float = 0.80
    auto_reject_threshold: float = 0.25

    llm_api_key: str = ""
    vision_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
