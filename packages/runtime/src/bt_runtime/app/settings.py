from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='BT_', extra='ignore')
    service_name: str = 'template'
    database_url: str
    database_pool_size: int = Field(default=5, ge=1, le=20)
    auth_public_key: str = ''
    service_auth_public_key: str = ''
    auth_issuer: str = 'beirut-time-identity'
    auth_audience: str = 'beirut-time'
    log_level: str = 'INFO'
    modules_path: Path = Path('/app/modules')
    request_body_limit: int = Field(default=1024 * 1024, ge=65536, le=32 * 1024 * 1024)
