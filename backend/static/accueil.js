// La une de l'observatoire.
//
// Ce qui est mis en avant n'est pas « le plus récent » — un observatoire du
// propos dans la durée qui trierait par date redeviendrait un fil. C'est le
// sujet le plus EXPLOITABLE : plusieurs voix, sur une longue étendue. C'est là,
// et seulement là, qu'une confrontation ou un revirement peut exister.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, asDate, relTime,
// themeLabel, themeVar, kicker, duree, periode.

const lien = (id) => `sujet.html?id=${id}`;

// ── La une : un sujet en grand, avec sa frise en aperçu ────────────────────

function apercu(speakers, theme) {
  const dated = speakers
    .map((s) => ({ name: s.name, ts: s.claims.filter((c) => c.published_at)
      .map((c) => asDate(c.published_at).getTime()) }))
    .filter((s) => s.ts.length);
  if (dated.length < 2) return "";

  const all = dated.flatMap((s) => s.ts);
  let t0 = Math.min(...all), t1 = Math.max(...all);
  if (t0 === t1) { t0 -= 864e5; t1 += 864e5; }

  // Aperçu, pas outil : pas de repères cliquables ni d'axe daté ici. La frise
  // complète est sur la page du sujet ; en dupliquer une version amoindrie sur
  // la une donnerait deux objets à moitié utiles au lieu d'un qui marche.
  return `<div class="frise" style="margin-top:var(--s5)" aria-hidden="true">
    ${dated.slice(0, 5).map((s) => `
      <div class="frise__lane" style="padding:var(--s2) 0">
        <p class="frise__who">${escapeHtml(s.name)}<span>${s.ts.length}</span></p>
        <div class="frise__track" style="height:1.1rem">
          ${s.ts.map((t) => `<span class="frise__dot" style="left:${
            (((t - t0) / (t1 - t0)) * 100).toFixed(2)}%;--th:${themeVar(theme)};pointer-events:none"></span>`).join("")}
        </div>
      </div>`).join("")}
  </div>`;
}

async function renderUne(top) {
  const el = $("#une");
  el.innerHTML = `
    <article>
      <a href="${lien(top.id)}" style="display:block">
        ${kicker(top.theme, `${top.n_speakers} locuteurs · ${duree(top.span_days)} de recul`)}
        <h1 class="hero-title">${escapeHtml(top.label)}</h1>
      </a>
      <p class="dek">${fmtNum(top.n_claims)} prises de position, ${periode(top.first_seen, top.last_seen)}.
        C’est le sujet où le corpus permet le mieux de comparer&nbsp;: le plus de voix, sur la plus
        longue durée.</p>
      <div id="apercu"></div>
      <p style="margin-top:var(--s4)">
        <a class="source-link" href="${lien(top.id)}">ouvrir le sujet ↗</a>
      </p>
    </article>`;

  // La frise demande le détail du sujet : on la charge après coup pour que le
  // titre s'affiche tout de suite.
  try {
    const d = await fetchJSON(`/subjects/${top.id}`);
    $("#apercu").innerHTML = apercu(d.speakers || [], top.theme);
  } catch { /* l'aperçu est un bonus : son absence ne casse pas la une */ }
}

// ── La grille ───────────────────────────────────────────────────────────────

const tuile = (s) => `
  <a class="tile" href="${lien(s.id)}">
    ${kicker(s.theme)}
    <h3 class="card-title">${escapeHtml(s.label)}</h3>
    <div class="tile__foot">
      <span class="stamp"><b>${s.n_speakers}</b> locuteurs · <b>${fmtNum(s.n_claims)}</b> propos</span>
      <span class="spacer"></span>
      <span class="stamp">${duree(s.span_days)}</span>
    </div>
  </a>`;

// ── Colonnes d'appoint ──────────────────────────────────────────────────────

function renderPending(items) {
  $("#pending").innerHTML = items.length
    ? `<div class="aside-list">${items.slice(0, 5).map((e) => `
        <a class="aside-item" href="contradictions.html">
          <p class="aside-item__t">${escapeHtml(
            (e.claim_a?.speaker_name || "locuteur inconnu"))} — ${escapeHtml(
            (e.claim_a?.canonical || e.claim_a?.verbatim || "").slice(0, 110))}</p>
          <p class="aside-item__m">${escapeHtml(relTime(e.detected_at))} · score ${e.score}</p>
        </a>`).join("")}</div>
       <p class="stamp" style="margin-top:var(--s3)">
         <a class="source-link" href="contradictions.html">tout relire ↗</a></p>`
    : `<p class="state" style="padding:var(--s5) 0">Aucun rapprochement en attente.</p>`;
}

// Le fonds : ce sur quoi tout repose. L'afficher sur la une n'est pas de la
// coquetterie — un observatoire qui ne dit pas l'étendue de son corpus demande
// qu'on le croie sur parole.
function renderFonds(f) {
  const n = (i) => f.steps?.[i]?.n ?? 0;
  $("#fonds").innerHTML = `<div class="kv" style="border-top:none">
    <div class="kv__row"><span class="kv__k">Publications consignées</span>
      <span class="kv__v">${fmtNum(n(0))}</span></div>
    <div class="kv__row"><span class="kv__k">Propos extraits</span>
      <span class="kv__v">${fmtNum(n(1))}</span></div>
    <div class="kv__row"><span class="kv__k">Sujets constitués</span>
      <span class="kv__v">${fmtNum(n(3))}</span></div>
    <div class="kv__row" style="border-bottom:none"><span class="kv__k">État de la chaîne</span>
      <span class="kv__v"><a class="source-link" href="atelier.html">l’atelier ↗</a></span></div>
  </div>`;
}

function renderThemes(themes) {
  const rows = Object.entries(themes || {}).sort((a, b) => b[1] - a[1]).slice(0, 10);
  $("#themes").innerHTML = rows.map(([t, n]) =>
    `<a class="filter" href="sujets.html?theme=${encodeURIComponent(t)}"
        style="--th:${themeVar(t)}">${escapeHtml(themeLabel(t))}<span class="count">${n}</span></a>`).join("");
}

// ── Chargement ──────────────────────────────────────────────────────────────

async function load() {
  try {
    const subj = await fetchJSON("/subjects?limit=25&confrontable=true");
    const items = subj.items || [];
    if (!items.length) {
      $("#une").innerHTML = `<p class="state">
        <span class="state__title">Aucun sujet exploitable pour l’instant</span>
        <span class="state__hint">Un sujet devient exploitable quand deux locuteurs au moins s’y
        expriment. Le regroupement tourne à chaque passe — voir
        <a class="source-link" href="atelier.html">l’atelier</a>.</span></p>`;
    } else {
      await renderUne(items[0]);
      $("#grid").innerHTML = `<div class="tiles">${items.slice(1, 13).map(tuile).join("")}</div>`;
    }
    renderThemes(subj.themes);
    $("#stats").innerHTML = `<strong>${fmtNum(items.length)}</strong> sujets exploitables`;
  } catch (e) {
    $("#une").innerHTML =
      `<p class="state state--error">Les sujets n’ont pas pu être chargés (${escapeHtml(e.message)}).</p>`;
  }

  // Les colonnes d'appoint ne doivent pas empêcher la une de s'afficher.
  fetchJSON("/contradictions?limit=6").then((d) => renderPending(d.items || [])).catch(() => {
    $("#pending").innerHTML = '<p class="state" style="padding:var(--s5) 0">Indisponible.</p>';
  });
  fetchJSON("/pipeline/funnel").then(renderFonds).catch(() => {
    $("#fonds").innerHTML = '<p class="state" style="padding:var(--s5) 0">Indisponible.</p>';
  });
}

load();
