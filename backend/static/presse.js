// Presse — prises de parole de l'extrême droite dans la presse (métadonnées de veille).
const API = "";  // même origine

const LEANINGS = [
  { key: null, label: "Toutes", color: "#a1a1aa" },
  { key: "far_right", label: "Extrême droite", color: "#b91c1c" },
  { key: "right", label: "Droite", color: "#b45309" },
  { key: "center", label: "Centre", color: "#6b7280" },
  { key: "left", label: "Gauche", color: "#2563eb" },
  { key: "far_left", label: "Gauche radicale", color: "#be123c" },
];
const LEAN_LABEL = Object.fromEntries(LEANINGS.map((l) => [l.key, l]));

const state = { leaning: null, offset: 0, limit: 25, total: 0, loading: false, done: false };
const $ = (s) => document.querySelector(s);
const listEl = $("#list");
const sentinel = $("#sentinel");

function escapeHtml(s) {
  return (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function relTime(iso) {
  if (!iso) return "";
  const d = new Date(iso), s = (Date.now() - d.getTime()) / 1000;
  if (s < 3600) return `il y a ${Math.max(1, Math.floor(s / 60))} min`;
  if (s < 86400) return `il y a ${Math.floor(s / 3600)} h`;
  if (s < 604800) return `il y a ${Math.floor(s / 86400)} j`;
  return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
}
const exactDate = (iso) => iso
  ? new Date(iso).toLocaleString("fr-FR", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" })
  : "";

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
      <span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300">prise de parole</span>
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
    const a = await (await fetch(`${API}/articles/${id}`)).json();
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

  const params = new URLSearchParams({ limit: state.limit, offset: state.offset, nature: "prise_de_parole" });
  if (state.leaning) params.set("leaning", state.leaning);

  try {
    const res = await fetch(`${API}/articles?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.total = data.total;
    listEl.insertAdjacentHTML("beforeend", data.items.map(card).join(""));
    state.offset += data.items.length;
    state.done = state.offset >= data.total || data.items.length === 0;
    sentinel.textContent = state.done
      ? (state.total ? `— fin · ${state.total.toLocaleString("fr-FR")} prises de parole —` : "Aucune prise de parole pour ce filtre.")
      : "";
    $("#stats").innerHTML = `<span class="text-zinc-300 font-medium">${state.total.toLocaleString("fr-FR")}</span> prises de parole`;
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

listEl.addEventListener("click", (e) => {
  const art = e.target.closest("article[data-id]");
  if (art) openArticle(art.dataset.id);
});
$("#readerClose").onclick = closeReader;
$("#readerBackdrop").onclick = closeReader;
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeReader(); });
new IntersectionObserver((entries) => { if (entries[0].isIntersecting) load(); }, { rootMargin: "600px" }).observe(sentinel);

renderPills();
load(true);
