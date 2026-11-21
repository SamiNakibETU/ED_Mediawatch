// Les écarts : la file de relecture, puis les divergences entre partis.
//
// Chaque écart montre les deux textes en entier, côte à côte, avant l'avis du
// juge : c'est au lecteur de voir l'écart, pas de le croire.
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, ecartCarte.

const STATUTS = [["retenu", "Retenus"], ["faible", "Mouvements faibles"], ["ecarte", "Écartés"], ["attente", "En attente"]];
const TYPES = [["", "Tous"], ["temps", "Dans le temps"], ["programme", "Contre le programme"], ["parti", "Dans le parti"], ["chiffre", "Chiffres"]];
const state = { statut: "retenu", type: "", offset: 0 };

const lireJeton = () => { try { return localStorage.getItem("jeton-relecture") || ""; } catch { return ""; } };

function ecartHtml(e) {
  const actions = !e.statut || e.statut === "a_relire"
    ? `<div class="ecart__actions">
        <label class="sr-only" for="note${e.id}">Note de relecture</label>
        <input id="note${e.id}" class="field field--inline" placeholder="Note (facultative)" />
        <button class="btn btn--sm" data-decision="confirme" data-id="${e.id}">Confirmer</button>
        <button class="btn btn--ghost btn--sm" data-decision="ecarte" data-id="${e.id}">Écarter</button>
      </div>`
    : (e.decision_note ? `<p class="sujet__meta">Note : ${escapeHtml(e.decision_note)}</p>` : "");
  return ecartCarte(e, actions);
}

async function decider(id, statut) {
  const note = $(`#note${id}`)?.value || null;
  let res;
  if (STATIQUE) {
    // Version en ligne : le relecteur est identifié par Cloudflare Access, la décision
    // attend dans un espace KV que `rapatrier_decisions` la ramène en base.
    res = await fetch("/decision", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ecart: id, statut, note }),
    });
  } else {
    const jeton = $("#jeton").value.trim();
    if (!jeton) { $("#jeton").focus(); return; }
    try { localStorage.setItem("jeton-relecture", jeton); } catch {}
    res = await fetch(`/ecarts/${id}/decision`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-API-Token": jeton },
      body: JSON.stringify({ statut, note }),
    });
  }
  const bloc = $(`#ecart${id}`);
  if (res.ok) {
    bloc.innerHTML = `<p class="sujet__meta">${statut === "confirme" ? "Confirmé" : "Écarté"}${
      STATIQUE ? ", enregistré. La page le montrera à la mise à jour du lundi." : "."}</p>`;
  } else {
    bloc.insertAdjacentHTML("beforeend", `<p class="state state--error">La décision n’a pas été enregistrée (${
      res.status === 401 ? "jeton refusé" : `erreur ${res.status}`}).</p>`);
  }
}

async function charger(suite = false) {
  if (!suite) state.offset = 0;
  const p = new URLSearchParams({ juge: state.statut, limit: 20, offset: state.offset });
  if (state.type) p.set("type", state.type);
  if (!suite) $("#liste").innerHTML = '<p class="state">Chargement…</p>';
  try {
    const r = await fetchJSON(`/ecarts/faits?${p}`);
    const html = r.items.map(ecartHtml).join("");
    $("#liste").innerHTML = suite ? $("#liste").innerHTML + html
      : (html || '<p class="state state--inline">Aucun écart dans cette catégorie.</p>');
    $("#total").textContent = r.paires > r.total
      ? `${fmtNum(r.total)} faits, ${fmtNum(r.paires)} paires de déclarations` : `${fmtNum(r.total)}`;
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
    $("#lecture").textContent = `${fmtNum(n("retenu"))} écarts retenus, ${fmtNum(n("faible"))} mouvements faibles, ${
      fmtNum(n("ecarte"))} écartés, ${fmtNum(n("attente"))} en attente. Tout est automatique : chaque déclaration en écart reçoit un second avis, puis deux juges de modèles différents relisent les deux textes. Un écart n'est retenu que si les deux le tiennent pour réel. Aucun écart n'a encore été vérifié par un humain.`;
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
  $("#suite").onclick = () => charger(true);
  $("#jeton").value = lireJeton();
  if (STATIQUE) $("#jeton").hidden = true;
}

filtres();
lecture();
charger();
divergencesHtml();
