// Aujourd'hui — ce qui compte, et pourquoi.
//
// Un seul chemin : une déclaration qui compte → son sujet → sa source. La page
// ne montre ni « le plus récent » (un observatoire du propos dans la durée qui
// trierait par date redeviendrait un fil) ni « le plus aimé » (les likes bruts
// classent un militant devant la cheffe du parti). Elle montre l'inhabituel, le
// repris, le contredit, l'engageant — et le dit, à côté de chaque ligne, pour
// qu'un lecteur puisse ne pas être d'accord avec le classement.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, relTime, exactDate,
// kicker, duree, periode, repartition, nomSujet, ico.

const lien = (id) => `sujet.html?id=${id}`;

// ── Une déclaration qui compte ─────────────────────────────────────────────
// Le visage, le nom, la date ; le propos dans les mots du locuteur ; puis la
// raison, en petit et en gris — c'est elle qui justifie la place, et c'est elle
// qu'on contestera si le classement est faux.

function face(d) {
  const initiales = (d.speaker || "?").split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  const src = d.photo_url || (d.handle ? `https://unavatar.io/x/${d.handle}?fallback=false` : "");
  const repli = `<span class="face face--txt">${escapeHtml(initiales)}</span>`;
  return src
    ? `<img class="face" src="${src}" alt="" loading="lazy" width="28" height="28"
         onerror="this.outerHTML=this.dataset.fb" data-fb='${repli}' />`
    : repli;
}

function declaration(d) {
  const sujet = d.subject_id
    ? `<a class="decl__sujet" href="${lien(d.subject_id)}">${nomSujet({ label: d.subject_label, status: d.subject_status })} ${ico("source")}</a>`
    : "";
  return `<article class="decl">
    <p class="entry__head">
      ${face(d)}
      <span class="speaker">${escapeHtml(d.speaker)}</span>
      ${d.party ? `<span class="tag">${escapeHtml(d.party)}</span>` : ""}
      <span class="spacer"></span>
      <span class="stamp">${escapeHtml(exactDate(d.published_at))}</span>
    </p>
    <p class="decl__texte">« ${escapeHtml(d.verbatim || d.text || "")} »</p>
    <p class="decl__pourquoi">${(d.why || []).map(escapeHtml).join(" · ") || "&nbsp;"}</p>
    <p class="entry__foot">
      ${sujet}
      <span class="spacer"></span>
      ${d.url ? `<a class="source-link" href="${escapeHtml(d.url)}" target="_blank"
          rel="noopener">vérifier la source ${ico("source")}</a>` : ""}
    </p>
  </article>`;
}

function renderAujourdhui(d) {
  const items = d.items || [];
  if (!items.length) {
    $("#aujourdhui").innerHTML = `<p class="state">
      <span class="state__title">Rien à signaler sur les ${d.jours} derniers jours</span>
      <span class="state__hint">Le classement se recalcule à chaque passe — voir
      <a class="source-link" href="atelier.html">les coulisses</a>.</span></p>`;
    return;
  }
  $("#aujourdhui").innerHTML = items.map(declaration).join("");
}

// ── La revue de la semaine ──────────────────────────────────────────────────

function renderRevue(items) {
  const host = $("#revue");
  if (!items.length) { host.hidden = true; return; }
  host.hidden = false;
  host.innerHTML = `
    <div class="band"><h2>La revue de la semaine</h2><span class="spacer"></span>
      <p>Sujet par sujet, chaque paragraphe cite ce qu’il rapporte.</p></div>
    <div class="tiles">${items.slice(0, 3).map((r) => `
      <a class="tile" href="revue.html?id=${r.id}">
        ${kicker(r.theme, r.status === "brouillon" ? "brouillon" : "relue")}
        <h3 class="card-title">${escapeHtml(r.title || "sans titre")}</h3>
        <p class="dek">${nomSujet({ label: r.subject_label || "", status: r.subject_status })}</p>
        <p class="tile__foot"><span class="stamp">${fmtNum(r.n_sources)} déclarations citées</span></p>
      </a>`).join("")}</div>
    <p class="mt-4"><a class="btn btn--sm" href="revue.html">Toutes les revues ${ico("source")}</a></p>`;
}

// ── Les sujets qui bougent ──────────────────────────────────────────────────
// Une tuile par sujet : le surtitre, le titre, la répartition de la parole en
// mots, et le dernier propos. Classés par le score du sujet, pas par sa taille.

function tuile(s) {
  const l = s.latest;
  return `<a class="tile" href="${lien(s.id)}">
    ${kicker(s.theme, `${s.n_speakers} voix · ${duree(s.span_days)}`)}
    <h3 class="card-title">${nomSujet(s)}</h3>
    ${repartition(s.frise, s.n_claims)}
    ${l ? `<p class="stamp mt-3">${escapeHtml(relTime(l.published_at))} · ${escapeHtml(l.speaker || "auteur inconnu")}</p>
           <p class="latest__q">« ${escapeHtml((l.text || "").slice(0, 160))} »</p>` : ""}
  </a>`;
}

// ── Chargement ──────────────────────────────────────────────────────────────

async function load() {
  const [decl, subj, revues] = await Promise.all([
    fetchJSON("/declarations?jours=7&limit=10").catch((e) => ({ items: [], err: e })),
    fetchJSON("/subjects?limit=9&confrontable=true").catch(() => ({ items: [] })),
    fetchJSON("/reviews?limit=3").catch(() => null),
  ]);
  if (decl.err) {
    $("#aujourdhui").innerHTML =
      `<p class="state state--error">Le classement n’a pas pu être chargé (${escapeHtml(decl.err.message)}).</p>`;
  } else {
    renderAujourdhui(decl);
  }
  renderRevue(revues?.items || []);
  $("#grid").innerHTML = (subj.items || []).map(tuile).join("")
    || `<p class="state">Aucun sujet nommé à plusieurs voix pour l’instant.</p>`;
  $("#stats").innerHTML = `<strong>${fmtNum(subj.total ?? 0)}</strong> sujets à plusieurs voix`;
}

load();
