"""
Script de test pour le service de scraping avancé
Valide l'extraction sur différents médias du Moyen-Orient
"""

import asyncio
import json
from typing import List, Dict
import aiohttp

# URLs de test représentatives des médias de la revue de presse
TEST_URLS = {
    "israel": [
        "https://www.haaretz.com/opinion/2025-04-19/article-title",
        "https://www.jpost.com/opinion/article-title",
        "https://www.timesofisrael.com/opinion/article-title",
    ],
    "saudi": [
        "https://www.arabnews.com/opinion/article-title",
        "https://www.alarabiya.net/views/article-title",
        "https://aawsat.com/الرأي/article-title",
    ],
    "turkey": [
        "https://www.hurriyet.com.tr/yazarlar/article-title",
        "https://www.dailysabah.com/opinion/article-title",
    ],
    "uae": [
        "https://www.thenationalnews.com/opinion/article-title",
        "https://gulfnews.com/opinion/article-title",
    ],
    "qatar": [
        "https://www.aljazeera.com/opinion/article-title",
        "https://www.gulf-times.com/opinion/article-title",
    ],
}

# URL du service (local ou déployé)
SERVICE_URL = "http://localhost:8080"  # ou "https://olj-advanced-scraper.up.railway.app"


async def test_single_url(session: aiohttp.ClientSession, url: str) -> Dict:
    """Teste l'extraction d'une URL"""
    endpoint = f"{SERVICE_URL}/extract"
    
    payload = {
        "url": url,
        "force_complete": True,
    }
    
    try:
        async with session.post(endpoint, json=payload, timeout=aiohttp.ClientTimeout(total=180)) as resp:
            if resp.status == 200:
                result = await resp.json()
                return {
                    "url": url,
                    "success": True,
                    "title": result.get("title"),
                    "word_count": result.get("word_count", 0),
                    "is_complete": result.get("is_complete", False),
                    "method": result.get("extraction_method"),
                    "duration_ms": result.get("total_duration_ms", 0),
                    "attempts": len(result.get("all_attempts", [])),
                }
            else:
                error = await resp.text()
                return {
                    "url": url,
                    "success": False,
                    "error": f"HTTP {resp.status}: {error[:100]}",
                }
    except Exception as e:
        return {
            "url": url,
            "success": False,
            "error": str(e)[:200],
        }


async def test_health(session: aiohttp.ClientSession) -> Dict:
    """Teste l'endpoint health"""
    try:
        async with session.get(f"{SERVICE_URL}/health", timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.json()
            return {"error": f"HTTP {resp.status}"}
    except Exception as e:
        return {"error": str(e)}


async def run_tests():
    """Exécute les tests"""
    print("=" * 60)
    print("OLJ Advanced Scraper - Tests de validation")
    print("=" * 60)
    print(f"Service URL: {SERVICE_URL}")
    print()
    
    async with aiohttp.ClientSession() as session:
        # Test health
        print("1. Vérification santé du service...")
        health = await test_health(session)
        print(f"   Statut: {health.get('status', 'unknown')}")
        print(f"   Version: {health.get('version', 'unknown')}")
        print(f"   Components: curl={health.get('curl_cffi_available')}, "
              f"pw={health.get('playwright_available')}, "
              f"scrapling={health.get('scrapling_available')}")
        print()
        
        # Tests d'extraction (exemple avec des URLs réelles à remplacer)
        print("2. Tests d'extraction (à compléter avec URLs réelles)...")
        print("   Utilisez des URLs réelles des médias cibles")
        print()
        
        # Exemple: tester avec une URL fournie en argument
        import sys
        if len(sys.argv) > 1:
            test_url = sys.argv[1]
            print(f"3. Test de l'URL: {test_url}")
            result = await test_single_url(session, test_url)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print("3. Usage: python test_service.py <URL>")
            print("   Exemple: python test_service.py 'https://www.haaretz.com/opinion/...'")
    
    print()
    print("=" * 60)
    print("Tests terminés")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
