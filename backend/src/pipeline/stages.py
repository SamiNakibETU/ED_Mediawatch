"""Déclaration des étapes du pipeline — un graphe, pas une pile de scripts.

Le problème que ce module résout : la chaîne d'analyse existait sous forme de
scripts à lancer à la main, dans un ordre qu'il fallait connaître (collecte →
enrichissement → L0 → embeddings → sujets → nommage → détection → juge). Sauter
une étape ou en inverser deux produisait un résultat vide, sans que rien ne le
signale. C'est la raison la plus banale pour laquelle « rien ne marchait ».

Chaque étape déclare :
  * ses **dépendances** — l'ordre n'est plus dans la tête de quelqu'un ;
  * son **coût** — `FREE` ou `PAID`, pour pouvoir tout rejouer sans dépenser ;
  * une fonction **idempotente** : relancer ne duplique rien, ça reprend.

Les imports sont faits DANS les fonctions : charger ce module ne doit pas tirer
torch, httpx et le reste — le routeur d'état l'importe pour lister les étapes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

FREE = "free"   # aucun appel LLM facturé
PAID = "paid"   # consomme du budget (bornée par le garde-budget)


@dataclass(frozen=True)
class Stage:
    name: str
    label: str
    cost: str
    run: Callable[[], Awaitable[dict]]
    depends_on: tuple[str, ...] = ()
    # Ce que l'étape produit, pour lire le rapport sans connaître le code.
    produces: str = ""
    params: dict = field(default_factory=dict)


# ── Implémentations (imports tardifs) ────────────────────────────────────

async def _collect_x() -> dict:
    from src.services.collection.x_collector import run_collection
    return await run_collection()


async def _collect_press() -> dict:
    from src.services.collection.press_collector import run_press_collection
    return await run_press_collection()


async def _enrich_truncated() -> dict:
    from src.services.collection.x_enrich import enrich_truncated_posts

    # Passe devant L0 : un texte coupé à 280 produit des déclarations fausses
    # par omission. Mieux vaut en réparer large que d'en segmenter de travers.
    return await enrich_truncated_posts(limit=600)


async def _amplifications() -> dict:
    from src.services.analysis.amplification import build_amplifications

    # Aucun appel de modèle : la typologie est en base et la cible vient de la
    # collecte. Il ne reste qu'à en tirer les conséquences.
    return await build_amplifications(limit=5000)


async def _extract_l0() -> dict:
    from src.services.analysis.declaration_extractor import run_declaration_extraction

    # Taille de fenêtre : bornée par le MUR-HORLOGE, pas par la prudence
    # budgétaire — le plafond LLM s'en charge déjà et s'arrête proprement.
    # Les appels sont sérialisés (~2-3 s pièce), donc ~1500 posts tiennent en
    # une heure environ, largement dans l'intervalle de 4 h entre deux passes,
    # pour un coût de l'ordre de 0,40 $. À 400, l'arriéré de 26 000 posts aurait
    # demandé onze jours ; ici trois.
    return await run_declaration_extraction(limit_posts=1500, limit_articles=400)


async def _cap_coding() -> dict:
    from src.services.analysis.cap_coder import code_claims

    # Tier 1 : une classification à 21 issues, pas une analyse. ~0,12 $ pour
    # 1 500 déclarations, et le pont déterministe en absorbe la plus grande part
    # sans appeler personne.
    return await code_claims(limit=1500)


async def _pledges() -> dict:
    from src.services.analysis.pledges import detect_pledges
    return await detect_pledges(limit=400)


async def _quotation() -> dict:
    from src.services.analysis.quotation import qualify_quotations
    return await qualify_quotations(limit=4000)


async def _party_of_record() -> dict:
    from src.services.analysis.party_of_record import fix_claim_parties
    return await fix_claim_parties(limit=5000)


async def _embed() -> dict:
    from src.services.analysis.claim_embeddings import embed_claims
    return await embed_claims(limit=5000)


async def _vector_index() -> dict:
    from src.services.analysis.vector_index import get_index

    index = get_index()
    ready = await index.ensure_ready()
    synced = await index.sync() if ready.get("ready") else {"synced": 0}
    return {**ready, **synced}


async def _enrich_claims() -> dict:
    from src.services.analysis.enrich import enrich_claims
    return await enrich_claims(limit=5000)


async def _build_subjects() -> dict:
    from src.services.analysis.subject_builder import build_subjects
    return await build_subjects()


async def _label_subjects() -> dict:
    from src.services.analysis.subject_labeller import label_subjects

    # 40 sujets par passe pour 900 en attente : quatre jours de rattrapage, et
    # entre-temps le sommaire affiche des sacs de mots triés par ordre
    # alphabétique (« davantage deputes designe gagner ») là où il faut un objet
    # de débat. À ~0,0002 $ le sujet, la prudence ne protégeait de rien : 400
    # sujets coûtent 8 centimes et tiennent dans le cycle de 4 h.
    #
    # `min_speakers=1` : un sujet à une seule voix n'est pas confrontable, mais
    # il s'affiche quand même sur la fiche du locuteur — et un libellé illisible
    # y est aussi gênant qu'ailleurs.
    return await label_subjects(limit=400, min_speakers=1)


async def _detect() -> dict:
    from src.services.analysis.contradiction_detector import run_contradiction_detection
    return await run_contradiction_detection()


async def _review() -> dict:
    from src.services.analysis.review import build_reviews
    return await build_reviews(limit=6, semaines=2)


async def _relevance() -> dict:
    from src.services.analysis.relevance import compute_relevance
    return await compute_relevance()


async def _judge() -> dict:
    from src.services.analysis.contradiction_judge import run_semantic_judging
    return await run_semantic_judging(max_pairs=60)


# ── Le graphe ────────────────────────────────────────────────────────────
#
# L'ordre de cette liste est indicatif : c'est `depends_on` qui fait foi, le
# runner trie topologiquement. Ajouter une étape = ajouter une entrée ici.

STAGES: tuple[Stage, ...] = (
    Stage("collect_x", "Collecte X", FREE, _collect_x,
          produces="posts"),
    Stage("collect_press", "Collecte presse", FREE, _collect_press,
          produces="articles"),
    Stage("enrich_truncated", "Texte intégral des tweets tronqués", FREE,
          _enrich_truncated, depends_on=("collect_x",),
          produces="posts complétés"),
    # L0 après l'enrichissement : segmenter un texte coupé à 280 produit des
    # déclarations fausses par omission, et la dépense est à refaire.
    Stage("amplifications", "Graphe d'amplification", FREE, _amplifications,
          depends_on=("collect_x",), produces="arêtes"),
    Stage("extract_l0", "Extraction des déclarations (L0)", PAID, _extract_l0,
          depends_on=("enrich_truncated", "collect_press"),
          produces="déclarations"),
    # Le codage thématique vient juste après l'extraction : les sujets, les
    # fiches et la revue s'agrègent tous par topique.
    Stage("cap_coding", "Codage thématique (grille CAP)", PAID, _cap_coding,
          depends_on=("extract_l0",), produces="topiques"),
    # Gratuite, et placée juste après l'extraction : tout ce qui agrège par
    # parti — sujets, fiches, revue — doit lire un parti daté, pas le parti du
    # jour où la déclaration a été extraite.
    Stage("party_of_record", "Parti à la date du propos", FREE, _party_of_record,
          depends_on=("extract_l0",), produces="partis rectifiés"),
    # Cité ou rapporté. Déduit de la ponctuation du document, sans modèle : la
    # position des guillemets est un fait vérifiable et gratuit.
    Stage("quotation", "Cité ou rapporté", FREE, _quotation,
          depends_on=("extract_l0",), produces="propos qualifiés"),
    # Le registre des engagements. Bornée à 400 par passe : la question ne se
    # pose que pour les propos normatifs et prédictifs, et rien ne presse — un
    # engagement pris hier vaudra la même chose demain.
    Stage("pledges", "Registre des engagements", PAID, _pledges,
          depends_on=("extract_l0",), produces="engagements"),
    Stage("embed", "Embeddings des déclarations", FREE, _embed,
          depends_on=("extract_l0",), produces="vecteurs"),
    Stage("vector_index", "Index vectoriel", FREE, _vector_index,
          depends_on=("embed",), produces="voisins interrogeables"),
    Stage("enrich_claims", "Thème et référent", FREE, _enrich_claims,
          depends_on=("embed",), produces="rattachements"),
    Stage("build_subjects", "Regroupement en sujets", FREE, _build_subjects,
          depends_on=("embed",), produces="sujets"),
    Stage("detect", "Détection déterministe", FREE, _detect,
          depends_on=("enrich_claims",), produces="rapprochements chiffrés"),
    # La priorisation — l'étape que la méthode place entre la détection et le
    # rapprochement, et qu'on avait sautée. Gratuite : tous ses signaux sont
    # en base. Les agents payants qui suivent travaillent sur ce classement,
    # pas sur la file entière.
    Stage("relevance", "Ce qui compte", FREE, _relevance,
          depends_on=("build_subjects", "detect", "pledges"), produces="classement"),
    Stage("label_subjects", "Nommage des sujets", PAID, _label_subjects,
          depends_on=("relevance",), produces="libellés"),
    Stage("judge", "Juge sémantique", PAID, _judge,
          depends_on=("relevance",), produces="contradictions à relire"),
    # Après le nommage : une revue qui désigne son sujet par « sujet 412 » ne
    # se lit pas. Bornée à six sujets et deux semaines par passe — la revue est
    # le poste le plus cher de la chaîne, et rien ne presse : une semaine close
    # le reste.
    Stage("review", "Revue hebdomadaire", PAID, _review,
          depends_on=("label_subjects",), produces="revues"),
)

BY_NAME: dict[str, Stage] = {s.name: s for s in STAGES}

# La collecte tient tout le reste en otage si on l'enchaîne à l'analyse. Mesuré
# en production : `collect_x` prend 2 h 20 (cadence de politesse imposée par le
# quota X), et comme le graphe la place en tête, une passe redémarrée — un
# redéploiement suffit — repart de la collecte et n'atteint jamais le codage,
# les vecteurs ni les sujets. Trente-trois mille publications collectées, zéro
# sujet construit : la chaîne tournait sans jamais dépasser son premier étage.
#
# Les deux moitiés n'ont ni le même rythme ni la même nature. La collecte est
# lente et dépend du réseau ; l'analyse est rapide et travaille sur ce qui est
# DÉJÀ en base. Les séparer permet de faire tourner l'analyse toutes les heures
# sur le corpus existant, sans attendre la collecte suivante.
COLLECTE = ("collect_x", "collect_press")


def analysis_stages() -> list[str]:
    """Toutes les étapes sauf la collecte, dans l'ordre du graphe."""
    return [s.name for s in STAGES if s.name not in COLLECTE]


def resolve_order(names: list[str] | None = None) -> list[Stage]:
    """Tri topologique des étapes demandées, dépendances incluses.

    Demander « judge » exécute tout ce dont il dépend : on ne peut plus juger
    sur des sujets qui n'ont pas été construits.
    """
    wanted = set(names or BY_NAME)
    unknown = wanted - set(BY_NAME)
    if unknown:
        raise ValueError(f"étape(s) inconnue(s) : {sorted(unknown)}")

    # Fermeture transitive des dépendances.
    todo, seen = list(wanted), set()
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        seen.add(n)
        todo.extend(BY_NAME[n].depends_on)

    ordered: list[Stage] = []
    placed: set[str] = set()
    while len(placed) < len(seen):
        progressed = False
        for s in STAGES:
            if s.name in seen and s.name not in placed:
                if all(d in placed for d in s.depends_on):
                    ordered.append(s)
                    placed.add(s.name)
                    progressed = True
        if not progressed:  # cycle : impossible avec STAGES figé, mais explicite
            raise ValueError(f"cycle de dépendances : {sorted(seen - placed)}")
    return ordered
