"""
Modèles Pydantic pour l'API
"""

from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class ExtractionStrategy(str, Enum):
    """Stratégies d'extraction disponibles"""
    CURL_CFFI = "curl_cffi"
    PLAYWRIGHT_STEALTH = "playwright_stealth"
    SCRAPLING_CF = "scrapling_cf"
    JINA_AI = "jina_ai"
    WAYBACK = "wayback"
    TEXTISE = "textise"
    OUTLINE = "outline"
    AUTO = "auto"


class ArticleRequest(BaseModel):
    """Requête d'extraction d'article"""
    url: HttpUrl = Field(..., description="URL de l'article à extraire")
    source_id: Optional[str] = Field(None, description="Identifiant de la source média")
    source_name: Optional[str] = Field(None, description="Nom de la source média")
    force_complete: bool = Field(True, description="Forcer l'extraction complète")
    preferred_strategy: Optional[ExtractionStrategy] = Field(
        ExtractionStrategy.AUTO,
        description="Stratégie préférée (auto par défaut)"
    )
    timeout: Optional[float] = Field(120.0, ge=10.0, le=300.0, description="Timeout en secondes")


class ExtractionAttempt(BaseModel):
    """Résultat d'une tentative d'extraction"""
    strategy: str
    word_count: int = 0
    is_complete: bool = False
    success: bool = True
    error: Optional[str] = None
    duration_ms: Optional[int] = None


class ArticleResponse(BaseModel):
    """Réponse d'extraction d'article"""
    url: str
    url_hash: str
    title: Optional[str] = None
    content: Optional[str] = None
    author: Optional[str] = None
    date: Optional[str] = None
    
    extraction_method: str
    is_complete: bool
    word_count: int
    confidence_score: float
    
    all_attempts: List[ExtractionAttempt]
    total_duration_ms: int
    extraction_duration_ms: Optional[int] = None
    
    error: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://example.com/article",
                "url_hash": "abc123def456",
                "title": "Titre de l'article",
                "content": "Contenu complet de l'article...",
                "author": "Jean Dupont",
                "date": "2024-01-15",
                "extraction_method": "curl_cffi",
                "is_complete": True,
                "word_count": 1250,
                "confidence_score": 0.95,
                "all_attempts": [
                    {
                        "strategy": "curl_cffi",
                        "word_count": 1250,
                        "is_complete": True,
                        "success": True,
                        "duration_ms": 2300
                    }
                ],
                "total_duration_ms": 2500
            }
        }


class BatchArticleRequest(BaseModel):
    """Requête d'extraction par lot"""
    urls: List[HttpUrl] = Field(..., min_length=1, max_length=50)
    source_id: Optional[str] = None
    force_complete: bool = True
    max_concurrent: int = Field(5, ge=1, le=10)


class BatchArticleResponse(BaseModel):
    """Réponse d'extraction par lot"""
    total: int
    successful: int
    failed: int
    articles: List[ArticleResponse]
    total_duration_ms: int
    errors: List[Dict[str, Any]] = []


class HealthStatus(BaseModel):
    """Statut de santé du service"""
    status: str
    version: str
    uptime_seconds: float
    timestamp: datetime
    
    # Composants
    curl_cffi_available: bool
    playwright_available: bool
    scrapling_available: bool
    
    # Stats
    total_extractions: int
    successful_extractions: int
    failed_extractions: int
    average_extraction_time_ms: float


class MediaOverride(BaseModel):
    """Configuration override pour un média spécifique"""
    domain: str
    strategies_priority: List[str]
    use_jina_primary: bool = False
    use_playwright: bool = True
    playwright_wait_ms: int = 5000
    playwright_scroll: bool = True
    custom_headers: Optional[Dict[str, str]] = None
    link_pattern: Optional[str] = None


class StatsRequest(BaseModel):
    """Requête de statistiques"""
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    source_id: Optional[str] = None


class ExtractionStats(BaseModel):
    """Statistiques d'extraction"""
    period: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    
    by_strategy: Dict[str, Dict[str, Any]]
    by_domain: Dict[str, Dict[str, Any]]
    
    average_word_count: float
    completeness_rate: float  # % d'articles complets
    average_duration_ms: float
    
    top_successful_domains: List[Dict[str, Any]]
    problematic_domains: List[Dict[str, Any]]


class VerificationRequest(BaseModel):
    """Requête de vérification de complétude"""
    content: str = Field(..., description="Contenu à vérifier")
    url: Optional[HttpUrl] = Field(None, description="URL source (optionnel)")
    min_words: int = Field(150, ge=50, le=1000)


class VerificationResponse(BaseModel):
    """Réponse de vérification"""
    is_complete: bool
    word_count: int
    completeness_score: float  # 0-1
    paywall_indicators: List[str]
    truncation_detected: bool
    details: Dict[str, Any]
