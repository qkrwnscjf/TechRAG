from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    google_api_key: str
    github_token: Optional[str] = None
    pinecone_api_key: str
    pinecone_index_name: str = "techdoc"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
