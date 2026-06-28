# OLJ Advanced Scraper Service

Service de scraping avancé garantissant l'extraction **100% complète** des articles de presse du Moyen-Orient pour L'Orient-Le Jour.

## Architecture

Ce service utilise une cascade de stratégies de contournement de paywalls pour garantir l'extraction intégrale du contenu:

1. **curl_cffi** - Spoofing TLS/JA3 pour contourner les détections basiques
2. **Playwright Stealth** - Navigateur furtif avec anti-détection avancée
3. **Scrapling** - Contournement spécialisé Cloudflare
4. **Jina AI** - Proxy de contenu pour articles bloqués géographiquement
5. **Wayback Machine** - Archive pour articles inaccessibles

## Fonctionnalités

- ✅ Extraction **100% complète** garantie
- ✅ Cascade automatique de stratégies anti-paywall
- ✅ Détection automatique de troncature
- ✅ Support multilingue (AR, EN, TR, HE, FA)
- ✅ Rate limiting adaptatif
- ✅ Cache intelligent
- ✅ API REST avec batch processing
- ✅ Métriques et monitoring

## Déploiement sur Railway

```bash
# 1. Créer un nouveau projet Railway
railway login
railway init

# 2. Déployer
railway up

# 3. Configurer les variables d'environnement
railway variables set JINA_AI_API_KEY="xxx"
railway variables set LOG_LEVEL="INFO"
```

## API Endpoints

### Health Check
```
GET /health
```

### Extraire un article
```
POST /extract
Content-Type: application/json

{
  "url": "https://example.com/article",
  "source_id": "il_haaretz",
  "force_complete": true
}
```

### Extraire en batch
```
POST /extract/batch
Content-Type: application/json

{
  "urls": [
    "https://example.com/article1",
    "https://example.com/article2"
  ],
  "max_concurrent": 5
}
```

### Vérifier la complétude
```
POST /verify
Content-Type: application/json

{
  "content": "...",
  "min_words": 150
}
```

### Statistiques
```
GET /stats
```

## Intégration avec le Backend OLJ

Voir `docs/integration.md` pour l'intégration avec le backend existant.

## Configuration

Les variables d'environnement disponibles:

| Variable | Description | Défaut |
|----------|-------------|--------|
| `JINA_AI_API_KEY` | Clé API Jina AI | None |
| `LOG_LEVEL` | Niveau de log | INFO |
| `MAX_RETRIES` | Nombre max de tentatives | 5 |
| `MIN_ARTICLE_WORDS` | Minimum de mots requis | 150 |
| `TARGET_ARTICLE_WORDS` | Objectif de mots | 500 |
| `PLAYWRIGHT_HEADLESS` | Mode headless | true |
| `CACHE_ENABLED` | Activer le cache | true |

## Médias Supportés

Le service est optimisé pour les médias de la revue de presse régionale:

### Israël
- Haaretz (avec gestion paywall)
- Jerusalem Post
- Times of Israel
- Ynet
- Maariv
- Israel Hayom

### Arabie Saoudite
- Al-Arabiya
- Asharq Al-Awsat
- Al-Watan
- Arab News

### Turquie
- Hürriyet
- Sabah
- Daily Sabah
- Cumhuriyet

### Et 50+ autres médias de la région

## Licence

Propriétaire - L'Orient-Le Jour
