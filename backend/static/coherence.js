// L'indice de cohérence : une ligne par parti, puis le RN enjeu par enjeu. Définition dans
// backend/src/services/analysis/coherence.py ; la page la redit en tête.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum.

const NOMS = { RN: "Rassemblement national", UDR: "UDR", Reconquete: "Reconquête" };
const SEUIL_FAIBLE = 70;   // en dessous, la ligne est marquée

const mesure = (m) => (m ? `${m.part}<span class="sujet__meta"> (${fmtNum(m.n)} sur ${fmtNum(m.sur)})</span>` : '<span class="sujet__meta">n. d.</span>');

function partiHtml(code, p) {
  if (p.indice == null) {
    return `<div class="band"><h2>${NOMS[code]}</h2></div>
      <p class="dek">Pas d’indice : ${p.enjeux_mesures} enjeu${p.enjeux_mesures > 1 ? "x" : ""} mesuré${p.enjeux_mesures > 1 ? "s" : ""},
      il en faut cinq. Les déclarations de ce parti sont encore trop peu nombreuses dans le registre.</p>`;
  }
  return `<div class="band"><h2>${NOMS[code]}</h2><span class="spacer"></span><p>${p.enjeux_mesures} enjeux mesurés</p></div>
    <div class="statbar">
      <span class="statbar__item"><span class="statbar__n">${p.indice}</span> indice sur 100</span>
      <span class="statbar__item">Alignement ${mesure(p.alignement)}</span>
      <span class="statbar__item">Constance ${mesure(p.constance)}</span>
      <span class="statbar__item">Programme ${mesure(p.programme)}</span>
    </div>`;
}

function enjeuxHtml(lignes) {
  const mesurees = lignes.filter((x) => x.indice != null);
  if (!mesurees.length) return "<caption>Aucun enjeu mesuré.</caption>";
  return `<thead><tr><th scope="col">Enjeu</th><th scope="col">Indice</th><th scope="col">Alignement</th>
      <th scope="col">Constance</th><th scope="col">Programme</th><th scope="col">Position majoritaire</th></tr></thead>
    <tbody>${mesurees.map((x) => `<tr${x.indice < SEUIL_FAIBLE ? ' class="tableau__marque"' : ""}>
      <th scope="row"><a href="enjeux.html?e=${encodeURIComponent(x.enjeu)}">${escapeHtml(x.titre)}</a></th>
      <td>${x.indice}</td><td>${mesure(x.alignement)}</td><td>${mesure(x.constance)}</td><td>${mesure(x.programme)}</td>
      <td>${escapeHtml(x.position_majoritaire_label || "")}</td></tr>`).join("")}</tbody>`;
}

fetchJSON("/coherence").then((r) => {
  $("#partis").innerHTML = ["RN", "UDR", "Reconquete"].map((p) => partiHtml(p, r.partis[p])).join("");
  $("#enjeux").innerHTML = enjeuxHtml(r.partis.RN.enjeux);
}).catch((err) => {
  $("#partis").innerHTML = `<p class="state state--error">L’indice ne s’est pas chargé (${escapeHtml(err.message)}).</p>`;
});
