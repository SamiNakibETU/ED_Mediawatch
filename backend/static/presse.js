// Revue de presse : articles où l'extrême droite parle ou est couverte.
// L'orientation du média est un encodage de données — toujours doublée du libellé.

const LEANINGS = [
  { key: null, label: "Tous les médias", color: "var(--muted)" },
  { key: "far_right", label: "Extrême droite", color: "var(--alert)" },
  { key: "right", label: "Droite", color: "var(--grp-udr)" },
  { key: "center", label: "Centre", color: "var(--muted)" },
  { key: "left", label: "Gauche", color: "var(--grp-rn)" },
  { key: "far_left", label: "Gauche radicale", color: "var(--grp-figure)" },
];
const LEAN = Object.fromEntries(LEANINGS.map((l) => [l.key, l]));

// nature : prise_de_parole (défaut) | mention | null (toutes)
const NATURES = [
  { key: "prise_de_parole", label: "Prises de parole" },
  { key: "mention", label: "Mentions" },
  { key: null, label: "Toutes" },
];

const state = {
  leaning: null, nature: "prise_de_parole", theme: null, subtheme: null,
  offset: 0, limit: 25, total: 0, loading: false, done: false,
};

const listEl = $("#list");
const sentinel = $("#sentinel");

const people = (list, max = 8) =>
  (list || []).slice(0, max).map((p) => `<span class="tag">${escapeHtml(p)}</span>`).join("");

function article(a) {
  const lean = LEAN[a.leaning] || LEAN[null];
  const nature = a.nature === "mention"
    ? '<span class="tag" title="Le parti est nommé, sans parole directe">mention</span>'
    : '<span class="tag tag--receipt" title="Une figure s’exprime directement">prise de parole</span>';

  return `<article class="article enter" data-id="${a.id}">
    <div class="article__head">
      <span class="outlet" style="color:${lean.color}">${escapeHtml(a.source_name || a.media_source_id)}</span>
      <span class="tag" style="--grp-color:${lean.color}">${lean.label}</span>
      ${nature}
      ${a.theme ? `<span class="tag tag--theme">${escapeHtml(a.theme)}</span>` : ""}
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

async function load(reset = false) {
  if (state.loading || (state.done && !reset)) return;
  state.loading = true;
  if (reset) { state.offset = 0; state.done = false; listEl.innerHTML = ""; }
  sentinel.className = "state";
  sentinel.textContent = "Chargement…";

  const noun = state.nature === "mention" ? "mentions"
    : state.nature === "prise_de_parole" ? "prises de parole" : "articles";
  const params = new URLSearchParams({ limit: state.limit, offset: state.offset });
  for (const [k, v] of [["nature", state.nature], ["leaning", state.leaning],
                        ["theme", state.theme], ["subtheme", state.subtheme]]) {
    if (v) params.set(k, v);
  }
  try {
    const data = await fetchJSON(`/articles?${params}`);
    state.total = data.total;
    listEl.insertAdjacentHTML("beforeend", data.items.map(article).join(""));
    state.offset += data.items.length;
    state.done = state.offset >= data.total || !data.items.length;
    sentinel.innerHTML = state.done
      ? (state.total
        ? `fin de la revue · ${fmtNum(state.total)} ${noun}`
        : `<span class="state__title">Aucun article</span><span class="state__hint">Aucun article ne correspond. Essaie « Toutes » ou un autre thème.</span>`)
      : "";
    $("#stats").innerHTML = `<strong>${fmtNum(state.total)}</strong> ${noun}`;
  } catch (e) {
    sentinel.className = "state state--error";
    sentinel.textContent = `La revue n’a pas pu être chargée (${e.message}).`;
  } finally {
    state.loading = false;
  }
}

function renderFilters() {
  $("#leaningFilters").innerHTML = LEANINGS.map((l) =>
    `<button class="filter" data-k="${l.key ?? ""}" aria-pressed="${state.leaning === l.key}">${l.label}</button>`).join("");
  $("#natureFilters").innerHTML = NATURES.map((n) =>
    `<button class="filter" data-n="${n.key ?? ""}" aria-pressed="${state.nature === n.key}">${n.label}</button>`).join("");

  document.querySelectorAll("#leaningFilters .filter").forEach((b) =>
    b.onclick = () => { state.leaning = b.dataset.k || null; renderFilters(); load(true); });
  document.querySelectorAll("#natureFilters .filter").forEach((b) =>
    b.onclick = () => { state.nature = b.dataset.n || null; renderFilters(); load(true); });
}

listEl.addEventListener("click", (e) => {
  const art = e.target.closest("article[data-id]");
  if (art) openArticle(art.dataset.id);
});
$("#readerClose").onclick = closeReader;
$("#readerBackdrop").onclick = closeReader;
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#reader").hidden) closeReader(); });

infiniteScroll(sentinel, () => load());
themeTree($("#themeTree"), {
  source: "articles",
  onSelect: ({ theme, subtheme }) => { state.theme = theme; state.subtheme = subtheme; load(true); },
});
renderFilters();
load(true);
