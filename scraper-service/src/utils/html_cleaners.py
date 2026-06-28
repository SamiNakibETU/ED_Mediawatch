"""
Nettoyeurs de HTML et détecteurs de paywall
"""

import re
from typing import List, Optional


# Patterns de nettoyage des boilerplates
BOILERPLATE_PATTERNS = [
    # Copyright
    r'©\s*\d{4}.*?\n',
    r'Copyright\s*©?\s*\d{4}.*?\n',
    r'Tous droits réservés.*?\n',
    r'All rights reserved.*?\n',
    
    # Social sharing
    r'Share this article.*?\n',
    r'Partager sur.*?\n',
    r'Partagez.*?\n',
    r'Suivez-nous.*?\n',
    r'Follow us.*?\n',
    
    # Subscription
    r'Subscribe to.*?\n',
    r'Abonnez-vous.*?\n',
    r'Newsletter.*?\n',
    
    # Navigation
    r'Read next.*?\n',
    r'Article suivant.*?\n',
    r'Article précédent.*?\n',
    r'Related articles.*?\n',
    r'Articles liés.*?\n',
    r'Voir aussi.*?\n',
    r'See also.*?\n',
    r'Plus de sujets.*?\n',
    r'More on this topic.*?\n',
    
    # Interactive elements
    r'Show comments.*?\n',
    r'Afficher les commentaires.*?\n',
    r'Leave a comment.*?\n',
    r'Laisser un commentaire.*?\n',
    
    # Tags
    r'Tags\s*:.*?\n',
    r'Mots-clés\s*:.*?\n',
    r'Categories\s*:.*?\n',
    r'Catégories\s*:.*?\n',
    
    # Author footer
    r'About the author.*?\n',
    r'À propos de l\'auteur.*?\n',
    
    # Reading time
    r'\d+\s*min(?:utes?)?\s*(?:de lecture|read)?.*?\n',
    r'Lecture\s*:\s*\d+.*?\n',
    
    # Generic footers
    r'^Taille du texte.*?\n',
    r'^La suite de l\'article.*?\n',
    r'^La suite après.*?\n',
    r'^Continuer.*?\n',
]


def clean_boilerplate(text: Optional[str]) -> Optional[str]:
    """Nettoie les éléments boilerplate du texte"""
    if not text:
        return text
    
    cleaned = text
    
    # Appliquer chaque pattern
    for pattern in BOILERPLATE_PATTERNS:
        cleaned = re.sub(pattern, '\n', cleaned, flags=re.IGNORECASE | re.MULTILINE)
    
    # Nettoyer les lignes vides multiples
    cleaned = re.sub(r'\n\s*\n\s*\n+', '\n\n', cleaned)
    
    return cleaned.strip()


def detect_paywall_indicators(html_or_text: str) -> List[str]:
    """Détecte les indicateurs de paywall dans le HTML ou texte"""
    found = []
    
    # Patterns de détection paywall
    patterns = [
        # HTML patterns
        r'class="[^"]*paywall[^"]*"',
        r'class="[^"]*premium[^"]*"',
        r'class="[^"]*subscription[^"]*"',
        r'class="[^"]*subscriber[^"]*"',
        r'id="[^"]*paywall[^"]*"',
        r'data-paywall',
        r'data-access-level',
        
        # Text patterns
        r'subscribe to continue reading',
        r'premium content',
        r'members only',
        r'subscription required',
        r'article réservé aux abonnés',
        r'contenu premium',
        r'pour lire la suite',
        r'abonnez-vous',
        r'create an account to read',
        r'sign in to read',
        r'login to continue',
        r's\'identifier pour lire',
        r'upgrade to premium',
        r'passer à la version premium',
        r'unlock this article',
        r'débloquer cet article',
        r'full access with subscription',
        r'accès complet avec abonnement',
        
        # JavaScript patterns (dans le HTML)
        r'window\.paywall',
        r'paywallConfig',
        r'gtm.*paywall',
        r'gtm.*premium',
    ]
    
    text_lower = html_or_text.lower()
    
    for pattern in patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            found.append(pattern)
    
    return found


def is_likely_paywalled(html: str) -> bool:
    """Détermine si une page est probablement derrière un paywall"""
    indicators = detect_paywall_indicators(html)
    
    # Score basé sur le nombre d'indicateurs
    score = len(indicators)
    
    # Patterns forts qui indiquent presque certainement un paywall
    strong_indicators = [
        'paywallConfig',
        'data-paywall',
        'article réservé aux abonnés',
        'subscription required',
        'premium content',
        'contenu premium',
        'abonnez-vous pour lire',
    ]
    
    for indicator in strong_indicators:
        if indicator in html.lower():
            return True
    
    # Si plusieurs indicateurs faibles
    return score >= 3


def extract_json_ld(html: str) -> List[dict]:
    """Extrait les données JSON-LD du HTML"""
    import json
    
    results = []
    
    # Pattern pour trouver les scripts JSON-LD
    pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
    
    matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
    
    for match in matches:
        try:
            data = json.loads(match.strip())
            results.append(data)
        except json.JSONDecodeError:
            continue
    
    return results


def get_article_json_ld(html: str) -> Optional[dict]:
    """Extrait les métadonnées d'article depuis JSON-LD"""
    json_ld_data = extract_json_ld(html)
    
    for data in json_ld_data:
        # Chercher un Article ou NewsArticle
        if isinstance(data, dict):
            if data.get("@type") in ["Article", "NewsArticle", "BlogPosting"]:
                return data
            # Parfois @type est une liste
            if isinstance(data.get("@type"), list):
                if any(t in ["Article", "NewsArticle", "BlogPosting"] for t in data["@type"]):
                    return data
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") in ["Article", "NewsArticle", "BlogPosting"]:
                    return item
    
    return None


def strip_html_tags(html: str) -> str:
    """Supprime les balises HTML"""
    clean = re.sub(r'<[^>]+>', ' ', html)
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()


def extract_meta_content(html: str, property_name: str) -> Optional[str]:
    """Extrait une valeur meta par propriété"""
    pattern = rf'<meta[^>]*(?:property|name)=["\']{re.escape(property_name)}["\'][^>]*content=["\']([^"\']*)["\'][^>]*>'
    match = re.search(pattern, html, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    
    # Essayer l'ordre inversé (content avant property)
    pattern = rf'<meta[^>]*content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{re.escape(property_name)}["\'][^>]*>'
    match = re.search(pattern, html, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    
    return None


def normalize_url(base_url: str, relative_url: str) -> str:
    """Normalise une URL relative en URL absolue"""
    from urllib.parse import urljoin, urlparse
    
    if not relative_url:
        return base_url
    
    # Déjà absolue
    if relative_url.startswith(('http://', 'https://')):
        return relative_url
    
    # Protocole relatif
    if relative_url.startswith('//'):
        parsed_base = urlparse(base_url)
        return f"{parsed_base.scheme}:{relative_url}"
    
    # URL relative
    return urljoin(base_url, relative_url)


def extract_links_from_html(html: str, base_url: str, pattern: Optional[str] = None) -> list:
    """Extrait les liens d'un HTML avec filtrage optionnel"""
    from bs4 import BeautifulSoup
    
    links = []
    try:
        soup = BeautifulSoup(html, 'lxml')
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            full_url = normalize_url(base_url, href)
            
            # Filtrer si pattern fourni
            if pattern:
                if re.search(pattern, full_url, re.IGNORECASE):
                    links.append(full_url)
            else:
                links.append(full_url)
                
    except Exception:
        pass
    
    return list(set(links))  # Dédoublonner
