"""
Service de Scraping Avancé - L'Orient-Le Jour
API FastAPI pour extraction garantie 100% des articles
"""

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from .api.models import (
    ArticleRequest, ArticleResponse, BatchArticleRequest, BatchArticleResponse,
    HealthStatus, ExtractionStats, StatsRequest, VerificationRequest, 
    VerificationResponse, ExtractionAttempt
)
from .core.ultimate_extractor import UltimateExtractor
from .config.settings import get_settings
from .utils.text_utils import is_article_complete, calculate_completeness_score

# Configuration logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Statistiques globales
_stats = {
    "start_time": time.time(),
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "total_duration_ms": 0,
    "by_strategy": {},
}

# Extractor singleton
_extractor: Optional[UltimateExtractor] = None


def get_extractor() -> UltimateExtractor:
    """Retourne l'extracteur singleton"""
    global _extractor
    if _extractor is None:
        _extractor = UltimateExtractor()
    return _extractor


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestionnaire de cycle de vie.

    On NE pré-charge plus l'extracteur ici : sur Railway, l'init de Playwright
    peut prendre >30s et bloquer la disponibilité du healthcheck `/health`.
    L'extracteur est instancié paresseusement au premier appel à `/extract`.
    """
    try:
        logger.info("service.starting", version=get_settings().version)
    except Exception:
        pass
    yield
    try:
        logger.info("service.stopping")
    except Exception:
        pass


app = FastAPI(
    title="OLJ Advanced Scraper",
    description="Service de scraping avancé garantissant l'extraction 100% complète des articles",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # À restreindre en production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthStatus)
async def health_check():
    """Endpoint de vérification de santé"""
    uptime = time.time() - _stats["start_time"]
    
    total = _stats["total_requests"]
    avg_duration = _stats["total_duration_ms"] / max(total, 1)
    
    # Vérifier disponibilité des composants
    curl_available = True
    pw_available = True
    scrapling_available = True
    
    try:
        from curl_cffi import requests
    except ImportError:
        curl_available = False
    
    try:
        import playwright
    except ImportError:
        pw_available = False
    
    try:
        import scrapling
    except ImportError:
        scrapling_available = False
    
    return HealthStatus(
        status="healthy" if total == 0 or _stats["successful_requests"] / max(total, 1) > 0.5 else "degraded",
        version=get_settings().version,
        uptime_seconds=uptime,
        timestamp=datetime.utcnow(),
        curl_cffi_available=curl_available,
        playwright_available=pw_available,
        scrapling_available=scrapling_available,
        total_extractions=total,
        successful_extractions=_stats["successful_requests"],
        failed_extractions=_stats["failed_requests"],
        average_extraction_time_ms=avg_duration,
    )


@app.post("/extract", response_model=ArticleResponse)
async def extract_article(request: ArticleRequest):
    """
    Extrait un article depuis une URL avec garantie de complétude.
    
    Cet endpoint utilise une cascade de stratégies pour garantir
    l'extraction complète de l'article (100% du contenu).
    """
    start_time = time.time()
    
    try:
        extractor = get_extractor()
        
        result = await extractor.extract_article(
            url=str(request.url),
            source_id=request.source_id,
            source_name=request.source_name,
            force_complete=request.force_complete,
        )
        
        # Mettre à jour les stats
        duration_ms = int((time.time() - start_time) * 1000)
        _stats["total_requests"] += 1
        _stats["total_duration_ms"] += duration_ms
        
        if result.get("content"):
            _stats["successful_requests"] += 1
        else:
            _stats["failed_requests"] += 1
        
        # Stats par stratégie
        method = result.get("extraction_method", "unknown")
        if method not in _stats["by_strategy"]:
            _stats["by_strategy"][method] = {"count": 0, "success": 0}
        _stats["by_strategy"][method]["count"] += 1
        if result.get("content"):
            _stats["by_strategy"][method]["success"] += 1
        
        # Convertir les tentatives en modèles Pydantic
        attempts = []
        for att in result.get("all_attempts", []):
            attempts.append(ExtractionAttempt(
                strategy=att.get("strategy", "unknown"),
                word_count=att.get("word_count", 0),
                is_complete=att.get("is_complete", False),
                success=att.get("success", True),
                error=att.get("error"),
                duration_ms=att.get("duration_ms"),
            ))
        
        return ArticleResponse(
            url=result["url"],
            url_hash=result["url_hash"],
            title=result.get("title"),
            content=result.get("content"),
            author=result.get("author"),
            date=result.get("date"),
            extraction_method=result.get("extraction_method", "unknown"),
            is_complete=result.get("is_complete", False),
            word_count=result.get("word_count", 0),
            confidence_score=result.get("confidence_score", 0.0),
            all_attempts=attempts,
            total_duration_ms=result.get("total_duration_ms", duration_ms),
            extraction_duration_ms=result.get("extraction_duration_ms"),
            error=result.get("error"),
        )
        
    except Exception as e:
        logger.error("extract_article.error", error=str(e))
        _stats["failed_requests"] += 1
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")


@app.post("/extract/batch", response_model=BatchArticleResponse)
async def extract_batch(request: BatchArticleRequest):
    """
    Extrait plusieurs articles en parallèle.
    
    Maximum 50 URLs par requête.
    """
    start_time = time.time()
    
    extractor = get_extractor()
    
    async def extract_one(url):
        try:
            result = await extractor.extract_article(
                url=str(url),
                source_id=request.source_id,
                force_complete=request.force_complete,
            )
            return result
        except Exception as e:
            return {
                "url": str(url),
                "error": str(e),
                "extraction_method": "failed",
                "is_complete": False,
                "word_count": 0,
                "confidence_score": 0,
                "all_attempts": [],
            }
    
    # Limiter la concurrence
    semaphore = asyncio.Semaphore(request.max_concurrent)
    
    async def extract_with_limit(url):
        async with semaphore:
            return await extract_one(url)
    
    # Exécuter toutes les extractions
    results = await asyncio.gather(*[extract_with_limit(url) for url in request.urls])
    
    # Convertir en réponses
    articles = []
    errors = []
    
    for result in results:
        if result.get("error") or not result.get("content"):
            errors.append({
                "url": result.get("url"),
                "error": result.get("error", "No content extracted"),
            })
        
        attempts = [
            ExtractionAttempt(
                strategy=att.get("strategy", "unknown"),
                word_count=att.get("word_count", 0),
                is_complete=att.get("is_complete", False),
                success=att.get("success", True),
                error=att.get("error"),
            )
            for att in result.get("all_attempts", [])
        ]
        
        articles.append(ArticleResponse(
            url=result["url"],
            url_hash=result.get("url_hash", ""),
            title=result.get("title"),
            content=result.get("content"),
            author=result.get("author"),
            date=result.get("date"),
            extraction_method=result.get("extraction_method", "unknown"),
            is_complete=result.get("is_complete", False),
            word_count=result.get("word_count", 0),
            confidence_score=result.get("confidence_score", 0.0),
            all_attempts=attempts,
            total_duration_ms=result.get("total_duration_ms", 0),
            error=result.get("error"),
        ))
    
    total_duration = int((time.time() - start_time) * 1000)
    
    return BatchArticleResponse(
        total=len(request.urls),
        successful=len([a for a in articles if a.content]),
        failed=len(errors),
        articles=articles,
        total_duration_ms=total_duration,
        errors=errors,
    )


@app.post("/verify", response_model=VerificationResponse)
async def verify_content(request: VerificationRequest):
    """
    Vérifie si un contenu est complet (sans troncature/paywall).
    
    Utile pour valider des contenus déjà extraits.
    """
    content = request.content
    
    is_complete, details = is_article_complete(
        content,
        min_words=request.min_words,
    )
    
    from .utils.text_utils import detect_paywall_indicators
    from .utils.html_cleaners import detect_paywall_indicators as html_indicators
    
    # Détecter les indicateurs de paywall
    paywall_indicators = detect_paywall_indicators(content)
    
    # Vérifier la troncature
    truncation_detected = details.get("reason", "").startswith("truncation") or \
                          details.get("reason", "").startswith("low_char")
    
    # Score de complétude
    score = calculate_completeness_score(content, target_word_count=request.min_words * 3)
    
    return VerificationResponse(
        is_complete=is_complete,
        word_count=details.get("word_count", 0),
        completeness_score=score,
        paywall_indicators=paywall_indicators[:5],  # Limiter
        truncation_detected=truncation_detected,
        details=details,
    )


@app.get("/stats")
async def get_stats():
    """Retourne les statistiques d'utilisation du service"""
    uptime = time.time() - _stats["start_time"]
    
    total = _stats["total_requests"]
    
    return {
        "uptime_seconds": uptime,
        "total_requests": total,
        "successful_requests": _stats["successful_requests"],
        "failed_requests": _stats["failed_requests"],
        "success_rate": _stats["successful_requests"] / max(total, 1),
        "average_duration_ms": _stats["total_duration_ms"] / max(total, 1),
        "by_strategy": _stats["by_strategy"],
    }


@app.get("/")
async def root():
    """Page d'accueil"""
    return {
        "service": "OLJ Advanced Scraper",
        "version": "1.0.0",
        "description": "Service de scraping garantissant l'extraction 100% complète des articles",
        "endpoints": {
            "health": "/health",
            "extract": "/extract (POST)",
            "extract_batch": "/extract/batch (POST)",
            "verify": "/verify (POST)",
            "stats": "/stats",
        },
        "documentation": "/docs",
    }


# Gestionnaire d'erreurs globaux
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error("unhandled_exception", error=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)[:100]},
    )
