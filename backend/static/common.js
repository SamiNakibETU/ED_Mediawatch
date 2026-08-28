// Socle partagé : masthead, thème, helpers, arbre thématique.
// Le masthead est monté ici et non répété dans les 4 pages : une seule source.

const API = ""; // même origine : le backend FastAPI sert ce front
const $ = (s) => document.querySelector(s);

const escapeHtml = (s) =>
  (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const fmtNum = (n) => (n ?? 0).toLocaleString("fr-FR");

// SQLite rend les horodatages sans fuseau, Postgres avec. `new Date("…T09:56:53")`
// les lit alors comme de l'heure LOCALE : deux heures d'écart affichées en
// production française, sur les seuls écrans où l'heure compte.
// Le séparateur espace de Postgres (« 2026-08-28 13:18:31+00:00 ») est hors
// norme ECMAScript : V8 l'accepte, d'autres moteurs rendent Invalid Date.
const asDate = (iso) => {
  const t = String(iso).replace(" ", "T");
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(t) ? t : `${t}Z`);
};

// Le département est parfois déjà contenu dans le libellé de circonscription
// (« Alpes-Maritimes - 1re circonscription ») : les concaténer produisait
// « Alpes-Maritimes Alpes-Maritimes - 1re circonscription ».
function mandat(departement, circo) {
  if (circo && departement && circo.toLowerCase().includes(departement.toLowerCase())) {
    return circo;
  }
  return [departement, circo].filter(Boolean).join(" ");
}

// Les thèmes du niveau L0 sont stockés en identifiants sans accent
// (`culture_identite`). Affichés bruts, ils donnent au relevé l'air d'un export
// de base — et « politique » y côtoie « pouvoir_achat » sans qu'on sache lequel
// est un mot et lequel est un code.
const THEMES = {
  immigration: "immigration", securite: "sécurité", economie: "économie",
  pouvoir_achat: "pouvoir d’achat", energie: "énergie",
  international: "international", logement: "logement", social: "social",
  sante: "santé", institutions: "institutions", ecologie: "écologie",
  education: "éducation", agriculture: "agriculture",
  culture_identite: "culture et identité", justice: "justice",
  politique: "politique", autre: "autre",
};
const themeLabel = (t) => THEMES[t] || String(t || "").replace(/_/g, " ");

// Six familles, pas quinze couleurs. Un arc-en-ciel de quinze teintes ne se
// mémorise pas et ne dit rien ; six familles disent quelque chose de vrai —
// on voit au premier coup d'œil qu'un locuteur ne parle que de sécurité.
const THEME_FAMILY = {
  economie: "eco", pouvoir_achat: "eco",
  immigration: "secu", securite: "secu", justice: "secu",
  international: "intl",
  social: "social", sante: "social", logement: "social", education: "social",
  ecologie: "envt", energie: "envt", agriculture: "envt",
  institutions: "inst", culture_identite: "inst", politique: "inst",
};
const themeVar = (t) => `var(--th-${THEME_FAMILY[t] || "eco"})`;

// Surtitre : la famille colorée, puis le libellé du thème.
const kicker = (theme, extra = "") =>
  `<p class="kicker" style="--th:${themeVar(theme)}">${escapeHtml(themeLabel(theme) || "sans thème")}${
    extra ? `<span class="kicker__sep">${extra}</span>` : ""}</p>`;

// Durée en clair. « 638 j » demande un calcul mental ; « 21 mois » se lit.
function duree(days) {
  const d = Math.max(0, Math.round(days || 0));
  if (d < 45) return `${d} jour${d > 1 ? "s" : ""}`;
  const m = Math.round(d / 30.4);
  return m < 24 ? `${m} mois` : `${(d / 365).toFixed(1).replace(".", ",")} ans`;
}

const periode = (a, b) => {
  if (!a || !b) return "période inconnue";
  const f = (x) => asDate(x).toLocaleDateString("fr-FR", { month: "short", year: "numeric" });
  return f(a) === f(b) ? f(a) : `${f(a)} – ${f(b)}`;
};

// « de économie » ne se dit pas. Élision devant voyelle et h muet.
const de = (mot) => (/^[aeiouyéèêàâîïôûù]|^h/i.test(mot) ? `d’${mot}` : `de ${mot}`);

function relTime(iso) {
  if (!iso) return "";
  const d = asDate(iso), s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "à l'instant";
  if (s < 3600) return `il y a ${Math.max(1, Math.floor(s / 60))} min`;
  if (s < 86400) return `il y a ${Math.floor(s / 3600)} h`;
  if (s < 604800) return `il y a ${Math.floor(s / 86400)} j`;
  return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
}

const exactDate = (iso) =>
  iso ? asDate(iso).toLocaleString("fr-FR", {
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

// L'ordre dit ce qu'est le produit. Le sujet vient d'abord : on arrive avec un
// objet en tête (« les retraites »), pas avec l'envie de lire un compte. Le fil
// X et la presse sont le FONDS — la matière première, rangée sous « Archive »,
// consultable mais pas la vitrine.
const PAGES = [
  ["index.html", "accueil", "L’observatoire"],
  ["sujets.html", "sujets", "Sujets"],
  ["figure.html", "figures", "Locuteurs"],
  ["compteur.html", "compteur", "Chiffres"],
  ["archive.html", "archive", "Archive"],
  ["contradictions.html", "validation", "Validation"],
  ["atelier.html", "atelier", "Atelier"],
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
    <div class="spacer"></div>
    <p class="masthead__meta" id="stats"></p>
    <button class="theme-toggle" id="themeToggle" aria-label="Basculer le thème"></button>
  </div>
  <div class="masthead__nav"><nav class="nav" aria-label="Sections">${nav}</nav></div>`;

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

// Une colonne qui n'affiche que « Aucun thème classé » occupe un sixième de
// l'écran pour ne rien dire. Tant que la classification n'a rien produit, le
// rail s'efface et la lecture prend toute la largeur.
function dropRail(container) {
  container.closest(".rail")?.setAttribute("hidden", "");
  document.querySelector(".layout")?.classList.add("layout--norail");
}

async function themeTree(container, { source, onSelect }) {
  const countOf = (n) => (source === "articles" ? n.articles : n.posts) || 0;
  let themes = [];
  try {
    const data = await fetchJSON("/themes/tree");
    themes = (data.themes || []).filter((t) => countOf(t) > 0).sort((a, b) => countOf(b) - countOf(a));
  } catch {
    dropRail(container);
    return;
  }
  if (!themes.length) {
    dropRail(container);
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
