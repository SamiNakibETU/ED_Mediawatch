// Les écarts : la file de relecture, puis les divergences entre partis.
//
// Chaque écart montre les deux textes en entier, côte à côte, avant l'avis du
// juge : c'est au lecteur de voir l'écart, pas de le croire.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, asDate, sourceCard.

const STATUTS = [["a_relire", "À relire"], ["confirme", "Confirmés"], ["ecarte", "Écartés"]];
const TYPES = [["", "Tous"], ["temps", "Dans le temps"], ["programme", "Contre le programme"], ["parti", "Dans le parti"]];
const JUGE = {
  revirement: "Revirement", divergence: "Divergence", ecart_au_programme: "Écart au programme",
  nuance: "Nuance", contexte_different: "Contexte différent", erreur_de_lecture: "Erreur de lecture",
};
const FORCE = ["aucun écart réel", "écart faible", "écart net", "contradiction nette"];
const JUGES = [["reels", "Écarts réels selon le juge"], ["lectures", "Erreurs de lecture et nuances"], ["tous", "Tout"]];
const state = { statut: "a_relire", type: "", juge: "reels", offset: 0 };

const jour = (iso) => (iso ? asDate(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }) : "date inconnue");
const lireJeton = () => { try { return localStorage.getItem("jeton-relecture") || ""; } catch { return ""; } };

function cote(c) {
  if (!c) return "";
  return `<div class="ecart__cote">
    <p class="entry__head"><span class="speaker">${escapeHtml(c.figure || "")}</span>
      ${c.parti ? `<span class="tag">${escapeHtml(c.parti)}</span>` : ""}
      <span class="spacer"></span><span class="sujet__meta">${jour(c.date)}</span></p>
    <p class="ecart__position">${escapeHtml(c.label)}</p>
    <p class="position__q">${escapeHtml(c.verbatim)}</p>
    ${sourceCard(c.source)}
  </div>`;
}

function coteProgramme(p) {
  if (!p) return "";
  return `<div class="ecart__cote">
    <p class="entry__head"><span class="speaker">Programme ${escapeHtml(p.parti)} ${p.annee}</span>
      <span class="spacer"></span>
      <span class="sujet__meta">livret « ${escapeHtml(p.livret.replace(/^projet-/, "").replace(/-/g, " "))} », p. ${p.page ?? "?"}</span></p>
    <p class="ecart__position">${escapeHtml(p.label)}</p>
    <p class="position__q">${escapeHtml(p.verbatim)}</p>
  </div>`;
}

function juge(j) {
  if (!j) return `<p class="sujet__meta">Pas encore relu par le juge.</p>`;
  return `<div class="ecart__juge">
    <p><span class="decl-ligne__k">${escapeHtml(JUGE[j.type] || j.type)}</span>
      <span class="sujet__meta">${FORCE[j.force] ?? ""}${j.justification === "oui" ? ", changement expliqué publiquement" : ""}</span></p>
    ${j.explication ? `<p class="prose" style="margin:0">${escapeHtml(j.explication)}</p>` : ""}
  </div>`;
}

function ecartHtml(e) {
  const actions = state.statut === "a_relire"
    ? `<div class="ecart__actions">
        <label class="sr-only" for="note${e.id}">Note de relecture</label>
        <input id="note${e.id}" class="field field--inline" placeholder="Note (facultative)" />
        <button class="btn btn--sm" data-decision="confirme" data-id="${e.id}">Confirmer</button>
        <button class="btn btn--ghost btn--sm" data-decision="ecarte" data-id="${e.id}">Écarter</button>
      </div>`
    : (e.decision_note ? `<p class="sujet__meta">Note : ${escapeHtml(e.decision_note)}</p>` : "");
  return `<article class="ecart" id="ecart${e.id}">
    <p class="ecart__titre">${escapeHtml(e.titre)}<span class="sujet__meta"> ${escapeHtml(e.type_label.toLowerCase())}</span></p>
    <p class="sujet__meta">${escapeHtml(e.question)}</p>
    <div class="ecart__cotes">${cote(e.a)}${e.b ? cote(e.b) : coteProgramme(e.programme)}</div>
    ${juge(e.juge)}
    ${actions}
  </article>`;
}

async function decider(id, statut) {
  const jeton = $("#jeton").value.trim();
  if (!jeton) { $("#jeton").focus(); return; }
  try { localStorage.setItem("jeton-relecture", jeton); } catch {}
  const note = $(`#note${id}`)?.value || null;
  const res = await fetch(`/ecarts/${id}/decision`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-API-Token": jeton },
    body: JSON.stringify({ statut, note }),
  });
  const bloc = $(`#ecart${id}`);
  if (res.ok) {
    bloc.innerHTML = `<p class="sujet__meta">${statut === "confirme" ? "Confirmé" : "Écarté"}.</p>`;
  } else {
    bloc.insertAdjacentHTML("beforeend", `<p class="state state--error">La décision n’a pas été enregistrée (${
      res.status === 401 ? "jeton refusé" : `erreur ${res.status}`}).</p>`);
  }
}

async function charger(suite = false) {
  if (!suite) state.offset = 0;
  const p = new URLSearchParams({ statut: state.statut, juge: state.juge, limit: 20, offset: state.offset });
  if (state.type) p.set("type", state.type);
  if (!suite) $("#liste").innerHTML = '<p class="state">Chargement…</p>';
  try {
    const r = await fetchJSON(`/ecarts?${p}`);
    const html = r.items.map(ecartHtml).join("");
    $("#liste").innerHTML = suite ? $("#liste").innerHTML + html
      : (html || '<p class="state state--inline">Aucun écart dans cette catégorie.</p>');
    $("#total").textContent = `${fmtNum(r.total)}`;
    state.offset += r.items.length;
    $("#plus").hidden = state.offset >= r.total;
    document.querySelectorAll("[data-decision]").forEach((b) => (b.onclick = () => decider(b.dataset.id, b.dataset.decision)));
  } catch (err) {
    $("#liste").innerHTML = `<p class="state state--error">Les écarts ne se sont pas chargés (${escapeHtml(err.message)}).</p>`;
  }
}

async function lecture() {
  try {
    const c = await fetchJSON("/ecarts/compte");
    const n = (s) => Object.values(c.compte).reduce((a, t) => a + (t[s] || 0), 0);
    $("#lecture").textContent = `${fmtNum(n("a_relire"))} écarts à relire, ${fmtNum(n("confirme"))} confirmés, ${
      fmtNum(n("ecarte"))} écartés. Un écart est relevé automatiquement quand deux positions sur la même question ne coïncident pas ; un juge relit les deux textes, puis un relecteur tranche. Seuls les écarts confirmés sont des faits.`;
  } catch { $("#lecture").textContent = ""; }
}

async function divergencesHtml() {
  try {
    const d = await fetchJSON("/ecarts/divergences?jours=365");
    const partis = ["RN", "UDR", "Reconquete"];
    const nom = { RN: "RN", UDR: "UDR", Reconquete: "Reconquête" };
    if (!d.length) { $("#divergences").innerHTML = "<caption>Pas assez de déclarations pour comparer les partis.</caption>"; return; }
    $("#divergences").innerHTML = `<thead><tr><th scope="col">Enjeu</th>${partis.map((p) => `<th scope="col">${nom[p]}</th>`).join("")}</tr></thead>
      <tbody>${d.map((x) => `<tr${x.divergent ? ' class="tableau__marque"' : ""}>
        <th scope="row">${escapeHtml(x.titre)}${x.divergent ? '<span class="sujet__meta"> divergent</span>' : ""}</th>
        ${partis.map((p) => {
          const v = x.partis[p];
          return v ? `<td>${escapeHtml(v.label)}<span class="sujet__meta"> ${v.part} % de ${v.declarations}</span></td>` : '<td class="sujet__meta">pas assez de déclarations</td>';
        }).join("")}</tr>`).join("")}</tbody>`;
  } catch (err) {
    $("#divergences").innerHTML = `<caption>Le tableau ne s’est pas chargé (${escapeHtml(err.message)}).</caption>`;
  }
}

function filtres() {
  const monter = (id, liste, cle) => {
    $(id).innerHTML = liste.map(([k, l]) => `<button class="filter" data-k="${k}" aria-pressed="${k === state[cle]}">${l}</button>`).join("");
    document.querySelectorAll(`${id} .filter`).forEach((b) => (b.onclick = () => {
      state[cle] = b.dataset.k;
      document.querySelectorAll(`${id} .filter`).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      $("#titreListe").textContent = STATUTS.find(([k]) => k === state.statut)[1];
      charger();
    }));
  };
  monter("#statut", STATUTS, "statut");
  monter("#type", TYPES, "type");
  monter("#juge", JUGES, "juge");
  $("#suite").onclick = () => charger(true);
  $("#jeton").value = lireJeton();
}

filtres();
lecture();
charger();
divergencesHtml();
