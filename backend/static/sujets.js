// Sommaire des sujets, puis confrontation des propos à l'intérieur d'un sujet.
// Helpers ($, fetchJSON, fmtNum, escapeHtml, exactDate) : common.js.

const state = { q: "", theme: null, confrontable: true, open: null };

const fmtDate = (iso) =>
  iso ? new Date(iso).toLocaleDateString("fr-FR", { month: "short", year: "numeric" }) : "—";

const span = (d) =>
  d >= 365 ? `${(d / 365).toFixed(1).replace(".0", "")} ans`
  : d >= 30 ? `${Math.round(d / 30)} mois`
  : `${d} j`;

function subjectRow(s) {
  // Un sujet trop court ne peut rien révéler : le dire, plutôt que laisser
  // croire que l'absence de contradiction est un résultat.
  const thin = s.span_days < 30 || s.n_speakers < 2;
  return `<article class="article enter" data-id="${s.id}">
    <div class="article__head">
      ${s.theme ? `<span class="tag tag--theme">${escapeHtml(s.theme)}</span>` : ""}
      ${!s.named ? '<span class="tag" title="Regroupement non encore nommé">libellé provisoire</span>' : ""}
      <span class="spacer"></span>
      <span class="stamp">${fmtDate(s.first_seen)} → ${fmtDate(s.last_seen)}</span>
    </div>
    <h3 class="article__title">${escapeHtml(s.label)}</h3>
    <div class="entry__foot">
      <span class="metrics">
        <span><b>${s.n_speakers}</b> ${s.n_speakers > 1 ? "locuteurs" : "locuteur"}</span>
        <span><b>${fmtNum(s.n_claims)}</b> propos</span>
        <span><b>${span(s.span_days)}</b> couverts</span>
      </span>
      ${thin ? '<span class="tag" title="Trop court ou trop peu de voix pour révéler une évolution">peu exploitable</span>' : ""}
      <span class="spacer"></span>
      <span class="source-link">ouvrir ↓</span>
    </div>
    <div class="subject-detail" id="detail-${s.id}" hidden></div>
  </article>`;
}

function claimLine(c) {
  const date = c.published_at
    ? new Date(c.published_at).toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "2-digit" })
    : "—";
  const value = c.qty_value != null ? `${c.qty_value}${c.qty_unit ? " " + c.qty_unit : ""}` : "";
  return `<li>
    <span class="stamp">${date}</span>
    ${value ? `<span class="claim__value" style="font-size:var(--t-ui)">${escapeHtml(value)}</span>` : ""}
    <span>${escapeHtml(c.text || "")}</span>
    ${c.source_url ? `<a class="source-link" href="${c.source_url}" target="_blank" rel="noopener">source ↗</a>`
      : '<span class="stamp">source non résolue</span>'}
  </li>`;
}

async function openSubject(id, host) {
  host.hidden = false;
  host.innerHTML = '<p class="state">Chargement…</p>';
  let d;
  try {
    d = await fetchJSON(`/subjects/${id}`);
  } catch (e) {
    host.innerHTML = `<p class="state state--error">Sujet indisponible (${e.message}).</p>`;
    return;
  }

  // Colonne par locuteur : la lecture utile sur un sujet est « qui défend quoi ».
  const columns = d.speakers.map((sp) => `
    <div class="speaker-col">
      <p class="speaker">${escapeHtml(sp.name)}<span class="count"> ${sp.n}</span></p>
      <ul class="claim-list">${sp.claims.map(claimLine).join("")}</ul>
    </div>`).join("");

  host.innerHTML = `
    ${d.contradictions.length ? `
      <div class="verdicts" style="margin-bottom:var(--s5)">
        ${d.contradictions.map((e) => `
          <article class="verdict">
            <div class="verdict__head">
              <span class="verdict__type">${escapeHtml(e.type_label)}</span>
              <span class="stamp">score ${e.score}</span>
              <span class="tag">${e.detection_method === "llm_judge" ? "juge" : "calculé"}</span>
              <span class="status status--${e.status === "confirmed" ? "ok" : e.status === "rejected" ? "alert" : "pending"}">${
                e.status === "confirmed" ? "confirmé" : e.status === "rejected" ? "écarté" : "à relire"}</span>
            </div>
            ${e.rationale ? `<p class="rationale" style="border-top:none;padding-top:0">${escapeHtml(e.rationale)}</p>` : ""}
          </article>`).join("")}
      </div>` : ""}
    <div class="speakers">${columns}</div>
    ${d.subject.entities.length
      ? `<p class="stamp" style="margin-top:var(--s4)">termes : ${d.subject.entities.slice(0, 12).map(escapeHtml).join(" · ")}</p>`
      : ""}`;
}

async function load() {
  const params = new URLSearchParams({ limit: 60 });
  if (state.q.trim()) params.set("q", state.q.trim());
  if (state.theme) params.set("theme", state.theme);
  if (state.confrontable) params.set("confrontable", "true");

  try {
    const d = await fetchJSON(`/subjects?${params}`);
    $("#stats").innerHTML = `<strong>${fmtNum(d.total)}</strong> sujets`;
    renderThemes(d.themes);
    if (!d.items.length) {
      $("#list").innerHTML = "";
      $("#empty").hidden = false;
      $("#empty").className = "state";
      $("#empty").innerHTML = `<span class="state__title">Aucun sujet</span>
        <span class="state__hint">Aucun objet de débat ne correspond. Décoche « plusieurs voix »
        ou lance une passe d’analyse pour en constituer.</span>`;
      return;
    }
    $("#empty").hidden = true;
    $("#list").className = "register";
    $("#list").innerHTML = d.items.map(subjectRow).join("");
  } catch (e) {
    $("#list").innerHTML = "";
    $("#empty").hidden = false;
    $("#empty").className = "state state--error";
    $("#empty").textContent = `Les sujets n’ont pas pu être chargés (${e.message}).`;
  }
}

function renderThemes(themes) {
  const entries = Object.entries(themes || {}).slice(0, 8);
  $("#themeFilters").innerHTML =
    `<button class="filter" data-t="" aria-pressed="${!state.theme}">Tous</button>` +
    entries.map(([t, n]) =>
      `<button class="filter" data-t="${escapeHtml(t)}" aria-pressed="${state.theme === t}">${escapeHtml(t)}<span class="count">${n}</span></button>`).join("");
  document.querySelectorAll("#themeFilters .filter").forEach((b) =>
    b.onclick = () => { state.theme = b.dataset.t || null; load(); });
}

$("#list").addEventListener("click", (e) => {
  const art = e.target.closest("article[data-id]");
  if (!art) return;
  const id = art.dataset.id;
  const host = $(`#detail-${id}`);
  if (!host.hidden) { host.hidden = true; return; }   // repli
  openSubject(id, host);
});

$("#onlyConfrontable").onchange = (e) => { state.confrontable = e.target.checked; load(); };
let timer;
$("#search").oninput = (e) => {
  clearTimeout(timer); state.q = e.target.value;
  timer = setTimeout(load, 220);
};

load();
