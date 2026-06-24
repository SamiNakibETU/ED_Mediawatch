// ED · MediaWatch — feed client (vanilla JS, talks to the FastAPI backend).
const API = "";  // même origine : le backend FastAPI sert ce front

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

function affiliation(p) {
  const g = GROUPS[p.group_code] || GROUPS.ALL;
  let html = `<span class="text-[10px] font-medium px-1.5 py-0.5 rounded" style="color:${g.color};background:${g.color}1a">${g.label}</span>`;
  const fam = (p.famille || "").trim();
  const skip = new Set(["", g.label.toLowerCase(), "officiel", "groupe"]);
  if (fam && !skip.has(fam.toLowerCase())) {
    html += `<span class="text-[10px] px-1.5 py-0.5 rounded border border-line text-muted">${escapeHtml(fam)}</span>`;
  }
  return html;
}

function verifMark(p) {
  if (p.verif === "verifie") return `<span title="Identité vérifiée" class="text-emerald-400">✓</span>`;
  if (p.verif === "a_confirmer") return `<span title="À confirmer" class="text-amber-500/60">•</span>`;
  return "";
}

// Parti du locuteur À LA DATE du post (§5). Affiché seulement s'il diffère de
// l'étiquette de groupe / famille déjà montrée (ex. Ciotti « UDR » sur un post
// de 2025 alors que son groupe historique était LR).
function partyAtDate(it, p) {
  const v = (it.party_at_date || "").trim();
  if (!v) return "";
  const g = GROUPS[p.group_code] || GROUPS.ALL;
  const known = new Set([g.label, p.famille || "", p.group_code].map((s) => s.toLowerCase()));
  if (known.has(v.toLowerCase())) return "";
  return `<span class="text-[10px] px-1.5 py-0.5 rounded border border-line text-muted" title="Parti à la date du post">${escapeHtml(v)}</span>`;
}

function metaLine(p) {
  const bits = [];
  if (p.role) bits.push(escapeHtml(p.role));
  const loc = [p.departement, p.circo].filter(Boolean).join(" ");
  if (loc) bits.push(escapeHtml(loc));
  return bits.length ? `<div class="text-[11px] text-muted mt-0.5 truncate">${bits.join(" · ")}</div>` : "";
}

function exactDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("fr-FR", {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function engagement(it) {
  const fmt = (n) => n.toLocaleString("fr-FR");
  const parts = [];
  if (it.likes != null) parts.push(`♥ ${fmt(it.likes)}`);
  if (it.retweets != null) parts.push(`🔁 ${fmt(it.retweets)}`);
  if (it.replies != null) parts.push(`💬 ${fmt(it.replies)}`);
  return parts.length ? `<span class="text-[11px] text-muted tabular-nums">${parts.join("  ")}</span>` : "";
}

function card(it) {
  const p = it.personality;
  const chips = [];
  if (it.is_retweet) chips.push(`<span class="text-[11px] text-muted">🔁 RT</span>`);
  if (it.is_reply) chips.push(`<span class="text-[11px] text-muted">↩︎ réponse</span>`);
  if (it.theme) chips.push(`<span class="text-[10px] px-1.5 py-0.5 rounded bg-figure/15 text-figure">${escapeHtml(it.theme)}</span>`);
  if (it.archived_at || it.snapshot_url) chips.push(`<span class="text-[11px] text-emerald-400/80" title="Copie archivée (reçu)">🗎 reçu</span>`);
  const eng = engagement(it);
  if (eng) chips.push(eng);

  const media = it.media_url
    ? `<a href="${it.url}" target="_blank" rel="noopener"><img src="${it.media_url}" loading="lazy"
         class="mt-3 rounded-xl border border-line max-h-96 w-full object-cover" onerror="this.remove()" /></a>` : "";

  return `<article class="card-enter py-4 flex gap-3">
    <div class="shrink-0">${avatar(p)}</div>
    <div class="min-w-0 flex-1">
      <div class="flex items-center gap-1.5 flex-wrap text-sm">
        <span class="font-semibold text-zinc-100 truncate">${escapeHtml(p.full_name)}</span>
        ${verifMark(p)}
        ${affiliation(p)}
        ${partyAtDate(it, p)}
        ${p.handle ? `<a href="https://x.com/${p.handle}" target="_blank" rel="noopener" class="text-muted hover:underline">@${p.handle}</a>` : ""}
        <span class="text-muted">·</span>
        <a href="${it.url}" target="_blank" rel="noopener" class="text-muted hover:underline" title="${exactDate(it.published_at)}">${relTime(it.published_at)}</a>
      </div>
      ${metaLine(p)}
      <p class="mt-1.5 text-[15px] leading-relaxed text-zinc-200 whitespace-pre-wrap break-words">${linkify(it.content)}</p>
      ${media}
      <div class="mt-2 flex items-center gap-3 flex-wrap">
        ${chips.join("")}
        <div class="flex-1"></div>
        <a href="${it.url}" target="_blank" rel="noopener" class="text-[11px] text-zinc-600 hover:text-figure" title="${exactDate(it.published_at)}">source ↗</a>
      </div>
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
  if (state.search.trim()) params.set("q", state.search.trim());

  try {
    const res = await fetch(`${API}/feed?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.total = data.total;
    feedEl.insertAdjacentHTML("beforeend", data.items.map(card).join(""));
    state.offset += data.items.length;
    state.done = state.offset >= data.total || data.items.length === 0;
    if (state.done) {
      sentinel.textContent = state.total
        ? `— fin · ${state.total.toLocaleString("fr-FR")} posts —`
        : "Aucun post pour ce filtre.";
    } else {
      sentinel.textContent = "";
    }
    renderStats();
  } catch (e) {
    sentinel.innerHTML = `<span class="text-red-400">Erreur de chargement du flux (${e.message}).</span>`;
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
