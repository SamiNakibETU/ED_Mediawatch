// Le sommaire des sujets.
//
// L'ordre n'est pas chronologique et ne doit pas l'être : un observatoire du
// propos dans la durée qui trierait par date redeviendrait un fil. Les sujets
// EXPLOITABLES viennent en tête — plusieurs voix, longue étendue — parce que ce
// sont les seuls où une comparaison a quelque chose à révéler.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, themeLabel, themeVar,
// kicker, duree.

const SCOPES = [
  { key: "conf", label: "Exploitables", conf: true },
  { key: "all", label: "Tous les sujets", conf: false },
];

const state = { conf: true, q: "", theme: null, themes: {} };

const tuile = (s) => `
  <a class="tile" href="sujet.html?id=${s.id}">
    ${kicker(s.theme)}
    <h3 class="card-title">${nomSujet(s)}</h3>
    <div class="tile__foot">
      <span class="stamp"><b>${s.n_speakers}</b> ${s.n_speakers > 1 ? "locuteurs" : "locuteur"}
        · <b>${fmtNum(s.n_claims)}</b> propos</span>
      <span class="spacer"></span>
      <span class="stamp">${duree(s.span_days)}</span>
    </div>
    ${s.named ? "" : '<p class="stamp" style="margin-top:var(--s2)">libellé provisoire</p>'}
  </a>`;

function renderScope() {
  $("#scope").innerHTML = SCOPES.map((s) =>
    `<button class="filter" data-conf="${s.conf}" aria-pressed="${state.conf === s.conf}">${s.label}</button>`).join("");
  document.querySelectorAll("#scope .filter").forEach((b) =>
    (b.onclick = () => { state.conf = b.dataset.conf === "true"; renderScope(); load(); }));
}

function renderThemes() {
  const rows = Object.entries(state.themes).sort((a, b) => b[1] - a[1]);
  $("#themes").innerHTML =
    `<button class="filter" data-theme="" aria-pressed="${!state.theme}">Tous les thèmes</button>` +
    rows.map(([t, n]) =>
      `<button class="filter" data-theme="${escapeHtml(t)}" aria-pressed="${state.theme === t}"
         style="--th:${themeVar(t)}">${escapeHtml(themeLabel(t))}<span class="count">${n}</span></button>`).join("");
  document.querySelectorAll("#themes .filter").forEach((b) =>
    (b.onclick = () => { state.theme = b.dataset.theme || null; renderThemes(); load(); }));
}

async function load() {
  const sentinel = $("#sentinel");
  sentinel.className = "state";
  sentinel.textContent = "Chargement…";

  const p = new URLSearchParams({ limit: 120 });
  if (state.conf) p.set("confrontable", "true");
  if (state.q.trim()) p.set("q", state.q.trim());
  if (state.theme) p.set("theme", state.theme);

  try {
    const data = await fetchJSON(`/subjects?${p}`);
    const items = data.items || [];
    if (!Object.keys(state.themes).length) {
      state.themes = data.themes || {};
      renderThemes();
    }
    $("#list").innerHTML = items.length ? `<div class="tiles">${items.map(tuile).join("")}</div>` : "";
    $("#bandTitle").textContent = state.conf ? "Sujets exploitables" : "Tous les sujets";
    $("#count").innerHTML = `<strong>${fmtNum(items.length)}</strong> sujets`;
    $("#stats").innerHTML = `<strong>${fmtNum(items.length)}</strong> sujets`;
    sentinel.innerHTML = items.length
      ? `fin du sommaire · ${fmtNum(items.length)} sujets`
      : `<span class="state__title">Aucun sujet</span><span class="state__hint">${
          state.conf
            ? "Aucun sujet ne réunit encore plusieurs locuteurs sur ce filtre. Affiche tous les sujets, ou vois où en est la chaîne dans <a class='source-link' href='atelier.html'>l’atelier</a>."
            : "Le regroupement n’a pas encore produit de sujet ici. <a class='source-link' href='atelier.html'>L’atelier</a> dit à quel étage la chaîne s’arrête."
        }</span>`;
  } catch (e) {
    sentinel.className = "state state--error";
    sentinel.textContent = `Les sujets n’ont pas pu être chargés (${e.message}).`;
  }
}

let timer;
$("#q").oninput = (e) => {
  clearTimeout(timer); state.q = e.target.value;
  timer = setTimeout(load, 250);
};

// Le thème peut arriver par l'URL : la une renvoie ici avec un thème choisi.
state.theme = new URLSearchParams(location.search).get("theme");
renderScope();
load();
