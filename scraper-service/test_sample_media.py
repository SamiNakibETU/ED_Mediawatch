#!/usr/bin/env python3
"""
Test rapide sur un échantillon de médias représentatifs
À exécuter avant le test complet pour validation rapide (2-3 minutes)
"""

import asyncio
import sys
from pathlib import Path

# Ajouter le src au path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.ultimate_extractor import UltimateExtractor

# Échantillon de médias représentatifs des différentes régions/protection
SAMPLE_MEDIA = [
    # Israël (paywalls forts)
    {"name": "Haaretz", "country": "Israël", "url": "https://www.haaretz.com/opinion"},
    {"name": "Jerusalem Post", "country": "Israël", "url": "https://www.jpost.com/opinion"},
    {"name": "Times of Israel", "country": "Israël", "url": "https://www.timesofisrael.com"},
    
    # Arabie Saoudite
    {"name": "Arab News", "country": "Arabie Saoudite", "url": "https://www.arabnews.com/opinion"},
    {"name": "Al-Arabiya", "country": "Arabie Saoudite", "url": "https://www.alarabiya.net/views"},
    {"name": "Asharq Al-Awsat", "country": "Arabie Saoudite", "url": "https://aawsat.com/الرأي"},
    
    # Turquie
    {"name": "Hürriyet", "country": "Turquie", "url": "https://www.hurriyet.com.tr/yazarlar/"},
    {"name": "Daily Sabah", "country": "Turquie", "url": "https://www.dailysabah.com/opinion"},
    
    # UAE
    {"name": "The National", "country": "UAE", "url": "https://www.thenationalnews.com/opinion/"},
    {"name": "Gulf News", "country": "UAE", "url": "https://gulfnews.com/opinion"},
    
    # Qatar
    {"name": "Al Jazeera", "country": "Qatar", "url": "https://www.aljazeera.com/opinion/"},
    {"name": "Gulf Times", "country": "Qatar", "url": "https://www.gulf-times.com/opinion"},
    
    # Jordanie
    {"name": "Jordan Times", "country": "Jordanie", "url": "https://jordantimes.com/opinion"},
    {"name": "Al Ghad", "country": "Jordanie", "url": "https://alghad.com/"},
    
    # Régional
    {"name": "Middle East Eye", "country": "Régional", "url": "https://www.middleeasteye.net/opinion"},
    
    # Iran
    {"name": "Iran International", "country": "Iran", "url": "https://www.iranintl.com/en/opinion"},
    {"name": "IranWire", "country": "Iran", "url": "https://iranwire.com/en/"},
]


async def test_media(extractor, media):
    """Test un média"""
    print(f"\n🧪 Test: {media['name']} ({media['country']})")
    print(f"   URL: {media['url']}")
    
    try:
        result = await asyncio.wait_for(
            extractor.extract_article(
                url=media['url'],
                source_name=media['name'],
                force_complete=False,
            ),
            timeout=30.0
        )
        
        if result and result.get('content'):
            words = result.get('word_count', 0)
            method = result.get('extraction_method', 'unknown')
            complete = result.get('is_complete', False)
            
            if complete and words > 200:
                print(f"   ✅ SUCCÈS ({words} mots, {method})")
                return True
            elif complete:
                print(f"   ⚠️  PARTIEL ({words} mots, {method})")
                return True
            else:
                print(f"   ⚠️  INCOMPLET ({words} mots, {method})")
                return False
        else:
            print(f"   ❌ ÉCHEC - Pas de contenu")
            return False
            
    except asyncio.TimeoutError:
        print(f"   ❌ ÉCHEC - Timeout (30s)")
        return False
    except Exception as e:
        print(f"   ❌ ÉCHEC - {str(e)[:60]}")
        return False


async def main():
    print("=" * 70)
    print(" TEST RAPIDE - ÉCHANTILLON DE MÉDIAS")
    print("=" * 70)
    print(f"\n📊 {len(SAMPLE_MEDIA)} médias représentatifs\n")
    print("Durée estimée: 2-3 minutes\n")
    
    extractor = UltimateExtractor()
    
    results = []
    for media in SAMPLE_MEDIA:
        success = await test_media(extractor, media)
        results.append({
            'name': media['name'],
            'country': media['country'],
            'success': success
        })
    
    # Résumé
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]
    
    print("\n" + "=" * 70)
    print(" RÉSULTATS")
    print("=" * 70)
    print(f"✅ Succès: {len(successful)}/{len(results)} ({len(successful)/len(results)*100:.0f}%)")
    print(f"❌ Échecs: {len(failed)}")
    
    if failed:
        print("\n❌ Médias en échec:")
        for m in failed:
            print(f"   - {m['name']} ({m['country']})")
    
    print("\n" + "=" * 70)
    
    # Verdict
    success_rate = len(successful) / len(results) * 100
    
    if success_rate >= 80:
        print("🎉 EXCELLENT - Prêt pour test complet de tous les médias!")
        print("   Exécuter: python test_all_media.py")
    elif success_rate >= 60:
        print("⚠️  MOYEN - Fonctionne sur la majorité mais peut être amélioré")
        print("   Revérifier les médias en échec avant de continuer")
    else:
        print("🚨 FAIBLE - Trop d'échecs, vérifier la configuration avant déploiement")
        print("   Problèmes possibles:")
        print("   - Playwright non installé: playwright install chromium")
        print("   - Dépendances manquantes: pip install -r requirements.txt")
    
    print("=" * 70)
    
    return success_rate


if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        success_rate = asyncio.run(main())
        
        # Exit code pour CI/CD
        if success_rate >= 80:
            sys.exit(0)
        elif success_rate >= 60:
            sys.exit(1)
        else:
            sys.exit(2)
            
    except KeyboardInterrupt:
        print("\n\n⚠️ Interrompu")
        sys.exit(130)
    except Exception as e:
        print(f"\n💥 Erreur: {e}")
        sys.exit(1)
