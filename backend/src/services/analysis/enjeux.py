"""Le référentiel des enjeux : une liste fermée de questions, une échelle par question.

On part d'en haut, à l'inverse des sujets émergents. Une question fermée, posée
par l'équipe, et chaque déclaration rangée sur son échelle. Un revirement n'est
plus une devinette sur des cosinus : c'est la même personne à deux endroits
différents de la même échelle, à deux dates. Une divergence, ce sont deux voix
de l'extrême droite à deux endroits différents au même moment.

Le choix des questions. Elles portent sur ce que le RN, l'UDR et Reconquête ont
défendu, promis ou abandonné depuis 2012, et sur ce qui les sépare entre eux.
Une question qui ne départage personne n'apprend rien : elle n'est pas ici.

Les échelles sont ordinales : `rang` mesure l'ampleur d'un écart (passer de 60
à 62 ans n'est pas passer de 60 à 64). Le silence n'a pas de cran : se taire
n'est pas une position, et on ne l'écrit pas. Ce qui n'entre dans aucune
question est gardé à part (`HORS_LISTE`), avec son objet en clair : c'est là
qu'on voit quelle question manque.

Ce référentiel est un premier jet, à valider par la rédaction. Toute
modification d'une question ou d'une échelle change `ENJEUX_VERSION`, et les
déclarations lues sous l'ancienne version se relisent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

ENJEUX_VERSION = "enjeux-v2"
HORS_LISTE = "hors_liste"

THEMES = {
    "economie": "Économie et fiscalité",
    "social": "Travail et protection sociale",
    "europe": "Europe et commerce",
    "immigration": "Immigration et nationalité",
    "securite": "Sécurité et justice",
    "institutions": "Institutions",
    "societe": "Société",
    "international": "International et défense",
    "energie": "Énergie et environnement",
}


@dataclass(frozen=True)
class Cran:
    code: str
    label: str
    rang: int


@dataclass(frozen=True)
class Enjeu:
    slug: str
    titre: str
    theme: str
    question: str
    echelle: tuple[Cran, ...]
    # Repères publics, pour lire la trajectoire. Ce ne sont pas des positions :
    # ils ne sortent jamais d'un tweet et ne comptent dans aucun écart.
    jalons: tuple[str, ...] = ()

    def cran(self, code: str | None) -> Cran | None:
        return next((c for c in self.echelle if c.code == code), None)


def _e(slug: str, titre: str, theme: str, question: str, *crans: tuple[str, str],
       jalons: tuple[str, ...] = ()) -> Enjeu:
    return Enjeu(slug, titre, theme, question,
                 tuple(Cran(code, label, i + 1) for i, (code, label) in enumerate(crans)), jalons)


ENJEUX: tuple[Enjeu, ...] = (
    # ── Économie et fiscalité
    _e("tva_energie", "TVA sur l'énergie", "economie",
       "Faut-il baisser la TVA sur l'énergie et les carburants ?",
       ("baisser_5_5", "la baisser à 5,5 %"), ("baisser_autrement", "la baisser autrement ou sous conditions"),
       ("maintenir", "la maintenir")),
    _e("impot_fortune", "Impôt sur la fortune", "economie",
       "Faut-il taxer le patrimoine des plus riches ?",
       ("isf", "rétablir un ISF large"), ("fortune_financiere", "taxer la fortune financière seulement"),
       ("statu_quo", "garder l'IFI tel qu'il est"), ("supprimer", "supprimer tout impôt sur la fortune")),
    _e("impot_jeunes", "Impôt des moins de 30 ans", "economie",
       "Faut-il exonérer d'impôt sur le revenu les moins de 30 ans ?",
       ("exonerer", "les exonérer"), ("conditionnel", "les exonérer sous conditions"), ("non", "ne pas les exonérer")),
    _e("deficit", "Déficit et dette", "economie",
       "Faut-il réduire rapidement le déficit public ?",
       ("reduire_vite", "le réduire vite, par des économies"), ("reduire_progressif", "le réduire progressivement"),
       ("relance", "dépenser davantage, la dette attendra")),
    _e("autoroutes", "Autoroutes", "economie",
       "Faut-il nationaliser les autoroutes ?",
       ("nationaliser", "les nationaliser"), ("a_echeance", "les reprendre à la fin des concessions"),
       ("non", "laisser les concessions")),

    # ── Travail et protection sociale
    _e("retraites", "Âge de départ à la retraite", "social",
       "À quel âge doit-on pouvoir partir à la retraite ?",
       ("60_tous", "60 ans pour tous"),
       ("60_carrieres_longues", "60 ans pour les carrières longues, plus tard pour les autres"),
       ("62", "62 ans"), ("64_ou_plus", "64 ans ou plus"),
       jalons=("2023-04-14 : promulgation de la réforme portant l'âge légal à 64 ans",)),
    _e("reforme_2023", "Réforme des retraites de 2023", "social",
       "Faut-il abroger la réforme des retraites de 2023 ?",
       ("abroger_vite", "l'abroger dès l'arrivée au pouvoir"), ("abroger_plus_tard", "l'abroger plus tard ou par étapes"),
       ("maintenir", "la maintenir")),
    _e("smic", "SMIC", "social",
       "Faut-il augmenter le SMIC ?",
       ("par_la_loi", "l'augmenter par la loi"), ("par_les_charges", "augmenter le salaire net en baissant les cotisations"),
       ("non", "ne pas l'augmenter")),
    _e("assurance_chomage", "Assurance chômage", "social",
       "Faut-il durcir les règles de l'assurance chômage ?",
       ("durcir", "les durcir"), ("maintenir", "les maintenir"), ("assouplir", "les assouplir")),

    # ── Europe et commerce
    _e("euro", "Euro", "europe",
       "La France doit-elle sortir de l'euro ?",
       ("sortir", "sortir de l'euro"), ("referendum", "en décider par référendum, ou sortir à terme"),
       ("rester", "rester dans l'euro"),
       jalons=("2017 : sortie de l'euro au programme présidentiel du FN",)),
    _e("frexit", "Appartenance à l'UE", "europe",
       "La France doit-elle quitter l'Union européenne ?",
       ("quitter", "la quitter"), ("referendum", "en décider par référendum"),
       ("reformer", "rester et la transformer de l'intérieur"), ("rester", "rester sans réserve")),
    _e("primaute_droit", "Droit national et droit européen", "europe",
       "Le droit français doit-il primer sur le droit européen ?",
       ("primer_toujours", "toujours, inscrit dans la Constitution"), ("primer_parfois", "sur certains sujets"),
       ("non", "non, le droit européen prime")),
    _e("contribution_ue", "Contribution au budget de l'UE", "europe",
       "Faut-il réduire la contribution de la France au budget de l'UE ?",
       ("reduire_fort", "la réduire fortement"), ("reduire", "la réduire un peu"), ("maintenir", "la maintenir")),
    _e("libre_echange", "Accords de libre-échange", "europe",
       "Faut-il ratifier les accords de libre-échange comme le Mercosur ?",
       ("rejeter", "les rejeter"), ("renegocier", "les renégocier"), ("ratifier", "les ratifier")),

    # ── Immigration et nationalité
    _e("referendum_immigration", "Référendum sur l'immigration", "immigration",
       "Faut-il un référendum sur l'immigration ?",
       ("oui", "oui"), ("non", "non")),
    _e("droit_du_sol", "Droit du sol", "immigration",
       "Faut-il supprimer le droit du sol ?",
       ("supprimer", "le supprimer partout"), ("restreindre", "le restreindre à certains territoires ou cas"),
       ("maintenir", "le maintenir")),
    _e("regroupement_familial", "Regroupement familial", "immigration",
       "Faut-il supprimer le regroupement familial ?",
       ("supprimer", "le supprimer"), ("restreindre", "le restreindre"), ("maintenir", "le maintenir")),
    _e("ame", "Aide médicale d'État", "immigration",
       "Faut-il supprimer l'aide médicale d'État ?",
       ("supprimer", "la supprimer"), ("urgences", "la réduire aux soins urgents"), ("maintenir", "la maintenir")),
    _e("priorite_nationale", "Priorité nationale", "immigration",
       "Faut-il réserver aux Français l'accès prioritaire au logement social, à l'emploi et aux aides ?",
       ("generale", "oui, pour le logement, l'emploi et les aides"), ("partielle", "oui, pour certaines aides seulement"),
       ("non", "non")),
    _e("binationaux", "Binationaux", "immigration",
       "Faut-il interdire aux binationaux certains postes sensibles ?",
       ("interdire", "les interdire"), ("non", "ne pas les interdire")),
    _e("remigration", "Remigration", "immigration",
       "Faut-il organiser le départ d'une partie des étrangers ou des Français d'origine étrangère déjà installés ?",
       ("remigration", "oui, une remigration à grande échelle"),
       ("expulser_delinquants", "seulement expulser les étrangers délinquants ou en situation irrégulière"),
       ("non", "non")),
    _e("expulsions", "Expulsions", "immigration",
       "Faut-il expulser systématiquement les étrangers sous obligation de quitter le territoire ?",
       ("systematique", "systématiquement"), ("renforcer", "en expulser davantage qu'aujourd'hui"),
       ("statu_quo", "garder la politique actuelle")),

    # ── Sécurité et justice
    _e("peines_planchers", "Peines planchers", "securite",
       "Faut-il rétablir les peines planchers ?",
       ("retablir", "les rétablir"), ("non", "ne pas les rétablir")),
    _e("peine_de_mort", "Peine de mort", "securite",
       "Faut-il rétablir la peine de mort ?",
       ("retablir", "la rétablir"), ("referendum", "en décider par référendum"), ("non", "ne pas la rétablir"),
       jalons=("2012 : référendum sur la peine de mort au programme du FN",)),
    _e("legitime_defense", "Présomption de légitime défense", "securite",
       "Faut-il une présomption de légitime défense pour les policiers ?",
       ("oui", "oui"), ("non", "non")),
    _e("majorite_penale", "Majorité pénale", "securite",
       "Faut-il abaisser la majorité pénale ?",
       ("abaisser", "l'abaisser"), ("non", "la maintenir à 18 ans")),
    _e("voile", "Voile dans l'espace public", "securite",
       "Faut-il interdire le voile islamique dans l'espace public ?",
       ("partout", "l'interdire partout dans l'espace public"),
       ("certains_lieux", "l'interdire dans certains lieux (sorties scolaires, sport, université)"),
       ("non", "ne pas étendre l'interdiction")),

    # ── Institutions
    _e("proportionnelle", "Mode de scrutin", "institutions",
       "Faut-il élire les députés à la proportionnelle ?",
       ("integrale", "à la proportionnelle intégrale"), ("mixte", "avec une dose de proportionnelle ou une prime"),
       ("majoritaire", "garder le scrutin majoritaire")),
    _e("referendum_initiative", "Référendum d'initiative citoyenne", "institutions",
       "Faut-il un référendum d'initiative citoyenne ?",
       ("ric", "oui, le RIC"), ("elargir", "élargir le référendum sans aller jusqu'au RIC"), ("non", "non")),
    _e("art_49_3", "Article 49.3", "institutions",
       "Faut-il supprimer l'article 49.3 ?",
       ("supprimer", "le supprimer"), ("encadrer", "l'encadrer"), ("maintenir", "le maintenir")),
    _e("union_droites", "Union des droites", "institutions",
       "L'extrême droite doit-elle s'allier avec la droite et entre ses partis ?",
       ("union", "oui, une union des droites"), ("au_cas_par_cas", "des accords au cas par cas"),
       ("refus", "non, chacun seul")),

    # ── Société
    _e("ivg_constitution", "IVG dans la Constitution", "societe",
       "Faut-il inscrire l'IVG dans la Constitution ?",
       ("pour", "pour"), ("reserves", "pour avec des réserves, ou abstention"), ("contre", "contre"),
       jalons=("2024-03-04 : inscription de l'IVG dans la Constitution",)),
    _e("mariage_pour_tous", "Mariage pour tous", "societe",
       "Faut-il revenir sur le mariage pour tous ?",
       ("abroger", "l'abroger"), ("union_civile", "le remplacer par une union civile"), ("maintenir", "le maintenir")),
    _e("pma_gpa", "PMA pour toutes", "societe",
       "Faut-il ouvrir ou maintenir la PMA pour toutes les femmes ?",
       ("pour", "pour"), ("contre", "contre")),
    _e("fin_de_vie", "Aide à mourir", "societe",
       "Faut-il légaliser l'aide à mourir ?",
       ("pour", "pour"), ("encadree", "seulement des soins palliatifs renforcés ou un cadre très strict"),
       ("contre", "contre")),

    # ── International et défense
    _e("ukraine", "Ukraine et Russie", "international",
       "La France doit-elle aider militairement l'Ukraine face à la Russie ?",
       ("aide_militaire", "aider militairement, y compris en armes"),
       ("aide_limitee", "aider, mais sans armes offensives ni troupes"),
       ("negocier", "cesser l'escalade, négocier avec la Russie"),
       ("contre_aide", "s'opposer à l'aide"),
       jalons=("2022-02-24 : invasion russe de l'Ukraine",)),
    _e("sanctions_russie", "Sanctions contre la Russie", "international",
       "Faut-il maintenir les sanctions contre la Russie ?",
       ("renforcer", "les renforcer"), ("maintenir", "les maintenir"),
       ("alleger", "les alléger ou les lever")),
    _e("otan", "OTAN", "international",
       "La France doit-elle quitter le commandement intégré de l'OTAN ?",
       ("quitter", "quitter le commandement intégré"), ("quitter_plus_tard", "le quitter, mais pas en temps de guerre"),
       ("rester", "rester dans le commandement intégré"),
       jalons=("2009 : retour de la France dans le commandement intégré",)),
    _e("etat_palestinien", "État palestinien", "international",
       "La France doit-elle reconnaître l'État palestinien ?",
       ("reconnaitre", "le reconnaître"), ("conditions", "le reconnaître sous conditions"), ("non", "ne pas le reconnaître"),
       jalons=("2025-09 : reconnaissance de l'État palestinien par la France",)),
    _e("budget_defense", "Budget de la défense", "international",
       "Faut-il augmenter fortement le budget de la défense ?",
       ("hausse_forte", "l'augmenter fortement"), ("hausse", "l'augmenter un peu"), ("maintenir", "le maintenir")),
    _e("service_militaire", "Service militaire", "international",
       "Faut-il rétablir un service militaire ?",
       ("obligatoire", "obligatoire"), ("volontaire", "volontaire"), ("non", "non")),

    # ── Énergie et environnement
    _e("nucleaire", "Nucléaire", "energie",
       "Faut-il construire de nouveaux réacteurs nucléaires ?",
       ("relance_forte", "en construire beaucoup"), ("quelques", "en construire quelques-uns"),
       ("reduire", "réduire la part du nucléaire")),
    _e("eolien", "Éolien", "energie",
       "Faut-il arrêter le développement de l'éolien ?",
       ("demanteler", "arrêter et démanteler les éoliennes"), ("moratoire", "un moratoire sur les nouvelles"),
       ("poursuivre", "poursuivre le développement")),
    _e("zfe", "Zones à faibles émissions", "energie",
       "Faut-il supprimer les zones à faibles émissions ?",
       ("supprimer", "les supprimer"), ("assouplir", "les assouplir"), ("maintenir", "les maintenir")),
)

PAR_SLUG: dict[str, Enjeu] = {e.slug: e for e in ENJEUX}


def referentiel_pour_prompt() -> str:
    """Le référentiel tel que le modèle le lit : une ligne par enjeu, ses codes de position."""
    lignes = []
    for theme, nom in THEMES.items():
        lignes.append(f"\n## {nom}")
        for e in ENJEUX:
            if e.theme == theme:
                crans = " | ".join(f"{c.code} = {c.label}" for c in e.echelle)
                lignes.append(f"- {e.slug} : {e.question} [{crans}]")
    return "\n".join(lignes).strip()


@dataclass(frozen=True)
class Point:
    """Une position datée d'une figure, telle qu'elle est en base."""

    personality_id: int
    position: str
    published_at: datetime
    post_id: int


@dataclass(frozen=True)
class Ecart:
    personality_id: int
    avant: Point
    apres: Point
    ampleur: int  # différence de rang, toujours positive


def ecarts(enjeu: Enjeu, points: list[Point], *, min_jours: int = 30) -> list[Ecart]:
    """Les changements de position d'une même figure, dans l'ordre du temps.

    On compare chaque position à la précédente de la même personne, pas à la
    première : une trajectoire 1 → 3 → 1 fait deux écarts, et c'est ce qu'il
    faut montrer. Deux positions à moins de `min_jours` d'écart ne comptent
    pas : dans la même semaine, c'est une nuance de formulation, pas un
    revirement, et c'est le relecteur qui tranchera en lisant les deux textes.
    """
    par_figure: dict[int, list[Point]] = {}
    for p in points:
        if enjeu.cran(p.position):
            par_figure.setdefault(p.personality_id, []).append(p)

    out: list[Ecart] = []
    for pid, serie in par_figure.items():
        serie.sort(key=lambda p: p.published_at)
        prec = serie[0]
        for p in serie[1:]:
            if p.position != prec.position:
                if (p.published_at - prec.published_at).days >= min_jours:
                    ampleur = abs(enjeu.cran(p.position).rang - enjeu.cran(prec.position).rang)
                    out.append(Ecart(pid, prec, p, ampleur))
                    prec = p
                # Un écart trop rapproché ne remplace pas la référence : la
                # position suivante se compare encore à la dernière qui tenait.
                continue
            prec = p
    out.sort(key=lambda e: (-e.ampleur, e.apres.published_at))
    return out
