// La une de l'observatoire.
//
// Ce qui est mis en avant n'est pas « le plus récent » — un observatoire du
// propos dans la durée qui trierait par date redeviendrait un fil. C'est le
// sujet le plus EXPLOITABLE : plusieurs voix, sur une longue étendue. C'est là,
// et seulement là, qu'une confrontation ou un revirement peut exister.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, asDate, relTime,
// themeLabel, themeVar, kicker, duree, periode, friseMini, ico.

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
      `<a href="${lien(s.id)}" style="--th:${themeVar(s.theme)}">${escapeHtml(s.label)}</a>`).join("")}
  </div>`;
}

// ── Le fonds, en chiffres ───────────────────────────────────────────────────
// Un observatoire qui ne dit pas l'étendue de son corpus demande qu'on le
// croie sur parole. « Propos attribués » plutôt que « propos extraits » : un
// propos sans locuteur ne se compare pas, il ne compte donc pas vraiment.

function renderFonds(f, nSubjects, nPending) {
  const n = (i) => f?.steps?.[i]?.n ?? 0;
  const attribues = (f?.steps?.[1]?.detail || "").match(/^(\d+)/);
  $("#fonds").innerHTML = `<div class="bento">
    <div class="cell">
      <p class="cell__label">${ico("archive")} Publications conservées</p>
      <p class="metric">${fmtNum(n(0))}</p>
      <p class="cell__sub">en ligne et dans la presse</p>
    </div>
    <div class="cell">
      <p class="cell__label">${ico("locuteurs")} Propos attribués</p>
      <p class="metric metric--accent">${fmtNum(attribues ? +attribues[1] : 0)}</p>
      <p class="cell__sub">sur ${fmtNum(n(1))} extraits — les autres n’ont pas de locuteur certain</p>
    </div>
    <div class="cell">
      <p class="cell__label">${ico("sujets")} Sujets exploitables</p>
      <p class="metric">${fmtNum(nSubjects)}</p>
      <p class="cell__sub">plusieurs voix, sur la durée</p>
    </div>
    <a class="cell" href="contradictions.html">
      <p class="cell__label">${ico("validation")} Rapprochements à relire</p>
      <p class="metric ${nPending ? "metric--alert" : ""}">${fmtNum(nPending)}</p>
      <p class="cell__sub">rien ne se publie sans relecture humaine</p>
      <p class="cell__foot"><span class="source-link">ouvrir la file ↗</span></p>
    </a>
  </div>`;
}

// ── Une bande par sujet ─────────────────────────────────────────────────────
// Titre à gauche, forme au centre, dernier état à droite : la structure d'une
// une de presse, transposée à un objet qui n'a pas d'image mais qui a une forme.

function story(s, big = false) {
  const l = s.latest;
  return `<article class="story">
    <div>
      <a href="${lien(s.id)}">
        ${kicker(s.theme, `${s.n_speakers} voix · ${duree(s.span_days)}`)}
        <h${big ? 1 : 2} class="${big ? "hero-title" : "story__title"}">${escapeHtml(s.label)}</h${big ? 1 : 2}>
      </a>
      <p class="dek">${fmtNum(s.n_claims)} prises de position, ${periode(s.first_seen, s.last_seen)}.${
        big ? " C’est le sujet où le corpus permet le mieux de comparer : le plus de voix, sur la plus longue durée." : ""}</p>
      <p style="margin-top:var(--s4)">
        <a class="btn btn--sm" href="${lien(s.id)}">Voir qui a dit quoi ${ico("source")}</a></p>
    </div>
    <div>${friseMini(s.frise, s.theme, big ? 5 : 3)}</div>
    <div class="story__aside">
      ${l ? `<p class="cell__label" style="margin-bottom:var(--s2)">${ico("temps")} Dernier propos</p>
        <p class="stamp"><span class="latest__when">${escapeHtml(relTime(l.published_at))}</span>
          · ${escapeHtml(l.speaker || "locuteur non établi")}</p>
        <p class="latest__q">« ${escapeHtml((l.text || "").slice(0, 190))} »</p>`
        : '<p class="stamp">Aucun propos daté.</p>'}
    </div>
  </article>`;
}

// ── Colonne « à relire » ────────────────────────────────────────────────────

function renderPending(items) {
  $("#pending").innerHTML = items.length
    ? `<div class="ranked">${items.slice(0, 5).map((e, i) => `
        <a class="ranked__item" href="contradictions.html">
          <span class="ranked__n">${i + 1}</span>
          <span>
            <span class="ranked__t">${escapeHtml(e.claim_a?.speaker_name || "locuteur non établi")}</span>
            <span class="ranked__m">${escapeHtml(relTime(e.detected_at))} · score ${e.score}</span>
          </span>
        </a>`).join("")}</div>
       <p style="margin-top:var(--s4)"><a class="btn btn--sm" href="contradictions.html">
         Tout relire ${ico("source")}</a></p>`
    : '<p class="state" style="padding:var(--s5) 0">Aucun rapprochement en attente.</p>';
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
  try {
    const subj = await fetchJSON("/subjects?limit=25&confrontable=true");
    items = subj.items || [];
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
    $("#stats").innerHTML = `<strong>${fmtNum(items.length)}</strong> sujets exploitables`;
  } catch (e) {
    $("#une").innerHTML =
      `<p class="state state--error">Les sujets n’ont pas pu être chargés (${escapeHtml(e.message)}).</p>`;
  }

  // Le bento a besoin de deux sources ; ni l'une ni l'autre ne doit empêcher la
  // une de s'afficher.
  const [funnel, pending] = await Promise.all([
    fetchJSON("/pipeline/funnel").catch(() => null),
    fetchJSON("/contradictions?limit=6").catch(() => null),
  ]);
  renderFonds(funnel, items.length, pending?.total ?? 0);
  renderPending(pending?.items || []);
}

load();
