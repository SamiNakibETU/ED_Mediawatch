"""
Utilitaires de traitement de texte pour validation de complétude
"""

import re
from typing import List, Optional, Tuple


# Indicateurs de troncature/paywall dans le contenu
PAYWALL_INDICATORS = [
    # Français
    r"pour lire la suite",
    r"lire la suite",
    r"continuer la lecture",
    r"article réservé aux abonnés",
    r"abonnez-vous",
    r"déjà abonné",
    r"connectez-vous",
    r"premium",
    r"contenu exclusif",
    r"réservé aux membres",
    r"inscrivez-vous",
    r"s'abonner",
    r"version complète",
    r"article complet disponible",
    
    # Anglais
    r"subscribe to read",
    r"subscribe now",
    r"sign up to continue",
    r"create an account",
    r"premium content",
    r"members only",
    r"exclusive content",
    r"login to read",
    r"register to continue",
    r"full article available",
    r"upgrade to premium",
    r"subscription required",
    r"access denied",
    r"unlock full story",
    r"continue reading",
    r"read more",
    
    # Arabe (patterns romanisés ou fréquents)
    r"لقراءة المزيد",
    r"متابعة القراءة",
    r"للمشتركين فقط",
    r"اشترك الآن",
    r"تسجيل الدخول",
    
    # Turc
    r"devamını oku",
    r"abone ol",
    r"üye girişi",
    r"tam sürüm",
    
    # Hébreu patterns
    r"המשך לקרוא",
    r"מנוי פרימיום",
]

# Indicateurs de contenu de qualité (anti-indicateurs)
QUALITY_INDICATORS = [
    r"\d+\s*minutes?\s*de lecture",
    r"\d+\s*min read",
    r"reading time",
    r"temps de lecture",
]


def count_words(text: Optional[str]) -> int:
    """Compte les mots dans un texte (multilingue)"""
    if not text:
        return 0
    
    # Normaliser les espaces
    text = re.sub(r'\s+', ' ', text)
    
    # Compter les tokens séparés par espaces
    # Cette méthode fonctionne pour latin, arabe, hébreu, etc.
    words = text.strip().split()
    return len(words)


def estimate_reading_time(word_count: int, wpm: int = 200) -> int:
    """Estime le temps de lecture en minutes"""
    return max(1, word_count // wpm)


def detect_paywall_indicators(text: Optional[str]) -> List[str]:
    """Détecte les indicateurs de troncature/paywall"""
    if not text:
        return []
    
    found = []
    text_lower = text.lower()
    
    for pattern in PAYWALL_INDICATORS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            found.append(pattern)
    
    return found


def is_article_complete(
    text: Optional[str],
    min_words: int = 150,
    min_chars_per_word: float = 3.0,
    max_paywall_indicators: int = 0,
) -> Tuple[bool, dict]:
    """
    Vérifie si un article est complet
    
    Returns:
        Tuple[bool, dict]: (is_complete, details)
    """
    if not text:
        return False, {"reason": "empty_content", "word_count": 0}
    
    word_count = count_words(text)
    char_count = len(text)
    
    details = {
        "word_count": word_count,
        "char_count": char_count,
        "chars_per_word": char_count / max(word_count, 1),
    }
    
    # Vérifier le nombre minimum de mots
    if word_count < min_words:
        details["reason"] = f"word_count_too_low:{word_count}<{min_words}"
        return False, details
    
    # Vérifier le ratio caractères/mots (indicateur de qualité)
    chars_per_word = char_count / max(word_count, 1)
    if chars_per_word < min_chars_per_word:
        details["reason"] = f"low_char_ratio:{chars_per_word:.1f}<{min_chars_per_word}"
        return False, details
    
    # Vérifier les indicateurs de paywall
    paywall_indicators = detect_paywall_indicators(text)
    if len(paywall_indicators) > max_paywall_indicators:
        details["reason"] = f"paywall_indicators:{len(paywall_indicators)}"
        details["paywall_patterns_found"] = paywall_indicators[:3]  # Limiter
        return False, details
    
    # Vérifier les patterns de troncature évidents
    truncation_patterns = [
        r"\.\.\.$",  # Se termine par ...
        r"…$",       # Se termine par …
        r"\[\.\.\.\]",
        r"\(\s*\.{3,}\s*\)",
    ]
    
    for pattern in truncation_patterns:
        if re.search(pattern, text.strip()[-100:], re.MULTILINE):
            details["reason"] = f"truncation_pattern:{pattern}"
            return False, details
    
    details["reason"] = "complete"
    return True, details


def calculate_completeness_score(
    text: Optional[str],
    target_word_count: int = 500,
) -> float:
    """Calcule un score de complétude entre 0 et 1"""
    if not text:
        return 0.0
    
    word_count = count_words(text)
    
    # Score basé sur le nombre de mots relatif à l'objectif
    word_score = min(1.0, word_count / target_word_count)
    
    # Pénalité pour indicateurs de paywall
    paywall_indicators = detect_paywall_indicators(text)
    paywall_penalty = min(0.5, len(paywall_indicators) * 0.25)
    
    # Vérifier la fin abrupte
    abrupt_end_penalty = 0.0
    truncation_patterns = [r"\.\.\.$", r"…$", r"\[\.\.\.\]"]
    for pattern in truncation_patterns:
        if re.search(pattern, text.strip()[-50:], re.MULTILINE):
            abrupt_end_penalty = 0.3
            break
    
    final_score = max(0.0, word_score - paywall_penalty - abrupt_end_penalty)
    return round(final_score, 3)


def merge_article_fragments(fragments: List[str]) -> str:
    """Fusionne plusieurs fragments d'article intelligemment"""
    if not fragments:
        return ""
    
    if len(fragments) == 1:
        return fragments[0]
    
    # Dédoublonner les paragraphes
    seen_paragraphs = set()
    unique_fragments = []
    
    for fragment in fragments:
        # Normaliser pour comparaison
        normalized = re.sub(r'\s+', ' ', fragment.lower().strip())
        
        # Vérifier si similaire à un paragraphe déjà vu
        is_duplicate = False
        for seen in seen_paragraphs:
            # Si similitude > 80%, considérer comme doublon
            if _similarity(normalized, seen) > 0.8:
                is_duplicate = True
                break
        
        if not is_duplicate:
            seen_paragraphs.add(normalized)
            unique_fragments.append(fragment)
    
    # Fusionner en gardant l'ordre
    return "\n\n".join(unique_fragments)


def _similarity(str1: str, str2: str) -> float:
    """Calcule une similarité simple entre deux chaînes"""
    if not str1 or not str2:
        return 0.0
    
    # Utiliser une métrique simple de similarité de mots
    words1 = set(str1.split())
    words2 = set(str2.split())
    
    if not words1 or not words2:
        return 0.0
    
    intersection = words1 & words2
    union = words1 | words2
    
    return len(intersection) / len(union)


def extract_paragraphs(text: str) -> List[str]:
    """Extrait les paragraphes d'un texte"""
    if not text:
        return []
    
    # Split par lignes vides ou sauts de ligne multiples
    paragraphs = re.split(r'\n\s*\n', text.strip())
    
    # Nettoyer et filtrer
    cleaned = []
    for p in paragraphs:
        p = p.strip()
        if len(p) > 20:  # Ignorer les très courts
            cleaned.append(p)
    
    return cleaned


def detect_language_simple(text: str) -> Optional[str]:
    """Détection simple de langue basée sur caractères caractéristiques"""
    if not text:
        return None
    
    # Comptages pour détection rapide
    arabic_chars = len(re.findall(r'[\u0600-\u06FF]', text))
    hebrew_chars = len(re.findall(r'[\u0590-\u05FF]', text))
    cyrillic_chars = len(re.findall(r'[\u0400-\u04FF]', text))
    latin_chars = len(re.findall(r'[a-zA-Z]', text))
    
    total = len(text)
    if total == 0:
        return None
    
    # Seuil: au moins 10% de caractères dans l'alphabet
    if arabic_chars / total > 0.1:
        return "ar"
    if hebrew_chars / total > 0.1:
        return "he"
    if cyrillic_chars / total > 0.1:
        return "ru"  # Ou autre langue cyrillique
    if latin_chars / total > 0.3:
        return "en"  # Ou autre langue latine
    
    return "unknown"


def truncate_to_words(text: str, max_words: int) -> str:
    """Tronque un texte à un nombre maximum de mots"""
    if not text:
        return ""
    
    words = text.split()
    if len(words) <= max_words:
        return text
    
    return " ".join(words[:max_words]) + "..."


def clean_whitespace(text: str) -> str:
    """Nettoie les espaces blancs multiples"""
    if not text:
        return ""
    
    # Normaliser les espaces
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # Max 2 sauts de ligne
    text = text.strip()
    
    return text
