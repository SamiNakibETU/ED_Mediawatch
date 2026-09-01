// L'archive : le fonds, deux sources sous un même toit.
//
// Le fil X et la revue de presse étaient deux pages distinctes, chacune se
// présentant comme une destination. Ce sont deux entrées du même fonds : on ne
// vient pas ici « lire X » ou « lire la presse », on vient vérifier ce qui a été
// conservé. Une seule page, un sélecteur de source — et les analyses vivent
// côté sujets.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, relTime, exactDate,
// themeLabel, infiniteScroll.

const SOURCES = [
  { key: "x", label: "En ligne (X)" },
  { key: "presse", label: "Presse" },
];

const GROUPS = {
  ALL: { label: "Toutes", color: "var(--muted)" },
  RN: { label: "RN", color: "var(--grp-rn)" },
  UDR: { label: "UDR", color: "var(--grp-udr)" },
  FIGURE: { label: "Figures", color: "var(--grp-figure)" },
};

const LEANINGS = [
  { key: null, label: "Tous les médias", color: "var(--muted)" },
  { key: "far_right", label: "Extrême droite", color: "var(--alert)" },
  { key: "right", label: "Droite", color: "var(--grp-udr)" },
  { key: "center", label: "Centre", color: "var(--muted)" },
  { key: "left", label: "Gauche", color: "var(--grp-rn)" },
  { key: "far_left", label: "Gauche radicale", color: "var(--grp-figure)" },
];
const LEAN = Object.fromEntries(LEANINGS.map((l) => [l.key, l]));

const NATURES = [
  { key: "prise_de_parole", label: "Prises de parole" },
  { key: "mention", label: "Mentions" },
  { key: null, label: "Toutes" },
];

const state = {
  source: "x",
  group: "ALL", hideRT: false,      // X
  leaning: null, nature: "prise_de_parole",   // presse
  q: "", offset: 0, limit: 25, total: 0, loading: false, done: false,
};

const listEl = $("#list");
const sentinel = $("#sentinel");

// ── Rendu : X ───────────────────────────────────────────────────────────────

function avatar(p) {
  const initials = p.full_name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  const fallback = `<div class="face face--txt">${initials}</div>`;
  const src = p.photo_url || (p.handle ? `https://unavatar.io/x/${p.handle}?fallback=false` : "");
  return src
    ? `<img class="face" src="${src}" alt="" loading="lazy" width="40" height="40"
         onerror="this.outerHTML=this.dataset.fb" data-fb='${fallback}' />`
    : fallback;
}

function linkify(s) {
  return escapeHtml(s)
    .replace(/(https?:\/\/\S+)/g, '<a class="link" href="$1" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|\s)@(\w{1,15})/g, '$1<span class="handle">@$2</span>');
}

function tags(it, p) {
  const g = GROUPS[p.group_code] || GROUPS.ALL;
  const out = [`<span class="tag tag--group" style="--grp-color:${g.color}">${g.label}</span>`];
  const fam = (p.famille || "").trim();
  if (fam && !["", g.label.toLowerCase(), "officiel", "groupe"].includes(fam.toLowerCase())) {
    out.push(`<span class="tag">${escapeHtml(fam)}</span>`);
  }
  const at = (it.party_at_date || "").trim();
  const known = [g.label, p.famille || "", p.group_code].map((s) => s.toLowerCase());
  if (at && !known.includes(at.toLowerCase())) {
    out.push(`<span class="tag" title="Parti à la date du propos">${escapeHtml(at)}</span>`);
  }
  if (p.verif === "a_confirmer") {
    out.push('<span class="tag" title="Identité non confirmée">identité à confirmer</span>');
  }
  return out.join("");
}

function metrics(it) {
  const parts = [];
  if (it.likes != null) parts.push(`<span><b>${fmtNum(it.likes)}</b> j’aime</span>`);
  if (it.retweets != null) parts.push(`<span><b>${fmtNum(it.retweets)}</b> RT</span>`);
  if (it.replies != null) parts.push(`<span><b>${fmtNum(it.replies)}</b> rép.</span>`);
  if (it.views != null) parts.push(`<span><b>${fmtNum(it.views)}</b> vues</span>`);
  return parts.length ? `<span class="metrics">${parts.join("")}</span>` : "";
}

function postRow(it) {
  const p = it.personality;
  const kind = it.is_retweet ? "retweet" : it.is_reply ? "réponse"
    : it.post_type === "quote" ? "citation" : "";
  const role = [p.role, mandat(p.departement, p.circo)].filter(Boolean);
  const foot = [
    kind ? `<span class="tag">${kind}</span>` : "",
    it.theme ? `<span class="tag tag--theme">${escapeHtml(themeLabel(it.theme))}</span>` : "",
    (it.archived_at || it.snapshot_url) ? '<span class="tag tag--receipt" title="Copie archivée">reçu</span>' : "",
    metrics(it),
  ].filter(Boolean).join("");

  return `<article class="entry enter">
    <div>${avatar(p)}</div>
    <div>
      <div class="entry__head">
        <span class="speaker">${escapeHtml(p.full_name)}</span>
        ${p.handle ? `<a class="handle" href="https://x.com/${p.handle}" target="_blank" rel="noopener">@${p.handle}</a>` : ""}
        ${tags(it, p)}
        <span class="spacer"></span>
        <a class="stamp" href="${it.url}" target="_blank" rel="noopener" title="${exactDate(it.published_at)}">${relTime(it.published_at)}</a>
      </div>
      ${role.length ? `<p class="entry__role">${role.map(escapeHtml).join(" · ")}</p>` : ""}
      <p class="prose">${linkify(it.content)}</p>
      ${it.quoted_content
        ? `<blockquote class="quoted">${escapeHtml(it.quoted_content)}${it.quoted_handle ? ` — @${escapeHtml(it.quoted_handle)}` : ""}</blockquote>` : ""}
      ${it.media_url
        ? `<a href="${it.url}" target="_blank" rel="noopener"><img class="entry__media" src="${it.media_url}" alt="" loading="lazy" onerror="this.remove()" /></a>` : ""}
      <div class="entry__foot">${foot}<span class="spacer"></span>
        <a class="source-link" href="${it.url}" target="_blank" rel="noopener">source ↗</a>
      </div>
    </div>
  </article>`;
}

// ── Rendu : presse ──────────────────────────────────────────────────────────

const people = (list, max = 8) =>
  (list || []).slice(0, max).map((p) => `<span class="tag">${escapeHtml(p)}</span>`).join("");

function articleRow(a) {
  const lean = LEAN[a.leaning] || LEAN[null];
  const nature = a.nature === "mention"
    ? '<span class="tag" title="Le parti est nommé, sans parole directe">mention</span>'
    : '<span class="tag tag--receipt" title="Une figure s’exprime directement">prise de parole</span>';

  return `<article class="article enter" data-id="${a.id}">
    <div class="article__head">
      <span class="outlet" style="color:${lean.color}">${escapeHtml(a.source_name || a.media_source_id)}</span>
      <span class="tag" style="--grp-color:${lean.color}">${lean.label}</span>
      ${nature}
      ${a.theme ? `<span class="tag tag--theme">${escapeHtml(themeLabel(a.theme))}</span>` : ""}
      <span class="spacer"></span>
      <span class="stamp" title="${exactDate(a.published_at)}">${relTime(a.published_at)}</span>
    </div>
    <h3 class="article__title">${escapeHtml(a.title)}</h3>
    ${a.author ? `<p class="article__byline">par ${escapeHtml(a.author)}</p>` : ""}
    ${a.matched_personalities?.length ? `<div class="entry__foot">${people(a.matched_personalities)}</div>` : ""}
    <div class="entry__foot">
      <span class="stamp">${(a.word_count || 0) < 80 ? "extrait seul" : `${fmtNum(a.word_count)} mots`}</span>
      ${(a.archived_at || a.snapshot_url) ? '<span class="tag tag--receipt" title="Copie archivée">reçu</span>' : ""}
      <span class="spacer"></span>
      <span class="source-link">lire ↗</span>
    </div>
  </article>`;
}

let lastFocus = null;

async function openArticle(id) {
  const reader = $("#reader");
  lastFocus = document.activeElement;
  reader.hidden = false;
  document.body.style.overflow = "hidden";
  $("#readerClose").focus();
  $("#readerBody").textContent = "Chargement…";
  for (const sel of ["#readerTitle", "#readerMeta"]) $(sel).textContent = "";
  for (const sel of ["#readerSub", "#readerPeople", "#readerFoot"]) $(sel).innerHTML = "";

  try {
    const a = await fetchJSON(`/articles/${id}`);
    const lean = LEAN[a.leaning] || LEAN[null];
    $("#readerMeta").innerHTML =
      `<span style="color:${lean.color}">${escapeHtml(a.source_name || a.media_source_id)}</span> · ${lean.label}`;
    $("#readerTitle").textContent = a.title;
    $("#readerSub").textContent = [
      a.author ? `par ${a.author}` : "", exactDate(a.published_at), `${fmtNum(a.word_count || 0)} mots`,
    ].filter(Boolean).join(" · ");
    $("#readerPeople").innerHTML = people(a.matched_personalities, 12);
    $("#readerBody").textContent = a.content || "Texte non disponible — voir la source.";
    $("#readerFoot").innerHTML =
      `<a class="btn btn--primary" href="${a.url}" target="_blank" rel="noopener">Article original ↗</a>` +
      (a.snapshot_url ? `<a class="btn" href="${a.snapshot_url}" target="_blank" rel="noopener">Copie archivée ↗</a>` : "");
  } catch (e) {
    $("#readerBody").textContent = `L’article n’a pas pu être chargé (${e.message}).`;
  }
}

function closeReader() {
  $("#reader").hidden = true;
  document.body.style.overflow = "";
  lastFocus?.focus();
}

// ── Chargement commun ───────────────────────────────────────────────────────

function params() {
  const p = new URLSearchParams({ limit: state.limit, offset: state.offset });
  if (state.source === "x") {
    p.set("include_retweets", (!state.hideRT).toString());
    if (state.group !== "ALL") p.set("group", state.group);
    if (state.q.trim()) p.set("q", state.q.trim());
  } else {
    if (state.nature) p.set("nature", state.nature);
    if (state.leaning) p.set("leaning", state.leaning);
  }
  return p;
}

const noun = () => state.source === "x"
  ? "entrées"
  : state.nature === "mention" ? "mentions"
  : state.nature === "prise_de_parole" ? "prises de parole" : "articles";

async function load(reset = false) {
  if (state.loading || (state.done && !reset)) return;
  state.loading = true;
  if (reset) { state.offset = 0; state.done = false; listEl.innerHTML = ""; }
  sentinel.className = "state";
  sentinel.textContent = "Chargement…";

  const path = state.source === "x" ? "/feed" : "/articles";
  const row = state.source === "x" ? postRow : articleRow;
  try {
    const data = await fetchJSON(`${path}?${params()}`);
    state.total = data.total;
    listEl.insertAdjacentHTML("beforeend", data.items.map(row).join(""));
    state.offset += data.items.length;
    state.done = state.offset >= data.total || !data.items.length;
    sentinel.innerHTML = state.done
      ? (state.total
        ? `fin du fonds · ${fmtNum(state.total)} ${noun()}`
        : `<span class="state__title">Rien à cet endroit du fonds</span>
           <span class="state__hint">Aucune entrée ne correspond à ce filtre. Élargis la sélection,
           ou vois où en est la collecte dans <a class="source-link" href="atelier.html">l’atelier</a>.</span>`)
      : "";
    $("#count").innerHTML = `<span class="statbar__n">${fmtNum(state.total)}</span> ${noun()}`;
    $("#stats").innerHTML = `<strong>${fmtNum(state.total)}</strong> ${noun()}`;
  } catch (e) {
    sentinel.className = "state state--error";
    sentinel.textContent = `Le fonds n’a pas pu être chargé (${e.message}).`;
  } finally {
    state.loading = false;
  }
}

// ── Filtres ─────────────────────────────────────────────────────────────────

function renderFilters() {
  $("#sourceTabs").innerHTML = SOURCES.map((s) =>
    `<button class="filter" data-src="${s.key}" aria-pressed="${state.source === s.key}">${s.label}</button>`).join("");

  if (state.source === "x") {
    $("#f1").innerHTML = Object.entries(GROUPS).map(([k, g]) =>
      `<button class="filter" data-g="${k}" aria-pressed="${state.group === k}">${g.label}</button>`).join("");
    $("#f2").innerHTML =
      `<label class="switch"><input id="hideRT" type="checkbox" ${state.hideRT ? "checked" : ""} /> Masquer les retweets</label>`;
    $("#q").placeholder = "Filtrer une personnalité (nom ou @handle)…";
    $("#q").hidden = false;
    $("#hideRT").onchange = (e) => { state.hideRT = e.target.checked; load(true); };
  } else {
    $("#f1").innerHTML = NATURES.map((n) =>
      `<button class="filter" data-n="${n.key ?? ""}" aria-pressed="${state.nature === n.key}">${n.label}</button>`).join("");
    $("#f2").innerHTML = LEANINGS.map((l) =>
      `<button class="filter" data-k="${l.key ?? ""}" aria-pressed="${state.leaning === l.key}">${l.label}</button>`).join("");
    // Le filtre plein texte n'existe pas côté presse : mieux vaut retirer la
    // commande que d'en offrir une qui ne fait rien.
    $("#q").hidden = true;
  }

  const on = (sel, fn) => document.querySelectorAll(sel).forEach((b) => (b.onclick = () => fn(b)));
  on("#sourceTabs .filter", (b) => {
    state.source = b.dataset.src; renderFilters(); load(true);
  });
  on("#f1 .filter", (b) => {
    if (state.source === "x") state.group = b.dataset.g;
    else state.nature = b.dataset.n || null;
    renderFilters(); load(true);
  });
  on("#f2 .filter", (b) => {
    state.leaning = b.dataset.k || null; renderFilters(); load(true);
  });
}

listEl.addEventListener("click", (e) => {
  const art = e.target.closest("article[data-id]");
  if (art && state.source === "presse") openArticle(art.dataset.id);
});
$("#readerClose").onclick = closeReader;
$("#readerBackdrop").onclick = closeReader;
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#reader").hidden) closeReader(); });

let timer;
$("#q").oninput = (e) => {
  clearTimeout(timer); state.q = e.target.value;
  timer = setTimeout(() => load(true), 250);
};

infiniteScroll(sentinel, () => load());
renderFilters();
load(true);
