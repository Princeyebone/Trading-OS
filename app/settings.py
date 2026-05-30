from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://postgres:password@localhost:5432/postgres"

    # Claude API
    anthropic_api_key: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_stub_mode: bool = False

    # MetaTrader 5
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = ""
    broker_stub_mode: bool = False
    account_balance_equiv: float = 500.0

    # API
    secret_key: str = "your_jwt_secret_key_here_change_this_in_production"
    frontend_url: str = "http://localhost:5173"

    # Engine
    ignore_staleness: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
