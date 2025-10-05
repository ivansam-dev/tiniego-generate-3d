import os
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Config:
    """Application configuration loaded from environment variables.

    Provides validated access to third-party configuration like Supabase.
    """

    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    SUPABASE_BUCKET: str = os.getenv("SUPABASE_BUCKET", "memory-photos")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production")

    CORS_ALLOWED_ORIGINS_ENV: str = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000")

    @staticmethod
    def allowed_origins(extra_origins: List[str] | None = None) -> List[str]:
        env_origins = [o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
        # Default Cloud Run and production domains
        defaults = [
            "https://tiniego.com",
            "https://www.tiniego.com",
            "https://dev.tiniego.com",
        ]
        merged = env_origins + defaults
        if extra_origins:
            merged.extend(extra_origins)
        # Deduplicate while preserving order
        seen = set()
        result: List[str] = []
        for origin in merged:
            if origin not in seen:
                seen.add(origin)
                result.append(origin)
        return result

    @classmethod
    def validate(cls) -> None:
        if not cls.SUPABASE_URL:
            raise ValueError("SUPABASE_URL environment variable is required")
        if not cls.SUPABASE_ANON_KEY:
            raise ValueError("SUPABASE_ANON_KEY environment variable is required")
        if not cls.SUPABASE_SERVICE_KEY:
            raise ValueError("SUPABASE_SERVICE_KEY environment variable is required")


