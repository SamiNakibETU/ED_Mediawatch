// Un sujet : qui a dit quoi dessus, quand, et comment ça a bougé.
//
// C'est la page du produit. Tout le reste — le fil X, la revue de presse — est
// le fonds qui l'alimente. La lecture utile n'est pas « les dernières prises de
// parole » mais « ces cinq voix, sur cet objet précis, sur deux ans ».
//
// Helpers (common.js) : $, fetchJSON, escapeHtml, fmtNum, asDate, exactDate,
// themeLabel, themeVar, kicker, duree, periode.

const TYPE_LABEL = {
  normatif: "position", factuel_quantitatif: "chiffre", factuel_qualitatif: "fait",
  predictif: "prédiction", attributif: "imputation",
};

const state = { id: null, data: null, marked: null, speaker: null };

const jour = (iso) =>
  iso ? asDate(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "2-digit" })
      : "date inconnue";

// ── La frise ────────────────────────────────────────────────────────────────
//
// Une ligne par locuteur, un repère par prise de position, un axe partagé.
// La comparaison se fait à l'œil : rien n'est interprété à la place du lecteur.
// On ne relie pas les repères — deux déclarations ne sont pas une trajectoire
// mesurée, et un trait laisserait croire à une évolution continue qu'on n'a
// pas observée.

function frise(speakers, theme) {
  const dated = speakers.map((s) => ({
    ...s, claims: s.claims.filter((c) => c.published_at),
  })).filter((s) => s.claims.length);
  if (!dated.length) return "";

  const ts = dated.flatMap((s) => s.claims.map((c) => asDate(c.published_at).getTime()));
  let t0 = Math.min(...ts), t1 = Math.max(...ts);
  if (t0 === t1) { t0 -= 15 * 864e5; t1 += 15 * 864e5; }
  const at = (iso) => ((asDate(iso).getTime() - t0) / (t1 - t0)) * 100;

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => {
    const d = new Date(t0 + (t1 - t0) * f);
    return `<span class="frise__tick" style="left:${(f * 100).toFixed(1)}%">${
      d.toLocaleDateString("fr-FR", { month: "short", year: "2-digit" })}</span>`;
  }).join("");

  const lanes = dated.map((s) => `
    <div class="frise__lane">
      <p class="frise__who">${escapeHtml(s.name)}<span>${s.claims.length}</span></p>
      <div class="frise__track">
        ${s.claims.map((c) => `
          <button class="frise__dot" style="left:${at(c.published_at).toFixed(2)}%;--th:${themeVar(theme)}"
                  data-claim="${c.id}" aria-pressed="false"
                  aria-label="${escapeHtml(`${s.name}, ${jour(c.published_at)} : ${(c.text || "").slice(0, 90)}`)}"
                  title="${escapeHtml(jour(c.published_at))}"></button>`).join("")}
      </div>
    </div>`).join("");

  return `<div class="frise">
    <div class="frise__head">
      <p class="section-label" style="margin:0">Locuteur</p>
      <div class="frise__scale">${ticks}</div>
    </div>
    ${lanes}
  </div>
  <div class="peek" id="peek" hidden style="--th:${themeVar(theme)}"></div>`;
}

// ── Les positions, in extenso ───────────────────────────────────────────────

// Le nom du locuteur n'est pas répété sur chaque ligne : le bloc porte déjà son
// nom, et le voir neuf fois de suite occupe la place sans rien ajouter.
function position(c) {
  return `<article class="position" id="c${c.id}">
    <div class="position__head">
      <span class="stamp">${jour(c.published_at)}</span>
      <span class="tag">${TYPE_LABEL[c.claim_type] || escapeHtml(c.claim_type || "")}</span>
      ${c.qty_value != null
        ? `<span class="tag">${c.qty_value}${c.qty_unit ? " " + escapeHtml(c.qty_unit) : ""}</span>` : ""}
      <span class="spacer"></span>
      ${c.source_url
        ? `<a class="source-link" href="${c.source_url}" target="_blank" rel="noopener">source ↗</a>`
        : '<span class="stamp">source non résolue</span>'}
    </div>
    <p class="position__q">${escapeHtml(c.text || c.verbatim || "")}</p>
  </article>`;
}

function positionsHtml(speakers) {
  const shown = state.speaker
    ? speakers.filter((s) => s.name === state.speaker)
    : speakers;
  return shown.map((s) => `
    <section style="margin-top:var(--s6)">
      <p class="section-label">${escapeHtml(s.name)} · ${s.n} propos</p>
      <div>${s.claims.map(position).join("")}</div>
    </section>`).join("");
}

// ── Ce que le corpus permet de conclure — et ce qu'il ne permet pas ────────
//
// Sans cette phrase, l'absence de revirement se lit comme une preuve de
// constance. Ce n'en est pas une quand le corpus ne couvre que six mois.

function portee(s) {
  if (s.n_speakers < 2) {
    return "Un seul locuteur s’exprime ici : rien à confronter pour l’instant.";
  }
  if (s.span_days < 90) {
    return `Le corpus ne couvre que ${duree(s.span_days)} sur ce sujet. Une position peut y
      paraître constante sans l’être : en deçà de quelques mois, l’absence de revirement
      ne prouve rien.`;
  }
  return `${s.n_speakers} voix sur ${duree(s.span_days)} : l’étendue suffit pour qu’un
    changement de position, s’il a eu lieu, soit visible.`;
}

// ── Rendu ───────────────────────────────────────────────────────────────────

function render(d) {
  const s = d.subject;
  const speakers = d.speakers || [];
  const total = speakers.reduce((n, x) => n + x.n, 0);

  const filtres = speakers.length > 1
    ? `<div class="filters" style="margin-top:var(--s4)">
        <button class="filter" data-who="" aria-pressed="${!state.speaker}">Tous</button>
        ${speakers.map((x) => `<button class="filter" data-who="${escapeHtml(x.name)}"
           aria-pressed="${state.speaker === x.name}">${escapeHtml(x.name)}<span class="count">${x.n}</span></button>`).join("")}
      </div>`
    : "";

  $("#page").innerHTML = `
    <header>
      ${kicker(s.theme, `${s.n_speakers} locuteur${s.n_speakers > 1 ? "s" : ""} · ${duree(s.span_days)} de recul`)}
      <h1 class="hero-title">${escapeHtml(s.label)}</h1>
      <p class="dek">${fmtNum(total)} prises de position consignées, ${periode(s.first_seen, s.last_seen)}.
        ${portee(s)}</p>
      ${s.named ? "" : `<p class="stamp" style="margin-top:var(--s3)">Libellé provisoire, tiré des
        mots du corpus — le nommage n’est pas encore passé sur ce sujet.</p>`}
    </header>

    <div class="band"><h2>Qui a dit quoi, quand</h2>
      <span class="spacer"></span><p>Clique un repère pour lire le propos.</p></div>
    ${frise(speakers, s.theme)}

    <div class="band"><h2>Les propos</h2>
      <span class="spacer"></span><p>Datés, cités mot pour mot, sourcés.</p></div>
    ${filtres}
    <div id="positions">${positionsHtml(speakers)}</div>

    ${d.contradictions?.length ? `
      <div class="band"><h2>Rapprochements</h2>
        <span class="spacer"></span><p>Propositions de la machine, à relire.</p></div>
      <div class="kv">${d.contradictions.map((e) => `
        <div class="kv__row" style="flex-wrap:wrap">
          <span class="kv__k" style="color:var(--ink)">${escapeHtml(e.type_label)}</span>
          <span class="kv__v">score ${e.score}</span>
          <span class="status status--${e.status === "confirmed" ? "ok" : e.status === "rejected" ? "alert" : "pending"}"
                style="margin-left:var(--s3)">${
            e.status === "confirmed" ? "confirmé" : e.status === "rejected" ? "écarté" : "à relire"}</span>
          ${e.rationale ? `<span class="kv__note">${escapeHtml(e.rationale)}</span>` : ""}
        </div>`).join("")}</div>` : ""}
  `;

  wire(d);
}

function wire(d) {
  const byId = new Map();
  for (const s of d.speakers || []) for (const c of s.claims) byId.set(String(c.id), { c, who: s.name });

  document.querySelectorAll(".frise__dot").forEach((b) => {
    b.onclick = () => {
      const hit = byId.get(b.dataset.claim);
      if (!hit) return;
      document.querySelectorAll('.frise__dot[aria-pressed="true"]')
        .forEach((o) => o.setAttribute("aria-pressed", "false"));
      b.setAttribute("aria-pressed", "true");

      const peek = $("#peek");
      peek.hidden = false;
      peek.innerHTML = `<div class="peek__meta">
          <span class="speaker">${escapeHtml(hit.who)}</span>
          <span class="stamp">${exactDate(hit.c.published_at) || "date inconnue"}</span>
          <span class="tag">${TYPE_LABEL[hit.c.claim_type] || ""}</span>
          <span class="spacer"></span>
          ${hit.c.source_url
            ? `<a class="source-link" href="${hit.c.source_url}" target="_blank" rel="noopener">source ↗</a>` : ""}
        </div>
        <p class="position__q">${escapeHtml(hit.c.text || hit.c.verbatim || "")}</p>`;

      // Marquer le propos correspondant plus bas : la frise sert de sommaire,
      // pas de vue de remplacement.
      document.querySelectorAll(".position--marked").forEach((o) => o.classList.remove("position--marked"));
      $(`#c${hit.c.id}`)?.classList.add("position--marked");
    };
  });

  document.querySelectorAll("[data-who]").forEach((b) => {
    b.onclick = () => {
      state.speaker = b.dataset.who || null;
      render(state.data);
    };
  });
}

async function load() {
  state.id = new URLSearchParams(location.search).get("id");
  if (!state.id) {
    $("#page").innerHTML = '<p class="state">Aucun sujet demandé.</p>';
    return;
  }
  try {
    state.data = await fetchJSON(`/subjects/${state.id}`);
    document.title = `${state.data.subject.label} — ED Mediawatch`;
    $("#stats").textContent = `${state.data.subject.n_speakers} locuteurs`;
    render(state.data);
  } catch (e) {
    $("#page").innerHTML =
      `<p class="state state--error">Ce sujet n’a pas pu être chargé (${escapeHtml(e.message)}).</p>`;
  }
}

load();
