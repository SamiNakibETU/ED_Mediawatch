// Presse — revue d'articles mentionnant l'extrême droite (métadonnées de veille).
const API = "";  // même origine

// Orientation éditoriale de la source (indiquée pour le lecteur).
const LEANINGS = [
  { key: null, label: "Toutes", color: "#a1a1aa" },
  { key: "far_right", label: "Extrême droite", color: "#b91c1c" },
  { key: "right", label: "Droite", color: "#b45309" },
  { key: "center", label: "Centre", color: "#6b7280" },
  { key: "left", label: "Gauche", color: "#2563eb" },
  { key: "far_left", label: "Gauche radicale", color: "#be123c" },
];
const LEAN_LABEL = Object.fromEntries(LEANINGS.map((l) => [l.key, l]));

const state = { leaning: null, statementsOnly: false, offset: 0, limit: 25, total: 0, loading: false, done: false };
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

function card(a) {
  const lean = LEAN_LABEL[a.leaning] || LEAN_LABEL[null];
  const people = (a.matched_personalities || []).slice(0, 6)
    .map((p) => `<span class="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800/70 text-zinc-300">${escapeHtml(p)}</span>`)
    .join(" ");
  const archive = a.archived_at || a.snapshot_url
    ? `<a href="${a.snapshot_url || a.url}" target="_blank" rel="noopener" class="text-[11px] text-emerald-400/80 hover:text-emerald-300" title="Copie archivée (reçu)">🗎 reçu</a>`
    : "";
  return `<article class="card-enter py-4">
    <div class="flex items-center gap-2 flex-wrap text-sm">
      <span class="font-semibold" style="color:${lean.color}">${escapeHtml(a.source_name || a.media_source_id)}</span>
      <span class="text-[10px] px-1.5 py-0.5 rounded border border-line" style="color:${lean.color}">${lean.label}</span>
      ${a.is_statement ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300" title="Contient une assertion chiffrable">chiffrable</span>` : ""}
      ${a.theme ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-figure/15 text-figure">${escapeHtml(a.theme)}</span>` : ""}
      <span class="text-muted">·</span>
      <span class="text-muted" title="${exactDate(a.published_at)}">${relTime(a.published_at)}</span>
    </div>
    <a href="${a.url}" target="_blank" rel="noopener" class="block mt-1.5 text-[16px] font-medium text-zinc-100 hover:text-figure leading-snug">${escapeHtml(a.title)}</a>
    ${a.author ? `<div class="text-[11px] text-muted mt-0.5">par ${escapeHtml(a.author)}</div>` : ""}
    ${people ? `<div class="mt-2 flex items-center gap-1 flex-wrap">${people}</div>` : ""}
    <div class="mt-2 flex items-center gap-3 text-[11px] text-zinc-600">
      <span>${a.word_count || 0} mots</span>
      ${archive}
      <div class="flex-1"></div>
      <a href="${a.url}" target="_blank" rel="noopener" class="hover:text-figure" title="${exactDate(a.published_at)}">lire ↗</a>
    </div>
  </article>`;
}

async function load(reset = false) {
  if (state.loading || (state.done && !reset)) return;
  state.loading = true;
  if (reset) { state.offset = 0; state.done = false; listEl.innerHTML = ""; }
  sentinel.textContent = "Chargement…";

  const params = new URLSearchParams({ limit: state.limit, offset: state.offset });
  if (state.leaning) params.set("leaning", state.leaning);
  if (state.statementsOnly) params.set("statements_only", "true");

  try {
    const res = await fetch(`${API}/articles?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.total = data.total;
    listEl.insertAdjacentHTML("beforeend", data.items.map(card).join(""));
    state.offset += data.items.length;
    state.done = state.offset >= data.total || data.items.length === 0;
    sentinel.textContent = state.done
      ? (state.total ? `— fin · ${state.total.toLocaleString("fr-FR")} articles —` : "Aucun article pour ce filtre.")
      : "";
    $("#stats").innerHTML = `<span class="text-zinc-300 font-medium">${state.total.toLocaleString("fr-FR")}</span> articles`;
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

$("#statementsOnly").onchange = (e) => { state.statementsOnly = e.target.checked; load(true); };
new IntersectionObserver((entries) => { if (entries[0].isIntersecting) load(); }, { rootMargin: "600px" }).observe(sentinel);

renderPills();
load(true);
