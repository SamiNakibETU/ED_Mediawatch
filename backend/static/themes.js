// De quoi parle l'extrême droite sur X : un petit graphique par thème, tous à
// la même échelle, puis les tweets derrière chaque barre et les sujets de la
// semaine.
//
// Même échelle pour tous les thèmes, et c'est voulu : une échelle par panneau
// ferait paraître aussi haut un thème à 3 tweets par jour qu'un thème à 300.
// La comparaison entre thèmes est la question que la page pose.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, asDate, sourceCard.

const PAS = [
  ["heure", "Heure"], ["jour", "Jour"], ["semaine", "Semaine"], ["mois", "Mois"],
];
const state = { pas: "jour", parti: "", retweets: true, serie: null };
const majuscule = (t) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : "");

const fmtCase = (k, pas) => {
  if (pas === "heure") return `${asDate(k).toLocaleDateString("fr-FR", { day: "numeric", month: "short" })} ${k.slice(11, 13)} h`;
  if (pas === "mois") return asDate(`${k}-01`).toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
  const d = asDate(k).toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
  return pas === "semaine" ? `semaine du ${d}` : d;
};

function bornes(k, pas) {
  const d = asDate(pas === "mois" ? `${k}-01` : k);
  const f = new Date(d);
  if (pas === "heure") f.setUTCHours(f.getUTCHours() + 1);
  else if (pas === "jour") f.setUTCDate(f.getUTCDate() + 1);
  else if (pas === "semaine") f.setUTCDate(f.getUTCDate() + 7);
  else f.setUTCMonth(f.getUTCMonth() + 1);
  const iso = (x) => x.toISOString().slice(0, 19);
  return [iso(d), iso(f)];
}

function lecture(s) {
  const totaux = s.themes.map((t) => ({ ...t, n: s.cases.reduce((a, c) => a + c[t.code], 0) }));
  const tout = totaux.reduce((a, t) => a + t.n, 0);
  if (!tout) return "Aucun tweet classé sur cette période pour l’instant.";
  const politiques = totaux.filter((t) => t.code !== "autre").sort((a, b) => b.n - a.n);
  const pct = (n) => `${Math.round((100 * n) / tout)} %`;
  const [a, b] = politiques;
  return `${fmtNum(tout)} tweets sur la période. ${a ? `${a.label} vient en tête (${pct(a.n)})` : ""}${
    b ? `, devant ${b.label.toLowerCase()} (${pct(b.n)})` : ""}. Le reste de la parole (campagne, vie du parti, réactions) pèse ${
    pct(totaux.find((t) => t.code === "autre")?.n || 0)}.`;
}

function multiples(s) {
  const totaux = s.themes.map((t) => ({ ...t, n: s.cases.reduce((a, c) => a + c[t.code], 0) }));
  totaux.sort((a, b) => (a.code === "autre") - (b.code === "autre") || b.n - a.n);
  const max = Math.max(1, ...s.cases.flatMap((c) => s.themes.map((t) => c[t.code])));
  const tout = totaux.reduce((a, t) => a + t.n, 0) || 1;
  const n = s.cases.length || 1;
  const W = 1000, H = 56, gap = n > 120 ? 0 : 1, bw = Math.max(1, W / n - gap);

  const panneau = (t) => `<div class="multiple">
      <p class="multiple__titre">${escapeHtml(t.label)}<span>${fmtNum(t.n)} tweets, ${Math.round((100 * t.n) / tout)} %</span></p>
      <svg class="multiple__svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img"
           aria-label="${escapeHtml(t.label)} : ${fmtNum(t.n)} tweets">
        <line x1="0" y1="${H - 0.5}" x2="${W}" y2="${H - 0.5}" class="multiple__base" />
        ${s.cases.map((c, i) => {
          const v = c[t.code];
          if (!v) return "";
          const h = Math.max(1.5, (v / max) * (H - 4));
          return `<rect class="multiple__barre" data-case="${c.case}" data-theme="${t.code}" x="${(i * W) / n}" y="${H - h}"
                    width="${bw}" height="${h}"><title>${escapeHtml(fmtCase(c.case, s.pas))} : ${v} tweet${v > 1 ? "s" : ""}</title></rect>`;
        }).join("")}
      </svg>
    </div>`;

  const axe = s.cases.length
    ? `<div class="multiples__axe"><span>${escapeHtml(fmtCase(s.cases[0].case, s.pas))}</span>
         <span>${escapeHtml(fmtCase(s.cases[s.cases.length - 1].case, s.pas))}</span></div>` : "";
  return totaux.map(panneau).join("") + axe;
}

function tweetHtml(t) {
  const decls = (t.declarations || []).map((d) => `<p class="decl-ligne">
      <span class="decl-ligne__k">Déclaration</span>
      ${escapeHtml(d.titre || d.objet || "")}${d.position ? ` : ${escapeHtml(d.position)}` : ""}
    </p>`).join("");
  return `<article class="entry entry--plain">
    <p class="entry__head"><span class="speaker">${escapeHtml(t.figure)}</span>
      ${t.groupe ? `<span class="tag">${escapeHtml(t.groupe)}</span>` : ""}</p>
    ${sourceCard(t.source)}
    ${decls}
  </article>`;
}

async function ouvrirMoment(k, theme) {
  const [debut, fin] = bornes(k, state.pas);
  const p = new URLSearchParams({ debut, fin, theme, limit: 80 });
  if (state.parti) p.set("parti", state.parti);
  const label = state.serie.themes.find((t) => t.code === theme)?.label || theme;
  $("#moment").hidden = false;
  $("#titreMoment").textContent = `${label}, ${fmtCase(k, state.pas)}`;
  $("#tweetsMoment").innerHTML = '<p class="state">Chargement…</p>';
  document.querySelectorAll(".multiple__barre[aria-current]").forEach((b) => b.removeAttribute("aria-current"));
  document.querySelector(`.multiple__barre[data-case="${k}"][data-theme="${theme}"]`)?.setAttribute("aria-current", "true");
  try {
    const r = await fetchJSON(`/themes/tweets?${p}`);
    $("#tweetsMoment").innerHTML = r.items.length ? r.items.map(tweetHtml).join("")
      : '<p class="state state--inline">Aucun tweet à ce moment.</p>';
    $("#moment").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    $("#tweetsMoment").innerHTML = `<p class="state state--error">Les tweets ne se sont pas chargés (${escapeHtml(err.message)}).</p>`;
  }
}

async function chargerSerie() {
  const p = new URLSearchParams({ pas: state.pas, retweets: state.retweets });
  if (state.parti) p.set("parti", state.parti);
  $("#multiples").innerHTML = '<p class="state">Chargement…</p>';
  try {
    const s = (state.serie = await fetchJSON(`/themes/serie?${p}`));
    $("#lecture").textContent = lecture(s);
    $("#periode").textContent = s.cases.length
      ? `${fmtCase(s.cases[0].case, s.pas)} au ${fmtCase(s.cases[s.cases.length - 1].case, s.pas)}` : "";
    $("#multiples").innerHTML = multiples(s);
    document.querySelectorAll(".multiple__barre").forEach((b) => {
      b.addEventListener("click", () => ouvrirMoment(b.dataset.case, b.dataset.theme));
    });
  } catch (err) {
    $("#multiples").innerHTML = `<p class="state state--error">Les courbes ne se sont pas chargées (${escapeHtml(err.message)}).</p>`;
  }
}

async function chargerSujets(semaine) {
  const r = await fetchJSON(`/themes/sujets${semaine ? `?semaine=${semaine}` : ""}`);
  $("#semaine").innerHTML = r.semaines.map((s) =>
    `<option value="${s}"${s === r.semaine ? " selected" : ""}>${escapeHtml(s.replace("-W", ", semaine "))}</option>`).join("");
  $("#sujets").innerHTML = r.sujets.length ? r.sujets.map((s) => `<li>
      <button class="sujet" data-id="${s.id}">
        <span class="sujet__libelle">${escapeHtml(majuscule(s.libelle))}</span>
        <span class="sujet__meta">${fmtNum(s.n_tweets)} tweets, ${s.n_figures} figures${
          s.theme && r.themes[s.theme] ? `, ${escapeHtml(r.themes[s.theme].toLowerCase())}` : ""}</span>
      </button></li>`).join("")
    : '<li class="state state--inline">Pas encore de sujets calculés pour cette semaine.</li>';
  document.querySelectorAll(".sujet").forEach((b) => (b.onclick = async () => {
    document.querySelectorAll(".sujet[aria-pressed]").forEach((x) => x.removeAttribute("aria-pressed"));
    b.setAttribute("aria-pressed", "true");
    $("#tweetsSujet").innerHTML = '<p class="state">Chargement…</p>';
    const d = await fetchJSON(`/themes/sujets/${b.dataset.id}`);
    $("#tweetsSujet").innerHTML = `<div class="band"><h2>${escapeHtml(majuscule(d.libelle))}</h2></div>` + d.items.map(tweetHtml).join("");
  }));
}

function reglages() {
  $("#pas").innerHTML = PAS.map(([k, l]) =>
    `<button class="filter" data-pas="${k}" aria-pressed="${k === state.pas}">${l}</button>`).join("");
  document.querySelectorAll("#pas .filter").forEach((b) => (b.onclick = () => {
    state.pas = b.dataset.pas;
    document.querySelectorAll("#pas .filter").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    $("#moment").hidden = true;
    chargerSerie();
  }));
  $("#parti").onchange = (e) => { state.parti = e.target.value; chargerSerie(); };
  $("#retweets").onchange = (e) => { state.retweets = e.target.checked; chargerSerie(); };
  $("#semaine").onchange = (e) => chargerSujets(e.target.value);
  $("#fermerMoment").onclick = () => { $("#moment").hidden = true; };
}

reglages();
chargerSerie();
chargerSujets().catch((err) => {
  $("#sujets").innerHTML = `<li class="state state--error">Les sujets ne se sont pas chargés (${escapeHtml(err.message)}).</li>`;
});
