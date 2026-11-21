// L'accueil : ce que le registre contient, les écarts les plus nets, les dernières déclarations,
// et une entrée par enjeu. Tout vient du registre des déclarations, donc des tweets.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, jourLong, ecartCarte, sourceCard.

const annee = (iso) => (iso ? String(iso).slice(0, 4) : "");

function phraseEtat(e) {
  return `${fmtNum(e.declarations)} déclarations lues dans ${fmtNum(e.tweets)} tweets de ${fmtNum(e.figures_suivies)} figures, de ${
    annee(e.debut)} à ${annee(e.fin)}, rangées sur ${e.enjeux} enjeux. Dernier tweet collecté le ${jourLong(e.dernier_tweet)}. `
    + `Les juges retiennent ${fmtNum(e.faits_retenu)} écarts et ${fmtNum(e.faits_faible)} mouvements faibles.`;
}

function declaration(d) {
  return `<article class="position">
    <div class="position__head">
      <a class="speaker" href="figure.html?id=${d.figure_id}">${escapeHtml(d.figure)}</a>
      ${d.parti ? `<span class="tag">${escapeHtml(d.parti)}</span>` : ""}
      <span class="stamp">${jourLong(d.date)}</span>
      <span class="spacer"></span>
      ${d.source?.url ? `<a class="source-link" href="${escapeHtml(d.source.url)}" target="_blank" rel="noopener">ouvrir sur X ↗</a>` : ""}
    </div>
    <p class="decl-ligne"><a href="enjeux.html?e=${encodeURIComponent(d.enjeu)}">${escapeHtml(d.titre)}</a>
      <span class="tag">${escapeHtml(d.label)}</span></p>
    <p class="position__q">${escapeHtml(d.verbatim)}</p>
  </article>`;
}

async function load() {
  const rate = (hote, quoi) => (err) => {
    $(hote).innerHTML = `<p class="state state--error">${quoi} (${escapeHtml(err.message)}).</p>`;
  };
  fetchJSON("/enjeux/etat").then((e) => { $("#etat").textContent = phraseEtat(e); })
    .catch(() => { $("#etat").textContent = ""; });
  fetchJSON("/ecarts/faits?juge=retenu&limit=3&offset=0").then((r) => {
    $("#ecartsMeta").textContent = `${fmtNum(r.total)} faits, les trois plus nets`;
    $("#ecarts").innerHTML = r.items.map((e) => ecartCarte(e)).join("")
      || '<p class="state state--inline">Aucun écart retenu pour l’instant.</p>';
  }).catch(rate("#ecarts", "Les écarts ne se sont pas chargés"));
  fetchJSON("/enjeux/recentes?limit=10").then((items) => {
    $("#recentes").innerHTML = items.map(declaration).join("")
      || '<p class="state state--inline">Aucune déclaration au registre.</p>';
  }).catch(rate("#recentes", "Les déclarations ne se sont pas chargées"));
  fetchJSON("/enjeux").then((liste) => {
    $("#enjeux").innerHTML = [...liste].sort((a, b) => b.positions - a.positions).slice(0, 12).map((e) => `
      <a class="entry entry--lien" href="enjeux.html?e=${encodeURIComponent(e.slug)}">
        <span class="entry__titre">${escapeHtml(e.titre)}</span>
        <span class="stamp">${fmtNum(e.positions)} déclarations, ${e.figures} figures</span>
      </a>`).join("");
  }).catch(rate("#enjeux", "Les enjeux ne se sont pas chargés"));
}

load();
