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


// ── Icônes ──────────────────────────────────────────────────────────────────
//
// Tracées, jamais pleines : à 16 px une icône pleine devient une tache. Elles
// DOUBLENT un libellé, ne le remplacent pas — un pictogramme seul se devine, il
// ne se lit pas, et ce produit affirme des choses vérifiables.
//
// Dessinées à la main sur une grille de 24, plutôt qu'importées : une police
// d'icônes ferait une requête réseau de plus pour une dizaine de formes.

const ICONS = {
  observatoire: '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5 10 10l-1.5 5.5L14 14z"/>',
  sujets: '<path d="M3 6h18M3 12h18M3 18h12"/>',
  locuteurs: '<path d="M16 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 20v-2a4 4 0 0 0-3-3.9"/>',
  chiffres: '<path d="M3 20V10M9 20V4M15 20v-7M21 20v-11"/>',
  archive: '<path d="M3 7h18v13H3z"/><path d="M3 7 5 3h14l2 4"/><path d="M10 12h4"/>',
  validation: '<path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="9"/>',
  atelier: '<path d="M3 17l4-4 3 3 5-6 6 7"/><circle cx="7" cy="13" r="1"/>',
  temps: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  source: '<path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6"/>',
  alerte: '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>',
  recherche: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
};

const ico = (name, cls = "") =>
  ICONS[name]
    ? `<svg class="ico ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`
    : "";

// ── Masthead ────────────────────────────────────────────────────────────
// Une publication a un titre composé, pas un logo dans un carré dégradé.

// L'ordre dit ce qu'est le produit. Le sujet vient d'abord : on arrive avec un
// objet en tête (« les retraites »), pas avec l'envie de lire un compte. Le fil
// X et la presse sont le FONDS — la matière première, rangée sous « Archive »,
// consultable mais pas la vitrine.
const PAGES = [
  ["index.html", "accueil", "L’observatoire", "observatoire"],
  ["sujets.html", "sujets", "Sujets", "sujets"],
  ["figure.html", "figures", "Locuteurs", "locuteurs"],
  ["compteur.html", "compteur", "Chiffres", "chiffres"],
  ["archive.html", "archive", "Archive", "archive"],
  ["contradictions.html", "validation", "Validation", "validation"],
  ["atelier.html", "atelier", "Atelier", "atelier"],
];


// Voyant de collecte : un observatoire doit dire s'il regarde encore. Un site
// figé depuis trois jours et un site à jour se ressemblent trait pour trait —
// et c'est précisément la différence qui compte pour qui vient vérifier.
async function liveIndicator() {
  const el = $("#live");
  if (!el) return;
  try {
    const f = await fetchJSON("/health/freshness");
    const h = Math.min(...[f.x?.age_hours, f.press?.age_hours]
      .filter((v) => typeof v === "number"));
    const stale = f.x?.stale && f.press?.stale;
    const cls = !Number.isFinite(h) ? "alert" : stale ? "warn" : "ok";
    const quand = !Number.isFinite(h) ? "aucune collecte"
      : h < 1 ? "collecte à l’instant"
      : h < 48 ? `collecte il y a ${Math.round(h)} h`
      : `collecte il y a ${Math.round(h / 24)} j`;
    el.innerHTML = `<span class="dot dot--${cls}${cls === "ok" ? " dot--live" : ""}"></span>${quand}`;
  } catch {
    el.hidden = true;   // muet plutôt que menteur
  }
}

function mountMasthead() {
  const host = $("#masthead");
  if (!host) return;
  const current = document.body.dataset.page;
  // Les rubriques, sans pictogramme. Huit icônes alignées au-dessus d'un titre
  // de publication donnaient une barre d'outils d'application ; un ours de
  // journal nomme ses sections, il ne les illustre pas.
  const nav = PAGES.map(([href, key, label]) =>
    `<a href="${href}"${key === current ? ' aria-current="page"' : ""}>${label}</a>`).join("");

  host.className = "masthead";
  host.innerHTML = `<div class="masthead__inner">
    <a class="wordmark" href="index.html">ED <span>Mediawatch</span></a>
    <p class="masthead__tagline">${escapeHtml(document.body.dataset.tagline || "")}</p>
    <div class="spacer"></div>
    <p class="chip" id="live"></p>
    <p class="masthead__meta" id="stats"></p>
    <button class="btn btn--ghost btn--sm" id="themeToggle" aria-label="Basculer le thème"></button>
  </div>
  <div class="masthead__nav"><nav class="nav" aria-label="Sections">${nav}</nav></div>`;

  liveIndicator();

  const toggle = $("#themeToggle");
  const label = () => {
    const dark = document.documentElement.dataset.theme === "dark";
    toggle.innerHTML = dark ? "clair" : "sombre";
  };
  toggle.onclick = () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme", next);
    label();
  };
  label();
}


// ── Répartition de la parole ────────────────────────────────────────────────
//
// Ce qui était ici : une frise miniature, des points sur une ligne, une par
// locuteur. À 200 px de large, sans axe lisible et sans échelle sur mobile,
// elle ne se lisait pas — c'était de la décoration qui se faisait passer pour
// de la donnée. Un graphique qu'on ne peut pas lire vaut moins que rien : il
// occupe la place ET fait croire qu'on a montré quelque chose.
//
// L'information qu'elle portait — qui domine ce sujet — se dit en toutes
// lettres, et se lit instantanément. La frise complète, elle, garde son sens
// sur la page du sujet : elle y a un axe daté, des libellés et de la place.

// Depuis, un visage accompagne chaque nom quand le locuteur est une figure
// suivie. Un sommaire de sujets n'a aucune illustration à sa disposition — les
// gens qui parlent SONT son image, et une rangée de portraits dit d'un coup
// d'œil si un sujet est porté par une voix ou par cinq.

// Les initiales : le repli quand il n'y a pas de photo, et le seul rendu
// possible pour « non attribué » — qui n'est personne, et ne doit donc pas
// recevoir de visage.
function initiales(nom) {
  const mots = String(nom).trim().split(/\s+/).filter((m) => /^[A-ZÀ-Þ]/.test(m));
  return (mots.length ? mots : [String(nom)])
    .map((m) => m[0]).slice(0, 2).join("").toUpperCase();
}

function portrait(nom, handle) {
  const repli = `<span class="face face--txt">${escapeHtml(initiales(nom))}</span>`;
  if (!handle) return repli;
  // `onerror` : le service de portraits ne connaît pas tous les comptes, et une
  // image cassée serait pire que des initiales.
  return `<img class="face" src="https://unavatar.io/x/${encodeURIComponent(handle)}?fallback=false"
    alt="" loading="lazy" width="28" height="28"
    onerror="this.outerHTML=this.dataset.fb" data-fb='${repli}' />`;
}

function repartition(frise, total) {
  const lanes = (frise || []).filter((f) => f.dates?.length);
  if (!lanes.length) return "";

  const compte = lanes.map((l) => ({ who: l.speaker, handle: l.handle, n: l.dates.length }))
    .sort((a, b) => b.n - a.n);
  const dit = compte.reduce((n, x) => n + x.n, 0);
  const reste = Math.max(0, (total || dit) - dit);

  // Le nom de famille suffit dans une liste serrée ; le prénom se retrouve sur
  // la page du sujet, où il y a la place de l'écrire. Mais seulement quand
  // c'est un nom : couper « non attribué » en « attribué » inversait le sens —
  // d'où le test sur la majuscule, qui distingue un patronyme d'une mention.
  const court = (nom) => {
    const mots = String(nom).trim().split(/\s+/);
    if (mots.length < 2) return nom;
    const suite = mots.slice(1).join(" ");
    return /^[A-ZÀ-Þ]/.test(suite) ? suite : nom;
  };

  return `<ul class="repart">${compte.slice(0, 4).map((x) => `
    <li class="repart__x">
      ${portrait(x.who, x.handle)}
      <span class="repart__who">${escapeHtml(court(x.who))}</span>
      <b class="repart__n">${x.n}</b>
    </li>`).join("")}${
    reste ? `<li class="repart__x repart__x--rest">+${reste} ailleurs</li>` : ""}</ul>`;
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
