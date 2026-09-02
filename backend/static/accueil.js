// La une de l'observatoire.
//
// Ce qui est mis en avant n'est pas « le plus récent » — un observatoire du
// propos dans la durée qui trierait par date redeviendrait un fil. C'est le
// sujet le plus EXPLOITABLE : plusieurs voix, sur une longue étendue. C'est là,
// et seulement là, qu'une confrontation ou un revirement peut exister.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, asDate, relTime,
// themeLabel, themeVar, kicker, duree, periode, repartition, ico.

const lien = (id) => `sujet.html?id=${id}`;

// ── Le fil « en ce moment » ─────────────────────────────────────────────────
// Ce que l'observatoire suit en ce moment, nommé. Lister ses rubriques n'apprend
// rien : elles ne changent jamais. Les objets de débat, si.

function renderNow(items) {
  const host = $("#now");
  if (!items.length) { host.hidden = true; return; }
  host.hidden = false;
  host.innerHTML = `<div class="now__inner">
    <span class="now__label">En ce moment</span>
    ${items.slice(0, 7).map((s) =>
      `<a href="${lien(s.id)}" style="--th:${themeVar(s.theme)}">${nomSujet(s)}</a>`).join("")}
  </div>`;
}

// ── Le fonds, en chiffres ───────────────────────────────────────────────────
//
// Un observatoire qui ne dit pas l'étendue de son corpus demande qu'on le croie
// sur parole. Mais quatre grosses cartes pour quatre nombres donnent le même
// poids à des choses qui n'en ont pas : une ligne dense suffit, et se lit d'un
// seul regard.
//
// « Propos attribués » plutôt que « propos extraits » : un propos sans locuteur
// ne se compare pas — il ne compte donc pas vraiment.

function renderFonds(f, nSubjects, nPending) {
  // Par CLÉ, jamais par position : l'entonnoir gagne des étages, et un index
  // figé afficherait le chiffre d'à côté sans que rien ne le signale.
  const etage = (cle) => (f?.steps || []).find((s) => s.key === cle) || {};
  const n = (cle) => etage(cle).n ?? 0;
  const m = (etage("extraction").detail || "").match(/^(\d+)/);
  const attribues = m ? +m[1] : 0;

  $("#fonds").innerHTML = `<div class="statbar">
    <span class="statbar__item"><span class="statbar__n">${fmtNum(n("collecte"))}</span>
      publications conservées</span>
    <span class="statbar__item"><span class="statbar__n statbar__n--accent">${fmtNum(attribues)}</span>
      propos attribués <span class="statbar__of">/ ${fmtNum(n("extraction"))} extraits</span></span>
    <span class="statbar__item"><span class="statbar__n">${fmtNum(nSubjects)}</span>
      sujets exploitables</span>
    <a class="statbar__item" href="contradictions.html">
      <span class="statbar__n">${fmtNum(nPending)}</span> à relire ${ico("source")}</a>
  </div>`;
}

// ── Une bande par sujet ─────────────────────────────────────────────────────
// Titre à gauche, forme au centre, dernier état à droite : la structure d'une
// une de presse, transposée à un objet qui n'a pas d'image mais qui a une forme.

function story(s, big = false) {
  const l = s.latest;
  return `<article class="story${big ? " story--lead" : ""}">
    <div>
      <a href="${lien(s.id)}">
        ${kicker(s.theme, `${s.n_speakers} voix · ${duree(s.span_days)}`)}
        <h${big ? 1 : 2} class="${big ? "hero-title" : "story__title"}">${nomSujet(s)}</h${big ? 1 : 2}>
      </a>
      <p class="dek">${fmtNum(s.n_claims)} prises de position, ${periode(s.first_seen, s.last_seen)}.${
        big ? " C’est le sujet où le corpus permet le mieux de comparer : le plus de voix, sur la plus longue durée." : ""}</p>
      <p class="mt-4">
        <a class="btn btn--sm" href="${lien(s.id)}">Voir qui a dit quoi ${ico("source")}</a></p>
    </div>
    <div>
      <p class="overline">${ico("locuteurs")} Qui parle</p>
      ${repartition(s.frise, s.n_claims)}
      <p class="stamp mt-4">${escapeHtml(periode(s.first_seen, s.last_seen))}</p>
    </div>
    <div class="story__aside">
      ${l ? `<p class="overline">${ico("temps")} Dernier propos</p>
        <p class="stamp"><span class="latest__when">${escapeHtml(relTime(l.published_at))}</span>
          · <span class="nowrap">${escapeHtml(l.speaker || "locuteur non établi")}</span></p>
        <p class="latest__q">« ${escapeHtml((l.text || "").slice(0, 190))} »</p>`
        : '<p class="stamp">Aucun propos daté.</p>'}
    </div>
  </article>`;
}

// ── Colonne « à relire » ────────────────────────────────────────────────────

function renderPending(items) {
  $("#pending").innerHTML = items.length
    ? `<div class="ranked mt-4">${items.slice(0, 5).map((e, i) => `
        <a class="ranked__item" href="contradictions.html">
          <span class="ranked__n">${i + 1}</span>
          <span>
            <span class="ranked__t">${escapeHtml(e.claim_a?.speaker_name || "locuteur non établi")}</span>
            <span class="ranked__m"><span class="nowrap">${escapeHtml(relTime(e.detected_at))}</span>
              · <span class="nowrap">score ${e.score}</span></span>
          </span>
        </a>`).join("")}</div>
       <p class="mt-4"><a class="btn btn--sm" href="contradictions.html">
         Tout relire ${ico("source")}</a></p>`
    : '<p class="state state--inline">Aucun rapprochement en attente.</p>';
}

// ── La revue de la semaine ──────────────────────────────────────────────────
//
// Une base bien tenue ne fait pas une lecture. La revue est l'angle que
// l'observatoire propose : ce qui s'est dit, sujet par sujet, sur la semaine
// close — et chaque phrase y cite les déclarations qu'elle rapporte.

function renderRevue(items) {
  const host = $("#revue");
  if (!items.length) { host.hidden = true; return; }
  host.hidden = false;
  const quand = items[0].period;
  host.innerHTML = `
    <div class="band"><h2>La revue</h2><span class="spacer"></span>
      <p>Ce qui s’est dit sur chaque sujet, la semaine close.</p></div>
    <div class="tiles">${items.slice(0, 3).map((r) => `
      <a class="tile" href="revue.html?id=${r.id}">
        ${kicker(r.theme, r.status === "brouillon" ? "brouillon" : "relue")}
        <h3 class="card-title">${escapeHtml(r.title || "sans titre")}</h3>
        <p class="dek">${escapeHtml(r.subject_label || "")}</p>
        <p class="tile__foot"><span class="stamp">${fmtNum(r.n_sources)} déclarations citées</span></p>
      </a>`).join("")}</div>
    <p class="mt-4"><a class="btn btn--sm" href="revue.html">Toutes les revues ${ico("source")}</a></p>`;
}

function renderThemes(themes) {
  $("#themes").innerHTML = Object.entries(themes || {})
    .sort((a, b) => b[1] - a[1]).slice(0, 12)
    .map(([t, n]) => `<a class="filter" href="sujets.html?theme=${encodeURIComponent(t)}"
        style="--th:${themeVar(t)}">${escapeHtml(themeLabel(t))}<span class="count">${n}</span></a>`).join("");
}

// ── Chargement ──────────────────────────────────────────────────────────────

async function load() {
  let items = [];
  // Le nombre annoncé est celui du fonds, pas celui de la page chargée.
  let total = 0;
  try {
    const subj = await fetchJSON("/subjects?limit=25&confrontable=true");
    items = subj.items || [];
    total = subj.total ?? items.length;
    renderThemes(subj.themes);
    renderNow(items);

    if (!items.length) {
      $("#une").innerHTML = `<p class="state">
        <span class="state__title">Aucun sujet exploitable pour l’instant</span>
        <span class="state__hint">Un sujet le devient quand deux locuteurs au moins s’y expriment.
        Le regroupement tourne à chaque passe — voir
        <a class="source-link" href="atelier.html">l’atelier</a>.</span></p>`;
    } else {
      $("#une").innerHTML = story(items[0], true);
      $("#grid").innerHTML = items.slice(1, 9).map((s) => story(s)).join("");
    }
    $("#stats").innerHTML = `<strong>${fmtNum(total)}</strong> sujets exploitables`;
  } catch (e) {
    $("#une").innerHTML =
      `<p class="state state--error">Les sujets n’ont pas pu être chargés (${escapeHtml(e.message)}).</p>`;
  }

  // Le bento a besoin de deux sources ; ni l'une ni l'autre ne doit empêcher la
  // une de s'afficher.
  const [funnel, pending, revues] = await Promise.all([
    fetchJSON("/pipeline/funnel").catch(() => null),
    fetchJSON("/contradictions?limit=6").catch(() => null),
    fetchJSON("/reviews?limit=3").catch(() => null),
  ]);
  renderFonds(funnel, total, pending?.total ?? 0);
  renderPending(pending?.items || []);
  renderRevue(revues?.items || []);
}

load();
