"""
Script de validation complet de tous les médias de la revue de presse
Teste toutes les URLs hub pour s'assurer qu'elles sont accessibles et extractibles
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
import aiohttp
import structlog

logger = structlog.get_logger(__name__)

# Chemin vers le registre média
MEDIA_REGISTRY_PATH = "../backend/data/MEDIA_REVUE_REGISTRY.json"


class MediaValidator:
    """Validateur complet de tous les médias de la revue de presse"""
    
    def __init__(self, timeout: int = 30):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.results: List[Dict] = []
        self.stats = {
            "total": 0,
            "accessible": 0,
            "blocked": 0,
            "errors": 0,
            "by_country": {},
        }
        
    def load_media_registry(self) -> List[Dict]:
        """Charge le registre média"""
        try:
            with open(MEDIA_REGISTRY_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("media", [])
        except Exception as e:
            logger.error("Failed to load media registry", error=str(e))
            return []
    
    async def test_url_accessibility(self, session: aiohttp.ClientSession, url: str) -> Tuple[bool, str, Optional[int]]:
        """Teste si une URL est accessible (sans extraction complète)"""
        try:
            async with session.get(url, timeout=self.timeout, allow_redirects=True) as resp:
                status = resp.status
                
                if status == 200:
                    # Vérifier si ce n'est pas une page Cloudflare/bloquée
                    html = await resp.text()
                    
                    # Indicateurs de blocage
                    if "cloudflare" in html.lower() and "challenge" in html.lower():
                        return False, "cloudflare_challenge", status
                    
                    if "access denied" in html.lower():
                        return False, "access_denied", status
                    
                    if "blocked" in html.lower() and "ip" in html.lower():
                        return False, "ip_blocked", status
                    
                    # Vérifier présence d'articles
                    if len(html) > 1000:  # Page significative
                        return True, "accessible", status
                    else:
                        return False, "empty_page", status
                        
                elif status == 403:
                    return False, "forbidden", status
                elif status == 404:
                    return False, "not_found", status
                elif status == 429:
                    return False, "rate_limited", status
                elif status >= 500:
                    return False, "server_error", status
                else:
                    return False, f"http_{status}", status
                    
        except asyncio.TimeoutError:
            return False, "timeout", None
        except aiohttp.ClientError as e:
            return False, f"client_error: {str(e)[:50]}", None
        except Exception as e:
            return False, f"error: {str(e)[:50]}", None
    
    async def validate_media_source(self, session: aiohttp.ClientSession, media: Dict) -> Dict:
        """Valide une source média (tous ses hubs)"""
        source_id = media.get("id", "unknown")
        name = media.get("name", "unknown")
        country = media.get("country", "unknown")
        is_active = media.get("is_active", True)
        
        result = {
            "source_id": source_id,
            "name": name,
            "country": country,
            "is_active": is_active,
            "hubs": [],
            "overall_status": "unknown",
            "issues": [],
        }
        
        # Tester chaque hub URL
        hub_urls = media.get("opinion_hub_urls", [])
        
        for hub_url in hub_urls:
            accessible, reason, status = await self.test_url_accessibility(session, hub_url)
            
            hub_result = {
                "url": hub_url,
                "accessible": accessible,
                "status": status,
                "reason": reason,
                "domain": urlparse(hub_url).netloc,
            }
            
            result["hubs"].append(hub_result)
            
            if not accessible:
                result["issues"].append(f"{hub_url}: {reason}")
        
        # Déterminer statut global
        if not hub_urls:
            result["overall_status"] = "no_hubs"
        elif any(h["accessible"] for h in result["hubs"]):
            result["overall_status"] = "ok"
        else:
            result["overall_status"] = "all_blocked" if is_active else "inactive_expected"
        
        return result
    
    async def validate_all(self, max_concurrent: int = 5) -> Dict:
        """Valide tous les médias"""
        media_list = self.load_media_registry()
        
        if not media_list:
            logger.error("No media loaded")
            return {"error": "No media loaded"}
        
        self.stats["total"] = len(media_list)
        
        logger.info(f"Starting validation of {len(media_list)} media sources")
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            
            for media in media_list:
                async def validate_with_limit(m):
                    async with semaphore:
                        return await self.validate_media_source(session, m)
                
                tasks.append(validate_with_limit(media))
            
            # Exécuter avec barre de progression
            completed = 0
            for coro in asyncio.as_completed(tasks):
                result = await coro
                self.results.append(result)
                completed += 1
                
                if completed % 10 == 0:
                    logger.info(f"Progress: {completed}/{len(media_list)}")
        
        # Calculer statistiques
        self._compute_stats()
        
        return self._generate_report()
    
    def _compute_stats(self):
        """Calcule les statistiques globales"""
        for result in self.results:
            country = result["country"]
            if country not in self.stats["by_country"]:
                self.stats["by_country"][country] = {"total": 0, "ok": 0, "blocked": 0}
            
            self.stats["by_country"][country]["total"] += 1
            
            if result["overall_status"] == "ok":
                self.stats["accessible"] += 1
                self.stats["by_country"][country]["ok"] += 1
            elif result["overall_status"] in ["all_blocked", "no_hubs"]:
                self.stats["blocked"] += 1
                self.stats["by_country"][country]["blocked"] += 1
            else:
                self.stats["errors"] += 1
    
    def _generate_report(self) -> Dict:
        """Génère le rapport final"""
        
        # Médias problématiques (actifs mais bloqués)
        problematic = [
            r for r in self.results 
            if r["overall_status"] in ["all_blocked", "no_hubs"] and r.get("is_active", True)
        ]
        
        # Médias OK
        ok_media = [r for r in self.results if r["overall_status"] == "ok"]
        
        # Inactifs (normal s'ils sont bloqués)
        inactive = [r for r in self.results if not r.get("is_active", True)]
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_media": self.stats["total"],
                "accessible": self.stats["accessible"],
                "blocked": self.stats["blocked"],
                "errors": self.stats["errors"],
                "success_rate": round(self.stats["accessible"] / max(self.stats["total"], 1) * 100, 1),
            },
            "by_country": self.stats["by_country"],
            "problematic_media": problematic,
            "ok_media_count": len(ok_media),
            "inactive_media_count": len(inactive),
            "recommendations": self._generate_recommendations(problematic),
        }
        
        return report
    
    def _generate_recommendations(self, problematic: List[Dict]) -> List[str]:
        """Génère des recommandations basées sur les problèmes"""
        recommendations = []
        
        if not problematic:
            recommendations.append("✅ Tous les médias actifs sont accessibles!")
            return recommendations
        
        # Grouper par type de problème
        by_issue = {}
        for media in problematic:
            for issue in media.get("issues", []):
                if "cloudflare" in issue.lower():
                    by_issue.setdefault("cloudflare", []).append(media["name"])
                elif "timeout" in issue.lower():
                    by_issue.setdefault("timeout", []).append(media["name"])
                elif "forbidden" in issue.lower() or "403" in issue:
                    by_issue.setdefault("blocked", []).append(media["name"])
                else:
                    by_issue.setdefault("other", []).append(media["name"])
        
        if "cloudflare" in by_issue:
            recommendations.append(
                f"⚠️  {len(by_issue['cloudflare'])} médias protégés par Cloudflare: "
                f"{', '.join(by_issue['cloudflare'][:3])}{'...' if len(by_issue['cloudflare']) > 3 else ''}. "
                f"Le service de scraping avancé avec curl_cffi et Playwright est RECOMMANDÉ."
            )
        
        if "blocked" in by_issue:
            recommendations.append(
                f"⚠️  {len(by_issue['blocked'])} médias bloquent les requêtes (403): "
                f"{', '.join(by_issue['blocked'][:3])}{'...' if len(by_issue['blocked']) > 3 else ''}. "
                f"Nécessite Jina AI ou des proxies."
            )
        
        if "timeout" in by_issue:
            recommendations.append(
                f"⚠️  {len(by_issue['timeout'])} médias timeout: "
                f"{', '.join(by_issue['timeout'][:3])}. "
                f"Vérifier la connectivité réseau."
            )
        
        recommendations.append(
            f"📊 Recommandation: Déployer le service de scraping avancé "
            f"pour résoudre {len(problematic)} problèmes d'accès."
        )
        
        return recommendations
    
    def save_report(self, report: Dict, filename: str = "media_validation_report.json"):
        """Sauvegarde le rapport"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info(f"Report saved to {filename}")
    
    def print_summary(self, report: Dict):
        """Affiche un résumé console"""
        print("\n" + "="*70)
        print("VALIDATION DES MÉDIAS - RAPPORT")
        print("="*70)
        
        summary = report["summary"]
        print(f"\n📊 STATISTIQUES GLOBALES")
        print(f"   Total médias: {summary['total_media']}")
        print(f"   ✅ Accessibles: {summary['accessible']} ({summary['success_rate']}%)")
        print(f"   ❌ Bloqués: {summary['blocked']}")
        print(f"   ⚠️  Erreurs: {summary['errors']}")
        
        print(f"\n🌍 PAR PAYS")
        for country, stats in sorted(report["by_country"].items()):
            ok_rate = round(stats["ok"] / max(stats["total"], 1) * 100, 0)
            status_emoji = "✅" if ok_rate >= 80 else "⚠️" if ok_rate >= 50 else "❌"
            print(f"   {status_emoji} {country}: {stats['ok']}/{stats['total']} OK ({ok_rate}%)")
        
        print(f"\n💡 RECOMMANDATIONS")
        for rec in report["recommendations"]:
            print(f"   {rec}")
        
        problematic = report.get("problematic_media", [])
        if problematic:
            print(f"\n❌ MÉDIAS PROBLÉMATIQUES ({len(problematic)})")
            for media in problematic[:10]:  # Limiter à 10
                print(f"   • {media['name']} ({media['country']})")
                for issue in media.get("issues", [])[:2]:
                    print(f"     └─ {issue[:60]}...")
            if len(problematic) > 10:
                print(f"     ... et {len(problematic) - 10} autres")
        
        print("\n" + "="*70)


async def main():
    """Point d'entrée principal"""
    print("🚀 Démarrage de la validation complète des médias...")
    print("   Cela peut prendre 2-3 minutes...\n")
    
    start_time = time.time()
    
    validator = MediaValidator(timeout=25)
    report = await validator.validate_all(max_concurrent=8)
    
    duration = time.time() - start_time
    
    # Sauvegarder rapport complet
    validator.save_report(report)
    
    # Afficher résumé
    validator.print_summary(report)
    
    print(f"\n⏱️  Durée: {duration:.1f} secondes")
    print(f"📄 Rapport complet sauvegardé dans: media_validation_report.json")
    
    # Retourner code de sortie approprié
    success_rate = report["summary"]["success_rate"]
    
    if success_rate >= 90:
        print("\n✅ VALIDATION RÉUSSIE - Peut fonctionner sans service avancé")
        return 0
    elif success_rate >= 70:
        print("\n⚠️  VALIDATION PARTIELLE - Service avancé RECOMMANDÉ")
        return 1
    else:
        print("\n❌ VALIDATION ÉCHOUÉE - Service avancé INDISPENSABLE")
        return 2


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
