from pydantic_settings import BaseSettings
from typing import List
import os

class Settings(BaseSettings):
    # FastAPI Configuration
    port: int = 8050
    host: str = "0.0.0.0"
    debug: bool = True
    
    # CORS Settings
    cors_origins: str = "*"
    
    # Data Storage
    data_dir: str = "data"
    
    # Scraping Configuration
    default_timeout: int = 30
    max_retries: int = 3
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    
    # Proxy configuration
    proxy_server: str = "http://eu.proxy-jet.io:1010"
    proxy_username: str = "2508039ysSM-resi_region-IT_Campania_Naples"
    proxy_password: str = "i3x47f1exevgAFg"
    
    # Rate Limiting
    rate_limit_requests: int = 100
    rate_limit_window: int = 3600
    
    class Config:
        env_file = ".env"
        case_sensitive = False
    
    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

settings = Settings()