// Recherche dans le registre, entièrement dans le navigateur : l'index des déclarations (/enjeux/recherche)
// est chargé une fois, puis filtré à chaque frappe. Marche aussi sur le site figé.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, jourLong.

const MAX = 100;
const sansAccent = (t) => (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const etat = { index: null, lignes: [] };

function preparer(d) {
  etat.index = d;
  // Une ligne : [id, date, figure, enjeu, position, passage, lien], plus le texte où chercher.
  etat.lignes = d.declarations.map((x) => {
    const [, , fid, enjeu] = x;
    const fig = d.figures[fid] || ["?", ""];
    return { x, texte: sansAccent(`${x[5]} ${fig[0]} ${d.enjeux[enjeu].titre}`) };
  });
  const options = (sel, paires) => { sel.innerHTML += paires.map(([v, l]) => `<option value="${escapeHtml(v)}">${escapeHtml(l)}</option>`).join(""); };
  options($("#figure"), Object.entries(d.figures).sort((a, b) => a[1][0].localeCompare(b[1][0], "fr")).map(([i, f]) => [i, f[0]]));
  options($("#enjeu"), Object.entries(d.enjeux).filter(([s]) => d.declarations.some((x) => x[3] === s))
    .sort((a, b) => a[1].titre.localeCompare(b[1].titre, "fr")).map(([s, e]) => [s, e.titre]));
  const annees = [...new Set(d.declarations.map((x) => (x[1] || "").slice(0, 4)).filter(Boolean))].sort().reverse();
  options($("#annee"), annees.map((a) => [a, a]));
  const voulu = new URLSearchParams(location.search);
  ["q", "figure", "enjeu", "annee"].forEach((k) => { if (voulu.get(k)) $(`#${k}`).value = voulu.get(k); });
}

function ligne({ x }) {
  const d = etat.index;
  const [, date, fid, enjeu, position, passage, lien] = x;
  const fig = d.figures[fid] || ["?", ""];
  return `<article class="position">
    <div class="position__head">
      <a class="speaker" href="figure.html?id=${fid}">${escapeHtml(fig[0])}</a>
      ${fig[1] ? `<span class="tag">${escapeHtml(fig[1])}</span>` : ""}
      <span class="stamp">${jourLong(date)}</span><span class="spacer"></span>
      ${lien ? `<a class="source-link" href="${escapeHtml(lien)}" target="_blank" rel="noopener">ouvrir sur X ↗</a>` : ""}
    </div>
    <p class="decl-ligne"><a href="enjeux.html?e=${encodeURIComponent(enjeu)}">${escapeHtml(d.enjeux[enjeu].titre)}</a>
      <span class="tag">${escapeHtml(d.enjeux[enjeu].crans[position] || position)}</span></p>
    <p class="position__q">${escapeHtml(passage)}</p>
  </article>`;
}

function filtrer() {
  const mots = sansAccent($("#q").value).split(/\s+/).filter(Boolean);
  const fig = $("#figure").value, enj = $("#enjeu").value, an = $("#annee").value;
  const trouves = etat.lignes.filter(({ x, texte }) =>
    (!fig || String(x[2]) === fig) && (!enj || x[3] === enj) && (!an || (x[1] || "").startsWith(an))
    && mots.every((m) => texte.includes(m)));
  $("#compte").textContent = `${fmtNum(trouves.length)} déclaration${trouves.length > 1 ? "s" : ""}${
    trouves.length > MAX ? `, les ${MAX} plus récentes affichées` : ""}`;
  $("#resultats").innerHTML = trouves.slice(0, MAX).map(ligne).join("")
    || '<p class="state state--inline">Aucune déclaration ne correspond.</p>';
  const p = new URLSearchParams();
  [["q", $("#q").value], ["figure", fig], ["enjeu", enj], ["annee", an]].forEach(([k, v]) => v && p.set(k, v));
  history.replaceState(null, "", p.toString() ? `?${p}` : location.pathname);
}

let minuteur;
fetchJSON("/enjeux/recherche").then((d) => {
  preparer(d);
  filtrer();
  $("#q").oninput = () => { clearTimeout(minuteur); minuteur = setTimeout(filtrer, 150); };
  ["figure", "enjeu", "annee"].forEach((k) => { $(`#${k}`).onchange = filtrer; });
}).catch((err) => {
  $("#resultats").innerHTML = `<p class="state state--error">Le registre ne s’est pas chargé (${escapeHtml(err.message)}).</p>`;
});
