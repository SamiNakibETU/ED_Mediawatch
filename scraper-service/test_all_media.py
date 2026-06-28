#!/usr/bin/env python3
"""
Test complet de tous les médias du CSV "media revue - Sheet1.csv"
Valide l'extraction sur chaque source avant déploiement
"""

import asyncio
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
import structlog

# Ajouter le src au path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.ultimate_extractor import UltimateExtractor
from config.settings import get_settings
from utils.text_utils import is_article_complete

# Configuration logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger(__name__)


class MediaTester:
    """Testeur de médias pour validation pré-déploiement"""
    
    def __init__(self):
        self.extractor = UltimateExtractor()
        self.results: List[Dict] = []
        self.csv_path = Path(__file__).parent.parent / "archive" / "media revue - Sheet1.csv"
        
    def read_media_csv(self) -> List[Dict]:
        """Lit le CSV des médias et retourne la liste des sources actives"""
        media_list = []
        
        if not self.csv_path.exists():
            logger.error("csv_not_found", path=str(self.csv_path))
            return []
        
        try:
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not row.get('nom') or not row.get('url'):
                        continue
                    
                    # Nettoyer les données
                    media = {
                        'country': row.get('Pays', '').strip(),
                        'name': row.get('nom', '').strip(),
                        'language': row.get('langue', '').strip(),
                        'url': row.get('url', '').strip(),
                        'category_url': row.get('catégories', '').strip(),
                        'notes': row.get('notes', '').strip(),
                    }
                    
                    if media['url'] and media['name']:
                        media_list.append(media)
                        
        except Exception as e:
            logger.error("csv_read_error", error=str(e))
            
        # Dédoublonner par URL
        seen = set()
        unique = []
        for m in media_list:
            if m['url'] not in seen:
                seen.add(m['url'])
                unique.append(m)
        
        logger.info("media_loaded", count=len(unique))
        return unique
    
    async def test_media(self, media: Dict) -> Dict:
        """Teste un média spécifique"""
        url = media['url']
        name = media['name']
        country = media['country']
        
        result = {
            'name': name,
            'country': country,
            'url': url,
            'tested_at': datetime.now().isoformat(),
            'success': False,
            'word_count': 0,
            'is_complete': False,
            'extraction_method': None,
            'error': None,
            'duration_ms': 0,
            'http_status': None,
        }
        
        try:
            # Timeout par média: 60s max
            start = time.time()
            
            extraction = await asyncio.wait_for(
                self.extractor.extract_article(
                    url=url,
                    source_name=name,
                    force_complete=False,  # Pas besoin de tout forcer pour le test
                ),
                timeout=60.0
            )
            
            duration = int((time.time() - start) * 1000)
            
            result.update({
                'success': extraction.get('content') is not None,
                'word_count': extraction.get('word_count', 0),
                'is_complete': extraction.get('is_complete', False),
                'extraction_method': extraction.get('extraction_method'),
                'duration_ms': duration,
            })
            
            if not extraction.get('content'):
                result['error'] = 'No content extracted'
                
        except asyncio.TimeoutError:
            result['error'] = 'Timeout (60s)'
            result['duration_ms'] = 60000
        except Exception as e:
            result['error'] = str(e)[:100]
            
        return result
    
    async def test_all_media(self, max_media: int = 0) -> Dict:
        """Teste tous les médias et génère un rapport"""
        media_list = self.read_media_csv()
        
        if max_media > 0:
            media_list = media_list[:max_media]
            
        total = len(media_list)
        logger.info("starting_tests", total=total)
        
        # Test avec concurrence limitée (3 simultanés max)
        semaphore = asyncio.Semaphore(3)
        
        async def test_with_limit(media):
            async with semaphore:
                return await self.test_media(media)
        
        # Exécuter tous les tests
        start_time = time.time()
        results = await asyncio.gather(*[test_with_limit(m) for m in media_list])
        total_duration = time.time() - start_time
        
        # Analyser les résultats
        successful = [r for r in results if r['success']]
        failed = [r for r in results if not r['success']]
        complete = [r for r in results if r['is_complete']]
        
        stats = {
            'total': total,
            'successful': len(successful),
            'failed': len(failed),
            'complete': len(complete),
            'success_rate': len(successful) / max(total, 1) * 100,
            'completeness_rate': len(complete) / max(len(successful), 1) * 100,
            'total_duration_sec': int(total_duration),
            'avg_duration_ms': sum(r['duration_ms'] for r in results) / max(total, 1),
        }
        
        # Grouper par pays
        by_country = {}
        for r in results:
            country = r['country'] or 'Unknown'
            if country not in by_country:
                by_country[country] = {'total': 0, 'success': 0, 'complete': 0}
            by_country[country]['total'] += 1
            if r['success']:
                by_country[country]['success'] += 1
            if r['is_complete']:
                by_country[country]['complete'] += 1
        
        # Grouper par méthode
        by_method = {}
        for r in results:
            method = r['extraction_method'] or 'failed'
            by_method[method] = by_method.get(method, 0) + 1
        
        report = {
            'generated_at': datetime.now().isoformat(),
            'stats': stats,
            'by_country': by_country,
            'by_method': by_method,
            'failed_media': failed,
            'top_performers': sorted(successful, key=lambda x: x['word_count'], reverse=True)[:10],
            'all_results': results,
        }
        
        return report
    
    def generate_html_report(self, report: Dict, output_path: str = "test_report.html"):
        """Génère un rapport HTML lisible"""
        stats = report['stats']
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Rapport Test Scraping OLJ</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
        .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 8px; }}
        .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin: 20px 0; }}
        .stat-card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .stat-value {{ font-size: 32px; font-weight: bold; color: #2c3e50; }}
        .stat-label {{ color: #7f8c8d; font-size: 14px; }}
        .success {{ color: #27ae60; }}
        .warning {{ color: #f39c12; }}
        .danger {{ color: #e74c3c; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; background: white; }}
        th {{ background: #34495e; color: white; padding: 12px; text-align: left; }}
        td {{ padding: 10px; border-bottom: 1px solid #ecf0f1; }}
        tr:hover {{ background: #f8f9fa; }}
        .badge {{ padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }}
        .badge-success {{ background: #d4edda; color: #155724; }}
        .badge-danger {{ background: #f8d7da; color: #721c24; }}
        .section {{ background: white; padding: 20px; margin: 20px 0; border-radius: 8px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 Rapport de Test - OLJ Advanced Scraper</h1>
        <p>Généré le: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
    
    <div class="stats">
        <div class="stat-card">
            <div class="stat-value">{stats['total']}</div>
            <div class="stat-label">Médias Testés</div>
        </div>
        <div class="stat-card">
            <div class="stat-value {'success' if stats['success_rate'] > 80 else 'warning' if stats['success_rate'] > 50 else 'danger'}">{stats['success_rate']:.1f}%</div>
            <div class="stat-label">Taux de Succès</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats['complete']}</div>
            <div class="stat-label">Articles Complets</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats['total_duration_sec']}s</div>
            <div class="stat-label">Durée Totale</div>
        </div>
    </div>
"""
        
        # Tableau des échecs
        if report['failed_media']:
            html += """
    <div class="section">
        <h2>❌ Médias en Échec ({})</h2>
        <table>
            <tr><th>Nom</th><th>Pays</th><th>URL</th><th>Erreur</th></tr>
""".format(len(report['failed_media']))
            
            for m in report['failed_media'][:50]:  # Limiter à 50
                html += f"""
            <tr>
                <td>{m['name']}</td>
                <td>{m['country']}</td>
                <td><a href="{m['url']}" target="_blank">{m['url'][:50]}...</a></td>
                <td>{m['error'] or 'Unknown'}</td>
            </tr>
"""
            html += "</table></div>"
        
        # Tableau par pays
        html += """
    <div class="section">
        <h2>🌍 Résultats par Pays</h2>
        <table>
            <tr><th>Pays</th><th>Total</th><th>Succès</th><th>Complets</th><th>Taux</th></tr>
"""
        for country, data in sorted(report['by_country'].items(), key=lambda x: x[1]['total'], reverse=True):
            rate = data['success'] / max(data['total'], 1) * 100
            html += f"""
            <tr>
                <td>{country}</td>
                <td>{data['total']}</td>
                <td>{data['success']}</td>
                <td>{data['complete']}</td>
                <td>{rate:.1f}%</td>
            </tr>
"""
        html += "</table></div>"
        
        # Méthodes utilisées
        html += """
    <div class="section">
        <h2>🔧 Méthodes d'Extraction Utilisées</h2>
        <table>
            <tr><th>Méthode</th><th>Count</th></tr>
"""
        for method, count in sorted(report['by_method'].items(), key=lambda x: x[1], reverse=True):
            html += f"<tr><td>{method}</td><td>{count}</td></tr>"
        html += "</table></div>"
        
        html += """
</body>
</html>
"""
        
        # Sauvegarder
        output = Path(output_path)
        output.write_text(html, encoding='utf-8')
        logger.info("html_report_generated", path=str(output))
        return str(output)


async def main():
    """Fonction principale"""
    print("=" * 70)
    print(" TEST COMPLET DES MÉDIAS - OLJ Advanced Scraper")
    print("=" * 70)
    print("\n⚠️  Ce script teste l'extraction sur TOUS les médias du CSV")
    print("   Durée estimée: 5-15 minutes selon le nombre de médias\n")
    
    # Option pour limiter le test
    max_test = 0
    if len(sys.argv) > 1:
        max_test = int(sys.argv[1])
        print(f"📝 Mode limité: test des {max_test} premiers médias\n")
    else:
        print("📝 Mode complet: test de tous les médias\n")
        print("   Pour tester seulement 10 médias: python test_all_media.py 10\n")
    
    # Lancer les tests
    tester = MediaTester()
    report = await tester.test_all_media(max_media=max_test)
    
    # Afficher résumé console
    stats = report['stats']
    print("\n" + "=" * 70)
    print(" RÉSULTATS")
    print("=" * 70)
    print(f"\n📊 Total médias: {stats['total']}")
    print(f"✅ Succès: {stats['successful']} ({stats['success_rate']:.1f}%)")
    print(f"❌ Échecs: {stats['failed']}")
    print(f"💯 Complets: {stats['complete']} ({stats['completeness_rate']:.1f}% des succès)")
    print(f"⏱️  Durée: {stats['total_duration_sec']}s")
    print(f"⏱️  Moyenne: {stats['avg_duration_ms']:.0f}ms par média")
    
    # Verdict
    print("\n" + "=" * 70)
    if stats['success_rate'] >= 90:
        print(" 🎉 VERDICT: PRÊT POUR DÉPLOIEMENT")
        print("    Taux de succès excellent (>90%)")
    elif stats['success_rate'] >= 70:
        print(" ⚠️  VERDICT: ACCEPTABLE MAIS À AMÉLIORER")
        print("    Taux de succès moyen (70-90%)")
    else:
        print(" 🚨 VERDICT: NON PRÊT")
        print("    Taux de succès trop faible (<70%)")
        print("    Revérifier les médias en échec avant déploiement")
    print("=" * 70)
    
    # Générer rapport HTML
    report_path = tester.generate_html_report(report)
    print(f"\n📄 Rapport HTML généré: {report_path}")
    
    # Sauvegarder JSON
    json_path = "test_report.json"
    Path(json_path).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"📄 Rapport JSON généré: {json_path}")
    
    # Lister les échecs
    if report['failed_media']:
        print(f"\n❌ {len(report['failed_media'])} médias en échec:")
        for m in report['failed_media'][:10]:  # Afficher les 10 premiers
            print(f"   - {m['name']} ({m['country']}): {m['error'] or 'No content'}")
        if len(report['failed_media']) > 10:
            print(f"   ... et {len(report['failed_media']) - 10} autres")
    
    print("\n✨ Test terminé!")
    return report


if __name__ == "__main__":
    # Support Windows asyncio
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        report = asyncio.run(main())
        # Exit code basé sur le taux de succès
        sys.exit(0 if report['stats']['success_rate'] >= 80 else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️ Test interrompu par l'utilisateur")
        sys.exit(130)
    except Exception as e:
        logger.error("fatal_error", error=str(e))
        print(f"\n💥 Erreur fatale: {e}")
        sys.exit(1)
