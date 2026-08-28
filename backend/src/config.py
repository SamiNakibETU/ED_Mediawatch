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

    # Nitter / X collection. Ordre = instances servant l'ENGAGEMENT (HTML, comptes
    # X = colonne « Likes ») d'abord, puis RSS-fiables. La collecte sonde au runtime
    # (html_capable) et bascule HTML+engagement dès qu'une instance le sert depuis
    # l'IP courante. ⚠️ Surchargeable via NITTER_INSTANCES ; pour engagement garanti
    # → NITTER_SELF_HOSTED. NB : une IP datacenter (Railway) peut être bloquée par
    # ces instances (comme la presse) → l'engagement marchera surtout depuis une IP
    # résidentielle ou un Nitter self-hosté. Trouver la bonne : `probe_nitter`.
    nitter_instances: str = (
        "https://nitter.privacydev.net,https://xcancel.com,"
        "https://nitter.poast.org,https://twitt.re,"
        "https://nitter.net,https://nitter.space,https://lightbrd.com,"
        "https://nitter.tiekoetter.com,https://nitter.catsarch.com"
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
    # Obsolète : la première passe du scheduler part 2 minutes après le
    # démarrage. Le faire dans le `lifespan` bloquait l'API pendant toute la
    # collecte. Conservé pour ne pas casser un déploiement qui définit encore
    # la variable ; sans effet.
    collect_on_startup: bool = False
    # Vue de fraîcheur : une source/passe est « périmée » si rien depuis N heures.
    # Une collecte qui échoue en silence est pire qu'une absente (cf. spec §12.1).
    freshness_alert_hours: int = 24

    # Sécurité (prod). Vides en local = ouvert ; renseignés en prod.
    # Jeton requis (header X-API-Token) sur les endpoints coûteux (collecte/LLM).
    api_token: str = ""
    # Origines CORS autorisées (CSV). Vide = n'importe quel port localhost (dev).
    cors_origins: str = ""

    # Pool
    pool_file: str = "./data/pool_rn_udr.json"

    # Full-text extraction. Cascade : EXTRACTOR_URL (scraper-service PMO, si défini)
    # → trafilatura direct → Jina Reader. Les « readers » publics (Jina, Wayback)
    # récupèrent depuis LEURS IP → contournent l'IP datacenter Railway blacklistée
    # (Figaro/Télégramme) et certains paywalls souples, sans proxy.
    extractor_url: str = ""
    # Jina Reader (https://r.jina.ai/<url>) : gratuit, rendu JS, IP tierces.
    jina_reader_enabled: bool = True
    jina_reader_url: str = "https://r.jina.ai"
    # ladder (everywall/ladder) : proxy anti-paywall auto-hébergeable (Railway).
    # Si déployé, on récupère via GET {ladder_url}/{article_url}. Gratuit, open source.
    ladder_url: str = ""
    # removepaywall.com : repli paywall (format variable → désactivé par défaut).
    removepaywall_enabled: bool = False
    removepaywall_url: str = "https://www.removepaywall.com"
    # Cookies d'abonné par domaine (SECRET, env uniquement, jamais committé).
    # JSON {"lemonde.fr": "ssid=…; …", "lefigaro.fr": "…"} → on récupère l'article
    # COMPLET en tant qu'abonné (la façon la plus fiable de passer un paywall dur).
    site_cookies: str = ""

    # Archivage / reçus
    #   local      : snapshot HTML local seul (sans infra)
    #   wayback    : local + lien Wayback si une capture publique existe (availability API)
    #   archivebox : local + archivage possédé multi-format (HTML/PDF/screenshot/WARC)
    archive_backend: str = "wayback"  # local | wayback | archivebox | none
    snapshot_dir: str = "./data/snapshots"
    archive_rate_seconds: float = 1.5  # availability API est rapide
    # Save Page Now (création de capture Wayback) : indispensable pour les items
    # frais sans archive existante. Lent + rate-limité → débit dédié + lot borné.
    wayback_save_enabled: bool = True
    archive_save_rate_seconds: float = 6.0
    # Taille de lot par passe d'archivage (presse/X) — conservateur (Wayback lent).
    archive_batch_limit: int = 40
    # Intervalle d'archivage planifié (heures). Aligné par défaut sur la collecte.
    archive_interval_hours: int = 4

    # ArchiveBox (repris de la branche v2/media-watch ; nécessite ArchiveBox installé)
    archivebox_enabled: bool = False
    archivebox_data_dir: str = "./archivebox_data"
    # binaire ou commande (ex. "docker compose -f docker-compose.archivebox.yml run --rm archivebox")
    archivebox_binary: str = "archivebox"

    # --- LLM (extraction de claims, routage par tier — repris du llm_router PMO) ---
    # Clés API (au moins une requise pour activer le raffinage LLM).
    # OpenRouter est la voie par défaut (choix de modèles + prix, zéro Anthropic).
    openrouter_api_key: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    cerebras_api_key: str = ""
    mistral_api_key: str = ""
    cohere_api_key: str = ""  # embeddings (blocking sémantique des référents)
    cohere_embed_model: str = "embed-multilingual-v3.0"  # 1024d, FR

    # Activer le raffinage LLM des claims (sinon : déterministe seul).
    llm_refine_enabled: bool = False
    # Tier-1 (filtre de masse) : openrouter | cerebras | groq | mistral | anthropic
    # DeepSeek V4 Flash : 0,08/0,17 $/M — vérifier l'ID exact sur openrouter.ai/models.
    claim_tier1_provider: str = "openrouter"
    claim_tier1_model: str = "deepseek/deepseek-v4-flash:floor"
    # Tier-2 (canonicalisation / fidélité, sortie structurée).
    # GPT-5.6 Luna : 0,20/1,20 $/M, JSON strict, éprouvé sur PMO.
    claim_tier2_provider: str = "openrouter"
    claim_tier2_model: str = "openai/gpt-5.6-luna"

    # Budgets LLM ($ ; 0 = désactivé). Sommés depuis les tokens réels
    # (table llm_usage_events) — voir services/analysis/llm_usage.py.
    llm_daily_budget_usd: float = 5.0
    llm_monthly_budget_usd: float = 60.0

    # Périmètre de la passe automatique : « full » (défaut) fait avancer le
    # corpus tout seul, extraction L0 et juge compris. Ce n'est tenable que
    # parce qu'un plafond est armé : sans plafond, la passe retombe à « free »
    # d'elle-même — un système autonome ne doit pas pouvoir dépenser sans borne.
    # Mettre « free » pour n'automatiser que le gratuit.
    pipeline_auto_scope: str = "full"

    # Pilote L0 : CSV de handles X (sans @). Non vide → l'extraction de
    # déclarations ne traite que ces personnalités (posts) et les articles où
    # elles apparaissent — pour calibrer précision/rappel avant l'échelle.
    l0_pilot_handles: str = ""

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
    def l0_pilot_handle_list(self) -> list[str]:
        return [h.strip().lstrip("@").lower() for h in self.l0_pilot_handles.split(",") if h.strip()]

    @property
    def pool_path(self) -> Path:
        p = Path(self.pool_file)
        return p if p.is_absolute() else (BACKEND_DIR / p)


@lru_cache
def get_settings() -> Settings:
    return Settings()
