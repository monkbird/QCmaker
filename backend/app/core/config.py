from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Smart QC-Circle Generator"
    API_V1_STR: str = "/api/v1"
    
    # LLM Settings (Bring Your Own Key)
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    
    # Local LLM Settings
    USE_LOCAL_LLM: bool = False
    LOCAL_LLM_URL: str = "http://localhost:11434/v1"
    
    # Search API
    TAVILY_API_KEY: Optional[str] = None
    
    # Budget
    MAX_BUDGET_USD: float = 5.0
    
    class Config:
        env_file = ".env"

settings = Settings()
