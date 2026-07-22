# ============================================================
# ATLAS OS - config.py
# Configurações centrais lidas do .env
# ============================================================

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações da aplicação, carregadas do .env."""

    # Banco de dados
    # Se DATABASE_URL for definido, ele tem prioridade (ex.: para testar
    # localmente com SQLite: DATABASE_URL=sqlite:///./atlas_local.db).
    DATABASE_URL: str = ""
    POSTGRES_USER: str = "atlas"
    POSTGRES_PASSWORD: str = "atlas"
    POSTGRES_DB: str = "atlas_os"
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432

    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379

    # App
    APP_NAME: str = "Atlas OS"
    APP_VERSION: str = "0.1.0"

    # Vendas Amazon: pasta extra (opcional) onde o ATLAS procura os
    # relatorios de afiliado baixados. Alem desta pasta, ele sempre olha
    # a pasta Downloads do usuario e a pasta "relatorios_amazon" do projeto.
    ATLAS_AMAZON_REPORTS_DIR: str = ""

    # Vendas Amazon: login automatico no Amazon Associates (o ATLAS loga
    # sozinho e baixa o relatorio, sem o usuario precisar baixar nada na
    # mao). Cada mercado e uma conta separada no site da Amazon.
    ATLAS_AMAZON_BR_EMAIL: str = ""
    ATLAS_AMAZON_BR_PASSWORD: str = ""
    ATLAS_AMAZON_US_EMAIL: str = ""
    ATLAS_AMAZON_US_PASSWORD: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        """URL de conexão do banco. Usa DATABASE_URL se definido, senão Postgres."""
        if self.DATABASE_URL.strip():
            return self.DATABASE_URL.strip()
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:"
            f"{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
