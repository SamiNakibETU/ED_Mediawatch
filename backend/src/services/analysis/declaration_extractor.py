"""L0 — Extraction GÉNÉRALE de déclarations (Grand Livre exhaustif).

Segmente chaque prise de parole (post X / article presse) en assertions atomiques
de TOUS types (factuel_quantitatif|qualitatif, normatif, predictif, attributif) via
LLM contraint par schéma, et les range dans la table `claims` (le Grand Livre).

Garde-fou de légitimité (specs §2.1) : le `verbatim` rendu par le LLM doit être une
sous-chaîne RÉELLE du texte source (à la normalisation près) — sinon on rejette
(rien d'inventé n'entre dans le substrat). Le `canonical` n'ajoute rien d'absent.

Sans LLM (clé absente) : aucune déclaration n'est créée (on ne fabrique pas de
substrat à partir de rien). Idempotent (dedup par source+verbatim).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database import get_session_factory
from src.services.affiliation import all_affiliations, party_of
from src.services.analysis.llm_usage import BudgetExceeded, ProviderRefused
from src.models.article import Article
from src.models.claim import Claim
from src.models.personality import Personality
from src.models.post import Post
from src.services.analysis.claim_llm import (
    DECLARATION_PROMPT_VERSION,
    Declaration,
    get_claim_llm,
)
from src.utils import sha256, strip_accents

logger = structlog.get_logger(__name__)

_WS = re.compile(r"\s+")
_URL = re.compile(r"https?://\S+|www\.\S+")
_ALPHA = re.compile(r"[A-Za-zÀ-ÿ]{2,}")


def worth_segmenting(text: str | None) -> bool:
    """Pré-filtre DÉTERMINISTE (gratuit) avant tout appel LLM : on ne segmente que
    du texte qui porte du contenu (≥ 5 mots alpha hors liens). Évite de brûler du
    LLM sur des tweets « lien seul », emojis, ou trop courts (maîtrise du coût)."""
    if not text:
        return False
    return len(_ALPHA.findall(_URL.sub("", text))) >= 5
# Normalise guillemets/apostrophes/tirets « typographiques » → ASCII, pour comparer.
_QUOTES = str.maketrans({"«": '"', "»": '"', "“": '"', "”": '"', "’": "'", "‘": "'",
                         "–": "-", "—": "-", "…": "..."})


def _canon(s: str) -> str:
    """Forme comparable : sans accents, guillemets neutralisés, espaces compactés.

    Les guillemets (« » " ") sont remplacés par des espaces — leur présence et leur
    espacement interne varient (français : « texte » avec espaces) et ne doivent pas
    faire échouer la vérif. Apostrophes/tirets conservés (mots : « d'abord »)."""
    s = s.translate(_QUOTES).replace('"', " ")
    return _WS.sub(" ", strip_accents(s)).strip().lower()


_NAME_TOKEN = re.compile(r"\b[A-ZÀ-Þ][\wÀ-ÿ'’-]{2,}")


def attributed_speaker(
    name: str | None, source: str, known: dict[str, int] | None = None
) -> tuple[str | None, int | None]:
    """Le locuteur rendu par le LLM, VÉRIFIÉ contre le texte source.

    Même esprit que `verbatim_in_source`, appliqué à l'attribution : le modèle
    propose, le texte dispose. Un nom qui n'apparaît pas dans le papier n'a pas
    pu y être désigné comme l'auteur du propos — c'est une hallucination ou une
    déduction, et une imputation déduite est la faute la plus grave d'un
    observatoire.

    Rend `(nom, personality_id | None)`. Rattache à une figure suivie quand
    c'est sans ambiguïté : sans ça, « Le Pen » et « Marine Le Pen » feraient
    deux locuteurs distincts et la comparaison dans le temps s'écroulerait.
    """
    if not name or not name.strip():
        return None, None
    raw = " ".join(name.split())[:80]
    # Un locuteur est une personne. « Le gouvernement », « le RN », « selon une
    # source » ne sont pas des locuteurs identifiables : on ne peut pas suivre
    # leur position dans le temps.
    if not _NAME_TOKEN.search(raw):
        return None, None

    src = _canon(source)
    if _canon(raw) not in src:
        return None, None

    # Rattachement aux figures suivies : on accepte l'inclusion dans un sens ou
    # dans l'autre (« Le Pen » ⊂ « Marine Le Pen »), et UNIQUEMENT si une seule
    # figure correspond — deux Le Pen dans le même papier, on n'attribue pas.
    if known:
        c = _canon(raw)
        hits = [(full, pid) for full, pid in known.items()
                if c in _canon(full) or _canon(full) in c]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return None, None
    return raw, None


def verbatim_in_source(verbatim: str, source: str) -> bool:
    """Le verbatim est-il réellement présent dans le texte source ? (anti-hallu)

    Tolère la normalisation (accents, guillemets, espaces) mais EXIGE que le LLM
    n'ait pas inventé/altéré le propos. Verbatim trop court = rejeté (pas une preuve).
    """
    v = _canon(verbatim)
    if len(v) < 12:
        return False
    return v in _canon(source)


def _dedup_key(src_ref: str, verbatim: str) -> str:
    return sha256(f"decl:{src_ref}:{_canon(verbatim)}")[:64]


async def _store(
    db: AsyncSession, *, decl: Declaration, src_ref: str, platform: str,
    post_id: int | None, article_id: int | None, personality_id: int | None,
    speaker_name: str | None, party: str | None, published_at, model: str,
) -> bool:
    if not decl.check_worthy:
        return False
    if not verbatim_in_source(decl.verbatim, _SRC_CACHE.get(src_ref, "")):
        logger.debug("decl.verbatim_rejected", src=src_ref, v=decl.verbatim[:60])
        return False
    dk = _dedup_key(src_ref, decl.verbatim)
    if await db.scalar(select(Claim.id).where(Claim.dedup_key == dk)):
        return False
    db.add(Claim(
        platform=platform, post_id=post_id, article_id=article_id,
        personality_id=personality_id, speaker_name=speaker_name, party=party,
        verbatim=decl.verbatim[:2000], canonical=(decl.canonical or None),
        claim_type=decl.claim_type, theme=(decl.theme if decl.theme != "autre" else None),
        stance_polarity=decl.stance_polarity,
        stance_target=(decl.stance_target or None), published_at=published_at,
        extraction_method="llm_segment", extraction_model=model,
        confidence=0.7, dedup_key=dk,
    ))
    return True


# Cache texte source par ref (pour la vérif verbatim sans le re-passer partout).
_SRC_CACHE: dict[str, str] = {}


async def _backfill_done_marks(db: AsyncSession) -> None:
    """Rattrape les sources segmentées avant l'existence de `l0_done_at`.

    Sans ça, la première passe après le déploiement re-paierait la segmentation
    de tout ce qui a déjà été traité. Idempotent : sans effet ensuite.
    """
    for model, fk in ((Post, Claim.post_id), (Article, Claim.article_id)):
        seen = select(fk).where(
            Claim.extraction_method == "llm_segment", fk.isnot(None)
        ).distinct()
        await db.execute(
            update(model)
            .where(model.id.in_(seen), model.l0_done_at.is_(None))
            .values(l0_done_at=datetime.now(timezone.utc))
        )
    await db.commit()


async def _mark_done(model, ids: list[int]) -> None:
    """Marque des sources comme vues par L0 — succès comme silence.

    Écrit par lots au fil de l'eau plutôt qu'à la fin : si le processus meurt en
    cours de route, ce qui a déjà été payé reste payé une seule fois.
    """
    if not ids:
        return
    factory = get_session_factory()
    async with factory() as db:
        await db.execute(
            update(model).where(model.id.in_(ids))
            .values(l0_done_at=datetime.now(timezone.utc))
        )
        await db.commit()
    ids.clear()


async def run_declaration_extraction(
    limit_posts: int = 500, limit_articles: int = 300
) -> dict:
    llm = get_claim_llm()
    if not llm.available():
        return {"declarations_new": 0, "skipped": "LLM indisponible (clé tier-2 absente)"}

    factory = get_session_factory()
    model = f"{get_claim_llm()._s.claim_tier2_provider}:{get_claim_llm()._s.claim_tier2_model}/{DECLARATION_PROMPT_VERSION}"
    n_new = posts_done = arts_done = skipped = attributed = 0
    budget_hit = False
    _SRC_CACHE.clear()

    # Mode pilote : périmètre restreint à quelques personnalités (calibration
    # précision/rappel avant l'échelle). Vide = tout le pool.
    pilot = set(get_settings().l0_pilot_handle_list)
    pilot_names: set[str] = set()
    if pilot:
        async with factory() as db:
            pilot_names = set((await db.execute(
                select(Personality.full_name).where(
                    func.lower(Personality.handle).in_(pilot)
                )
            )).scalars().all())

    # Répertoire nom → id des figures suivies : sert à rattacher une attribution
    # de presse à la bonne fiche, donc à ce que « Le Pen » dans Le Monde et
    # @MLP_officiel sur X soient la même voix dans une comparaison.
    async with factory() as db:
        people: dict[str, int] = dict(
            (await db.execute(select(Personality.full_name, Personality.id))).all()
        )
        # Les fiches et les affiliations datées, chargées une fois pour la passe :
        # le parti inscrit sur un propos est celui du jour où il a été tenu, et
        # une requête par déclaration serait ruineuse à ce volume.
        fiches = {f.id: f for f in
                  (await db.execute(select(Personality))).scalars().all()}
        affils = await all_affiliations(db)

    async with factory() as db:
        await _backfill_done_marks(db)

        # Le filtre « pas encore vu » est DANS la requête, avant le LIMIT.
        # Le faire après, en Python, faisait redescendre les mêmes posts récents
        # à chaque passe : une fois ce lot traité plus rien n'avançait, et les
        # 26 000 posts d'archive n'étaient jamais atteints.
        posts_q = (
            select(Post, Personality)
            .join(Personality, Post.personality_id == Personality.id)
            .where(
                Post.l0_done_at.is_(None),
                Post.is_retweet.is_(False),
                # Jamais de LLM sur un texte tronqué (la syndication coupe à 280) :
                # on attend `enrich_truncated`, sinon déclarations fausses par
                # omission ET dépense à refaire.
                Post.text_truncated.isnot(True),
            )
        )
        if pilot:
            posts_q = posts_q.where(func.lower(Personality.handle).in_(pilot))
        posts = (
            await db.execute(
                posts_q.order_by(Post.published_at.desc().nullslast()).limit(limit_posts)
            )
        ).all()

    done_posts: list[int] = []
    try:
        for post, p in posts:
            # Garde-fou coût (gratuit) AVANT l'appel LLM : texte sans contenu.
            # Marqué vu quand même — le verdict est déterministe, le repasser au
            # crible à chaque passe ne changerait rien et bloquerait la fenêtre.
            if not worth_segmenting(post.content):
                skipped += 1
                done_posts.append(post.id)
                continue
            src_ref = f"post{post.id}"
            _SRC_CACHE[src_ref] = post.content or ""
            try:
                result = await llm.segment_declarations(
                    text=post.content, speaker=p.full_name
                )
            except ProviderRefused:
                raise      # rien à marquer, et rien à retenter sur cette passe
            except BudgetExceeded as exc:
                # Non traité : surtout ne pas le marquer, il doit repasser.
                logger.warning("declarations.budget_exceeded", detail=str(exc))
                budget_hit = True
                break
            # `None` = l'appel n'a pas abouti, pas « rien à extraire ». Marquer
            # la publication comme traitée la retirerait de la file pour de bon,
            # et ses déclarations seraient perdues sans trace. Même faute que
            # celle vue au codage thématique, sur un objet plus précieux.
            if result is None:
                skipped += 1
                continue
            posts_done += 1
            done_posts.append(post.id)
            if result and result.has_declaration:
                async with factory() as db:
                    for decl in result.declarations:
                        if await _store(
                            db, decl=decl, src_ref=src_ref, platform="x", post_id=post.id,
                            article_id=None, personality_id=p.id, speaker_name=p.full_name,
                            party=party_of(affils, p, post.published_at),
                            published_at=post.published_at, model=model,
                        ):
                            n_new += 1
                    await db.commit()
            if len(done_posts) >= 50:
                await _mark_done(Post, done_posts)
    finally:
        await _mark_done(Post, done_posts)

    # ── Presse ────────────────────────────────────────────────────────────
    # Le filtre pilote porte sur `matched_personalities` (JSON) : pas de prédicat
    # portable entre SQLite et Postgres. On lit donc les seules colonnes
    # d'aiguillage sur le reliquat — deux champs, c'est peu — puis on ne charge
    # que les articles retenus. Le pilote étant temporaire, un article hors
    # périmètre n'est PAS marqué : il redeviendra éligible quand il s'élargira.
    async with factory() as db:
        candidates = (await db.execute(
            select(Article.id, Article.matched_personalities)
            .where(Article.l0_done_at.is_(None))
            .order_by(Article.published_at.desc().nullslast())
        )).all()
        keep = [
            aid for aid, mp in candidates
            if not pilot or (set(mp or []) & pilot_names)
        ][:limit_articles]
        skipped += len(candidates) - len(keep)
        arts = (await db.execute(
            select(Article).where(Article.id.in_(keep))
            .order_by(Article.published_at.desc().nullslast())
        )).scalars().all() if keep else []

    done_arts: list[int] = []
    try:
        for art in arts:
            if budget_hit:
                break
            text = f"{art.title}. {art.content}"
            if not worth_segmenting(text):
                skipped += 1
                done_arts.append(art.id)
                continue
            src_ref = f"art{art.id}"
            _SRC_CACHE[src_ref] = text
            # Les figures suivies repérées dans l'article : un contexte donné au
            # modèle pour orthographier un nom, jamais une réponse à recopier.
            #
            # Cette ligne a manqué pendant trois jours : sa suppression par
            # mégarde a fait échouer extract_l0 en production (NameError) à
            # chaque passe, et tout l'aval — codage, embeddings, sujets — était
            # sauté. Le local n'a rien vu : sa boucle presse n'avait plus rien à
            # traiter, la ligne ne s'exécutait jamais. Un test couvre désormais
            # le chemin presse de bout en bout.
            mp = art.matched_personalities or []
            # JAMAIS de locuteur présumé pour un article : un papier qui mentionne
            # une figure contient aussi la voix du journaliste et des tiers cités.
            # Attribuer tout le contenu à `mp[0]` fabriquait des imputations fausses
            # (propos de Marylise Léon prêtés à Marine Le Pen, puis
            # « contradictions » bâties dessus). Une imputation erronée est la
            # faute la plus grave d'un observatoire : sans attribution certaine,
            # on n'attribue pas.
            #
            # Ne rien attribuer du tout avait cependant un coût qu'on a fini par
            # voir : TOUTE la presse tombait dans « non attribué », donc hors de
            # la comparaison — alors que l'objet du produit est justement de
            # rattacher un propos à quelqu'un, à une date. La réponse n'est pas
            # de deviner mais de FAIRE DIRE au texte qui parle : le modèle
            # renseigne `speaker` par déclaration, et `attributed_speaker` refuse
            # tout nom qui n'est pas littéralement dans le papier.
            try:
                result = await llm.segment_declarations(
                    text=text, speaker=None, known=[n for n in mp if n in people],
                )
            except ProviderRefused:
                raise
            except BudgetExceeded as exc:
                logger.warning("declarations.budget_exceeded", detail=str(exc))
                budget_hit = True
                break
            if result is None:
                skipped += 1
                continue
            arts_done += 1
            done_arts.append(art.id)
            if result and result.has_declaration:
                async with factory() as db:
                    for decl in result.declarations:
                        who, pid = attributed_speaker(decl.speaker, text, people)
                        if who:
                            attributed += 1
                        if await _store(
                            db, decl=decl, src_ref=src_ref, platform="press", post_id=None,
                            article_id=art.id, personality_id=pid, speaker_name=who,
                            party=party_of(affils, fiches.get(pid), art.published_at),
                            published_at=art.published_at, model=model,
                        ):
                            n_new += 1
                    await db.commit()
            if len(done_arts) >= 50:
                await _mark_done(Article, done_arts)
    finally:
        await _mark_done(Article, done_arts)

    # Ce qui reste : la seule façon de savoir s'il faut relancer, plutôt que de
    # relancer à l'aveugle jusqu'à ce que le compteur cesse de bouger.
    async with factory() as db:
        rest_posts = await db.scalar(
            select(func.count()).select_from(Post).where(
                Post.l0_done_at.is_(None), Post.is_retweet.is_(False),
                Post.text_truncated.isnot(True),
            )
        ) or 0
        rest_arts = await db.scalar(
            select(func.count()).select_from(Article).where(Article.l0_done_at.is_(None))
        ) or 0

    stats = {"declarations_new": n_new, "posts_processed": posts_done,
             "articles_processed": arts_done, "skipped_no_llm": skipped,
             "press_attributed": attributed,
             "remaining_posts": rest_posts, "remaining_articles": rest_arts,
             "budget_exceeded": budget_hit, "pilot": sorted(pilot) or None,
             "prompt_version": DECLARATION_PROMPT_VERSION}
    logger.info("declarations.extracted", **stats)
    return stats
