"""Application settings (pydantic-settings).

Local-first defaults: SQLite + public Nitter instances. Every value can be
overridden via environment variables / .env so the same code runs unchanged
against PostgreSQL + a self-hosted Nitter once we deploy.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "sqlite+aiosqlite:///./ed_mediawatch.db"

    # Nitter / X collection
    nitter_instances: str = (
        "https://nitter.net,https://nitter.poast.org,"
        "https://nitter.tiekoetter.com,https://nitter.catsarch.com,"
        "https://nitter.kareem.one"
    )
    nitter_health_url: str = "https://status.d420.de/api/v1/instances"
    nitter_self_hosted: str = ""

    # Polite scraping
    request_delay_seconds: float = 2.5
    request_timeout_seconds: int = 20
    max_concurrent_requests: int = 3
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    # Scheduler
    collection_interval_hours: int = 4
    collect_on_startup: bool = False

    # Sécurité (prod). Vides en local = ouvert ; renseignés en prod.
    # Jeton requis (header X-API-Token) sur les endpoints coûteux (collecte/LLM).
    api_token: str = ""
    # Origines CORS autorisées (CSV). Vide = n'importe quel port localhost (dev).
    cors_origins: str = ""

    # Pool
    pool_file: str = "./data/pool_rn_udr.json"

    # Full-text extraction. When set, press articles are extracted through the
    # v2/media-watch anti-paywall scraper-service (POST {url}/extract); else
    # we fall back to local trafilatura.
    extractor_url: str = ""

    # Archivage / reçus
    #   local      : snapshot HTML local seul (sans infra)
    #   wayback    : local + lien Wayback si une capture publique existe (availability API)
    #   archivebox : local + archivage possédé multi-format (HTML/PDF/screenshot/WARC)
    archive_backend: str = "wayback"  # local | wayback | archivebox | none
    snapshot_dir: str = "./data/snapshots"
    archive_rate_seconds: float = 1.5  # availability API est rapide

    # ArchiveBox (repris de la branche v2/media-watch ; nécessite ArchiveBox installé)
    archivebox_enabled: bool = False
    archivebox_data_dir: str = "./archivebox_data"
    # binaire ou commande (ex. "docker compose -f docker-compose.archivebox.yml run --rm archivebox")
    archivebox_binary: str = "archivebox"

    # --- LLM (extraction de claims, routage par tier — repris du llm_router PMO) ---
    # Clés API (au moins une requise pour activer le raffinage LLM).
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    cerebras_api_key: str = ""
    mistral_api_key: str = ""
    cohere_api_key: str = ""  # embeddings (blocking sémantique des référents)
    cohere_embed_model: str = "embed-multilingual-v3.0"  # 1024d, FR

    # Activer le raffinage LLM des claims (sinon : déterministe seul).
    llm_refine_enabled: bool = False
    # Tier-1 (filtre de masse, open) : cerebras | groq | mistral | anthropic
    claim_tier1_provider: str = "cerebras"
    claim_tier1_model: str = "gpt-oss-120b"
    # Tier-2 (canonicalisation / fidélité) : cerebras | anthropic | mistral | groq
    # Cerebras gpt-oss-120b : open, rapide, filtre bien (Anthropic réservé/économisé).
    claim_tier2_provider: str = "cerebras"
    claim_tier2_model: str = "gpt-oss-120b"

    @property
    def snapshot_path_dir(self) -> Path:
        p = Path(self.snapshot_dir)
        return p if p.is_absolute() else (BACKEND_DIR / p)

    @property
    def nitter_instance_list(self) -> list[str]:
        ordered: list[str] = []
        if self.nitter_self_hosted.strip():
            ordered.append(self.nitter_self_hosted.strip().rstrip("/"))
        ordered.extend(
            i.strip().rstrip("/")
            for i in self.nitter_instances.split(",")
            if i.strip()
        )
        # de-dupe preserving order
        seen: set[str] = set()
        return [i for i in ordered if not (i in seen or seen.add(i))]

    @property
    def pool_path(self) -> Path:
        p = Path(self.pool_file)
        return p if p.is_absolute() else (BACKEND_DIR / p)


@lru_cache
def get_settings() -> Settings:
    return Settings()
