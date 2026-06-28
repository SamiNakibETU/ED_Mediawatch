"""
Configuration du service de scraping avancé
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Optional


class Settings(BaseSettings):
    """Configuration centralisée du scraper"""
    
    # Service
    app_name: str = Field(default="OLJ Advanced Scraper")
    version: str = Field(default="1.0.0")
    port: int = Field(default=8080)
    log_level: str = Field(default="INFO")
    
    # Scraping - Paramètres agressifs pour 100% extraction
    max_retries: int = Field(default=5, ge=1, le=20)
    retry_base_delay: float = Field(default=2.0)
    retry_max_delay: float = Field(default=60.0)
    request_timeout: float = Field(default=120.0)
    connect_timeout: float = Field(default=30.0)
    
    # Concurrency
    max_concurrent_requests: int = Field(default=8)
    playwright_max_contexts: int = Field(default=4)
    semaphore_limit: int = Field(default=10)
    
    # Article quality thresholds
    min_article_words: int = Field(default=150)
    min_article_chars: int = Field(default=800)
    target_article_words: int = Field(default=500)  # Objectif pour article complet
    
    # Playwright settings - Optimisés pour contournement
    playwright_headless: bool = Field(default=True)
    playwright_viewport_width: int = Field(default=1920)
    playwright_viewport_height: int = Field(default=1080)
    playwright_default_timeout: int = Field(default=90000)
    playwright_navigation_timeout: int = Field(default=120000)
    playwright_wait_after_load: int = Field(default=5000)
    playwright_max_scrolls: int = Field(default=15)
    
    # Bypass services
    jina_ai_enabled: bool = Field(default=True)
    jina_ai_api_key: Optional[str] = Field(default=None)
    jina_ai_timeout: float = Field(default=45.0)
    
    scrapling_enabled: bool = Field(default=True)
    scrapling_solve_cf: bool = Field(default=True)
    
    # Cache
    cache_enabled: bool = Field(default=True)
    cache_ttl_seconds: int = Field(default=3600)
    
    # Rate limiting - Adaptatif
    rate_limit_base_delay: float = Field(default=1.5)
    rate_limit_min_delay: float = Field(default=0.5)
    rate_limit_max_delay: float = Field(default=120.0)
    rate_limit_jitter: float = Field(default=0.3)
    
    # Health check
    health_check_interval: int = Field(default=30)
    
    # Media-specific overrides file
    media_overrides_path: str = Field(default="config/media_overrides.json")
    
    # Extraction strategies priority (presse FR : googlebot_referer + archive_ph
    # gratuits et efficaces sur la presse premium FR → en tête après curl_cffi).
    extraction_strategies: List[str] = Field(default=[
        "curl_cffi",           # TLS/JA3 spoofing (bat l'IP datacenter blacklistée)
        "googlebot_referer",   # UA Googlebot + Referer Google (first-click-free)
        "archive_ph",          # archive.ph submit-and-fetch (paywall dur gratuit)
        "playwright_stealth",  # Navigateur furtif avec anti-détection
        "jina_ai",             # Proxy de contenu (rendu JS, IP tierces)
        "scrapling_cf",        # Contournement Cloudflare spécifique
        "wayback",             # Archive Wayback Machine
    ])
    
    # Anti-detection
    rotate_user_agents: bool = Field(default=True)
    rotate_proxies: bool = Field(default=False)  # Activable si besoin
    proxy_list: Optional[str] = Field(default=None)  # URL ou chemin fichier
    
    # Content verification
    verify_completeness: bool = Field(default=True)
    completeness_threshold: float = Field(default=0.95)  # 95% = considéré complet
    
    # Debug
    save_failed_html: bool = Field(default=False)
    failed_html_dir: str = Field(default="/tmp/failed_scrapes")
    debug_mode: bool = Field(default=False)
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


# Instance singleton
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Retourne l'instance de configuration"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings():
    """Réinitialise la configuration (utile pour les tests)"""
    global _settings
    _settings = None
