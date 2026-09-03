// File de validation — l'humain tranche. La machine propose, elle ne publie pas.
// Helpers ($, fetchJSON, fmtNum, escapeHtml) : common.js.

const TYPE = {
  1: "Revirement du même locuteur",
  2: "Divergence au sein du parti",
  3: "Divergence entre partis",
  4: "Écart au programme",
  5: "Contradiction avec un fait vérifié",
  6: "Variance numérique",
};

const state = { type: null };

// Le type de rapprochement en cours de relecture. La déclaration avait disparu
// avec le bloc de couleurs par parti, retiré juste au-dessus : la page se
// chargeait puis restait vide, sans rien afficher de l'erreur.


function claim(c) {
  const who = c.speaker_name || c.party || "source non attribuée";
  const date = c.published_at ? new Date(c.published_at).toLocaleDateString("fr-FR") : "date inconnue";
  const platform = c.platform === "x" ? "X" : c.platform === "press" ? "presse" : c.platform;
  const value = c.qty_value != null ? `${c.qty_value}${c.qty_unit ? " " + c.qty_unit : ""}` : "";

  return `<div class="claim">
    ${value ? `<p class="claim__value">${escapeHtml(value)}</p>` : ""}
    <p class="entry__head"><span class="speaker">${escapeHtml(who)}</span>
      <span class="stamp">${date}</span><span class="tag">${escapeHtml(platform)}</span></p>
    <p class="claim__text">« ${escapeHtml((c.canonical || c.verbatim || "").slice(0, 220))} »</p>
    ${c.source_url ? `<p class="entry__foot"><a class="source-link" href="${c.source_url}"
      target="_blank" rel="noopener">vérifier la source ↗</a></p>` : ""}
  </div>`;
}

async function renderFilters() {
  const counts = {};
  await Promise.all([null, 1, 2, 3, 6].map(async (t) => {
    const q = new URLSearchParams({ status: "pending", limit: 1 });
    if (t) q.set("type", t);
    try { counts[t ?? "all"] = (await fetchJSON(`/contradictions?${q}`)).total; }
    catch { counts[t ?? "all"] = 0; }
  }));

  $("#typeFilters").innerHTML = [["all", "Toutes", null], ...[1, 2, 3, 6].map((t) => [t, TYPE[t], t])]
    .map(([key, label, t]) =>
      `<button class="filter" data-t="${t ?? ""}" aria-pressed="${state.type === t}">${label}
        <span class="count">${counts[key] ?? 0}</span></button>`).join("");

  document.querySelectorAll("#typeFilters .filter").forEach((b) =>
    b.onclick = () => { state.type = b.dataset.t ? +b.dataset.t : null; renderFilters(); load(); });
}


// Le bandeau de tête : ce qui reste, ce qui a été tranché, dans quel sens.
// Sans lui, la file ressemble à une boîte de réception sans fond — on ne sait
// pas si on avance.
async function renderBar() {
  const host = $("#stats-bar");
  if (!host) return;
  try {
    const [p, c, r] = await Promise.all([
      fetchJSON("/contradictions?status=pending&limit=1"),
      fetchJSON("/contradictions?status=confirmed&limit=1"),
      fetchJSON("/contradictions?status=rejected&limit=1"),
    ]);
    const decided = (c.total || 0) + (r.total || 0);
    const prec = decided ? Math.round(((c.total || 0) / decided) * 100) : null;
    host.innerHTML = `<div class="statbar">
      <span class="statbar__item"><span class="statbar__n statbar__n--accent">${fmtNum(p.total)}</span>
        en attente</span>
      <span class="statbar__item"><span class="statbar__n">${fmtNum(c.total)}</span> confirmés</span>
      <span class="statbar__item"><span class="statbar__n">${fmtNum(r.total)}</span> écartés</span>
      <span class="statbar__item">${prec == null
        ? "précision inconnue — trop peu de décisions"
        : `<span class="statbar__n">${prec}\u202f%</span> de propositions retenues`}</span>
    </div>`;
  } catch {
    host.hidden = true;
  }
}

async function load() {
  const q = new URLSearchParams({ status: "pending", limit: 100 });
  if (state.type) q.set("type", state.type);

  let data;
  try { data = await fetchJSON(`/contradictions?${q}`); }
  catch (e) {
    $("#list").innerHTML = "";
    $("#empty").hidden = false;
    $("#empty").className = "state state--error";
    $("#empty").textContent = `La file n’a pas pu être chargée (${e.message}).`;
    return;
  }

  $("#stats").innerHTML = `<strong>${fmtNum(data.total)}</strong> en attente`;

  if (!data.items.length) {
    $("#list").innerHTML = "";
    $("#empty").hidden = false;
    $("#empty").className = "state";
    $("#empty").innerHTML = `<span class="state__title">File vide</span>
      <span class="state__hint">Aucun rapprochement n’attend de relecture. Le juge sémantique n’a rien proposé sur ce filtre — c’est le comportement voulu tant qu’il n’a pas de matière.</span>`;
    return;
  }
  $("#empty").hidden = true;

  $("#list").innerHTML = data.items.map((c) => `
    <article class="verdict enter" data-id="${c.id}">
      <div class="verdict__head">
        <span class="verdict__type">${escapeHtml(TYPE[c.type] || TYPE[6])}</span>
        <span class="stamp">score ${c.score}</span>
        ${c.detection_method === "llm_judge"
          ? `<span class="tag" title="Proposé par le juge sémantique (${escapeHtml(c.judge_version || "")})">juge LLM</span>`
          : '<span class="tag" title="Calculé de façon déterministe">calculé</span>'}
        ${c.referent_key ? `<span class="stamp">${escapeHtml(c.referent_key)}</span>` : ""}
        <span class="verdict__actions">
          <button class="btn btn--primary" data-act="confirm">Confirmer</button>
          <button class="btn" data-act="reject">Écarter</button>
        </span>
      </div>
      <div class="claims">
        ${claim(c.claim_a)}
        <span class="claims__vs" aria-hidden="true">contre</span>
        ${claim(c.claim_b)}
      </div>
      ${c.rationale ? `<p class="rationale">${escapeHtml(c.rationale)}</p>` : ""}
    </article>`).join("");

  $("#list").querySelectorAll("article").forEach((el) =>
    el.querySelectorAll("button[data-act]").forEach((b) =>
      b.onclick = () => validate(el.dataset.id, b.dataset.act, el, b)));
}

async function validate(id, decision, el, btn) {
  el.style.opacity = "0.45";
  el.querySelectorAll("button").forEach((b) => (b.disabled = true));
  btn.textContent = decision === "confirm" ? "Confirmation…" : "Retrait…";
  try {
    const res = await fetch(`/contradictions/${id}/validate?decision=${decision}`, { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    el.remove();
    renderFilters();
    load();
  } catch (e) {
    el.style.opacity = "1";
    el.querySelectorAll("button").forEach((b) => (b.disabled = false));
    btn.textContent = decision === "confirm" ? "Confirmer" : "Écarter";
    const err = document.createElement("p");
    err.className = "rationale state--error";
    err.textContent = `Décision non enregistrée (${e.message}). Réessaie — rien n’a été modifié.`;
    el.append(err);
  }
}

renderFilters();
load();
renderBar();
