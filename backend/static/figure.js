// Fiche d'une figure : ses positions enjeu par enjeu, ses écarts, et ce que la collecte a ramené de
// ses tweets. Tout vient du registre des déclarations, lues dans les tweets.
//
// Helpers (common.js, chart.js) : $, fetchJSON, escapeHtml, fmtNum, jourLong, ecartCarte, portrait,
// mandat, ico, relTime, moisLisible, barresMensuelles.

const state = { id: null, figures: [] };

// ── Répertoire ──────────────────────────────────────────────────────────────

function renderList() {
  const q = ($("#figSearch").value || "").toLowerCase().trim();
  const shown = state.figures.filter((f) =>
    !q || f.full_name.toLowerCase().includes(q) || (f.handle || "").toLowerCase().includes(q));

  $("#figList").innerHTML = shown.length
    ? shown.map((f) => `
      <button class="referent referent--face" data-id="${f.id}" aria-pressed="${state.id === f.id}">
        ${portrait(f.full_name, f.handle)}
        <span>
          <span class="referent__label">${escapeHtml(f.full_name)}</span>
          <span class="referent__meta">${f.n_declarations ? `${fmtNum(f.n_declarations)} déclaration${f.n_declarations > 1 ? "s" : ""}` : "aucune déclaration"}, ${fmtNum(f.n_tweets)} tweets</span>
        </span>
      </button>`).join("")
    : '<p class="state">Aucune figure ne correspond.</p>';

  $("#figList").querySelectorAll(".referent").forEach((b) =>
    (b.onclick = () => load(+b.dataset.id)));
}


// ── Quand la collecte est muette ────────────────────────────────────────
// Le pire malentendu que cette page puisse produire : un compteur à 158 propos
// qu'on lit comme le rythme d'un locuteur, alors que la collecte de son compte
// échoue depuis des semaines. Douze comptes sur 113 étaient dans ce cas, dont
// un à seize échecs d'affilée, et rien ne le disait nulle part.
//
// Le seuil est celui de `/health/collectors` : deux échecs consécutifs. Un
// échec isolé arrive (quota, coupure) et ne veut rien dire.

const ECHECS_AVANT_ALERTE = 2;

function collecteMuette(f) {
  if (!f.handle || (f.collecte_echecs || 0) < ECHECS_AVANT_ALERTE) return "";
  const depuis = f.collecte_le ? `, dernière collecte réussie ${relTime(f.collecte_le)}` : "";
  return `<p class="caveat">
    <span class="caveat__mention">Collecte interrompue</span>
    La collecte de <span class="nowrap">@${escapeHtml(f.handle)}</span> échoue depuis
    ${f.collecte_echecs} passes${escapeHtml(depuis)}. Ce qui suit est donc incomplet :
    l’absence de propos récents ne veut pas dire qu’il n’y en a pas eu.
    ${f.collecte_erreur ? `<span class="caveat__cause">${escapeHtml(f.collecte_erreur)}</span>` : ""}</p>`;
}


// ── Rendu ───────────────────────────────────────────────────────────────────

function render(d) {
  const f = d.figure, s = d.stats;

  // Le portrait, en tête. Une fiche de personne sans visage est le seul écran
  // du produit qui pouvait en porter un et n'en portait pas.
  $("#detail").innerHTML = `
    <header class="profil">
      ${portrait(f.full_name, f.handle)}
      <div>
        <p class="overline">${ico("locuteurs")} Fiche</p>
        <h1 class="hero-title profil__nom">${escapeHtml(f.full_name)}</h1>
        <div class="entry__foot">
          <span class="tag">${escapeHtml(f.group_code)}</span>
          ${f.famille && f.famille.toLowerCase() !== (f.group_code || "").toLowerCase()
            ? `<span class="tag">${escapeHtml(f.famille)}</span>` : ""}
          ${f.role ? `<span class="tag">${escapeHtml(f.role)}</span>` : ""}
          ${mandat(f.departement, f.circo)
            ? `<span class="tag">${escapeHtml(mandat(f.departement, f.circo))}</span>` : ""}
          ${f.handle ? `<a class="handle" href="https://x.com/${f.handle}" target="_blank" rel="noopener">@${escapeHtml(f.handle)}</a>` : ""}
        </div>
        <div class="statbar">
          <span class="statbar__item"><span class="statbar__n">${fmtNum(s.n_posts)}</span> tweets en base</span>
          <span class="statbar__item"><span class="statbar__n" id="statDecl">…</span> déclarations au registre</span>
          <span class="statbar__item"><span class="statbar__n" id="statEnjeux">…</span> enjeux</span>
          <span class="statbar__item"><span class="statbar__n statbar__n--accent" id="statEcarts">…</span> écarts retenus</span>
        </div>
      </div>
    </header>

    ${collecteMuette(f)}

    <div class="band"><h2>Ses positions sur les enjeux</h2><span class="spacer"></span><p id="posMeta"></p></div>
    <div id="positions"><p class="state state--inline">Chargement…</p></div>

    <div class="band"><h2>Ses tweets en base, mois par mois</h2><span class="spacer"></span>
      <p>Ce que la collecte a ramené, pas ce que la figure a publié.</p></div>
    <div id="couverture"><p class="state state--inline">Chargement…</p></div>`;

  renderPositions(f.id);
  renderCouverture(f.id);
}

function positionLigne(p, avant) {
  const change = avant && avant.position !== p.position;
  return `<article class="position">
    <div class="position__head">
      <span class="stamp">${jourLong(p.date)}</span>
      <span class="tag${change ? " tag--theme" : ""}">${escapeHtml(p.label)}</span>
      ${p.valeur != null ? `<span class="tag">${p.valeur}${p.unite ? " " + escapeHtml(p.unite) : ""}</span>` : ""}
      <span class="spacer"></span>
      ${p.source?.url ? `<a class="source-link" href="${escapeHtml(p.source.url)}" target="_blank" rel="noopener">ouvrir sur X ↗</a>` : ""}
    </div>
    <p class="position__q">${escapeHtml(p.verbatim)}</p>
  </article>`;
}

function enjeuBloc(e) {
  const n = e.positions.length;
  const an = (p) => (p.date ? p.date.slice(0, 4) : "");
  const bornes = an(e.positions[0]) === an(e.positions[n - 1]) ? an(e.positions[0]) : `${an(e.positions[0])} à ${an(e.positions[n - 1])}`;
  const dernier = e.positions[n - 1];
  return `<details class="fig-enjeu"${e.crans > 1 ? " open" : ""}>
    <summary><span class="fig-enjeu__titre">${escapeHtml(e.titre)}</span>
      <span class="tag">${escapeHtml(dernier.label)}</span>
      <span class="sujet__meta">${n} déclaration${n > 1 ? "s" : ""}, ${bornes}${
        e.crans > 1 ? `, ${e.crans} positions différentes` : ""}</span></summary>
    <p class="sujet__meta">${escapeHtml(e.question)} <a href="enjeux.html?e=${encodeURIComponent(e.slug)}">Voir toutes les figures</a></p>
    ${e.positions.map((p, i) => positionLigne(p, e.positions[i - 1])).join("")}
  </details>`;
}

async function renderPositions(id) {
  const host = $("#positions");
  try {
    const d = await fetchJSON(`/figures/${id}/positions`);
    if (state.id !== id || !$("#positions")) return;
    if (!d.enjeux.length) {
      host.innerHTML = '<p class="state state--inline">Aucune position lue dans ses tweets sur les enjeux du référentiel.</p>';
      ["#statDecl", "#statEnjeux", "#statEcarts"].forEach((i) => ($(i).textContent = "0"));
      return;
    }
    $("#posMeta").textContent = "Lues dans ses tweets, dans l’ordre du temps.";
    $("#statDecl").textContent = fmtNum(d.declarations);
    $("#statEnjeux").textContent = d.enjeux.length;
    $("#statEcarts").textContent = d.ecarts.total;
    const ec = d.ecarts.items;
    host.innerHTML = `${ec.length ? `<p class="section-label">Écarts retenus par les juges</p>${ec.map((e) => ecartCarte(e)).join("")}` : ""}
      ${d.mouvements_faibles ? `<p class="sujet__meta">${fmtNum(d.mouvements_faibles)} mouvement${d.mouvements_faibles > 1 ? "s" : ""} faible${d.mouvements_faibles > 1 ? "s" : ""} relevé${d.mouvements_faibles > 1 ? "s" : ""} par ailleurs, à voir sur <a href="ecarts.html">la page des écarts</a>.</p>` : ""}
      <p class="section-label">Enjeu par enjeu</p>
      ${d.enjeux.map(enjeuBloc).join("")}`;
  } catch (err) {
    host.innerHTML = `<p class="state state--error">Les positions ne se sont pas chargées (${escapeHtml(err.message)}).</p>`;
  }
}


// La couverture : sans elle, l'absence d'écart chez une figure se lit comme de la constance,
// alors qu'elle tient souvent à un historique que la collecte n'a pas pu ramener.
async function renderCouverture(id) {
  const host = $("#couverture");
  try {
    const d = await fetchJSON(`/figures/${id}/couverture`);
    if (state.id !== id || !$("#couverture")) return;
    if (!d.points.length) {
      host.innerHTML = '<p class="state state--inline">Aucun tweet en base pour cette figure.</p>';
      return;
    }
    const vides = d.points.filter((p) => !p.n).length;
    host.innerHTML = `<p class="chart__lecture">${fmtNum(d.tweets)} tweets de ${moisLisible(d.points[0].mois)} à ${
      moisLisible(d.points[d.points.length - 1].mois)}${vides ? `, dont ${vides} mois sans aucun tweet en base` : ""}. ${
      fmtNum(d.declarations)} y portent une position.</p>${barresMensuelles(d.points, { unite: "tweets" })}`;
  } catch (err) {
    host.innerHTML = `<p class="state state--error">La couverture ne s’est pas chargée (${escapeHtml(err.message)}).</p>`;
  }
}

async function load(id) {
  state.id = id;
  // L'adresse suit le locuteur affiché. Sans ça, aucune fiche n'était
  // citable : la page ouvrait toujours sur le premier nom de la liste, et un
  // observatoire dont on ne peut pas lier une fiche ne se cite pas.
  history.replaceState(null, "", `figure.html?id=${id}`);
  renderList();
  $("#detail").innerHTML = '<p class="state">Chargement…</p>';
  try {
    render(await fetchJSON(`/figures/${id}?limit=1&offset=0`));
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
    // Le locuteur demandé dans l'adresse ; à défaut, le premier qui a parlé.
    const voulu = +new URLSearchParams(location.search).get("id") || null;
    const cible = state.figures.find((f) => f.id === voulu)
      || state.figures.find((f) => f.n_declarations > 0);
    if (cible) load(cible.id);
  } catch (e) {
    $("#figList").innerHTML = `<p class="state state--error">Répertoire indisponible (${e.message}).</p>`;
  }
}

let searchTimer;
$("#figSearch").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(renderList, 200); };
init();
