// Presse — prises de parole de l'extrême droite dans la presse. Utilitaires : common.js.
const LEANINGS = [
  { key: null, label: "Toutes", color: "#a1a1aa" },
  { key: "far_right", label: "Extrême droite", color: "#b91c1c" },
  { key: "right", label: "Droite", color: "#b45309" },
  { key: "center", label: "Centre", color: "#6b7280" },
  { key: "left", label: "Gauche", color: "#2563eb" },
  { key: "far_left", label: "Gauche radicale", color: "#be123c" },
];
const LEAN_LABEL = Object.fromEntries(LEANINGS.map((l) => [l.key, l]));

// nature : "prise_de_parole" (défaut), "mention", ou null (toutes).
const NATURES = [
  { key: "prise_de_parole", label: "Prises de parole" },
  { key: "mention", label: "Mentions" },
  { key: null, label: "Toutes" },
];
const state = { leaning: null, nature: "prise_de_parole", theme: null, subtheme: null, offset: 0, limit: 25, total: 0, loading: false, done: false };
const listEl = $("#list");
const sentinel = $("#sentinel");

function peopleChips(list, max = 8) {
  return (list || []).slice(0, max)
    .map((p) => `<span class="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800/70 text-zinc-300">${escapeHtml(p)}</span>`)
    .join(" ");
}

function card(a) {
  const lean = LEAN_LABEL[a.leaning] || LEAN_LABEL[null];
  const truncated = (a.word_count || 0) < 80;
  return `<article data-id="${a.id}" class="card-enter py-4 cursor-pointer group">
    <div class="flex items-center gap-2 flex-wrap text-sm">
      <span class="font-semibold" style="color:${lean.color}">${escapeHtml(a.source_name || a.media_source_id)}</span>
      <span class="text-[10px] px-1.5 py-0.5 rounded border border-line" style="color:${lean.color}">${lean.label}</span>
      ${a.nature === "mention"
        ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-zinc-700/40 text-zinc-400" title="Le RN est couvert/nommé, sans parole directe">mention</span>`
        : `<span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300" title="Une figure ED s'exprime directement">prise de parole</span>`}
      ${a.theme ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-figure/15 text-figure">${escapeHtml(a.theme)}</span>` : ""}
      <span class="text-muted">·</span>
      <span class="text-muted" title="${exactDate(a.published_at)}">${relTime(a.published_at)}</span>
    </div>
    <h3 class="mt-1.5 text-[16px] font-medium text-zinc-100 group-hover:text-figure leading-snug">${escapeHtml(a.title)}</h3>
    ${a.author ? `<div class="text-[11px] text-muted mt-0.5">par ${escapeHtml(a.author)}</div>` : ""}
    ${a.matched_personalities && a.matched_personalities.length ? `<div class="mt-2 flex items-center gap-1 flex-wrap">${peopleChips(a.matched_personalities)}</div>` : ""}
    <div class="mt-2 flex items-center gap-3 text-[11px] text-zinc-600">
      <span>${truncated ? "extrait" : (a.word_count || 0) + " mots"}</span>
      ${a.archived_at || a.snapshot_url ? `<span class="text-emerald-400/80">🗎 reçu</span>` : ""}
      <div class="flex-1"></div>
      <span class="text-figure/80 group-hover:text-figure">lire dans l'app →</span>
    </div>
  </article>`;
}

async function openArticle(id) {
  const reader = $("#reader");
  reader.classList.remove("hidden");
  $("#readerBody").textContent = "Chargement…";
  $("#readerTitle").textContent = "";
  $("#readerSub").innerHTML = ""; $("#readerPeople").innerHTML = ""; $("#readerFoot").innerHTML = ""; $("#readerMeta").textContent = "";
  document.body.style.overflow = "hidden";
  try {
    const a = await fetchJSON(`/articles/${id}`);
    const lean = LEAN_LABEL[a.leaning] || LEAN_LABEL[null];
    $("#readerMeta").innerHTML = `<span style="color:${lean.color}" class="font-medium">${escapeHtml(a.source_name || a.media_source_id)}</span> · ${lean.label}`;
    $("#readerTitle").textContent = a.title;
    $("#readerSub").innerHTML = [
      a.author ? `par ${escapeHtml(a.author)}` : "",
      exactDate(a.published_at),
      `${a.word_count || 0} mots`,
    ].filter(Boolean).map((x) => `<span>${x}</span>`).join('<span class="text-zinc-700">·</span>');
    $("#readerPeople").innerHTML = peopleChips(a.matched_personalities, 12);
    $("#readerBody").textContent = a.content || "(texte non disponible — voir la source)";
    $("#readerFoot").innerHTML = `
      <a href="${a.url}" target="_blank" rel="noopener" class="px-3 py-1.5 rounded-lg bg-figure/20 text-figure hover:bg-figure/30">Article original ↗</a>
      ${a.snapshot_url ? `<a href="${a.snapshot_url}" target="_blank" rel="noopener" class="px-3 py-1.5 rounded-lg bg-emerald-600/15 text-emerald-300 hover:bg-emerald-600/25">Copie archivée 🗎</a>` : ""}`;
  } catch (e) {
    $("#readerBody").textContent = "Erreur de chargement de l'article.";
  }
}

function closeReader() {
  $("#reader").classList.add("hidden");
  document.body.style.overflow = "";
}

async function load(reset = false) {
  if (state.loading || (state.done && !reset)) return;
  state.loading = true;
  if (reset) { state.offset = 0; state.done = false; listEl.innerHTML = ""; }
  sentinel.textContent = "Chargement…";

  const params = new URLSearchParams({ limit: state.limit, offset: state.offset });
  if (state.nature) params.set("nature", state.nature);
  if (state.leaning) params.set("leaning", state.leaning);
  if (state.theme) params.set("theme", state.theme);
  if (state.subtheme) params.set("subtheme", state.subtheme);

  const noun = state.nature === "mention" ? "mentions"
    : state.nature === "prise_de_parole" ? "prises de parole" : "articles";
  try {
    const data = await fetchJSON(`/articles?${params}`);
    state.total = data.total;
    listEl.insertAdjacentHTML("beforeend", data.items.map(card).join(""));
    state.offset += data.items.length;
    state.done = state.offset >= data.total || data.items.length === 0;
    sentinel.textContent = state.done
      ? (state.total ? `— fin · ${fmtNum(state.total)} ${noun} —` : `Aucun résultat pour ce filtre.`)
      : "";
    $("#stats").innerHTML = `<span class="text-zinc-300 font-medium">${fmtNum(state.total)}</span> ${noun}`;
  } catch (e) {
    sentinel.innerHTML = `<span class="text-red-400">Erreur de chargement (${e.message}).</span>`;
  } finally {
    state.loading = false;
  }
}

function renderPills() {
  $("#leaningPills").innerHTML = LEANINGS.map((l) => {
    const active = state.leaning === l.key;
    return `<button data-k="${l.key ?? ''}" class="text-xs px-2.5 py-1 rounded-full border"
      style="${active ? `background:${l.color}1a;border-color:${l.color}66;color:${l.color}` : "border-color:#26262b;color:#8a8a93"}">${l.label}</button>`;
  }).join("");
  document.querySelectorAll("#leaningPills button").forEach((b) =>
    b.onclick = () => { state.leaning = b.dataset.k || null; renderPills(); load(true); });
}

function renderNaturePills() {
  $("#naturePills").innerHTML = NATURES.map((n) => {
    const active = state.nature === n.key;
    return `<button data-k="${n.key ?? ''}" class="text-[11px] px-2 py-1 rounded-md border ${
      active ? "border-figure/60 bg-figure/15 text-figure" : "border-line text-muted hover:text-zinc-100"
    }">${n.label}</button>`;
  }).join("");
  document.querySelectorAll("#naturePills button").forEach((b) =>
    b.onclick = () => { state.nature = b.dataset.k || null; renderNaturePills(); load(true); });
}

listEl.addEventListener("click", (e) => {
  const art = e.target.closest("article[data-id]");
  if (art) openArticle(art.dataset.id);
});
$("#readerClose").onclick = closeReader;
$("#readerBackdrop").onclick = closeReader;
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeReader(); });

infiniteScroll(sentinel, () => load());
themeTree($("#themeTree"), {
  source: "articles",
  onSelect: ({ theme, subtheme }) => { state.theme = theme; state.subtheme = subtheme; load(true); },
});
renderPills();
renderNaturePills();
load(true);
