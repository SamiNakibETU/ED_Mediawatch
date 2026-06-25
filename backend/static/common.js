// common.js — socle partagé des deux surfaces (vanilla JS, chargé avant app/presse).
// Factorise ce qui était dupliqué (escapeHtml, dates, infinite-scroll, pills) et
// fournit le composant d'arbre thématique branché sur /themes/tree.
const API = ""; // même origine : le backend FastAPI sert ce front

const $ = (s) => document.querySelector(s);

function escapeHtml(s) {
  return (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

const fmtNum = (n) => (n ?? 0).toLocaleString("fr-FR");

function relTime(iso) {
  if (!iso) return "";
  const d = new Date(iso), s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "à l'instant";
  if (s < 3600) return `il y a ${Math.max(1, Math.floor(s / 60))} min`;
  if (s < 86400) return `il y a ${Math.floor(s / 3600)} h`;
  if (s < 604800) return `il y a ${Math.floor(s / 86400)} j`;
  return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
}

function exactDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("fr-FR", {
    day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

async function fetchJSON(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// Déclenche loadMore() quand le sentinel approche du viewport.
function infiniteScroll(sentinelEl, loadMore) {
  new IntersectionObserver(
    (entries) => { if (entries[0].isIntersecting) loadMore(); },
    { rootMargin: "600px" }
  ).observe(sentinelEl);
}

// Arbre de navigation Thème → Sous-thème, avec compteurs par source.
//   container : élément hôte
//   source    : "posts" | "articles" (compteur affiché)
//   onSelect  : ({ theme, subtheme }) => void  (null/null = tous)
async function themeTree(container, { source, onSelect }) {
  const countOf = (n) => (source === "articles" ? n.articles : n.posts) || 0;
  let themes = [];
  try {
    const data = await fetchJSON("/themes/tree");
    themes = (data.themes || []).filter((t) => countOf(t) > 0).sort((a, b) => countOf(b) - countOf(a));
  } catch {
    container.innerHTML = '<div class="text-[11px] text-red-400 px-2 py-1">Arbre thématique indisponible.</div>';
    return;
  }
  if (!themes.length) {
    container.innerHTML = '<div class="text-[11px] text-zinc-600 px-2 py-1">Aucun thème classé pour l’instant.</div>';
    return;
  }

  let active = { theme: null, subtheme: null };

  function render() {
    const allOn = !active.theme;
    const head = `<button data-all class="w-full text-left px-2 py-1.5 rounded-md text-sm ${
      allOn ? "bg-figure/15 text-figure" : "text-muted hover:text-zinc-100"
    }">Tous les thèmes</button>`;

    const body = themes.map((t) => {
      const on = active.theme === t.id;
      const subs = (t.subthemes || []).filter((s) => (source === "articles" ? s.articles : s.posts) > 0);
      const subList = on && subs.length
        ? `<div class="ml-2 border-l border-line pl-2 mt-0.5 space-y-0.5">` + subs.map((s) => {
            const son = active.subtheme === s.id;
            const c = (source === "articles" ? s.articles : s.posts);
            return `<button data-theme="${t.id}" data-subtheme="${s.id}"
              class="w-full flex items-center gap-2 px-2 py-1 rounded text-[13px] ${son ? "text-figure" : "text-muted hover:text-zinc-100"}">
              <span class="flex-1 text-left truncate">${escapeHtml(s.label)}</span>
              <span class="text-[10px] tabular-nums text-zinc-600">${c}</span></button>`;
          }).join("") + `</div>`
        : "";
      return `<div>
        <button data-theme="${t.id}"
          class="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm ${
            on && !active.subtheme ? "bg-figure/15 text-figure" : "text-zinc-300 hover:bg-panel"
          }">
          <span class="flex-1 text-left truncate">${escapeHtml(t.label)}</span>
          <span class="text-[10px] tabular-nums text-zinc-500">${countOf(t)}</span>
        </button>${subList}</div>`;
    }).join("");

    container.innerHTML = head + body;
    container.querySelector("[data-all]").onclick = () => {
      active = { theme: null, subtheme: null };
      render(); onSelect(active);
    };
    container.querySelectorAll("button[data-theme]").forEach((b) => {
      b.onclick = () => {
        const th = b.dataset.theme, st = b.dataset.subtheme || null;
        if (st) active = { theme: th, subtheme: st };
        else active = active.theme === th && !active.subtheme ? { theme: null, subtheme: null } : { theme: th, subtheme: null };
        render(); onSelect(active);
      };
    });
  }
  render();
}
