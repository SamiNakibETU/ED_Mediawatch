// Sommaire des sujets : ce dont l'extrême droite parle, et qui dit quoi.
// Helpers ($, fetchJSON, fmtNum, escapeHtml) : common.js.

const SCOPES = [
  { key: "confrontable", label: "Confrontables", conf: true },
  { key: "all", label: "Tous les sujets", conf: false },
];

const state = { conf: true, q: "", items: [] };
const TYPE_LABEL = {
  normatif: "position", factuel_quantitatif: "chiffre", factuel_qualitatif: "fait",
  predictif: "prédiction", attributif: "imputation",
};

const months = (a, b) => {
  if (!a || !b) return 0;
  return Math.max(0, Math.round((new Date(b) - new Date(a)) / (1000 * 60 * 60 * 24 * 30)));
};

const period = (s) => {
  if (!s.first_seen || !s.last_seen) return "période inconnue";
  const f = new Date(s.first_seen), l = new Date(s.last_seen);
  const fmt = (d) => d.toLocaleDateString("fr-FR", { month: "short", year: "numeric" });
  return f.getTime() === l.getTime() ? fmt(f) : `${fmt(f)} → ${fmt(l)}`;
};

function card(s) {
  const m = months(s.first_seen, s.last_seen);
  // L'étendue est le signal le plus utile : c'est elle qui dit si un revirement
  // est seulement possible. On l'affiche, on ne la cache pas dans une métrique.
  const depth = m >= 12 ? "ok" : m >= 3 ? "pending" : "alert";
  const depthText = m >= 12 ? `${m} mois de recul`
    : m >= 3 ? `${m} mois — recul court`
    : "moins de 3 mois — trop court pour un revirement";

  return `<article class="article enter" data-id="${s.id}">
    <div class="article__head">
      ${s.theme ? `<span class="tag tag--theme">${escapeHtml(s.theme)}</span>` : ""}
      <span class="tag">${s.n_speakers} ${s.n_speakers > 1 ? "locuteurs" : "locuteur"}</span>
      <span class="status status--${depth}">${depthText}</span>
      <span class="spacer"></span>
      <span class="stamp">${period(s)}</span>
    </div>
    <h3 class="article__title">${escapeHtml(s.label)}</h3>
    <div class="entry__foot">
      <span class="stamp"><b>${fmtNum(s.n_claims)}</b> propos consignés</span>
      ${s.status === "labelled" ? "" : '<span class="tag" title="Libellé provisoire, issu des mots du corpus">non nommé</span>'}
      <span class="spacer"></span>
      <span class="source-link">ouvrir ↗</span>
    </div>
  </article>`;
}

let lastFocus = null;

async function openSubject(id) {
  const reader = $("#reader");
  lastFocus = document.activeElement;
  reader.hidden = false;
  document.body.style.overflow = "hidden";
  $("#readerClose").focus();
  $("#readerTitle").textContent = "";
  $("#readerSub").textContent = "";
  $("#readerBody").innerHTML = '<p class="state">Chargement…</p>';

  try {
    const d = await fetchJSON(`/subjects/${id}`);
    const s = d.subject;
    $("#readerMeta").textContent = s.theme || "sans thème";
    $("#readerTitle").textContent = s.label;
    $("#readerSub").textContent =
      `${fmtNum(s.n_claims)} propos · ${s.n_speakers} locuteurs · ${period(s)}`;

    // Groupé par locuteur : sur un sujet, la lecture utile est « qui défend
    // quoi », et comment chacun évolue.
    const blocks = Object.entries(d.by_speaker || {})
      .sort((a, b) => b[1].length - a[1].length)
      .map(([who, claims]) => `
        <section style="margin-top:var(--s6)">
          <p class="section-label">${escapeHtml(who)} · ${claims.length} propos</p>
          <div class="register">
            ${claims.map((c) => `
              <article class="entry" style="grid-template-columns:5rem 1fr;padding:var(--s4) 0">
                <p class="stamp" style="padding-top:2px">${
                  c.published_at ? new Date(c.published_at).toLocaleDateString("fr-FR",
                    { day: "numeric", month: "short", year: "2-digit" }) : "—"}</p>
                <div>
                  ${c.qty_value != null
                    ? `<p class="claim__value">${c.qty_value}${c.qty_unit ? " " + escapeHtml(c.qty_unit) : ""}</p>` : ""}
                  <p class="prose" style="margin-top:0">${escapeHtml(c.text || "")}</p>
                  <div class="entry__foot">
                    <span class="tag">${TYPE_LABEL[c.claim_type] || escapeHtml(c.claim_type || "")}</span>
                    <span class="spacer"></span>
                    ${c.source_url
                      ? `<a class="source-link" href="${c.source_url}" target="_blank" rel="noopener">source ↗</a>`
                      : '<span class="stamp">source non résolue</span>'}
                  </div>
                </div>
              </article>`).join("")}
          </div>
        </section>`).join("");

    $("#readerBody").innerHTML = blocks || '<p class="state">Aucun propos rattaché.</p>';
  } catch (e) {
    $("#readerBody").innerHTML =
      `<p class="state state--error">Le sujet n’a pas pu être chargé (${e.message}).</p>`;
  }
}

function closeReader() {
  $("#reader").hidden = true;
  document.body.style.overflow = "";
  lastFocus?.focus();
}

async function load() {
  const sentinel = $("#sentinel");
  sentinel.className = "state";
  sentinel.textContent = "Chargement…";
  const params = new URLSearchParams({ limit: 120 });
  if (state.conf) params.set("confrontable", "true");
  if (state.q.trim()) params.set("q", state.q.trim());

  try {
    const data = await fetchJSON(`/subjects?${params}`);
    state.items = data.items || [];
    $("#list").innerHTML = state.items.length
      ? `<div class="register">${state.items.map(card).join("")}</div>` : "";
    $("#stats").innerHTML = `<strong>${fmtNum(data.total ?? state.items.length)}</strong> sujets`;
    sentinel.innerHTML = state.items.length
      ? `fin du sommaire · ${fmtNum(state.items.length)} sujets affichés`
      : `<span class="state__title">Aucun sujet</span><span class="state__hint">${
          state.conf
            ? "Aucun sujet ne réunit encore plusieurs locuteurs. Lance le regroupement, ou affiche tous les sujets."
            : "Le regroupement n’a pas encore tourné — voir l’entonnoir du pipeline."
        }</span>`;
  } catch (e) {
    sentinel.className = "state state--error";
    sentinel.textContent = `Les sujets n’ont pas pu être chargés (${e.message}).`;
  }
}

function renderFilters() {
  $("#scopeFilters").innerHTML = SCOPES.map((s) =>
    `<button class="filter" data-conf="${s.conf}" aria-pressed="${state.conf === s.conf}">${s.label}</button>`).join("");
  document.querySelectorAll("#scopeFilters .filter").forEach((b) =>
    b.onclick = () => { state.conf = b.dataset.conf === "true"; renderFilters(); load(); });
}

$("#list").addEventListener("click", (e) => {
  const art = e.target.closest("article[data-id]");
  if (art) openSubject(art.dataset.id);
});
$("#readerClose").onclick = closeReader;
$("#readerBackdrop").onclick = closeReader;
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#reader").hidden) closeReader();
});

let timer;
$("#subjSearch").oninput = (e) => {
  clearTimeout(timer); state.q = e.target.value;
  timer = setTimeout(load, 250);
};

renderFilters();
load();
