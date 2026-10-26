// La fiche d'un enjeu : la question, les écarts, puis la trajectoire de chaque
// figure sur l'échelle.
//
// Les écarts passent devant les trajectoires : c'est ce qu'on vient chercher.
// La trajectoire sert à vérifier qu'un écart n'est pas un tweet isolé au milieu
// de vingt autres qui disent le contraire.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, asDate.

const jour = (iso) =>
  iso ? asDate(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }) : "date inconnue";

const state = { slug: new URLSearchParams(location.search).get("e"), fiche: null };

function citation(p) {
  return `<article class="position">
    <div class="position__head">
      <span class="stamp">${jour(p.date)}</span>
      <span class="tag">${escapeHtml(p.label)}</span>
      ${p.modalite ? `<span class="stamp">${escapeHtml(p.modalite)}</span>` : ""}
      ${p.valeur != null ? `<span class="tag">${p.valeur}${p.unite ? " " + escapeHtml(p.unite) : ""}</span>` : ""}
    </div>
    <p class="position__q">${escapeHtml(p.verbatim)}</p>
    ${sourceCard(p.source)}
  </article>`;
}

function ecartsHtml(f) {
  if (!f.ecarts.length) {
    return `<p class="state state--inline">Aucun écart pour l’instant&nbsp;: aucune figure ne
      s’est placée à deux endroits différents de l’échelle à plus d’un mois d’intervalle.</p>`;
  }
  return f.ecarts.map((e) => `
    <div class="card mb-3">
      <p class="kicker">${escapeHtml(e.figure)}<span class="kicker__sep">${
        escapeHtml(e.avant.label)} → ${escapeHtml(e.apres.label)}</span></p>
      ${citation(e.avant)}
      ${citation(e.apres)}
    </div>`).join("");
}

// Le temps à l'horizontale, l'échelle à la verticale. Le premier cran est en
// haut, dans l'ordre où la question l'écrit.
function trajectoires(f) {
  const lanes = f.figures.filter((g) => g.positions.some((p) => p.date));
  if (!lanes.length) return "";
  const ts = lanes.flatMap((g) => g.positions.filter((p) => p.date).map((p) => asDate(p.date).getTime()));
  let t0 = Math.min(...ts), t1 = Math.max(...ts);
  if (t0 === t1) { t0 -= 15 * 864e5; t1 += 15 * 864e5; }
  // 4 % de marge de chaque côté : un point posé à 0 ou 100 % sort à moitié
  // de la piste, et la dernière date déborde du cadre.
  const at = (iso) => 4 + ((asDate(iso).getTime() - t0) / (t1 - t0)) * 92;
  const n = f.echelle.length;
  // Centre du cran, en rem depuis le haut de la piste (0,3 rem de marge).
  const haut = (rang) => `calc(0.3rem + ${rang - 0.5} * 0.9rem)`;
  const filets = f.echelle.map((c) =>
    `<span class="frise__cran" style="top:${haut(c.rang)}" aria-hidden="true"></span>`).join("");

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((x) => {
    const d = new Date(t0 + (t1 - t0) * x);
    return `<span class="frise__tick" style="left:${(4 + x * 92).toFixed(1)}%">${
      d.toLocaleDateString("fr-FR", { month: "short", year: "2-digit" })}</span>`;
  }).join("");

  const lane = (g) => `
    <div class="frise__lane">
      <p class="frise__who">${escapeHtml(g.nom)}<span>${g.groupe || ""} · ${g.positions.length}</span></p>
      <div class="frise__track frise__track--echelle" style="--crans:${n}">
        ${filets}
        ${g.positions.filter((p) => p.date).map((p) => `
          <button class="frise__dot" style="left:${at(p.date).toFixed(2)}%;top:${haut(p.rang)}"
                  data-post="${p.post_id}" aria-pressed="false"
                  aria-label="${escapeHtml(`${g.nom}, ${jour(p.date)} : ${p.label}`)}"
                  title="${escapeHtml(`${jour(p.date)} · ${p.label}`)}"></button>`).join("")}
      </div>
    </div>`;

  return `<div class="frise">
    <div class="frise__head">
      <p class="section-label" style="margin:0">Figure</p>
      <div class="frise__scale">${ticks}</div>
    </div>
    ${lanes.map(lane).join("")}
  </div>
  <ol class="echelle-cle">${f.echelle.map((c) => `<li>${escapeHtml(c.label)}</li>`).join("")}</ol>
  <div class="peek" id="peek" hidden></div>`;
}

// Ce que dit le programme, livret et page à l'appui : la référence contre
// laquelle les déclarations d'un parti se lisent.
function programmeHtml(f) {
  const prog = f.programme || [];
  if (!prog.length) {
    return `<p class="state state--inline">Le programme lu ne dit rien de précis sur cette question.</p>`;
  }
  return prog.map((e) => `<article class="position">
      <div class="position__head">
        <span class="tag">${escapeHtml(e.parti)} ${e.annee}</span>
        <span class="tag">${escapeHtml(e.label)}</span>
        <span class="spacer"></span>
        <span class="stamp">livret « ${escapeHtml(e.livret.replace(/^projet-/, "").replace(/-/g, " "))} », p.&nbsp;${e.page ?? "?"}</span>
      </div>
      <p class="position__q">${escapeHtml(e.verbatim)}</p>
    </article>`).join("");
}

function ecartsProgrammeHtml(f) {
  const items = f.ecarts_programme || [];
  if (!items.length) return "";
  return `<div class="band"><h2>Écarts au programme</h2><span class="spacer"></span><p>${items.length}</p></div>
    ${items.map((x) => `<div class="card mb-3">
      <p class="kicker">${escapeHtml(x.figure)}<span class="kicker__sep">${escapeHtml(x.declaration.label)}, quand le programme ${x.annee} dit : ${
        escapeHtml([...new Set(x.programme.map((e) => e.label))].join(" / "))}</span></p>
      ${citation(x.declaration)}
    </div>`).join("")}`;
}

function render() {
  const f = state.fiche;
  const nPos = f.figures.reduce((a, g) => a + g.positions.length, 0);
  $("#fiche").innerHTML = `
    <h1 class="hero-title mt-6">${escapeHtml(f.question)}</h1>
    <p class="dek">${fmtNum(nPos)} prise${nPos > 1 ? "s" : ""} de position, ${f.figures.length} figure${
      f.figures.length > 1 ? "s" : ""}.${f.jalons.length ? ` Repère&nbsp;: ${f.jalons.map(escapeHtml).join(" ; ")}.` : ""}</p>

    <div class="band"><h2>Ce que dit le programme</h2></div>
    ${programmeHtml(f)}

    ${ecartsProgrammeHtml(f)}

    <div class="band"><h2>Les écarts</h2><span class="spacer"></span><p>${f.ecarts.length}</p></div>
    ${ecartsHtml(f)}

    <div class="band"><h2>Les trajectoires</h2></div>
    ${nPos ? `<div class="card">${trajectoires(f)}</div>`
      : '<p class="state state--inline">Aucune position lue sur cet enjeu pour l’instant.</p>'}`;

  const byPost = new Map(f.figures.flatMap((g) => g.positions.map((p) => [String(p.post_id), { g, p }])));
  document.querySelectorAll(".frise__dot").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll('.frise__dot[aria-pressed="true"]').forEach((x) => x.setAttribute("aria-pressed", "false"));
      b.setAttribute("aria-pressed", "true");
      const { g, p } = byPost.get(b.dataset.post);
      const peek = $("#peek");
      peek.hidden = false;
      peek.innerHTML = `<p class="kicker">${escapeHtml(g.nom)}</p>${citation(p)}`;
    };
  });
}

async function load() {
  const liste = await fetchJSON("/enjeux");
  // Par défaut, l'enjeu le mieux documenté : arriver sur une fiche vide ne
  // montre rien de ce que la page sait faire.
  if (!state.slug || !liste.some((e) => e.slug === state.slug)) {
    state.slug = [...liste].sort((a, b) => b.positions - a.positions)[0]?.slug;
  }
  // Groupés par thème, dans l'ordre du référentiel : quarante-quatre boutons à
  // la suite ne se parcourent pas.
  const themes = [];
  for (const e of liste) {
    let t = themes.find((x) => x.theme === e.theme);
    if (!t) themes.push((t = { theme: e.theme, label: e.theme_label, items: [] }));
    t.items.push(e);
  }
  $("#enjeux").innerHTML = themes.map((t) => `<div class="enjeux-theme">
      <p class="section-label">${escapeHtml(t.label)}</p>
      <div class="filters">${t.items.map((e) =>
        `<button class="filter" data-slug="${e.slug}" aria-pressed="${e.slug === state.slug}">${
          escapeHtml(e.titre)}<span class="count">${fmtNum(e.positions)}</span></button>`).join("")}</div>
    </div>`).join("");
  document.querySelectorAll("#enjeux .filter").forEach((b) => (b.onclick = () => {
    state.slug = b.dataset.slug;
    history.replaceState(null, "", `?e=${state.slug}`);
    document.querySelectorAll("#enjeux .filter").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    fiche();
  }));
  await fiche();
}

async function fiche() {
  try {
    state.fiche = await fetchJSON(`/enjeux/${state.slug}`);
    render();
  } catch (err) {
    $("#fiche").innerHTML = `<p class="state state--error">La fiche ne s’est pas chargée (${escapeHtml(err.message)}).</p>`;
  }
}

load().catch((err) => {
  $("#fiche").innerHTML = `<p class="state state--error">Les enjeux ne se sont pas chargés (${escapeHtml(err.message)}).</p>`;
});
