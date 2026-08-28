// Le Compteur — les valeurs annoncées pour un même référent, dans le temps.
// L'écart entre deux points est le matériau du travail : on le montre, on ne le lisse pas.
// Helpers ($, fetchJSON, fmtNum, exactDate) : common.js.

const PARTY_VAR = {
  RN: "--grp-rn", UDR: "--grp-udr", FIGURE: "--grp-figure",
  "Reconquête": "--grp-figure", "Droite radicale": "--grp-figure",
};

const PARTY_CLASS = {
  RN: "rn", UDR: "udr", FIGURE: "figure",
  "Reconquête": "figure", "Droite radicale": "figure",
};

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const colorFor = (party) => css(PARTY_VAR[party] || "--muted");

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

function plot(points, unit) {
  if (points.length < 2) {
    return `<p class="state">${points.length
      ? "Une seule valeur relevée : il n’y a pas encore d’écart à montrer."
      : "Aucune valeur datée pour ce référent."}</p>`;
  }

  const W = 760, H = 240, L = 56, R = 16, T = 16, B = 34;
  const xs = points.map((p) => asDate(p.published_at).getTime());
  const ys = points.map((p) => p.value);
  let [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const pad = (y1 - y0) * 0.12;
  y0 -= pad; y1 += pad;
  let [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  if (x0 === x1) { x0 -= 864e5; x1 += 864e5; }

  const px = (t) => L + ((t - x0) / (x1 - x0)) * (W - L - R);
  const py = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);

  const yTicks = niceTicks(y0, y1);
  const xTicks = [x0, (x0 + x1) / 2, x1];
  const fmtDate = (t) => new Date(t).toLocaleDateString("fr-FR", { month: "short", year: "2-digit" });

  const grid = yTicks.map((v) => `
    <line class="plot__grid" x1="${L}" x2="${W - R}"
          y1="${py(v).toFixed(1)}" y2="${py(v).toFixed(1)}" />
    <text class="plot__tick" x="${L - 8}" y="${(py(v) + 3.5).toFixed(1)}"
          text-anchor="end">${num(v)}</text>`).join("");

  const xAxis = xTicks.map((t, i) => `
    <text class="plot__tick" x="${px(t).toFixed(1)}" y="${H - 12}"
          text-anchor="${i === 0 ? "start" : i === 2 ? "end" : "middle"}">${fmtDate(t)}</text>`).join("");

  // Un `<title>` natif plutôt qu'une infobulle scriptée : lisible au clavier,
  // au lecteur d'écran, et sans une ligne de JavaScript de plus.
  //
  // Les couleurs passent par des classes et non par un attribut : `var()` dans
  // un attribut de présentation SVG n'est pas honoré partout, et une couleur
  // résolue au rendu ne suivrait pas le basculement clair/sombre.
  const dots = points.map((p) => `
    <circle class="plot__dot plot__dot--${PARTY_CLASS[p.party] || "autre"}"
            cx="${px(asDate(p.published_at).getTime()).toFixed(1)}"
            cy="${py(p.value).toFixed(1)}" r="5">
      <title>${escapeHtml(`${num(p.value)} ${unitLabel(unit)} · ${p.speaker || "locuteur inconnu"} · ${
        asDate(p.published_at).toLocaleDateString("fr-FR")}`)}</title>
    </circle>`).join("");

  return `<div class="chart-frame">
    <svg class="plot" viewBox="0 0 ${W} ${H}" role="img"
         aria-label="Valeurs annoncées dans le temps, en ${escapeHtml(unitLabel(unit))}">
      ${grid}${xAxis}${dots}
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
  $("#sub").textContent = `${data.n} valeur${data.n > 1 ? "s" : ""} annoncée${
    data.n > 1 ? "s" : ""} · exprimées en ${unitLabel(data.unit) || "unité inconnue"}`;

  $("#chart").innerHTML = plot(
    data.points.filter((p) => p.published_at && p.value != null), data.unit);

  $("#points").innerHTML = data.points.map((p) => `
    <article class="entry enter" style="grid-template-columns:1fr">
      <div>
        <div class="entry__head">
          <span class="claim__value" style="color:${colorFor(p.party)}">${num(p.value)} ${escapeHtml(unitLabel(data.unit))}</span>
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
