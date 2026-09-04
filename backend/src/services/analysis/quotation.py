"""Les mots du locuteur, ou ceux du journaliste — la distinction que la une n'avait pas.

Vécu le 04/09/2026. Les six déclarations en tête de la une étaient toutes issues
de la presse, et toutes affichées entre guillemets comme la parole de la
personne. Quatre ne l'étaient pas :

    « Marine Le Pen assure avoir elle-même souhaité ce départ. »
    « répétée ce samedi par Jordan Bardella depuis la Foire de Châlons »

La première est une phrase de journaliste à la troisième personne. La seconde
n'est même pas une phrase. Les mettre entre guillemets sous le nom du locuteur,
c'est lui prêter des mots qu'il n'a pas prononcés — pour un observatoire du
discours, la faute qui invalide tout le reste.

D'OÙ VENAIT L'ERREUR. Le garde-fou d'extraction (`verbatim_in_source`) vérifie
que le verbatim est une sous-chaîne réelle de l'article. Il garantit donc la
fidélité AU DOCUMENT, et la page la lisait comme la fidélité AU LOCUTEUR. Or
« Marine Le Pen assure avoir souhaité ce départ » est bien dans l'article : ce
sont les mots du journaliste sur elle.

Les deux natures sont du matériau légitime — un observatoire suit aussi ce que
la presse rapporte. Ce qui ne l'est pas, c'est de les afficher pareil. On les
sépare donc ici, sans modèle : la ponctuation du document le dit déjà. Ce qui
est entre guillemets DANS l'article est du style direct ; le reste est du
discours rapporté, et s'affiche sans guillemets.

Un mot sur le choix de ne pas demander cela au LLM : la position des guillemets
est un fait typographique, vérifiable, gratuit et stable. Un modèle y
répondrait juste la plupart du temps, ce qui est exactement la propriété dont on
ne veut pas pour un garde-fou.
"""

from __future__ import annotations

import re

from src.utils import strip_accents

DIRECT = "direct"
RAPPORTE = "rapporte"

# Un caractère qui n'existe pas dans un texte de presse : il tient la place des
# guillemets pendant la recherche, sans se confondre avec une espace ni avec une
# lettre. Le remplacement est à longueur constante, donc les positions dans le
# texte normalisé restent celles du texte d'origine.
_MARQUE = "\x01"
_GUILLEMETS = "«»“”\"″"
# Apostrophes et tirets typographiques ramenés à leur forme simple : le modèle
# rend « l'espace » là où le journal écrit « l’espace », et la localisation ne
# doit pas se casser sur une courbure. Remplacements à longueur constante, pour
# que les positions restent celles du document.
_TABLE = str.maketrans({**{c: _MARQUE for c in _GUILLEMETS},
                        "’": "'", "‘": "'", "–": "-", "—": "-"})
_ESPACES = re.compile(r"\s")


def _marque(texte: str) -> str:
    """Le texte comparable, guillemets remplacés par une marque à leur place."""
    return _ESPACES.sub(" ", strip_accents(texte.translate(_TABLE))).lower()


def _motif(verbatim: str) -> re.Pattern[str]:
    """Le verbatim, tolérant sur les espaces ET sur les guillemets internes.

    Un verbatim rendu par le modèle a pu perdre une espace insécable ou avaler
    un guillemet intérieur ; exiger l'égalité stricte ferait échouer la
    localisation sur des différences qui ne changent pas le propos.
    """
    v = _ESPACES.sub(" ", strip_accents(verbatim.translate(_TABLE))).lower()
    v = v.replace(_MARQUE, " ").strip()
    morceaux = [re.escape(m) for m in v.split(" ") if m]
    return re.compile(f"[\\s{_MARQUE}]+".join(morceaux)) if morceaux else re.compile(r"(?!)")


def _voisin(texte: str, indices) -> str | None:
    """Le premier caractère non blanc rencontré, ou None au bout du texte."""
    for i in indices:
        if texte[i] != " ":
            return texte[i]
    return None


def style_de_citation(verbatim: str, source: str) -> str:
    """`direct` si le verbatim est encadré de guillemets dans le document.

    Encadré des DEUX côtés : un guillemet ouvrant seul signale une citation qui
    commence, pas qu'elle couvre le passage retenu. En cas de doute — verbatim
    introuvable dans le document, guillemets absents — on répond `rapporte`.
    C'est le sens prudent : présenter un propos rapporté comme rapporté ne coûte
    rien, présenter une paraphrase de journaliste comme une citation coûte la
    crédibilité de l'observatoire.
    """
    if not verbatim or not source:
        return RAPPORTE
    texte = _marque(source)
    trouve = _motif(verbatim).search(texte)
    if trouve is None:
        return RAPPORTE
    avant = _voisin(texte, range(trouve.start() - 1, -1, -1))
    apres = _voisin(texte, range(trouve.end(), len(texte)))
    return DIRECT if avant == _MARQUE and apres == _MARQUE else RAPPORTE


# ── Le rattrapage sur ce qui est déjà en base ──────────────────────────────
# Le style se déduit du document, qu'on possède : `Article.content` pour la
# presse, `Post.content` pour X. Étape gratuite, reprenable, idempotente — elle
# ne traite que les déclarations dont le style n'est pas encore établi.

async def qualify_quotations(limit: int = 4000) -> dict:
    """Établit, pour chaque déclaration, si son verbatim est cité ou rapporté."""
    import structlog
    from sqlalchemy import select

    from src.database import get_session_factory
    from src.models.article import Article
    from src.models.claim import Claim
    from src.models.post import Post

    logger = structlog.get_logger(__name__)
    factory = get_session_factory()
    directs = rapportes = sans_source = 0

    async with factory() as db:
        rows = (await db.execute(
            select(Claim.id, Claim.verbatim, Post.content, Article.content)
            .outerjoin(Post, Post.id == Claim.post_id)
            .outerjoin(Article, Article.id == Claim.article_id)
            .where(Claim.quote_style.is_(None))
            .limit(limit)
        )).all()

        for cid, verbatim, texte_post, texte_article in rows:
            # Un post X est écrit par le locuteur : ses mots sont ses mots. La
            # question ne se pose que pour la presse, qui rapporte.
            if texte_post is not None:
                style = DIRECT
            elif texte_article is not None:
                style = style_de_citation(verbatim or "", texte_article)
            else:
                # Source disparue : on ne sait pas, on ne marque rien, et la
                # prochaine passe reposera la question. Marquer « rapporté » ici
                # reviendrait à décider sur une absence.
                sans_source += 1
                continue
            obj = await db.get(Claim, cid)
            if obj is None:
                continue
            obj.quote_style = style
            if style == DIRECT:
                directs += 1
            else:
                rapportes += 1
        await db.commit()

    out = {"cites": directs, "rapportes": rapportes, "sans_source": sans_source}
    logger.info("quotation.done", **out)
    return out
