// Coulisses : l'état de la chaîne, en tableaux. Une seule requête, /etat.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, jourLong.

const TYPES = { temps: "Dans le temps", programme: "Contre le programme", parti: "Dans le parti", chiffre: "Chiffres" };
const DECISIONS = [["retenu", "Retenus"], ["faible", "Faibles"], ["ecarte", "Écartés"], ["attente", "En attente"]];

const ligne = (cellules, entete = false) =>
  `<tr>${cellules.map((c, i) => (i === 0 && !entete ? `<th scope="row">${c}</th>` : entete ? `<th scope="col">${c}</th>` : `<td>${c}</td>`)).join("")}</tr>`;

function rendre(d) {
  const c = d.collecte;
  $("#collecteMeta").textContent = `${fmtNum(c.tweets)} tweets, dernier publié le ${jourLong(c.dernier_tweet)}`;
  $("#voies").innerHTML = `<thead>${ligne(["Voie de collecte", "Tweets", "Dernier tweet"], true)}</thead><tbody>${
    c.voies.map((v) => ligne([escapeHtml(v.libelle), fmtNum(v.tweets), jourLong(v.dernier)])).join("")}</tbody>`;

  const r = d.registre;
  $("#registre").innerHTML = `<thead>${ligne(["Registre", "Nombre"], true)}</thead><tbody>${[
    ["Tweets lus", r.tweets_lus], ["Déclarations", r.total], ["Avec une position retenue", r.avec_position],
    ["Jugées douteuses", r.douteuses], ["Sans position", r.sans_position],
  ].map(([k, v]) => ligne([k, fmtNum(v)])).join("")}</tbody>`;

  $("#ecarts").innerHTML = `<thead>${ligne(["Écarts", ...DECISIONS.map(([, l]) => l)], true)}</thead><tbody>${
    Object.entries(TYPES).map(([t, l]) => ligne([l, ...DECISIONS.map(([k]) => fmtNum((d.ecarts[t] || {})[k] || 0))])).join("")}</tbody>`;

  const a = d.archivage;
  $("#archivage").textContent = `${fmtNum(a.archives)} tweets archivés sur Wayback sur les ${fmtNum(a.tweets_a_archiver)} qui portent une déclaration retenue. `
    + "Les tweets des écarts retenus passent en premier.";

  const dep = d.depense_30_jours;
  $("#depenseMeta").textContent = `${dep.total.toLocaleString("fr-FR")} $ en tout`;
  $("#depense").innerHTML = `<thead>${ligne(["Tâche", "Modèle", "Appels", "Coût ($)"], true)}</thead><tbody>${
    dep.detail.map((x) => ligne([escapeHtml(x.tache), escapeHtml(x.modele), fmtNum(x.appels), x.cout.toLocaleString("fr-FR")])).join("")}</tbody>`;

  const cov = d.couverture;
  const pleines = cov.figures.filter((f) => f.mois_couverts >= cov.mois * 0.9).length;
  $("#couvMeta").textContent = `${pleines} figures sur ${cov.figures.length} couvertes à 90 % des ${cov.mois} mois`;
  $("#couverture").innerHTML = `<thead>${ligne(["Figure", "Parti", "Tweets depuis 2022", "Mois couverts"], true)}</thead><tbody>${
    cov.figures.map((f) => ligne([`<a href="figure.html?id=${f.id}">${escapeHtml(f.nom)}</a>`, escapeHtml(f.groupe || ""),
      fmtNum(f.tweets), `${f.mois_couverts} sur ${cov.mois}`])).join("")}</tbody>`;
}

fetchJSON("/etat").then(rendre).catch((err) => {
  $("#collecteMeta").textContent = "";
  $("#voies").innerHTML = `<caption>L’état de la chaîne ne s’est pas chargé (${escapeHtml(err.message)}).</caption>`;
});
