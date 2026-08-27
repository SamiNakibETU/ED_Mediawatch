// Socle partagé : masthead, thème, helpers, arbre thématique.
// Le masthead est monté ici et non répété dans les 4 pages : une seule source.

const API = ""; // même origine : le backend FastAPI sert ce front
const $ = (s) => document.querySelector(s);

const escapeHtml = (s) =>
  (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

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

const exactDate = (iso) =>
  iso ? new Date(iso).toLocaleString("fr-FR", {
    day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit",
  }) : "";

async function fetchJSON(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function infiniteScroll(sentinelEl, loadMore) {
  new IntersectionObserver((e) => { if (e[0].isIntersecting) loadMore(); }, { rootMargin: "600px" })
    .observe(sentinelEl);
}

// ── Masthead ────────────────────────────────────────────────────────────
// Une publication a un titre composé, pas un logo dans un carré dégradé.

const PAGES = [
  ["index.html", "feed", "Réseaux sociaux"],
  ["figure.html", "figures", "Figures"],
  ["presse.html", "presse", "Presse"],
  ["compteur.html", "compteur", "Le Compteur"],
  ["contradictions.html", "validation", "Validation"],
];

function mountMasthead() {
  const host = $("#masthead");
  if (!host) return;
  const current = document.body.dataset.page;
  const nav = PAGES.map(([href, key, label]) =>
    `<a href="${href}"${key === current ? ' aria-current="page"' : ""}>${label}</a>`).join("");

  host.className = "masthead";
  host.innerHTML = `<div class="masthead__inner">
    <a class="wordmark" href="index.html">ED <span>Mediawatch</span></a>
    <p class="masthead__tagline">${escapeHtml(document.body.dataset.tagline || "")}</p>
    <nav class="nav" aria-label="Sections">${nav}</nav>
    <div class="spacer"></div>
    <p class="masthead__meta" id="stats"></p>
    <button class="theme-toggle" id="themeToggle" aria-label="Basculer le thème"></button>
  </div>`;

  const toggle = $("#themeToggle");
  const label = () => { toggle.textContent = document.documentElement.dataset.theme === "dark" ? "clair" : "sombre"; };
  toggle.onclick = () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme", next);
    label();
  };
  label();
}

// ── Arbre thématique (Thème → Sous-thème) ───────────────────────────────

async function themeTree(container, { source, onSelect }) {
  const countOf = (n) => (source === "articles" ? n.articles : n.posts) || 0;
  let themes = [];
  try {
    const data = await fetchJSON("/themes/tree");
    themes = (data.themes || []).filter((t) => countOf(t) > 0).sort((a, b) => countOf(b) - countOf(a));
  } catch {
    container.innerHTML = '<p class="state state--error">Arbre thématique indisponible.</p>';
    return;
  }
  if (!themes.length) {
    container.innerHTML = '<p class="state">Aucun thème classé.</p>';
    return;
  }

  let active = { theme: null, subtheme: null };

  const row = (id, sub, label, count, on) =>
    `<button data-theme="${id}"${sub ? ` data-subtheme="${sub}"` : ""} aria-pressed="${on}">
      <span class="label">${escapeHtml(label)}</span><span class="count">${count}</span></button>`;

  function render() {
    container.innerHTML =
      `<button data-all aria-pressed="${!active.theme}"><span class="label">Tous les thèmes</span></button>` +
      themes.map((t) => {
        const on = active.theme === t.id;
        const subs = on ? (t.subthemes || []).filter((s) => countOf(s) > 0) : [];
        const list = subs.length
          ? `<div class="sub">${subs.map((s) => row(t.id, s.id, s.label, countOf(s), active.subtheme === s.id)).join("")}</div>`
          : "";
        return row(t.id, null, t.label, countOf(t), on && !active.subtheme) + list;
      }).join("");

    container.querySelector("[data-all]").onclick = () => {
      active = { theme: null, subtheme: null };
      render(); onSelect(active);
    };
    container.querySelectorAll("button[data-theme]").forEach((b) => {
      b.onclick = () => {
        const th = b.dataset.theme, st = b.dataset.subtheme || null;
        active = st ? { theme: th, subtheme: st }
          : (active.theme === th && !active.subtheme ? { theme: null, subtheme: null } : { theme: th, subtheme: null });
        render(); onSelect(active);
      };
    });
  }
  render();
}

mountMasthead();
