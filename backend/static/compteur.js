// Le Compteur — les valeurs annoncées pour un même référent, dans le temps.
// L'écart entre deux points est le matériau du travail : on le montre, on ne le lisse pas.
// Helpers ($, fetchJSON, fmtNum, exactDate) : common.js.

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// Les unités arrivent du LLM sous forme de slugs (`pct_pib`). Un identifiant
// machine affiché tel quel dans un relevé public le fait passer pour un code
// officiel : on le rend en français, et on garde le slug en repli.
const UNITS = {
  pct_pib: "% du PIB", pct: "%", pourcent: "%", pourcentage: "%",
  milliards_euros: "Md\u202f\u20ac", milliards: "milliards",
  millions_euros: "M\u202f\u20ac", millions: "millions",
  euros: "\u20ac", personnes: "personnes", annees: "ans",
  emplois: "emplois", logements: "logements", places: "places",
};
const unitLabel = (u) => UNITS[u] || String(u || "").replace(/_/g, " ");

// ── Tracé ───────────────────────────────────────────────────────────────────────
//
// SVG écrit à la main plutôt qu'une bibliothèque de graphes. Trois raisons :
// la page chargeait 60 ko depuis un CDN pour poser quelques points ; les
// grilles et la typographie par défaut ne sont pas celles du système visuel,
// et ça se voyait ; et une dépendance externe est une panne de plus à
// surveiller sur un site qui doit tenir seul.
//
// Aucune courbe reliant les points : ce sont des déclarations datées, pas une
// série mesurée. Un trait entre deux annonces suggérerait une évolution
// continue que personne n'a observée.

// Chiffres a la francaise : la virgule decimale. Un releve public qui affiche
// « 5.4 » se lit comme une sortie de machine, pas comme un chiffre cite.
const num = (v) => Number(v).toLocaleString("fr-FR", { maximumFractionDigits: 2 });

// Graduations sur des valeurs rondes. Decouper l'intervalle en parts egales
// donnait « 5,71 / 4,64 / 3,56 » : des reperes qu'on ne peut pas lire d'un
// coup d'oeil, et qui donnent l'air d'une precision qui n'existe pas.
function niceTicks(lo, hi, target = 4) {
  const span = hi - lo;
  if (!(span > 0)) return [lo, hi];
  const mag = 10 ** Math.floor(Math.log10(span));
  // On essaie les pas du plus fin au plus grossier et on retient le premier
  // qui tombe dans une fourchette lisible. Choisir le pas d'après la seule
  // largeur de l'intervalle produisait une graduation unique sur certaines
  // plages — et donc un axe muet.
  for (const m of [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10]) {
    const step = m * mag;
    const first = Math.ceil(lo / step) * step;
    const n = Math.floor((hi - first) / step) + 1;
    if (n >= 3 && n <= target + 2) {
      return Array.from({ length: n }, (_, i) => Number((first + i * step).toFixed(10)));
    }
  }
  return [lo, hi];
}

// Le nom de famille seul : dans un relevé où chaque point porte une étiquette,
// « Marine Le Pen » et « Sébastien Chenu » se chevauchent, « Le Pen » et
// « Chenu » non.
function nomCourt(qui) {
  const mots = String(qui || "").trim().split(/\s+/);
  if (mots.length < 2) return qui || "locuteur inconnu";
  const i = mots.findIndex((m, k) => k > 0 && /^[A-ZÉÈÀÂÎÔÛÄËÏÖÜÇ]/.test(m));
  return i > 0 ? mots.slice(i).join(" ") : mots[mots.length - 1];
}

// Le format de date suit l'ÉTENDUE, pas une convention fixe. Cinq valeurs
// annoncées dans le même mois donnaient trois graduations identiques —
// « juin 26 » trois fois — soit un axe qui n'ordonne rien.
function formatAxe(span) {
  const jour = 864e5;
  if (span < 2 * jour) return (t) => new Date(t).toLocaleString("fr-FR",
    { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  if (span < 300 * jour) return (t) => new Date(t).toLocaleDateString("fr-FR",
    { day: "numeric", month: "short" });
  return (t) => new Date(t).toLocaleDateString("fr-FR", { month: "short", year: "2-digit" });
}

function plot(points, unit) {
  if (points.length < 2) {
    return `<p class="state">${points.length
      ? "Une seule valeur relevée : il n’y a pas encore d’écart à montrer."
      : "Aucune valeur datée pour ce référent."}</p>`;
  }

  // Marge droite courte : l'étiquette se pose CONTRE son point, pas dans une
  // colonne à part. Alignées à droite, les étiquettes perdaient le lien avec
  // leur point dès que deux valeurs se rapprochaient — on lisait cinq noms et
  // cinq points sans savoir lequel allait avec lequel.
  const W = 760, H = 260, L = 52, R = 24, T = 20, B = 34;
  const xs = points.map((p) => asDate(p.published_at).getTime());
  const ys = points.map((p) => p.value);
  let [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const pad = (y1 - y0) * 0.16;
  y0 -= pad; y1 += pad;
  let [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  if (x0 === x1) { x0 -= 864e5; x1 += 864e5; }

  const px = (t) => L + ((t - x0) / (x1 - x0)) * (W - L - R);
  const py = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);

  const fmtDate = formatAxe(x1 - x0);
  const grid = niceTicks(y0, y1).map((v) => `
    <line class="plot__grid" x1="${L}" x2="${W - R}"
          y1="${py(v).toFixed(1)}" y2="${py(v).toFixed(1)}" />
    <text class="plot__tick" x="${L - 8}" y="${(py(v) + 3.5).toFixed(1)}"
          text-anchor="end">${num(v)}</text>`).join("");

  const xAxis = [x0, (x0 + x1) / 2, x1].map((t, i) => `
    <text class="plot__tick" x="${px(t).toFixed(1)}" y="${H - 12}"
          text-anchor="${i === 0 ? "start" : i === 2 ? "end" : "middle"}">${fmtDate(t)}</text>`).join("");

  const marques = points.map((p) => {
    const cx = px(asDate(p.published_at).getTime());
    const cy = py(p.value);
    // L'étiquette bascule à gauche du point quand elle déborderait la zone :
    // un nom coupé au bord vaut moins qu'un nom du mauvais côté.
    const droite = cx < W - R - 130;
    return `
    <g class="plot__pt">
      <circle class="plot__dot"
              cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="5">
        <title>${escapeHtml(`${num(p.value)} ${unitLabel(unit)} · ${p.speaker || "locuteur inconnu"} · ${
          asDate(p.published_at).toLocaleDateString("fr-FR")}`)}</title>
      </circle>
      <text class="plot__nom" x="${(cx + (droite ? 11 : -11)).toFixed(1)}"
            y="${(cy + 4).toFixed(1)}" text-anchor="${droite ? "start" : "end"}">
        <tspan class="plot__val">${num(p.value)}</tspan>
        ${escapeHtml(nomCourt(p.speaker))}</text>
    </g>`;
  }).join("");

  return `<div class="chart-frame">
    <svg class="plot" viewBox="0 0 ${W} ${H}" role="img"
         aria-label="Valeurs annoncées dans le temps, en ${escapeHtml(unitLabel(unit))}">
      ${grid}${xAxis}${marques}
    </svg>
  </div>`;
}

async function loadList() {
  const el = $("#list");
  let compteurs = [];
  try {
    ({ compteurs } = await fetchJSON("/compteurs"));
  } catch (e) {
    el.innerHTML = `<p class="state state--error">Compteurs indisponibles (${e.message}).</p>`;
    return;
  }
  if (!compteurs.length) {
    el.innerHTML = `<p class="state"><span class="state__title">Aucun compteur</span>
      <span class="state__hint">Aucune valeur chiffrée n’a encore été extraite. Lance l’analyse pour peupler le relevé.</span></p>`;
    return;
  }

  el.innerHTML = compteurs.map((c) => `
    <button class="referent" data-key="${c.referent_key}" aria-pressed="false">
      <span class="referent__label">${escapeHtml(c.label)}</span>
      <span class="referent__meta">${c.n_claims} valeur${c.n_claims > 1 ? "s" : ""}${
        c.spread > 0 ? ` · écart ${num(c.spread)}` : ""}<br />${num(c.min)}–${num(c.max)} ${
        escapeHtml(unitLabel(c.unit))}</span>
    </button>`).join("");

  el.querySelectorAll(".referent").forEach((b) => b.onclick = () => {
    el.querySelectorAll(".referent").forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
    loadCompteur(b.dataset.key);
  });
  el.querySelector(".referent").setAttribute("aria-pressed", "true");
  $("#stats").innerHTML = `<strong>${compteurs.length}</strong> référents`;

  // Le bandeau de tête : combien d'objets suivis, combien de valeurs, et le
  // plus grand désaccord observé — c'est lui qui dit si la page a quelque chose
  // à montrer aujourd'hui.
  const valeurs = compteurs.reduce((n, c) => n + (c.n_claims || 0), 0);
  const pire = compteurs.reduce((a, c) => (c.spread > (a?.spread ?? -1) ? c : a), null);
  $("#stats-bar").innerHTML = `<div class="statbar">
    <span class="statbar__item"><span class="statbar__n">${fmtNum(compteurs.length)}</span>
      objets suivis</span>
    <span class="statbar__item"><span class="statbar__n">${fmtNum(valeurs)}</span>
      valeurs annoncées</span>
    ${pire && pire.spread > 0 ? `<span class="statbar__item">
      <span class="statbar__n statbar__n--accent">${num(pire.spread)}</span>
      d’écart maximal <span class="statbar__of">${escapeHtml(pire.label)}</span></span>`
      : `<span class="statbar__item">aucun écart relevé pour l’instant</span>`}
  </div>`;
  loadCompteur(compteurs[0].referent_key);
}

async function loadCompteur(key) {
  let data;
  try {
    data = await fetchJSON(`/compteur?key=${encodeURIComponent(key)}`);
  } catch (e) {
    $("#points").innerHTML = `<p class="state state--error">Relevé indisponible (${e.message}).</p>`;
    return;
  }

  $("#title").textContent = data.label;
  // L'écart en toutes lettres sous le titre plutôt que tracé dans le graphe :
  // c'est le résultat de la page, il se lit avant d'aller compter les points.
  const vals = (data.points || []).map((p) => p.value).filter((v) => v != null);
  const ecart = vals.length > 1 ? Math.max(...vals) - Math.min(...vals) : null;
  $("#sub").textContent = `${data.n} valeur${data.n > 1 ? "s" : ""} annoncée${
    data.n > 1 ? "s" : ""} · en ${unitLabel(data.unit) || "unité inconnue"}${
    ecart ? ` · écart de ${num(ecart)}` : ""}`;

  $("#chart").innerHTML = plot(
    data.points.filter((p) => p.published_at && p.value != null), data.unit);

  $("#points").innerHTML = data.points.map((p) => `
    <article class="entry enter" style="grid-template-columns:1fr">
      <div>
        <div class="entry__head">
          <span class="claim__value">${num(p.value)} ${escapeHtml(unitLabel(data.unit))}</span>
          <span class="speaker">${escapeHtml(p.speaker || "locuteur inconnu")}</span>
          <span class="tag">${escapeHtml(p.party || p.platform)}</span>
          ${p.human_validated ? '<span class="tag tag--receipt">validé</span>' : ""}
          <span class="spacer"></span>
          <span class="stamp">${p.published_at ? asDate(p.published_at).toLocaleDateString("fr-FR") : "date inconnue"}</span>
        </div>
        <blockquote class="quoted">${escapeHtml((p.verbatim || "").slice(0, 240))}</blockquote>
        ${p.source_url ? `<div class="entry__foot"><span class="spacer"></span>
          <a class="source-link" href="${p.source_url}" target="_blank" rel="noopener">source ↗</a></div>` : ""}
      </div>
    </article>`).join("");
}

loadList();
