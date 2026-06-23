// ED · MediaWatch — feed client (vanilla JS, talks to the FastAPI backend).
const API = (location.hostname === "localhost" || location.hostname === "127.0.0.1")
  ? "http://127.0.0.1:8000"
  : `${location.protocol}//${location.hostname}:8000`;

const GROUPS = {
  ALL: { label: "Tous", color: "#a1a1aa" },
  RN: { label: "RN", color: "#2563eb" },
  UDR: { label: "UDR", color: "#b45309" },
  FIGURE: { label: "Figures", color: "#7c3aed" },
};

const state = { group: "ALL", hideRT: false, search: "", offset: 0, limit: 25, total: 0, loading: false, done: false };

const $ = (s) => document.querySelector(s);
const feedEl = $("#feed");
const sentinel = $("#sentinel");

function relTime(iso) {
  if (!iso) return "";
  const d = new Date(iso), s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "à l'instant";
  if (s < 3600) return `il y a ${Math.floor(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.floor(s / 3600)} h`;
  if (s < 604800) return `il y a ${Math.floor(s / 86400)} j`;
  return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
}

function avatar(p) {
  const color = GROUPS[p.group_code]?.color || "#52525b";
  const initials = p.full_name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  const src = p.photo_url || (p.handle ? `https://unavatar.io/x/${p.handle}?fallback=false` : "");
  if (src) {
    return `<img src="${src}" alt="" loading="lazy"
      class="h-11 w-11 rounded-full object-cover bg-panel ring-1 ring-line"
      onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'h-11 w-11 rounded-full grid place-items-center text-sm font-semibold text-white',style:'background:${color}',textContent:'${initials}'}))" />`;
  }
  return `<div class="h-11 w-11 rounded-full grid place-items-center text-sm font-semibold text-white" style="background:${color}">${initials}</div>`;
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function linkify(s) {
  return escapeHtml(s)
    .replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" rel="noopener" class="text-rn hover:underline">$1</a>')
    .replace(/(^|\s)@(\w{1,15})/g, '$1<span class="text-figure">@$2</span>')
    .replace(/(^|\s)#(\w+)/g, '$1<span class="text-zinc-400">#$2</span>');
}

function badge(p) {
  const g = GROUPS[p.group_code] || GROUPS.ALL;
  return `<span class="text-[10px] font-medium px-1.5 py-0.5 rounded" style="color:${g.color};background:${g.color}1a">${g.label}</span>`;
}

function card(it) {
  const p = it.personality;
  const tags = [];
  if (it.is_retweet) tags.push(`<span class="text-[11px] text-muted">🔁 RT</span>`);
  if (it.is_reply) tags.push(`<span class="text-[11px] text-muted">↩︎ réponse</span>`);
  const media = it.media_url
    ? `<a href="${it.url}" target="_blank" rel="noopener"><img src="${it.media_url}" loading="lazy"
         class="mt-3 rounded-xl border border-line max-h-96 w-full object-cover" onerror="this.remove()" /></a>` : "";
  return `<article class="card-enter py-4 flex gap-3">
    <div class="shrink-0">${avatar(p)}</div>
    <div class="min-w-0 flex-1">
      <div class="flex items-center gap-1.5 flex-wrap text-sm">
        <span class="font-semibold text-zinc-100 truncate">${escapeHtml(p.full_name)}</span>
        ${badge(p)}
        ${p.handle ? `<a href="https://x.com/${p.handle}" target="_blank" rel="noopener" class="text-muted hover:underline">@${p.handle}</a>` : ""}
        <span class="text-muted">·</span>
        <a href="${it.url}" target="_blank" rel="noopener" class="text-muted hover:underline" title="${it.published_at || ""}">${relTime(it.published_at)}</a>
      </div>
      <p class="mt-1 text-[15px] leading-relaxed text-zinc-200 whitespace-pre-wrap break-words">${linkify(it.content)}</p>
      ${media}
      ${tags.length ? `<div class="mt-2 flex gap-3">${tags.join("")}</div>` : ""}
    </div>
  </article>`;
}

async function load(reset = false) {
  if (state.loading || (state.done && !reset)) return;
  state.loading = true;
  if (reset) { state.offset = 0; state.done = false; feedEl.innerHTML = ""; }
  sentinel.textContent = "Chargement…";

  const params = new URLSearchParams({
    limit: state.limit, offset: state.offset, include_retweets: (!state.hideRT).toString(),
  });
  if (state.group !== "ALL") params.set("group", state.group);

  try {
    const res = await fetch(`${API}/feed?${params}`);
    const data = await res.json();
    state.total = data.total;
    let items = data.items;
    if (state.search.trim()) {
      const q = state.search.toLowerCase();
      items = items.filter((i) =>
        i.personality.full_name.toLowerCase().includes(q) ||
        (i.personality.handle || "").toLowerCase().includes(q));
    }
    feedEl.insertAdjacentHTML("beforeend", items.map(card).join(""));
    state.offset += data.items.length;
    state.done = state.offset >= data.total || data.items.length === 0;
    sentinel.textContent = state.done ? `— fin · ${state.total} posts —` : "";
    renderStats();
  } catch (e) {
    sentinel.innerHTML = `<span class="text-red-400">Erreur API. Le backend tourne-t-il sur :8000 ?</span>`;
  } finally {
    state.loading = false;
  }
}

function renderStats() {
  $("#stats").innerHTML = `<span class="text-zinc-300 font-medium">${state.total.toLocaleString("fr-FR")}</span> posts`;
}

function renderPills() {
  $("#groupPills").innerHTML = Object.entries(GROUPS).map(([k, g]) => {
    const active = state.group === k;
    return `<button data-g="${k}" class="pill text-xs px-2.5 py-1 rounded-full border"
      style="${active ? `background:${g.color}1a;border-color:${g.color}66;color:${g.color}` : "border-color:#26262b;color:#8a8a93"}">${g.label}</button>`;
  }).join("");
  document.querySelectorAll("#groupPills button").forEach((b) =>
    b.onclick = () => { state.group = b.dataset.g; renderPills(); load(true); });
}

$("#hideRT").onchange = (e) => { state.hideRT = e.target.checked; load(true); };
let searchTimer;
$("#search").oninput = (e) => { clearTimeout(searchTimer); state.search = e.target.value; searchTimer = setTimeout(() => load(true), 250); };

new IntersectionObserver((entries) => {
  if (entries[0].isIntersecting) load();
}, { rootMargin: "600px" }).observe(sentinel);

renderPills();
load(true);
