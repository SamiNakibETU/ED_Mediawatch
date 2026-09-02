// Le registre des engagements.
//
// Deux choses par ligne, et rien d'autre : l'engagement dans les mots du
// locuteur, et ce qu'il faudrait observer pour dire qu'il est tenu. La seconde
// est ce qui distingue un registre d'une collection de citations — sans critère
// d'observation, « tenu » ou « rompu » resterait une opinion.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, exactDate, ico,
// infiniteScroll.

const state = { speaker: null, offset: 0, total: 0, fin: false };
const listEl = $("#list");

function ligne(e) {
  return `<article class="entry entry--plain">
    <div>
      <p class="entry__head">
        <span class="speaker">${escapeHtml(e.speaker || "locuteur non établi")}</span>
        ${e.party ? `<span class="tag">${escapeHtml(e.party)}</span>` : ""}
        <span class="spacer"></span>
        <span class="stamp">${escapeHtml(exactDate(e.published_at))}</span>
      </p>
      <p class="prose">« ${escapeHtml(e.verbatim || "")} »</p>
      ${e.mesure ? `<p class="engagement__mesure">
        <span class="overline">Tenu si</span> ${escapeHtml(e.mesure)}</p>` : ""}
      <p class="entry__foot">
        <span class="status status--pending">${escapeHtml(e.status || "")}</span>
        ${e.subject_id ? `<a class="source-link" href="sujet.html?id=${e.subject_id}">le sujet</a>` : ""}
        <span class="spacer"></span>
        ${e.url ? `<a class="source-link" href="${escapeHtml(e.url)}" target="_blank"
            rel="noopener">vérifier la source ${ico("source")}</a>` : ""}
      </p>
    </div>
  </article>`;
}

function renderQui(gens) {
  $("#qui").innerHTML = [
    `<button class="filter" data-qui="" aria-pressed="${!state.speaker}">Tous</button>`,
    ...gens.slice(0, 12).map((g) =>
      `<button class="filter" data-qui="${escapeHtml(g.speaker)}"
         aria-pressed="${state.speaker === g.speaker}">${escapeHtml(g.speaker)}
         <span class="count">${g.n}</span></button>`),
  ].join("");
  $("#qui").onclick = (ev) => {
    const b = ev.target.closest("[data-qui]");
    if (!b) return;
    state.speaker = b.dataset.qui || null;
    state.offset = 0; state.fin = false;
    listEl.innerHTML = "";
    load();
  };
}

async function load() {
  const q = new URLSearchParams({ limit: 30, offset: state.offset });
  if (state.speaker) q.set("speaker", state.speaker);
  try {
    const d = await fetchJSON(`/engagements?${q}`);
    state.total = d.total;
    if (!state.offset) renderQui(d.par_locuteur || []);
    $("#count").textContent = `${fmtNum(d.total)} engagement${d.total > 1 ? "s" : ""} consigné${d.total > 1 ? "s" : ""}`;

    if (!d.items.length && !state.offset) {
      listEl.innerHTML = `<p class="state">
        <span class="state__title">Aucun engagement consigné pour l’instant</span>
        <span class="state__hint">Le registre se remplit à chaque passe, et il est
        exigeant&nbsp;: la plupart des propos normatifs sont des injonctions adressées
        à d’autres, pas des engagements. Voir <a class="source-link" href="atelier.html">l’atelier</a>.</span></p>`;
      return;
    }
    listEl.insertAdjacentHTML("beforeend", d.items.map(ligne).join(""));
    state.offset += d.items.length;
    state.fin = state.offset >= d.total;
    $("#sentinel").textContent = state.fin ? "" : "Chargement…";
  } catch (e) {
    listEl.innerHTML =
      `<p class="state state--error">Le registre n’a pas pu être chargé (${escapeHtml(e.message)}).</p>`;
  }
}

infiniteScroll($("#sentinel"), () => { if (!state.fin) load(); });
load();
