// Fiche d'un locuteur : CE QU'IL DÉFEND, sujet par sujet.
//
// La page listait ses propos par ordre chronologique. Personne n'arrive avec la
// question « qu'a-t-elle dit le 12 mars » ; on arrive avec « que dit-elle des
// retraites, et depuis quand » — et, si d'autres en parlent, « qui dit le
// contraire ». La chronologie reste, en second : c'est une pièce du dossier,
// pas la porte d'entrée.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, asDate, exactDate,
// themeLabel, themeVar, kicker, duree, periode, ico, mandat.

const GROUP_VAR = { RN: "--grp-rn", UDR: "--grp-udr", FIGURE: "--grp-figure" };
const TYPE_LABEL = {
  normatif: "position", factuel_quantitatif: "chiffre", factuel_qualitatif: "fait",
  predictif: "prédiction", attributif: "imputation",
};
const MONTHS = ["janv.", "févr.", "mars", "avril", "mai", "juin",
                "juil.", "août", "sept.", "oct.", "nov.", "déc."];

// Une fiche peut porter 1 400 propos : on en charge une tranche et on annonce
// combien il en reste.
const PAGE = 60;

const state = { id: null, figures: [], data: null, loading: false, onlyConf: true };

const monthLabel = (key) => {
  if (key === "date-inconnue") return "Date inconnue";
  const [y, m] = key.split("-");
  return `${MONTHS[+m - 1]} ${y}`;
};

// ── Répertoire ──────────────────────────────────────────────────────────────

function renderList() {
  const q = ($("#figSearch").value || "").toLowerCase().trim();
  const shown = state.figures.filter((f) =>
    !q || f.full_name.toLowerCase().includes(q) || (f.handle || "").toLowerCase().includes(q));

  $("#figList").innerHTML = shown.length
    ? shown.map((f) => `
      <button class="referent" data-id="${f.id}" aria-pressed="${state.id === f.id}">
        <span class="referent__label">${escapeHtml(f.full_name)}</span>
        <span class="referent__meta">${f.n_claims ? `${fmtNum(f.n_claims)} propos` : "aucun propos"}${
          f.handle ? ` · @${escapeHtml(f.handle)}` : ""}</span>
      </button>`).join("")
    : '<p class="state">Aucune figure ne correspond.</p>';

  $("#figList").querySelectorAll(".referent").forEach((b) =>
    (b.onclick = () => load(+b.dataset.id)));
}

// ── Ce qu'il défend ─────────────────────────────────────────────────────────
//
// Les sujets CONFRONTABLES d'abord : ce sont les seuls où la position de cette
// figure peut être mise en regard d'une autre. Un sujet où elle parle seule
// documente ce qu'elle dit, il ne prouve rien sur le débat.

function subjectRow(x) {
  return `<a class="ranked__item" href="sujet.html?id=${x.id}" style="--th:${themeVar(x.theme)}">
    <span class="ranked__n">${x.n}</span>
    <span>
      <span class="ranked__t">${escapeHtml(x.label)}</span>
      <span class="ranked__m">${escapeHtml(themeLabel(x.theme) || "sans thème")}
        · ${duree(x.span_days)} · ${x.confrontable
          ? `${x.n_speakers} voix — confrontable`
          : "une seule voix"}</span>
    </span>
  </a>`;
}

function renderSubjects() {
  const all = state.data?.by_subject || [];
  const conf = all.filter((x) => x.confrontable);
  const shown = (state.onlyConf ? conf : all).slice(0, 40);

  $("#subjects").innerHTML = `
    <div class="filters" style="margin-bottom:var(--s4)">
      <button class="filter" data-conf="1" aria-pressed="${state.onlyConf}">
        Confrontables<span class="count">${conf.length}</span></button>
      <button class="filter" data-conf="0" aria-pressed="${!state.onlyConf}">
        Tous les sujets<span class="count">${all.length}</span></button>
    </div>
    ${shown.length
      ? `<div class="ranked">${shown.map(subjectRow).join("")}</div>`
      : `<p class="state"><span class="state__title">Aucun sujet confrontable</span>
         <span class="state__hint">Cette figure ne partage encore aucun objet de débat avec une
         autre voix du corpus. Affiche tous les sujets pour voir ce qu’elle porte seule.</span></p>`}`;

  $("#subjects").querySelectorAll("[data-conf]").forEach((b) =>
    (b.onclick = () => { state.onlyConf = b.dataset.conf === "1"; renderSubjects(); }));
}

// ── Chronologie (second plan) ───────────────────────────────────────────────

function claimRow(c) {
  const date = c.published_at
    ? asDate(c.published_at).toLocaleDateString("fr-FR", { day: "numeric", month: "short" })
    : "—";
  const value = c.qty_value != null ? `${c.qty_value}${c.qty_unit ? " " + c.qty_unit : ""}` : "";
  return `<article class="entry" style="grid-template-columns:4.5rem 1fr;padding:var(--s4) 0">
    <p class="stamp" style="padding-top:2px">${date}</p>
    <div>
      ${value ? `<p class="claim__value">${escapeHtml(value)}</p>` : ""}
      <p class="prose" style="margin-top:0">${escapeHtml(c.canonical || c.verbatim)}</p>
      <div class="entry__foot">
        <span class="tag">${TYPE_LABEL[c.claim_type] || escapeHtml(c.claim_type)}</span>
        ${c.theme ? `<span class="tag tag--theme">${escapeHtml(themeLabel(c.theme))}</span>` : ""}
        <span class="tag">${c.platform === "x" ? "X" : "presse"}</span>
        <span class="spacer"></span>
        ${c.source_url ? `<a class="source-link" href="${c.source_url}" target="_blank" rel="noopener">source ↗</a>`
          : '<span class="stamp">source non résolue</span>'}
      </div>
    </div>
  </article>`;
}

// Une page peut commencer au milieu d'un mois : sans fusion, deux blocs
// « août 2026 » se suivraient et donneraient l'impression d'un trou.
function mergeTimeline(into, incoming) {
  const byMonth = new Map(into.map((m) => [m.month, m]));
  for (const m of incoming) {
    const cur = byMonth.get(m.month);
    if (cur) cur.claims.push(...m.claims);
    else { byMonth.set(m.month, m); into.push(m); }
  }
  into.sort((a, b) => (a.month < b.month ? 1 : -1));
  return into;
}

function renderTimeline() {
  const host = $("#timeline");
  const d = state.data;
  if (!host || !d) return;
  if (!d.timeline.length) {
    host.innerHTML = `<p class="state"><span class="state__title">Aucun propos consigné</span>
      <span class="state__hint">Rien n’a encore été extrait pour cette figure. La collecte a
      peut-être échoué (compte renommé, homonyme) — voir
      <a class="source-link" href="atelier.html">l’atelier</a>.</span></p>`;
    return;
  }
  const shown = d.timeline.reduce((n, m) => n + m.claims.length, 0);
  const left = Math.max(0, (d.timeline_total || shown) - shown);
  host.innerHTML = d.timeline.map((m) => `
      <h3 style="font-size:var(--t-title);margin:var(--s6) 0 var(--s2)">${monthLabel(m.month)}</h3>
      <div class="register">${m.claims.map(claimRow).join("")}</div>`).join("")
    + (left ? `<button class="more" id="more">Afficher les <b>${fmtNum(left)}</b> propos plus anciens</button>` : "");
  const more = $("#more");
  if (more) more.onclick = loadMore;
}

async function loadMore() {
  if (state.loading || !state.data) return;
  state.loading = true;
  const btn = $("#more");
  const shown = state.data.timeline.reduce((n, m) => n + m.claims.length, 0);
  if (btn) btn.textContent = "Chargement…";
  try {
    const next = await fetchJSON(`/figures/${state.id}?limit=${PAGE}&offset=${shown}`);
    mergeTimeline(state.data.timeline, next.timeline);
    state.data.timeline_total = next.timeline_total;
    renderTimeline();
    $("#more")?.scrollIntoView({ block: "center" });
  } catch (e) {
    if (btn) btn.textContent = `Chargement impossible (${e.message})`;
  } finally {
    state.loading = false;
  }
}

// ── Rendu ───────────────────────────────────────────────────────────────────

function render(d) {
  const f = d.figure, s = d.stats;
  const color = `var(${GROUP_VAR[f.group_code] || "--muted"})`;
  const months = s.first_seen && s.last_seen
    ? Math.max(1, Math.round((asDate(s.last_seen) - asDate(s.first_seen)) / (1000 * 60 * 60 * 24 * 30)))
    : 0;
  const conf = (d.by_subject || []).filter((x) => x.confrontable).length;

  $("#detail").innerHTML = `
    <p class="overline">${ico("locuteurs")} Fiche</p>
    <h1 class="hero-title" style="margin-top:0">${escapeHtml(f.full_name)}</h1>
    <div class="entry__foot" style="margin-top:var(--s3)">
      <span class="tag tag--group" style="--grp-color:${color}">${escapeHtml(f.group_code)}</span>
      ${f.famille && f.famille.toLowerCase() !== (f.group_code || "").toLowerCase()
        ? `<span class="tag">${escapeHtml(f.famille)}</span>` : ""}
      ${f.role ? `<span class="tag">${escapeHtml(f.role)}</span>` : ""}
      ${mandat(f.departement, f.circo)
        ? `<span class="tag">${escapeHtml(mandat(f.departement, f.circo))}</span>` : ""}
      ${f.handle ? `<a class="handle" href="https://x.com/${f.handle}" target="_blank" rel="noopener">@${escapeHtml(f.handle)}</a>` : ""}
    </div>

    <div class="statbar" style="margin-top:var(--s5)">
      <span class="statbar__item"><span class="statbar__n">${fmtNum(s.n_claims)}</span> propos consignés</span>
      <span class="statbar__item"><span class="statbar__n statbar__n--accent">${fmtNum(conf)}</span>
        sujets confrontables</span>
      <span class="statbar__item"><span class="statbar__n">${months}</span> mois de recul</span>
      <span class="statbar__item">${escapeHtml(periode(s.first_seen, s.last_seen))}</span>
    </div>

    ${months < 24 && s.first_seen ? `<p class="rationale" style="border-top:none;padding-top:var(--s3)">
      Un changement de position se lit sur plusieurs années. En deçà, l’absence de revirement
      ne prouve rien — c’est une limite du corpus, pas un résultat.</p>` : ""}

    ${d.dossier?.summary ? `
      <div class="band"><h2>Synthèse</h2><span class="spacer"></span>
        <p>Produite par ${escapeHtml(d.dossier.model || "—")}, à relire.</p></div>
      <p class="prose">${escapeHtml(d.dossier.summary)}</p>` : ""}

    <div class="band"><h2>Les sujets que porte ${escapeHtml(f.full_name)}</h2>
      <span class="spacer"></span>
      <p>Par sujet, du plus investi au moins. Cliquer ouvre la confrontation.</p></div>
    <div id="subjects"></div>

    ${d.contradictions?.length ? `
      <div class="band"><h2>Rapprochements la concernant</h2></div>
      <div class="kv">${d.contradictions.map((e) => `
        <div class="kv__row" style="flex-wrap:wrap">
          <span class="kv__k" style="color:var(--ink)">${escapeHtml(e.type_label)}</span>
          <span class="kv__v">score ${e.score}</span>
          <span class="status status--${e.status === "confirmed" ? "ok" : e.status === "rejected" ? "alert" : "pending"}"
                style="margin-left:var(--s3)">${
            e.status === "confirmed" ? "confirmé" : e.status === "rejected" ? "écarté" : "à relire"}</span>
          ${e.rationale ? `<span class="kv__note">${escapeHtml(e.rationale)}</span>` : ""}
        </div>`).join("")}</div>` : ""}

    <div class="band"><h2>Chronologie</h2><span class="spacer"></span>
      <p>Le relevé brut, daté et sourcé.</p></div>
    <div id="timeline"></div>`;

  renderSubjects();
  renderTimeline();
}

async function load(id) {
  state.id = id;
  state.onlyConf = true;
  renderList();
  $("#detail").innerHTML = '<p class="state">Chargement…</p>';
  try {
    state.data = await fetchJSON(`/figures/${id}?limit=${PAGE}&offset=0`);
    render(state.data);
  } catch (e) {
    $("#detail").innerHTML = `<p class="state state--error">Fiche indisponible (${e.message}).</p>`;
  }
}

async function init() {
  try {
    const data = await fetchJSON("/figures");
    state.figures = data.items;
    $("#stats").innerHTML = `<strong>${fmtNum(data.total)}</strong> locuteurs`;
    renderList();
    const first = state.figures.find((f) => f.n_claims > 0);
    if (first) load(first.id);
  } catch (e) {
    $("#figList").innerHTML = `<p class="state state--error">Répertoire indisponible (${e.message}).</p>`;
  }
}

let searchTimer;
$("#figSearch").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(renderList, 200); };
init();
