"""
Extracteur Ultime - Garantit 100% d'extraction complète
Cascade de stratégies de plus en plus agressives pour contourner les paywalls
"""

import asyncio
import hashlib
import json
import random
import re
import time
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlparse, urljoin, quote
import structlog

from curl_cffi import requests as curl_requests
from curl_cffi.requests import Session as CurlSession
import trafilatura
from bs4 import BeautifulSoup

from ..config.settings import get_settings
from ..utils.text_utils import count_words, estimate_reading_time, is_article_complete
from ..utils.html_cleaners import clean_boilerplate, detect_paywall_indicators

logger = structlog.get_logger(__name__)


class UltimateExtractor:
    """
    Extracteur ultime avec cascade de stratégies pour extraction 100%
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.curl_session: Optional[CurlSession] = None
        self._init_curl_session()
        self._extraction_stats: Dict[str, Dict] = {}
        
    def _init_curl_session(self):
        """Initialise la session curl_cffi avec impersonation TLS"""
        try:
            self.curl_session = CurlSession()
            logger.info("curl_session.initialized")
        except Exception as e:
            logger.warning("curl_session.init_failed", error=str(e))
    
    async def extract_article(
        self,
        url: str,
        source_id: Optional[str] = None,
        source_name: Optional[str] = None,
        force_complete: bool = True,
    ) -> Dict[str, Any]:
        """
        Extrait un article avec garantie de complétude
        
        Args:
            url: URL de l'article
            source_id: Identifiant de la source (pour overrides)
            source_name: Nom de la source
            force_complete: Si True, continue jusqu'à obtenir un article complet
            
        Returns:
            Dict avec: title, content, author, date, url, extraction_method, 
                      is_complete, word_count, confidence_score
        """
        start_time = time.time()
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        
        logger.info(
            "extraction.start",
            url=url[:100],
            url_hash=url_hash,
            source=source_name or source_id or "unknown",
        )
        
        # Cache check
        if self.settings.cache_enabled:
            cached = await self._get_from_cache(url_hash)
            if cached:
                logger.info("extraction.cache_hit", url_hash=url_hash)
                return cached
        
        # Stratégies d'extraction en cascade
        strategies = self._get_strategies_for_url(url, source_id)
        
        best_result: Optional[Dict] = None
        all_attempts: List[Dict] = []
        
        for idx, strategy in enumerate(strategies):
            attempt_start = time.time()
            
            try:
                result = await self._execute_strategy(
                    strategy, 
                    url, 
                    source_id=source_id,
                    attempt_number=idx + 1
                )
                
                attempt_duration = time.time() - attempt_start
                
                if result and result.get("content"):
                    # Évaluer la qualité
                    is_complete = self._evaluate_completeness(result, url)
                    result["is_complete"] = is_complete
                    result["extraction_duration_ms"] = int(attempt_duration * 1000)
                    
                    all_attempts.append({
                        "strategy": strategy,
                        "word_count": result.get("word_count", 0),
                        "is_complete": is_complete,
                        "success": True,
                    })
                    
                    # Garder le meilleur résultat
                    if best_result is None or self._is_better_result(result, best_result):
                        best_result = result
                        logger.info(
                            "extraction.better_result",
                            strategy=strategy,
                            word_count=result.get("word_count", 0),
                            is_complete=is_complete,
                        )
                    
                    # Si complet et pas force_complete, on s'arrête
                    if is_complete and not force_complete:
                        logger.info(
                            "extraction.complete_early",
                            strategy=strategy,
                            attempts=idx + 1,
                        )
                        break
                        
                    # Si très complet (>95% de l'objectif), on peut s'arrêter
                    if result.get("word_count", 0) > self.settings.target_article_words * 0.95:
                        logger.info(
                            "extraction.target_reached",
                            strategy=strategy,
                            word_count=result.get("word_count", 0),
                        )
                        break
                        
            except Exception as e:
                attempt_duration = time.time() - attempt_start
                logger.warning(
                    "extraction.strategy_failed",
                    strategy=strategy,
                    error=str(e)[:100],
                    duration_ms=int(attempt_duration * 1000),
                )
                all_attempts.append({
                    "strategy": strategy,
                    "success": False,
                    "error": str(e)[:100],
                })
                continue
        
        total_duration = time.time() - start_time
        
        if best_result:
            best_result["total_duration_ms"] = int(total_duration * 1000)
            best_result["all_attempts"] = all_attempts
            best_result["url_hash"] = url_hash

            # Final completeness check with combined strategies if needed
            if not best_result.get("is_complete", False) and force_complete:
                best_result = await self._try_combined_strategies(url, best_result, all_attempts)

            # SPEC §3.1 T6 — LLM cleanup en dernier recours.
            # Si le meilleur texte obtenu contient encore du résidu paywall
            # (CTAs, "Vous aimerez aussi"…), on demande à un LLM cheap de
            # nettoyer. Bypass-é si pas de clé Groq configurée.
            try:
                from .paywall_bypass import (
                    LLM_CLEANUP_API_KEY,
                    extract_llm_cleanup,
                    looks_paywalled,
                )

                content = best_result.get("content") or ""
                if (
                    LLM_CLEANUP_API_KEY
                    and content
                    and looks_paywalled(content)
                    and len(content) > 400
                ):
                    cleaned = await extract_llm_cleanup(url, content)
                    if cleaned and cleaned.get("word_count", 0) >= max(
                        80, int(best_result.get("word_count", 0) * 0.3)
                    ):
                        # On garde le meilleur des deux selon completeness.
                        cleaned["is_complete"] = self._evaluate_completeness(cleaned, url)
                        cleaned["all_attempts"] = (
                            all_attempts
                            + [{"strategy": "llm_cleanup", "success": True,
                                "word_count": cleaned.get("word_count", 0)}]
                        )
                        cleaned["url_hash"] = url_hash
                        cleaned["total_duration_ms"] = int(
                            (time.time() - start_time) * 1000
                        )
                        # On préfère cleanup si il livre un texte plus complet
                        # OU si l'original contient toujours du paywall residue.
                        if cleaned.get("is_complete") or not looks_paywalled(
                            cleaned.get("content") or ""
                        ):
                            best_result = cleaned
                            logger.info(
                                "extraction.llm_cleanup_applied",
                                url_hash=url_hash,
                                before_wc=len(content.split()),
                                after_wc=cleaned.get("word_count"),
                            )
            except Exception as exc:
                logger.warning(
                    "extraction.llm_cleanup_skipped",
                    url_hash=url_hash,
                    error=str(exc)[:200],
                )
            
            # Cache le résultat
            if self.settings.cache_enabled:
                await self._save_to_cache(url_hash, best_result)
            
            logger.info(
                "extraction.success",
                url_hash=url_hash,
                method=best_result.get("extraction_method"),
                word_count=best_result.get("word_count", 0),
                is_complete=best_result.get("is_complete", False),
                duration_ms=int(total_duration * 1000),
            )
            
            return best_result
        
        # Échec total
        logger.error(
            "extraction.total_failure",
            url=url[:100],
            attempts=len(all_attempts),
            duration_ms=int(total_duration * 1000),
        )
        
        return {
            "url": url,
            "url_hash": url_hash,
            "title": None,
            "content": None,
            "author": None,
            "date": None,
            "extraction_method": "failed",
            "is_complete": False,
            "word_count": 0,
            "error": "All extraction strategies failed",
            "all_attempts": all_attempts,
            "total_duration_ms": int(total_duration * 1000),
        }
    
    def _get_strategies_for_url(
        self, 
        url: str, 
        source_id: Optional[str]
    ) -> List[str]:
        """Détermine les stratégies prioritaires selon l'URL"""
        domain = urlparse(url).netloc.lower()
        
        # Stratégies par défaut
        strategies = list(self.settings.extraction_strategies)
        
        # Overrides par domaine — PRESSE FRANÇAISE (ED_Mediawatch).
        # Pour les sites premium FR, on prépose googlebot_referer + archive_ph aux
        # tiers JS lourds (gratuits, souvent suffisants pour contourner le paywall,
        # et ramènent un body propre que jina parse mal). curl_cffi (impersonation
        # TLS) sert pour les sites qui rendent un 403 à l'IP datacenter Railway
        # (Figaro, Télégramme, groupe EBRA). Les paywalls DURS souscrits (Le Monde,
        # Mediapart) passent surtout par SITE_COOKIES, géré côté backend en amont.
        domain_overrides = {
            # --- Nationaux paywall doux / first-click-free ---
            "lemonde.fr": [
                "googlebot_referer", "archive_ph", "curl_cffi",
                "playwright_stealth", "jina_ai",
            ],
            "lefigaro.fr": [
                "googlebot_referer", "archive_ph", "curl_cffi", "playwright_stealth",
            ],
            "liberation.fr": [
                "googlebot_referer", "archive_ph", "curl_cffi", "jina_ai",
                "playwright_stealth",
            ],
            "lepoint.fr": [
                "googlebot_referer", "archive_ph", "curl_cffi", "playwright_stealth",
            ],
            "lexpress.fr": [
                "googlebot_referer", "archive_ph", "curl_cffi", "playwright_stealth",
            ],
            "nouvelobs.com": [
                "googlebot_referer", "archive_ph", "curl_cffi", "playwright_stealth",
            ],
            "lopinion.fr": ["googlebot_referer", "archive_ph", "curl_cffi"],
            "marianne.net": ["googlebot_referer", "curl_cffi", "jina_ai"],
            "latribune.fr": ["googlebot_referer", "curl_cffi", "jina_ai"],
            "lesechos.fr": [
                "googlebot_referer", "archive_ph", "curl_cffi", "playwright_stealth",
            ],
            # --- Paywall DUR (archive.ph en tête ; cookies côté backend si dispo) ---
            "mediapart.fr": ["archive_ph", "curl_cffi", "playwright_stealth"],
            # --- Médias droite / ED (souvent anti-bot, parfois full en RSS) ---
            "valeursactuelles.com": ["curl_cffi", "jina_ai", "playwright_stealth"],
            "causeur.fr": ["curl_cffi", "jina_ai"],
            "bvoltaire.fr": ["curl_cffi", "jina_ai"],
            "frontpopulaire.fr": ["googlebot_referer", "curl_cffi", "jina_ai"],
            # --- PQR groupe EBRA (paywall + 403 datacenter → curl_cffi/googlebot) ---
            "ledauphine.com": ["googlebot_referer", "archive_ph", "curl_cffi", "jina_ai"],
            "estrepublicain.fr": ["googlebot_referer", "archive_ph", "curl_cffi", "jina_ai"],
            "dna.fr": ["googlebot_referer", "archive_ph", "curl_cffi", "jina_ai"],
            "lalsace.fr": ["googlebot_referer", "archive_ph", "curl_cffi", "jina_ai"],
            "republicain-lorrain.fr": ["googlebot_referer", "archive_ph", "curl_cffi", "jina_ai"],
            "bienpublic.com": ["googlebot_referer", "archive_ph", "curl_cffi", "jina_ai"],
            "leprogres.fr": ["googlebot_referer", "archive_ph", "curl_cffi", "jina_ai"],
            # --- Autre PQR (curl_cffi d'abord ; beaucoup servent l'article complet) ---
            "letelegramme.fr": ["googlebot_referer", "curl_cffi", "archive_ph", "jina_ai"],
            "ouest-france.fr": ["curl_cffi", "googlebot_referer", "jina_ai"],
            "sudouest.fr": ["googlebot_referer", "curl_cffi", "jina_ai"],
            "lavoixdunord.fr": ["googlebot_referer", "curl_cffi", "jina_ai"],
            "ladepeche.fr": ["curl_cffi", "googlebot_referer", "jina_ai"],
            "nicematin.com": ["googlebot_referer", "curl_cffi", "jina_ai"],
            "laprovence.com": ["googlebot_referer", "curl_cffi", "jina_ai"],
        }
        
        for key_domain, override_strategies in domain_overrides.items():
            if key_domain in domain:
                strategies = override_strategies + [s for s in strategies if s not in override_strategies]
                break
        
        return strategies
    
    async def _execute_strategy(
        self,
        strategy: str,
        url: str,
        source_id: Optional[str] = None,
        attempt_number: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """Exécute une stratégie d'extraction spécifique"""

        if strategy == "curl_cffi":
            return await self._extract_with_curl_cffi(url)
        elif strategy == "playwright_stealth":
            return await self._extract_with_playwright(url, stealth=True)
        elif strategy == "scrapling_cf":
            return await self._extract_with_scrapling(url)
        elif strategy == "jina_ai":
            return await self._extract_with_jina_ai(url)
        elif strategy == "wayback":
            return await self._extract_with_wayback(url)
        elif strategy == "textise":
            return await self._extract_with_textise(url)
        elif strategy == "outline":
            return await self._extract_with_outline(url)
        # SPEC §3.1 — nouveaux tiers paywall bypass
        elif strategy == "googlebot_referer":
            from .paywall_bypass import extract_googlebot_referer
            return await extract_googlebot_referer(url)
        elif strategy == "archive_ph":
            from .paywall_bypass import extract_archive_ph
            return await extract_archive_ph(url)
        elif strategy == "llm_cleanup":
            # T6 — n'a de sens qu'en dernier recours, sur le meilleur texte
            # déjà obtenu. Géré par l'orchestrateur principal, pas via la
            # boucle linéaire.
            logger.debug("extraction.llm_cleanup_skipped_in_loop")
            return None
        else:
            logger.warning("extraction.unknown_strategy", strategy=strategy)
            return None
    
    async def _extract_with_curl_cffi(self, url: str) -> Optional[Dict]:
        """Extraction avec curl_cffi (spoofing TLS/JA3)"""
        if not self.curl_session:
            self._init_curl_session()
        
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,fr;q=0.8,ar;q=0.7,he;q=0.6",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
        
        # Impersonate Chrome 131 (dernier stable au moment du développement)
        impersonate = random.choice(["chrome131", "chrome136", "chrome124", "edge101"])
        
        try:
            resp = self.curl_session.get(
                url,
                headers=headers,
                impersonate=impersonate,
                timeout=self.settings.request_timeout,
                allow_redirects=True,
            )
            
            if resp.status_code != 200:
                logger.warning(
                    "curl_cffi.http_error",
                    url=url[:80],
                    status=resp.status_code,
                )
                return None
            
            html = resp.text
            return self._parse_html_to_article(html, url, method="curl_cffi")
            
        except Exception as e:
            logger.warning("curl_cffi.error", url=url[:80], error=str(e)[:100])
            return None
    
    async def _extract_with_playwright(
        self, 
        url: str, 
        stealth: bool = True
    ) -> Optional[Dict]:
        """Extraction avec Playwright en mode furtif"""
        from playwright.async_api import async_playwright
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=self.settings.playwright_headless,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-web-security",
                        "--disable-features=IsolateOrigins,site-per-process",
                    ],
                    ignore_default_args=["--enable-automation"],
                )
                
                context = await browser.new_context(
                    viewport={
                        "width": self.settings.playwright_viewport_width,
                        "height": self.settings.playwright_viewport_height,
                    },
                    user_agent=random.choice([
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
                    ]),
                    locale="en-US",
                    timezone_id="America/New_York",
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
                        "Sec-Ch-Ua-Mobile": "?0",
                        "Sec-Ch-Ua-Platform": '"Windows"',
                        "DNT": "1",
                    },
                )
                
                # Anti-detection scripts
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                    window.chrome = { runtime: {} };
                    window.Notification = undefined;
                """)
                
                page = await context.new_page()
                
                # Blocker de ressources non essentielles
                await page.route(
                    "**/*",
                    lambda route: route.abort() if route.request.resource_type in [
                        "image", "media", "font", "websocket"
                    ] else route.continue_()
                )
                
                # Navigation
                await page.goto(
                    url, 
                    wait_until="networkidle",
                    timeout=self.settings.playwright_navigation_timeout,
                )
                
                # Attendre le chargement
                await page.wait_for_timeout(self.settings.playwright_wait_after_load)
                
                # Scroll pour lazy loading
                await self._smart_scroll(page)
                
                # Extraire le contenu
                html = await page.content()
                
                await browser.close()
                
                return self._parse_html_to_article(html, url, method="playwright_stealth")
                
        except Exception as e:
            logger.warning("playwright.error", url=url[:80], error=str(e)[:150])
            return None
    
    async def _smart_scroll(self, page):
        """Scroll intelligent pour charger le contenu lazy"""
        try:
            # Scroll progressif
            for i in range(self.settings.playwright_max_scrolls):
                await page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
                await page.wait_for_timeout(500 + random.randint(100, 400))
                
                # Vérifier si on est en bas de page
                is_bottom = await page.evaluate(
                    "window.innerHeight + window.scrollY >= document.body.scrollHeight - 100"
                )
                if is_bottom:
                    break
                    
        except Exception as e:
            logger.debug("scroll.warning", error=str(e))
    
    async def _extract_with_scrapling(self, url: str) -> Optional[Dict]:
        """Extraction avec Scrapling (bypass Cloudflare spécialisé)"""
        try:
            from scrapling.fetchers import StealthyFetcher
            
            fetcher = StealthyFetcher()
            page = fetcher.fetch(
                url,
                headless=True,
                solve_cloudflare=self.settings.scrapling_solve_cf,
                network_idle=True,
            )
            
            html = page.html if hasattr(page, "html") else str(page)
            return self._parse_html_to_article(html, url, method="scrapling_cf")
            
        except Exception as e:
            logger.warning("scrapling.error", url=url[:80], error=str(e)[:100])
            return None
    
    async def _extract_with_jina_ai(self, url: str) -> Optional[Dict]:
        """Extraction via Jina AI Reader (proxy de contenu)"""
        try:
            import aiohttp
            
            clean_url = url.replace("https://", "").replace("http://", "")
            jina_url = f"https://r.jina.ai/https://{clean_url}"
            
            headers = {
                "Accept": "text/html,text/plain,*/*",
                "User-Agent": "Mozilla/5.0 (compatible; JinaReader/1.0)",
            }
            
            if self.settings.jina_ai_api_key:
                headers["Authorization"] = f"Bearer {self.settings.jina_ai_api_key}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    jina_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.settings.jina_ai_timeout),
                ) as resp:
                    if resp.status != 200:
                        return None
                    
                    text = await resp.text()
                    
                    # Jina retourne du markdown, parser intelligemment
                    return self._parse_jina_response(text, url)
                    
        except Exception as e:
            logger.warning("jina_ai.error", url=url[:80], error=str(e)[:100])
            return None
    
    async def _extract_with_wayback(self, url: str) -> Optional[Dict]:
        """Extraction depuis Wayback Machine"""
        try:
            import aiohttp
            
            # Chercher un snapshot récent
            cdx_url = (
                f"http://web.archive.org/cdx/search/cdx"
                f"?url={quote(url)}&output=json&limit=5&fl=timestamp,original"
                f"&filter=statuscode:200&from=20240101"
            )
            
            async with aiohttp.ClientSession() as session:
                async with session.get(cdx_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return None
                    
                    data = await resp.json()
                    if not data or len(data) < 2:
                        return None
                    
                    # Prendre le snapshot le plus récent
                    timestamps = [row[0] for row in data[1:]]
                    if not timestamps:
                        return None
                    
                    latest = max(timestamps)
                    archive_url = f"http://web.archive.org/web/{latest}/{url}"
                    
                    # Fetch depuis l'archive
                    async with session.get(
                        archive_url,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as archive_resp:
                        if archive_resp.status != 200:
                            return None
                        
                        html = await archive_resp.text()
                        return self._parse_html_to_article(html, url, method="wayback")
                        
        except Exception as e:
            logger.warning("wayback.error", url=url[:80], error=str(e)[:100])
            return None
    
    async def _extract_with_textise(self, url: str) -> Optional[Dict]:
        """Extraction via textise dot iitty ou services similaires"""
        # Cette méthode peut être implémentée avec des services comme textise dot iitty
        # ou textise dot net si disponibles
        return None
    
    async def _extract_with_outline(self, url: str) -> Optional[Dict]:
        """Extraction via outline dot com ou services similaires"""
        # Cette méthode peut être implémentée avec outline ou services similaires
        return None
    
    def _parse_html_to_article(
        self, 
        html: str, 
        url: str, 
        method: str
    ) -> Dict[str, Any]:
        """Parse le HTML et extrait l'article avec trafilatura + fallback"""
        
        # D'abord essayer trafilatura en mode recall
        content = None
        title = None
        
        try:
            content = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=False,
                favor_recall=True,
                output_format="txt",
                deduplicate=True,
                url=url,
            )
            
            if not content or len(content) < 200:
                # Essayer en mode precision
                content = trafilatura.extract(
                    html,
                    include_comments=False,
                    include_tables=False,
                    favor_precision=True,
                    output_format="txt",
                    deduplicate=True,
                    url=url,
                )
        except Exception as e:
            logger.debug("trafilatura.error", error=str(e))
        
        # Fallback: extraction BS4 si trafilatura échoue
        if not content or len(content) < 200:
            content = self._fallback_bs4_extraction(html)
        
        # Extraction des métadonnées
        title = self._extract_title(html) or ""
        author = self._extract_author(html)
        date = self._extract_date(html)
        
        # Nettoyage
        if content:
            content = clean_boilerplate(content)
        
        word_count = count_words(content) if content else 0
        
        return {
            "url": url,
            "title": title,
            "content": content,
            "author": author,
            "date": date,
            "extraction_method": method,
            "word_count": word_count,
            "confidence_score": self._calculate_confidence(word_count, method),
        }
    
    def _fallback_bs4_extraction(self, html: str) -> Optional[str]:
        """Extraction fallback avec BeautifulSoup"""
        try:
            soup = BeautifulSoup(html, "lxml")
            
            # Supprimer les éléments non pertinents
            for tag in soup(["script", "style", "nav", "header", "footer", "aside", "ads"]):
                tag.decompose()
            
            # Chercher les conteneurs d'article communs
            selectors = [
                "article",
                "[class*='article-content']",
                "[class*='article-body']",
                "[class*='story-body']",
                "[class*='post-content']",
                "[class*='entry-content']",
                "main",
                "[role='main']",
                ".content",
                "#content",
                ".article",
                ".story",
                ".post",
            ]
            
            best_content = ""
            for selector in selectors:
                element = soup.select_one(selector)
                if element:
                    text = element.get_text(separator="\n", strip=True)
                    if len(text) > len(best_content):
                        best_content = text
            
            return best_content if len(best_content) > 200 else None
            
        except Exception as e:
            logger.debug("bs4_extraction.error", error=str(e))
            return None
    
    def _parse_jina_response(self, text: str, url: str) -> Dict:
        """Parse la réponse de Jina AI"""
        lines = text.split("\n")
        title = ""
        content_lines = []
        
        # Jina format: première ligne souvent le titre
        if lines:
            title = lines[0].strip()
            content_lines = lines[1:]
        
        content = "\n".join(content_lines).strip()
        
        # Nettoyer les marqueurs markdown
        content = re.sub(r'^#+\s*', '', content, flags=re.MULTILINE)
        
        word_count = count_words(content)
        
        return {
            "url": url,
            "title": title,
            "content": content,
            "author": None,
            "date": None,
            "extraction_method": "jina_ai",
            "word_count": word_count,
            "confidence_score": 0.7 if word_count > 300 else 0.5,
        }
    
    def _extract_title(self, html: str) -> Optional[str]:
        """Extrait le titre de l'article"""
        try:
            soup = BeautifulSoup(html, "lxml")
            
            # OG title
            og = soup.find("meta", property="og:title")
            if og and og.get("content"):
                return og["content"].strip()
            
            # Twitter title
            tw = soup.find("meta", attrs={"name": "twitter:title"})
            if tw and tw.get("content"):
                return tw["content"].strip()
            
            # Article title
            for selector in ["h1.article-title", "h1.entry-title", "h1.post-title", "h1", ".article-title", ".entry-title"]:
                el = soup.select_one(selector)
                if el:
                    return el.get_text(strip=True)
            
            # Fallback: title tag
            if soup.title:
                return soup.title.get_text(strip=True)
                
        except Exception:
            pass
        return None
    
    def _extract_author(self, html: str) -> Optional[str]:
        """Extrait l'auteur de l'article"""
        try:
            soup = BeautifulSoup(html, "lxml")
            
            # JSON-LD
            scripts = soup.find_all("script", type="application/ld+json")
            for script in scripts:
                try:
                    data = json.loads(script.string or "{}")
                    if isinstance(data, dict):
                        author = data.get("author", {})
                        if isinstance(author, dict):
                            return author.get("name")
                        elif isinstance(author, list) and author:
                            return author[0].get("name")
                except:
                    pass
            
            # Meta tags
            for prop in ["article:author", "author", "byl"]:
                meta = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
                if meta and meta.get("content"):
                    return meta["content"].strip()
            
            # Class patterns
            for cls in ["author", "byline", "writer", "journalist"]:
                el = soup.find(class_=re.compile(cls, re.I))
                if el:
                    return el.get_text(strip=True)
                    
        except Exception:
            pass
        return None
    
    def _extract_date(self, html: str) -> Optional[str]:
        """Extrait la date de publication"""
        try:
            soup = BeautifulSoup(html, "lxml")
            
            # Meta tags
            for prop in ["article:published_time", "publishedDate", "datePublished", "date"]:
                meta = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
                if meta and meta.get("content"):
                    return meta["content"].strip()
            
            # Time element
            time_el = soup.find("time")
            if time_el:
                return time_el.get("datetime") or time_el.get_text(strip=True)
                
        except Exception:
            pass
        return None
    
    def _evaluate_completeness(self, result: Dict, url: str) -> bool:
        """Évalue si l'article est complet"""
        content = result.get("content", "")
        word_count = result.get("word_count", 0)
        
        # Vérification mot-clé
        if not content:
            return False
        
        # Vérifier les indicateurs de troncature
        paywall_indicators = detect_paywall_indicators(content)
        if paywall_indicators:
            logger.debug("paywall_indicators_found", url=url[:80], indicators=paywall_indicators)
            return False
        
        # Seuil de complétude
        if word_count < self.settings.min_article_words:
            return False
        
        # Vérification ratio caractères/mots (indicateur de qualité)
        if len(content) / max(word_count, 1) < 3:  # Trop peu de caractères par mot = probablement incomplet
            return False
        
        return True
    
    def _is_better_result(self, new: Dict, current: Dict) -> bool:
        """Détermine si un nouveau résultat est meilleur que l'actuel"""
        new_words = new.get("word_count", 0)
        current_words = current.get("word_count", 0)
        
        # Priorité au contenu complet
        new_complete = new.get("is_complete", False)
        current_complete = current.get("is_complete", False)
        
        if new_complete and not current_complete:
            return True
        if not new_complete and current_complete:
            return False
        
        # Si même statut de complétude, comparer le nombre de mots
        return new_words > current_words
    
    def _calculate_confidence(self, word_count: int, method: str) -> float:
        """Calcule un score de confiance"""
        base_scores = {
            "curl_cffi": 0.85,
            "playwright_stealth": 0.9,
            "scrapling_cf": 0.8,
            "jina_ai": 0.75,
            "wayback": 0.7,
            "fallback": 0.5,
        }
        
        base = base_scores.get(method, 0.6)
        
        # Bonus pour articles longs
        if word_count > 500:
            base += 0.1
        if word_count > 1000:
            base += 0.05
        
        return min(1.0, base)
    
    async def _try_combined_strategies(
        self,
        url: str,
        best_result: Dict,
        attempts: List[Dict],
    ) -> Dict:
        """Essaye de combiner les résultats de plusieurs stratégies"""
        # Si plusieurs stratégies ont donné des résultats, essayer de les fusionner
        contents = [best_result.get("content", "")]
        
        # TODO: Implémenter la fusion intelligente de contenu
        # Pour l'instant, on garde le meilleur
        
        return best_result
    
    async def _get_from_cache(self, url_hash: str) -> Optional[Dict]:
        """Récupère un résultat du cache"""
        # TODO: Implémenter cache Redis ou disque
        return None
    
    async def _save_to_cache(self, url_hash: str, result: Dict):
        """Sauvegarde un résultat dans le cache"""
        # TODO: Implémenter cache Redis ou disque
        pass
