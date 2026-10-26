// La revue de la semaine : de quoi l'extrême droite a parlé sur X, et ce qui a
// bougé. Chaque sujet montre les tweets qui le fondent ; aucun chiffre n'est
// donné sans la phrase qui le lit.
//
// Elle remplace la revue rédigée par la chaîne payante, gelée depuis octobre
// 2026 : celle-ci n'écrit rien, elle assemble ce que la chaîne a établi.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, exactDate, sourceCard.

const params = new URLSearchParams(location.search);
const TYPES = { temps: "une même figure dans le temps", programme: "contre le programme du parti",
  parti: "deux voix du même parti", chiffre: "une même mesure, deux chiffres" };
const PARTIS = { RN: "RN", UDR: "UDR", FIGURE: "autres figures" };

const majuscule = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");
const jour = (iso, opts = {}) => new Date(iso).toLocaleDateString("fr-FR",
  { day: "numeric", month: "long", timeZone: "Europe/Paris", ...opts });
const pct = (x) => `${fmtNum(Math.round(x))} %`;
const pluriel = (n, mot) => `${fmtNum(n)} ${mot}${n > 1 ? "s" : ""}`;

function lecture(r) {
  const v = r.volume;
  const enCours = new Date(r.au) > new Date();
  const avant = r.volume_avant && r.volume_avant.tweets
    ? `, contre ${fmtNum(r.volume_avant.tweets)} la semaine d’avant` : "";
  const partis = Object.entries(v.partis).slice(0, 3)
    .map(([p, n]) => `${PARTIS[p] || p} ${fmtNum(n)}`).join(", ");
  return `${enCours ? "Semaine en cours. " : ""}${pluriel(v.tweets, "tweet")} de ${pluriel(v.figures, "figure")}${avant}`
    + `, retweets non comptés. Par origine&nbsp;: ${escapeHtml(partis)}.`;
}

function voix(s) {
  const noms = s.voix.map((x) => `${escapeHtml(x.nom)} (${x.tweets})`);
  const reste = s.n_figures - s.voix.length;
  return noms.join(", ") + (reste > 0 ? ` et ${pluriel(reste, "autre")}` : "");
}

function sujet(s) {
  const periode = s.du && s.au ? (jour(s.du) === jour(s.au) ? `le ${jour(s.du)}` : `du ${jour(s.du)} au ${jour(s.au)}`) : "";
  return `<article class="une">
    <h2 class="card-title">${escapeHtml(majuscule(s.libelle))}</h2>
    <p class="sujet__meta">${pluriel(s.n_tweets, "tweet")} de ${pluriel(s.n_figures, "figure")}, ${periode}.
      ${s.voix.length ? `Surtout ${voix(s)}.` : ""}</p>
    ${s.tweets.map(sourceCard).join("")}
    ${s.n_tweets > s.tweets.length ? `<p class="une__plus"><button class="btn btn--ghost btn--sm" data-sujet="${s.id}"
        aria-expanded="false">Les ${fmtNum(s.n_tweets)} tweets du sujet</button></p>
      <div class="une__tous" id="tous-${s.id}" hidden></div>` : ""}
  </article>`;
}

function tableauTendances(titre, lignes) {
  if (!lignes.length) return "";
  return `<div class="table-scroll mt-6"><table class="tableau">
    <caption class="sr-only">${escapeHtml(titre)}</caption>
    <thead><tr><th scope="col">${escapeHtml(titre)}</th><th scope="col">Cette semaine</th>
      <th scope="col">Quatre semaines d’avant</th><th scope="col">Écart</th></tr></thead>
    <tbody>${lignes.map((t) => `<tr${Math.abs(t.ecart) >= 10 ? ' class="tableau__marque"' : ""}>
      <th scope="row">${escapeHtml(t.label)}</th><td>${pct(t.part)}</td><td>${pct(t.reference)}</td>
      <td>${t.ecart > 0 ? "+" : "−"}${fmtNum(Math.abs(Math.round(t.ecart)))} points</td></tr>`).join("")}</tbody>
  </table></div>`;
}

function tendances(r) {
  if (!r.familles.length && !r.marqueurs.length) {
    return '<p class="state state--inline">Rien ne s’écarte de plus de deux points de la moyenne des quatre semaines d’avant.</p>';
  }
  const fort = r.familles[0];
  const phrase = fort ? `<p class="dek lede-first">${escapeHtml(fort.label)} ${fort.ecart > 0 ? "pèse" : "ne pèse plus que"}
    ${pct(fort.part)} des tweets cette semaine, contre ${pct(fort.reference)} en moyenne les quatre semaines d’avant.</p>` : "";
  return phrase + tableauTendances("Thème", r.familles) + tableauTendances("Marqueur du discours", r.marqueurs);
}

function enjeux(r) {
  if (!r.declarations) return '<p class="state state--inline">Aucune déclaration relevée cette semaine.</p>';
  const lignes = r.enjeux.map((e) => `<tr><th scope="row"><a class="source-link" href="enjeux.html?e=${
    encodeURIComponent(e.slug)}">${escapeHtml(e.titre)}</a></th><td>${fmtNum(e.declarations)}</td><td>${fmtNum(e.figures)}</td></tr>`);
  return `<p class="dek lede-first">${pluriel(r.declarations, "déclaration")} relevée${r.declarations > 1 ? "s" : ""} dans les tweets de la semaine${
    r.hors_liste ? `, dont ${fmtNum(r.hors_liste)} hors des 44 enjeux suivis` : ""}. Les enjeux où le plus de figures
    se sont prononcées&nbsp;:</p>
    ${lignes.length ? `<div class="table-scroll mt-6"><table class="tableau">
      <caption class="sr-only">Déclarations par enjeu</caption>
      <thead><tr><th scope="col">Enjeu</th><th scope="col">Déclarations</th><th scope="col">Figures</th></tr></thead>
      <tbody>${lignes.join("")}</tbody></table></div>` : ""}`;
}

function ecarts(r) {
  if (!r.ecarts.length) {
    return '<p class="state state--inline">Aucun écart retenu ni signalé comme faible cette semaine.</p>';
  }
  return r.ecarts.map((e) => `<div class="ecart">
    <p class="ecart__titre">${escapeHtml(e.enjeu)}&nbsp;: ${escapeHtml(TYPES[e.type] || e.type)}</p>
    <p class="sujet__meta">${escapeHtml([e.figure_a, e.figure_b].filter(Boolean).join(" et "))}, ${
      e.auto === "retenu" ? "retenu par les deux juges" : "mouvement faible"}.</p>
    ${e.explication ? `<p class="dek lede-first">${escapeHtml(e.explication)}</p>` : ""}
  </div>`).join("");
}

function lus(r) {
  return r.plus_vus.map((t) => `<div class="une__lu">
    <p class="sujet__meta"><span class="speaker">${escapeHtml(t.figure)}</span>, ${
      pluriel(t.likes || 0, "j’aime")}, ${pluriel(t.partages || 0, "partage")}</p>
    ${sourceCard(t)}</div>`).join("") || '<p class="state state--inline">Aucun tweet cette semaine.</p>';
}

async function ouvrir(bouton) {
  const id = bouton.dataset.sujet;
  const cible = $(`#tous-${id}`);
  const ouvert = bouton.getAttribute("aria-expanded") === "true";
  bouton.setAttribute("aria-expanded", String(!ouvert));
  cible.hidden = ouvert;
  if (ouvert || cible.dataset.charge) return;
  cible.innerHTML = '<p class="state state--inline">Chargement…</p>';
  try {
    const d = await fetchJSON(`/themes/sujets/${id}`);
    cible.innerHTML = d.items.map((t) => sourceCard(t.source)).join("");
    cible.dataset.charge = "1";
  } catch (e) {
    cible.innerHTML = `<p class="state state--error">Les tweets ne se sont pas chargés (${escapeHtml(e.message)}).</p>`;
  }
}

function render(r) {
  const du = jour(r.du, { year: "numeric" });
  document.title = `Semaine du ${du}, ED Mediawatch`;
  $("#titre").textContent = `La semaine du ${du} sur X`;
  $("#semaine").innerHTML = r.semaines.map((s) =>
    `<option value="${s}"${s === r.semaine ? " selected" : ""}>${escapeHtml(s.replace("-W", ", semaine "))}</option>`).join("");
  $("#lecture").innerHTML = lecture(r);
  $("#une").innerHTML = r.une.map(sujet).join("")
    || '<p class="state state--inline">Pas encore de sujets calculés pour cette semaine.</p>';
  $("#autres").innerHTML = r.autres_sujets.length
    ? `Aussi cette semaine&nbsp;: ${r.autres_sujets.map((s) => `${escapeHtml(s.libelle)} (${fmtNum(s.n_tweets)})`).join(", ")}.` : "";
  $("#tendances").innerHTML = tendances(r);
  $("#enjeux").innerHTML = enjeux(r);
  $("#ecarts").innerHTML = ecarts(r);
  $("#lus").innerHTML = lus(r);
  document.querySelectorAll("[data-sujet]").forEach((b) => (b.onclick = () => ouvrir(b)));
}

async function load(semaine) {
  try {
    const r = await fetchJSON(`/revue${semaine ? `?semaine=${encodeURIComponent(semaine)}` : ""}`);
    if (!r.semaine) {
      $("#lecture").textContent = "Aucune semaine n’a encore été calculée.";
      return;
    }
    render(r);
  } catch (e) {
    $("#lecture").innerHTML = `<span class="state--error">La revue n’a pas pu être chargée (${escapeHtml(e.message)}).</span>`;
  }
}

$("#semaine").onchange = (e) => {
  history.replaceState(null, "", `?semaine=${e.target.value}`);
  load(e.target.value);
};
load(params.get("semaine"));
