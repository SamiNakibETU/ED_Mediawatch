// L'atelier de codage : une déclaration, vingt-deux réponses possibles.
//
// La contrainte d'interface vient de la mesure. Le code de la machine n'est
// jamais affiché avant la décision — le voir transformerait le codeur en
// relecteur, et l'accord mesuré cesserait d'être indépendant. Rien non plus ne
// suggère une réponse : pas de « probablement », pas de tri des topiques par
// vraisemblance. L'ordre de la grille est l'ordre du codebook.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, exactDate.

const state = { coder: "", grille: [], claim: null };
const champ = $("#coder");

// L'identifiant reste d'une session à l'autre : retaper son nom à chaque unité
// est le meilleur moyen de coder dix unités au lieu de deux cents.
try { champ.value = localStorage.getItem("coder") || ""; } catch {}
state.coder = champ.value.trim();

champ.addEventListener("change", () => {
  state.coder = champ.value.trim();
  try { localStorage.setItem("coder", state.coder); } catch {}
  suivant();
});

function boutons() {
  return `<div class="filters mt-5">
    ${state.grille.map((t) => `
      <button class="filter" data-code="${t.code}" title="${escapeHtml(t.aide)}">
        <span class="count">${String(t.code).padStart(2, "0")}</span>
        ${escapeHtml(t.label)}</button>`).join("")}
    <button class="filter filter--hors" data-code="">Hors politique publique</button>
  </div>`;
}

function renderUnite(d) {
  state.claim = d.claim;
  $("#faites").textContent = state.coder
    ? `${fmtNum(d.faites)} unité${d.faites > 1 ? "s" : ""} codée${d.faites > 1 ? "s" : ""}`
    : "";

  if (!state.coder) {
    $("#unite").innerHTML = `<p class="state">
      <span class="state__title">Donne-toi un identifiant de codeur</span>
      <span class="state__hint">Il sépare tes décisions de celles d’un second codeur —
      c’est cette séparation qui rend l’alpha calculable.</span></p>`;
    return;
  }
  if (!d.claim) {
    $("#unite").innerHTML = `<p class="state">
      <span class="state__title">Plus rien à coder pour l’instant</span>
      <span class="state__hint">Toutes les déclarations codées par la machine sont
      passées entre tes mains. La prochaine passe en apportera d’autres.</span></p>`;
    return;
  }

  $("#unite").innerHTML = `<div class="card">
    <p class="stamp">déclaration n° ${d.claim.id} · ${escapeHtml(exactDate(d.claim.published_at))}</p>
    <p class="prose">« ${escapeHtml(d.claim.texte || "")} »</p>
    ${boutons()}
  </div>`;

  $("#unite").onclick = async (ev) => {
    const b = ev.target.closest("[data-code]");
    if (!b || !state.claim) return;
    const code = b.dataset.code === "" ? null : +b.dataset.code;
    b.setAttribute("aria-pressed", "true");
    await fetch(`${API}/codage`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ claim_id: state.claim.id, coder: state.coder, code }),
    });
    await suivant();
    await renderFiabilite();
  };
}

function ligne(m) {
  const seuil = m.alpha === null ? "" :
    m.alpha >= 0.8 ? "status--ok" : m.alpha >= 0.67 ? "status--pending" : "status--alert";
  return `<div class="kv__row">
    <span class="kv__k">${escapeHtml(m.a)} × ${escapeHtml(m.b)}</span>
    <span class="kv__v">${m.alpha === null ? "—" : m.alpha.toFixed(3)}</span>
    <span class="kv__note">
      <span class="status ${seuil}">${escapeHtml(m.verdict)}</span> ·
      ${fmtNum(m.n)} unités communes</span>
  </div>`;
}

async function renderFiabilite() {
  try {
    const d = await fetchJSON("/codage/fiabilite");
    $("#fiabilite").innerHTML = d.mesures?.length
      ? `<div class="kv">${d.mesures.map(ligne).join("")}</div>
         <p class="stamp mt-4">Seuils : α ≥ 0,80 fiable · 0,67–0,79 provisoire ·
           en dessous, non publiable.</p>`
      : `<p class="state">Aucune annotation humaine pour l’instant. La mesure de
         référence reste celle du jeu annoté&nbsp;: α = ${d.reference?.alpha ?? "—"},
         ${escapeHtml(d.reference?.verdict || "")}.</p>`;
  } catch (e) {
    $("#fiabilite").innerHTML =
      `<p class="state state--error">Mesure indisponible (${escapeHtml(e.message)}).</p>`;
  }
}

async function suivant() {
  if (!state.coder) return renderUnite({ claim: null, faites: 0 });
  try {
    renderUnite(await fetchJSON(`/codage/suivant?coder=${encodeURIComponent(state.coder)}`));
    $("#etat").textContent = "";
  } catch (e) {
    $("#etat").textContent = e.message;
  }
}

async function load() {
  state.grille = (await fetchJSON("/codage/grille")).topiques || [];
  await suivant();
  await renderFiabilite();
}

load();
