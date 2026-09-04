// Un seul graphique, réutilisable : la parole mois par mois.
//
// Écrit à la main en SVG, comme le tracé du compteur, et pour les mêmes
// raisons : soixante kilo-octets de bibliothèque pour poser des barres, une
// typographie qui n'est pas celle du système, et une dépendance de plus à
// surveiller sur un site qui doit tenir seul.
//
// Ce qu'on a appris de la version précédente — « les petits graphiques, on
// comprend rien » : un graphique doit porter une AFFIRMATION, pas décorer une
// page. Celui-ci en porte une, écrite au-dessus de lui en français, et ses
// deux axes sont légendés. Pas de sparkline, pas de courbe sans échelle.
//
// Il ne montre que des additions sur des données vérifiées : la hauteur d'une
// barre est un nombre de déclarations attribuées, jamais un jugement de modèle.
// C'est ce qui le rend publiable là où la répartition thématique attend encore
// un second annotateur.

// « 2026-03 » → « mars 26 ». Pas de table de mois écrite à la main : le
// navigateur en a une, correcte et abrégée comme il faut en français
// (« janv. », « févr. », « juil. »), qu'aucun slice ne reproduit.
function moisLisible(cle) {
  const [a, m] = cle.split("-");
  const quand = new Date(Date.UTC(+a, +m - 1, 1));
  return `${quand.toLocaleDateString("fr-FR", { month: "short", timeZone: "UTC" })} ${a.slice(2)}`;
}

// Graduations rondes pour l'axe des hauteurs. Découper en parts égales donnait
// « 7 · 14 · 21 » : des repères qu'on ne lit pas d'un coup d'œil.
function paliers(max, cible = 3) {
  if (max <= 0) return [0];
  const magnitude = 10 ** Math.floor(Math.log10(max));
  for (const m of [1, 2, 2.5, 5, 10]) {
    const pas = m * magnitude;
    if (max / pas <= cible) {
      const out = [];
      for (let v = 0; v <= max + 1e-9; v += pas) out.push(Math.round(v));
      return out;
    }
  }
  return [0, max];
}

// Un mois dont plus de la moitié a été rattrapée après coup n'a pas été
// surveillé : son compte est un plancher. Voir `src/routers/series.py`.
const rattrape = (p) => p.n > 0 && p.retro / p.n > 0.5;

// « Son rythme habituel » sur trois mois de veille n'est pas un rythme, c'est
// un début de série. Même seuil que la normalisation d'audience dans
// `relevance.py` : en deçà de six points, on décrit, on ne compare pas.
const MIN_MOIS_POUR_UN_RYTHME = 6;

/**
 * Barres mensuelles. `points` : [{mois, n, retro, contradictions}].
 * Les mois vides sont attendus DANS la série : un trou non comblé écraserait
 * l'axe, et deux barres voisines seraient à six mois d'écart sans le dire.
 *
 * Les mois reconstitués après coup sont dessinés CREUX. C'est la protection qui
 * survit à une capture d'écran : la légende peut être coupée, la barre vide se
 * lit quand même comme « incomplet ». Sur le corpus réel, mars 2026 (9 posts
 * rattrapés) et août 2026 (2 097 posts surveillés) se suivent sur le même axe —
 * pleins tous les deux, ils raconteraient une explosion du discours qui n'a
 * jamais eu lieu.
 */
function barresMensuelles(points, { unite = "déclarations" } = {}) {
  if (!points || points.length < 2) {
    return `<p class="state state--inline">Pas encore assez de mois pour dessiner une évolution.</p>`;
  }

  const W = 760, H = 200, L = 40, R = 16, T = 14, B = 34;
  const max = Math.max(...points.map((p) => p.n), 1);
  const grad = paliers(max);
  const haut = grad[grad.length - 1];
  const largeurUtile = W - L - R;
  const pas = largeurUtile / points.length;
  const largeurBarre = Math.max(2, Math.min(28, pas * 0.62));
  const y = (v) => T + (1 - v / haut) * (H - T - B);

  const grille = grad.map((v) => `
    <line class="chart__grid" x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" />
    <text class="chart__tick" x="${L - 6}" y="${(y(v) + 3.5).toFixed(1)}" text-anchor="end">${v}</text>`).join("");

  // Un mois sur N en abscisse : douze étiquettes se chevauchent, trois ne
  // situent rien. On vise une étiquette tous les 90 px environ.
  const saut = Math.max(1, Math.ceil(points.length / Math.floor(largeurUtile / 90)));
  const axe = points.map((p, i) => {
    const dernier = i === points.length - 1;
    if (i % saut !== 0 && !dernier) return "";
    // La dernière étiquette est ancrée à droite : centrée, « sept. 26 » sortait
    // du cadre et se faisait couper en « sept. 2 ».
    return `<text class="chart__tick" x="${(L + i * pas + pas / (dernier ? 1 : 2)).toFixed(1)}"
             y="${H - 12}" text-anchor="${dernier ? "end" : "middle"}">${moisLisible(p.mois)}</text>`;
  }).join("");

  const barres = points.map((p, i) => {
    const cx = L + i * pas + pas / 2;
    const creux = rattrape(p);
    const titre = `${moisLisible(p.mois)} — ${p.n} ${unite}`
      + (creux ? " (reconstitué après coup : au moins)" : "")
      + (p.contradictions ? ` · ${p.contradictions} rapprochement${p.contradictions > 1 ? "s" : ""}` : "");
    return `<g>
      <rect class="chart__bar${creux ? " chart__bar--retro" : ""}"
            x="${(cx - largeurBarre / 2).toFixed(1)}" y="${y(p.n).toFixed(1)}"
            width="${largeurBarre.toFixed(1)}" height="${Math.max(0, y(0) - y(p.n)).toFixed(1)}">
        <title>${escapeHtml(titre)}</title>
      </rect>
      ${p.contradictions
        ? `<circle class="chart__flag" cx="${cx.toFixed(1)}" cy="${(y(p.n) - 7).toFixed(1)}" r="3" />`
        : ""}
    </g>`;
  }).join("");

  const legende = [];
  if (points.some((p) => p.contradictions)) {
    legende.push(`<span class="chart__cle"><span class="chart__flag-inline"></span>
      mois où un rapprochement a été retenu</span>`);
  }
  if (points.some(rattrape)) {
    legende.push(`<span class="chart__cle"><span class="chart__retro-inline"></span>
      reconstitué après coup : le compte est un plancher</span>`);
  }

  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img"
       aria-label="Nombre de ${unite} par mois">
      ${grille}${axe}${barres}
    </svg>
    ${legende.length ? `<p class="chart__legende">${legende.join("")}</p>` : ""}`;
}

/**
 * La phrase au-dessus du graphique — celle qui porte l'information.
 *
 * Elle ne raisonne QUE sur les mois surveillés. Sur le corpus réel, la version
 * naïve annonçait « 1 423 déclarations en août 26, son mois le plus dense » :
 * une affirmation sur le collecteur, pas sur le locuteur. Le mois le plus dense
 * d'un corpus rattrapé est le mois où le rattrapage a le mieux marché.
 */
function lireSerie(d, { unite = "déclarations" } = {}) {
  const points = d.points || [];
  const surveilles = d.veille_depuis
    ? points.filter((p) => p.mois >= d.veille_depuis)
    : [];
  const depuis = d.veille_depuis ? moisLisible(d.veille_depuis) : null;

  // Trop peu de mois surveillés pour qu'une tendance veuille dire quelque
  // chose : on dit ce qu'on a, et on s'arrête là. C'est le cas de tout le
  // corpus aujourd'hui — la veille continue a commencé en juillet 2026.
  if (surveilles.length < MIN_MOIS_POUR_UN_RYTHME) {
    return `<p class="chart__lecture">${
      depuis
        ? `Veille continue depuis ${escapeHtml(depuis)} — trop court pour lire un rythme.`
        : "Relevé entièrement reconstitué après coup."}
      <span class="chart__portee">Les mois antérieurs ont été rattrapés source par
      source : chacun compte <em>au moins</em> ce qu’il affiche, jamais tout ce
      qui a été dit.</span></p>`;
  }

  const pleins = surveilles.filter((p) => p.n > 0);
  const fort = pleins.reduce((a, b) => (b.n > a.n ? b : a), pleins[0]);
  const moyenne = surveilles.reduce((n, p) => n + p.n, 0) / surveilles.length;
  const muets = surveilles.length - pleins.length;
  const bouts = [`${fmtNum(fort.n)} ${unite} en ${moisLisible(fort.mois)}`];
  if (moyenne > 0 && fort.n >= 2 * moyenne) bouts.push("plus du double de son rythme habituel");
  if (muets) bouts.push(`${muets} mois sans rien de consigné`);
  return `<p class="chart__lecture">${escapeHtml(bouts.join(" · "))}.
    <span class="chart__portee">Veille continue depuis ${escapeHtml(depuis)} ;
    ce qui précède a été reconstitué après coup.</span></p>`;
}
