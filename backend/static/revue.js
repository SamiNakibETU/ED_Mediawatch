// La revue hebdomadaire : ce qui s'est dit sur un sujet, et sous chaque phrase
// ce qui la fonde.
//
// Le parti pris d'affichage tient en une règle : aucune phrase de synthèse ne
// s'affiche seule. Chaque paragraphe est suivi des déclarations qu'il cite, avec
// le locuteur, la date et le lien vers la source. Une revue d'observatoire se
// distingue d'un résumé par là, et par rien d'autre — sans les sources sous les
// phrases, le lecteur ne peut pas faire la différence entre ce qui a été dit et
// ce qu'un modèle a cru comprendre.
//
// Une seule page pour deux états : le sommaire, et une revue ouverte (?id=).
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, relTime, exactDate,
// themeLabel, themeVar, kicker, ico.

const host = $("#page");
const params = new URLSearchParams(location.search);

// « 2026-W36 » ne se lit pas. « Semaine du 31 août » se lit.
function semaine(period) {
  const m = /^(\d{4})-W(\d{2})$/.exec(period || "");
  if (!m) return period || "";
  const jan4 = new Date(Date.UTC(+m[1], 0, 4));
  const lundi = new Date(jan4);
  lundi.setUTCDate(jan4.getUTCDate() - ((jan4.getUTCDay() + 6) % 7) + (+m[2] - 1) * 7);
  return `semaine du ${lundi.toLocaleDateString("fr-FR", { day: "numeric", month: "long", timeZone: "UTC" })}`;
}

// ── Le sommaire ─────────────────────────────────────────────────────────────

function carte(r) {
  return `<a class="tile" href="revue.html?id=${r.id}">
    ${kicker(r.theme, semaine(r.period))}
    <h2 class="card-title">${escapeHtml(r.title || "sans titre")}</h2>
    <p class="dek">${nomSujet({label: r.subject_label || "sujet sans nom", status: r.subject_status})}</p>
    <p class="tile__foot">
      <span class="stamp">${fmtNum(r.n_paragraphes)} paragraphes ·
        ${fmtNum(r.n_sources)} déclarations citées</span>
      <span class="spacer"></span>
      ${r.status === "brouillon"
        ? '<span class="tag">brouillon</span>'
        : '<span class="tag tag--receipt">relue</span>'}
    </p>
  </a>`;
}

function renderSommaire(d) {
  const actif = params.get("period") || (d.periods || [])[0] || "";
  const items = (d.items || []).filter((r) => !actif || r.period === actif);

  host.innerHTML = `
    <p class="dek lede-first">
      Chaque semaine close, ce qui s’est dit sujet par sujet.
      <strong>Chaque paragraphe cite les déclarations qu’il rapporte</strong>&nbsp;;
      les revues restent des brouillons tant qu’un humain ne les a pas relues.
    </p>

    <div class="filters mt-6" role="group" aria-label="Semaine">
      ${(d.periods || []).slice(0, 8).map((p) => `
        <a class="filter" href="revue.html?period=${p}"
           aria-pressed="${p === actif}">${escapeHtml(semaine(p))}</a>`).join("")}
    </div>

    <div class="band"><h2>Revues</h2><span class="spacer"></span>
      <p>${fmtNum(items.length)} sujet${items.length > 1 ? "s" : ""} traité${items.length > 1 ? "s" : ""}</p></div>

    ${items.length
      ? `<div class="tiles">${items.map(carte).join("")}</div>`
      : `<p class="state">
          <span class="state__title">Aucune revue pour l’instant</span>
          <span class="state__hint">Une revue s’écrit sur une semaine close, pour les sujets
          où deux locuteurs au moins se sont exprimés — voir
          <a class="source-link" href="atelier.html">l’atelier</a>.</span></p>`}`;
}

// ── Une revue ouverte ───────────────────────────────────────────────────────

function source(s) {
  return `<div class="position">
    <p class="entry__head">
      <span class="speaker">${escapeHtml(s.speaker || "locuteur non établi")}</span>
      ${s.party ? `<span class="tag">${escapeHtml(s.party)}</span>` : ""}
      <span class="spacer"></span>
      <span class="stamp">${escapeHtml(exactDate(s.published_at))}</span>
    </p>
    <p class="quoted">${escapeHtml(s.text || "")}</p>
    ${s.url ? `<p class="entry__foot"><a class="source-link" href="${escapeHtml(s.url)}"
        target="_blank" rel="noopener">vérifier la source ${ico("source")}</a></p>` : ""}
  </div>`;
}

function renderRevue(r) {
  document.title = `${r.title} — ED Mediawatch`;
  host.innerHTML = `
    <p class="stamp mb-5"><a class="source-link" href="revue.html">← toutes les revues</a></p>
    ${kicker(r.theme, semaine(r.period))}
    <h1 class="hero-title">${escapeHtml(r.title || "sans titre")}</h1>
    <p class="dek">Sur le sujet
      <a class="link" href="sujet.html?id=${r.subject_id}">${escapeHtml(r.subject_label || "sans nom")}</a>.
      ${r.status === "brouillon"
        ? "Brouillon&nbsp;: écrit par la machine, pas encore relu."
        : "Relu et validé."}</p>

    ${(r.paragraphes || []).map((p) => `
      <section class="revue__bloc">
        <p class="revue__texte">${escapeHtml(p.texte)}</p>
        <div class="revue__sources">
          <p class="overline">${ico("source")} Ce qui fonde ce paragraphe</p>
          ${(p.sources || []).map(source).join("")}
        </div>
      </section>`).join("")}`;
}

// ── Chargement ──────────────────────────────────────────────────────────────

async function load() {
  const id = params.get("id");
  try {
    if (id) renderRevue(await fetchJSON(`/reviews/${id}`));
    else renderSommaire(await fetchJSON("/reviews?limit=60"));
  } catch (e) {
    host.innerHTML =
      `<p class="state state--error">La revue n’a pas pu être chargée (${escapeHtml(e.message)}).</p>`;
  }
}

load();
