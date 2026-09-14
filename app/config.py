from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://ogrodnik:ogrodnik@postgres:5432/ogrodnik"
    redis_url: str = "redis://redis:6379/0"

    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "chunks"

    minio_endpoint: str = "http://minio:9000"
    minio_access_key: str = "ogrodnik"
    minio_secret_key: str = "ogrodnik12345"
    minio_bucket: str = "ogrodnik"

    openai_api_key: str = "changeme"
    embedding_model: str = "text-embedding-3-large"
    answer_model: str = "gpt-4o"
    analysis_model: str = "gpt-4o-mini"

    auth_username: str = "redaktor"
    auth_password: str = "changeme"


settings = Settings()
