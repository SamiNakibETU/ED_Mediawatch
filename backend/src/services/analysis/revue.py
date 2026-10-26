"""La revue de la semaine : de quoi l'extrême droite a parlé sur X, et ce qui a bougé.

Rien n'y est écrit par un modèle, hors le nom des sujets. La revue assemble ce
que la chaîne a déjà établi (sujets regroupés, thèmes, déclarations du
registre, écarts jugés) et montre sous chaque sujet les tweets qui le
fondent. Une revue d'observatoire se distingue d'un résumé par là : le
lecteur voit ce qui a été écrit, pas ce qu'on en a compris.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select

from src.models.declaration import Declaration
from src.models.ecart import Ecart
from src.models.personality import Personality
from src.models.post import Post
from src.models.sujet_semaine import SujetSemaine
from src.services.analysis.enjeux import HORS_LISTE, PAR_SLUG
from src.services.analysis.themes import FAMILLE_DE, FAMILLES, GRILLE, MARQUEURS

SEMAINES_REFERENCE = 4  # la moyenne à laquelle une semaine se compare
UNE = 8  # sujets à la une
TWEETS_PAR_SUJET = 3
ECART_MIN_POINTS = 2.0  # en deçà, une variation de part n'est pas une tendance


def _source(post: Post, pers: Personality) -> dict:
    return {"kind": "tweet", "url": post.url, "text": post.content, "published_at": post.published_at,
            "archive": post.snapshot_url, "author": pers.handle, "post_type": post.post_type,
            "quoted_author": post.quoted_handle, "quoted_text": post.quoted_content,
            "truncated": bool(post.text_truncated)}


def _audience(post: Post) -> int:
    return (post.likes or 0) + 2 * (post.retweets or 0)


def _propre(post: Post) -> bool:
    return not post.is_retweet and post.post_type != "retweet"


async def _tweets(db, debut: datetime, fin: datetime) -> list[tuple[Post, Personality]]:
    return (await db.execute(
        select(Post, Personality).join(Personality, Personality.id == Post.personality_id)
        .where(Post.published_at >= debut, Post.published_at < fin))).all()


def _volume(rows) -> dict:
    propres = [(p, f) for p, f in rows if _propre(p)]
    partis = Counter(f.group_code or "autre" for _, f in propres)
    return {"tweets": len(propres), "retweets": len(rows) - len(propres),
            "figures": len({f.id for _, f in propres}), "partis": dict(partis.most_common())}


def _parts(rows, cle) -> Counter:
    """Part de chaque catégorie dans les tweets propres classés, en pourcentage."""
    c: Counter = Counter()
    n = 0
    for p, _ in rows:
        if not _propre(p) or not p.theme_ed:
            continue
        n += 1
        for k in cle(p):
            c[k] += 1
    return Counter({k: 100 * v / n for k, v in c.items()}) if n else Counter()


def _tendances(semaine, avant, cle, noms) -> list[dict]:
    """Ce qui monte et ce qui recule, contre la moyenne des semaines d'avant."""
    actuelle = _parts(semaine, cle)
    passees = [_parts(r, cle) for r in avant if r]
    if not passees:
        return []
    out = []
    for k in set(actuelle) | {k for p in passees for k in p}:
        ref = sum(p.get(k, 0) for p in passees) / len(passees)
        part = actuelle.get(k, 0)
        if abs(part - ref) >= ECART_MIN_POINTS:
            out.append({"code": k, "label": noms.get(k, k), "part": round(part, 1),
                        "reference": round(ref, 1), "ecart": round(part - ref, 1)})
    return sorted(out, key=lambda t: -abs(t["ecart"]))


async def semaines(db) -> list[str]:
    return [s for (s,) in (await db.execute(
        select(SujetSemaine.semaine).distinct().order_by(SujetSemaine.semaine.desc()))).all()]


async def revue(db, semaine: str | None = None) -> dict:
    dispo = await semaines(db)
    semaine = semaine if semaine in dispo else (dispo[0] if dispo else None)
    if semaine is None:
        return {"semaine": None, "semaines": []}
    sujets = (await db.execute(select(SujetSemaine).where(SujetSemaine.semaine == semaine)
                               .order_by(SujetSemaine.ordre))).scalars().all()
    debut = sujets[0].debut
    fin = debut + timedelta(days=7)

    rows = await _tweets(db, debut, fin)
    avant = [await _tweets(db, debut - timedelta(days=7 * (k + 1)), debut - timedelta(days=7 * k))
             for k in range(SEMAINES_REFERENCE)]
    par_id = {p.id: (p, f) for p, f in rows}

    une = []
    for s in sujets[:UNE]:
        membres = [par_id[i] for i in s.post_ids or [] if i in par_id]
        voix = Counter(f.full_name for _, f in membres)
        dates = sorted(p.published_at for p, _ in membres if p.published_at)
        choisis = sorted((m for m in membres if _propre(m[0])), key=lambda m: -_audience(m[0]))
        une.append({
            "id": s.id, "libelle": s.libelle, "theme": GRILLE.get(s.theme, (None,))[0],
            "n_tweets": s.n_tweets, "n_figures": s.n_figures,
            "voix": [{"nom": n, "tweets": c} for n, c in voix.most_common(4)],
            "du": dates[0] if dates else None, "au": dates[-1] if dates else None,
            "tweets": [_source(p, f) for p, f in choisis[:TWEETS_PAR_SUJET]],
        })

    noms_familles = {k: nom for k, (nom, _) in FAMILLES.items()}
    noms_marqueurs = {k: nom for k, (nom, _) in MARQUEURS.items()}

    decls = (await db.execute(
        select(Declaration).where(Declaration.published_at >= debut, Declaration.published_at < fin,
                                  Declaration.douteuse.isnot(True)))).scalars().all()
    par_enjeu: dict[str, list] = defaultdict(list)
    for d in decls:
        par_enjeu[d.enjeu].append(d)
    enjeux = [{"slug": e, "titre": PAR_SLUG[e].titre, "declarations": len(ds),
               "figures": len({d.personality_id for d in ds})}
              for e, ds in par_enjeu.items() if e in PAR_SLUG]
    enjeux.sort(key=lambda e: (-e["figures"], -e["declarations"]))

    ecarts = (await db.execute(
        # Un écart date de sa seconde déclaration ; celui au programme n'en a qu'une.
        select(Ecart).where(or_(and_(Ecart.date_b >= debut, Ecart.date_b < fin),
                                and_(Ecart.date_b.is_(None), Ecart.date_a >= debut, Ecart.date_a < fin)),
                            Ecart.auto.in_(("retenu", "faible")))
        .order_by(Ecart.auto.desc(), Ecart.ampleur.desc()))).scalars().all()
    figures = {f.id: f.full_name for _, f in rows}
    for e in ecarts:
        for fid in (e.figure_a_id, e.figure_b_id):
            if fid and fid not in figures:
                pers = await db.get(Personality, fid)
                figures[fid] = pers.full_name if pers else None

    plus_vus = sorted((m for m in rows if _propre(m[0])), key=lambda m: -_audience(m[0]))[:5]
    return {
        "semaine": semaine, "semaines": dispo, "du": debut, "au": fin - timedelta(seconds=1),
        "volume": _volume(rows), "volume_avant": _volume(avant[0]) if avant else None,
        "une": une, "autres_sujets": [{"id": s.id, "libelle": s.libelle, "n_tweets": s.n_tweets}
                                      for s in sujets[UNE:]],
        "familles": _tendances(rows, avant, lambda p: [FAMILLE_DE.get(p.theme_ed, "actualite")], noms_familles),
        "marqueurs": _tendances(rows, avant, lambda p: p.marqueurs or [], noms_marqueurs),
        "enjeux": enjeux[:8], "hors_liste": len(par_enjeu.get(HORS_LISTE, [])),
        "declarations": len(decls),
        "ecarts": [{"id": e.id, "type": e.type, "auto": e.auto,
                    "enjeu": PAR_SLUG[e.enjeu].titre if e.enjeu in PAR_SLUG else e.enjeu,
                    "figure_a": figures.get(e.figure_a_id), "figure_b": figures.get(e.figure_b_id),
                    "explication": e.juge_explication} for e in ecarts[:10]],
        "plus_vus": [{**_source(p, f), "figure": f.full_name, "likes": p.likes, "partages": p.retweets}
                     for p, f in plus_vus],
    }
