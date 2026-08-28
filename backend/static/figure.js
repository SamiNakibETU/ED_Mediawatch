// Fiche personnalité : la chronologie des positions, pas un flux de plus.
// Helpers ($, fetchJSON, fmtNum, escapeHtml, exactDate) : common.js.

const GROUP_VAR = { RN: "--grp-rn", UDR: "--grp-udr", FIGURE: "--grp-figure" };
const TYPE_LABEL = {
  normatif: "position", factuel_quantitatif: "chiffre", factuel_qualitatif: "fait",
  predictif: "prédiction", attributif: "imputation",
};
const MONTHS = ["janv.", "févr.", "mars", "avril", "mai", "juin",
                "juil.", "août", "sept.", "oct.", "nov.", "déc."];

const state = { id: null, theme: null, figures: [] };

const monthLabel = (key) => {
  if (key === "date-inconnue") return "Date inconnue";
  const [y, m] = key.split("-");
  return `${MONTHS[+m - 1]} ${y}`;
};

function renderList() {
  const q = ($("#figSearch").value || "").toLowerCase().trim();
  const shown = state.figures.filter((f) =>
    !q || f.full_name.toLowerCase().includes(q) || (f.handle || "").toLowerCase().includes(q));

  $("#figList").innerHTML = shown.length
    ? shown.map((f) => `
      <button class="referent" data-id="${f.id}" aria-pressed="${state.id === f.id}">
        <span class="referent__label">${escapeHtml(f.full_name)}</span>
        <span class="referent__meta">${f.n_claims ? `${fmtNum(f.n_claims)} propos` : "aucun propos"}${
          f.handle ? ` · @${escapeHtml(f.handle)}` : ""}</span>
      </button>`).join("")
    : '<p class="state">Aucune figure ne correspond.</p>';

  $("#figList").querySelectorAll(".referent").forEach((b) =>
    b.onclick = () => { state.theme = null; load(+b.dataset.id); });
}

function themeFilters(byTheme) {
  const entries = Object.entries(byTheme);
  if (!entries.length) return "";
  return `<div class="filters" style="margin:var(--s4) 0">
    <button class="filter" data-theme="" aria-pressed="${!state.theme}">Tous les thèmes</button>
    ${entries.map(([t, n]) =>
      `<button class="filter" data-theme="${escapeHtml(t)}" aria-pressed="${state.theme === t}">
        ${escapeHtml(t)}<span class="count">${n}</span></button>`).join("")}
  </div>`;
}

function claimRow(c) {
  const date = c.published_at
    ? new Date(c.published_at).toLocaleDateString("fr-FR", { day: "numeric", month: "short" })
    : "—";
  const value = c.qty_value != null ? `${c.qty_value}${c.qty_unit ? " " + c.qty_unit : ""}` : "";
  return `<article class="entry" style="grid-template-columns:4.5rem 1fr;padding:var(--s4) 0">
    <p class="stamp" style="padding-top:2px">${date}</p>
    <div>
      ${value ? `<p class="claim__value">${escapeHtml(value)}</p>` : ""}
      <p class="prose" style="margin-top:0">${escapeHtml(c.canonical || c.verbatim)}</p>
      <div class="entry__foot">
        <span class="tag">${TYPE_LABEL[c.claim_type] || escapeHtml(c.claim_type)}</span>
        ${c.theme ? `<span class="tag tag--theme">${escapeHtml(c.theme)}</span>` : ""}
        <span class="tag">${c.platform === "x" ? "X" : "presse"}</span>
        <span class="spacer"></span>
        ${c.source_url ? `<a class="source-link" href="${c.source_url}" target="_blank" rel="noopener">source ↗</a>`
          : '<span class="stamp">source non résolue</span>'}
      </div>
    </div>
  </article>`;
}

function render(d) {
  const f = d.figure, s = d.stats;
  const color = `var(${GROUP_VAR[f.group_code] || "--muted"})`;
  const span = s.first_seen && s.last_seen
    ? `${new Date(s.first_seen).toLocaleDateString("fr-FR")} → ${new Date(s.last_seen).toLocaleDateString("fr-FR")}`
    : "période inconnue";
  const months = Math.max(1, Math.round(
    (new Date(s.last_seen) - new Date(s.first_seen)) / (1000 * 60 * 60 * 24 * 30)));

  // Une profondeur courte doit être DITE : sans elle, l'absence de revirement
  // n'est pas un résultat, c'est une limite du corpus.
  const depth = s.first_seen && months < 24
    ? `<p class="rationale" style="border-top:none;padding-top:0">Profondeur d’historique : ${months} mois.
       Un changement de position se lit sur plusieurs années — en deçà, l’absence de
       revirement ne prouve rien.</p>`
    : "";

  $("#detail").innerHTML = `
    <p class="section-label">Fiche</p>
    <h1>${escapeHtml(f.full_name)}</h1>
    <div class="entry__foot" style="margin-top:var(--s2)">
      <span class="tag tag--group" style="--grp-color:${color}">${escapeHtml(f.group_code)}</span>
      ${f.famille ? `<span class="tag">${escapeHtml(f.famille)}</span>` : ""}
      ${f.role ? `<span class="tag">${escapeHtml(f.role)}</span>` : ""}
      ${mandat(f.departement, f.circo)
        ? `<span class="tag">${escapeHtml(mandat(f.departement, f.circo))}</span>` : ""}
      ${f.handle ? `<a class="handle" href="https://x.com/${f.handle}" target="_blank" rel="noopener">@${escapeHtml(f.handle)}</a>` : ""}
    </div>

    <p class="lede" style="margin-top:var(--s4)">
      <strong>${fmtNum(s.n_claims)}</strong> propos consignés · <strong>${fmtNum(s.n_posts)}</strong> publications collectées · ${span}
    </p>
    ${depth}

    ${d.dossier?.summary
      ? `<section style="margin-top:var(--s6)">
          <p class="section-label">Synthèse</p>
          <p class="prose">${escapeHtml(d.dossier.summary)}</p>
          <p class="stamp" style="margin-top:var(--s2)">produite par ${escapeHtml(d.dossier.model || "—")}, à relire</p>
         </section>`
      : ""}

    ${d.contradictions.length
      ? `<section style="margin-top:var(--s6)">
          <p class="section-label">Rapprochements la concernant</p>
          <div class="verdicts">${d.contradictions.map((e) => `
            <article class="verdict">
              <div class="verdict__head">
                <span class="verdict__type">${escapeHtml(e.type_label)}</span>
                <span class="stamp">score ${e.score}</span>
                <span class="status status--${e.status === "confirmed" ? "ok" : e.status === "rejected" ? "alert" : "pending"}">${
                  e.status === "confirmed" ? "confirmé" : e.status === "rejected" ? "écarté" : "à relire"}</span>
              </div>
              ${e.rationale ? `<p class="rationale" style="border-top:none;padding-top:0">${escapeHtml(e.rationale)}</p>` : ""}
            </article>`).join("")}</div>
         </section>`
      : ""}

    <section style="margin-top:var(--s6)">
      <p class="section-label">Chronologie des propos</p>
      ${themeFilters(s.by_theme)}
      ${d.timeline.length
        ? d.timeline.map((m) => `
            <h2 style="font-size:var(--t-title);margin:var(--s6) 0 var(--s2)">${monthLabel(m.month)}</h2>
            <div class="register">${m.claims.map(claimRow).join("")}</div>`).join("")
        : `<p class="state"><span class="state__title">Aucun propos consigné</span>
           <span class="state__hint">Rien n’a encore été extrait pour cette figure. La collecte a peut-être échoué
           (compte renommé, homonyme) — voir la santé des collecteurs.</span></p>`}
    </section>`;

  $("#detail").querySelectorAll("[data-theme]").forEach((b) =>
    b.onclick = () => { state.theme = b.dataset.theme || null; load(state.id); });
}

async function load(id) {
  state.id = id;
  renderList();
  $("#detail").innerHTML = '<p class="state">Chargement…</p>';
  const q = state.theme ? `?theme=${encodeURIComponent(state.theme)}` : "";
  try {
    render(await fetchJSON(`/figures/${id}${q}`));
  } catch (e) {
    $("#detail").innerHTML = `<p class="state state--error">Fiche indisponible (${e.message}).</p>`;
  }
}

async function init() {
  try {
    const data = await fetchJSON("/figures");
    state.figures = data.items;
    $("#stats").innerHTML = `<strong>${fmtNum(data.total)}</strong> figures`;
    renderList();
    const first = state.figures.find((f) => f.n_claims > 0);
    if (first) load(first.id);
  } catch (e) {
    $("#figList").innerHTML = `<p class="state state--error">Répertoire indisponible (${e.message}).</p>`;
  }
}

let searchTimer;
$("#figSearch").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(renderList, 200); };
init();
