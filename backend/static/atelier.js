// Atelier : l'état du système, lisible sans terminal.
// Helpers ($, fetchJSON, fmtNum, escapeHtml, relTime, exactDate) : common.js.

const REFRESH_MS = 30000;

const dur = (s) => {
  if (s == null) return "—";
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m} min ${Math.round(s % 60)} s` : `${Math.floor(m / 60)} h ${m % 60} min`;
};

const usd = (n) => `${(n ?? 0).toFixed(2)} $`;

// ── Entonnoir ───────────────────────────────────────────────────────────
//
// Pas de barres proportionnelles : les étages ne comptent pas la même unité
// (des publications, puis des déclarations, puis des sujets). Un pourcentage
// d'un étage à l'autre serait un chiffre faux présenté comme une mesure.
//
// Le point d'arrêt est le premier étage à zéro — pas le premier étage qui
// signale une réserve. Un millier de tweets tronqués est une réserve réelle,
// mais la chaîne continue ; la désigner comme le blocage détournerait le
// regard du vrai point mort.

function renderFunnel(data) {
  const steps = data.steps || [];
  const choke = steps.findIndex((s) => !s.n);

  $("#funnel").innerHTML = `<div class="funnel">${steps.map((s, i) => {
    const isChoke = i === choke;
    const waiting = choke !== -1 && i > choke && !s.n;
    const cls = isChoke ? " funnel__step--blocked" : waiting ? " funnel__step--waiting" : "";
    return `<div class="funnel__step${cls}">
      <span class="funnel__ord">${String(i + 1).padStart(2, "0")}</span>
      <div>
        <p class="funnel__label">${escapeHtml(s.step)}</p>
        ${s.detail ? `<p class="funnel__detail">${escapeHtml(s.detail)}</p>` : ""}
        ${s.blocked ? `<p class="funnel__why">${escapeHtml(s.blocked)}</p>` : ""}
        ${s.todo ? `<p class="funnel__todo">${escapeHtml(s.todo)}</p>` : ""}
      </div>
      <span class="funnel__n">${fmtNum(s.n)}</span>
    </div>`;
  }).join("")}</div>`;

  // La réponse en une phrase, avant le détail : c'est ce que quelqu'un vient
  // chercher ici, et il ne devrait pas avoir à la reconstituer en lisant six
  // lignes de chiffres.
  $("#verdict").innerHTML = choke === -1
    ? "La chaîne va jusqu’au bout : chaque étage alimente le suivant."
    : `La chaîne s’arrête à <em>${escapeHtml(steps[choke].step.toLowerCase())}</em>.`;

  return `${fmtNum(steps[1]?.n ?? 0)} déclarations · ${fmtNum(steps[3]?.n ?? 0)} sujets`;
}

// ── Dernière passe ──────────────────────────────────────────────────────

const STATUS_WORD = {
  ok: ["ok", "terminée"],
  running: ["pending", "en cours"],
  failed: ["alert", "en échec"],
  budget_exceeded: ["pending", "plafond atteint"],
  interrupted: ["alert", "interrompue"],
};

function renderLastRun(run) {
  if (!run) {
    $("#lastRun").innerHTML =
      '<p class="state">Aucune passe enregistrée. La première part deux minutes après le démarrage.</p>';
    return;
  }
  const [tone, word] = STATUS_WORD[run.status] || ["pending", run.status];
  const steps = (run.steps || []).map((s) =>
    `<span class="step-chip step-chip--${s.status}" title="${escapeHtml(
      `${s.status}${s.detail ? " — " + s.detail : ""} · ${dur(s.duration_s)}`)}">${escapeHtml(s.stage)}</span>`
  ).join("");

  // Ce que la passe a réellement produit : les chiffres rendus par chaque
  // étape. Une passe « ok » qui n'a rien produit est une information, pas un
  // succès — et sans ces lignes elle passerait pour l'un comme pour l'autre.
  const produced = (run.steps || [])
    .filter((s) => s.stats && Object.keys(s.stats).length)
    .map((s) => {
      const kv = Object.entries(s.stats)
        .filter(([, v]) => typeof v === "number" && v)
        .map(([k, v]) => `${k.replace(/_/g, " ")} ${fmtNum(v)}`)
        .join(" · ");
      return kv ? `<div class="kv__row"><span class="kv__k">${escapeHtml(s.stage)}</span>
        <span class="kv__v" style="font-size:var(--t-micro)">${escapeHtml(kv)}</span></div>` : "";
    }).join("");

  $("#lastRun").innerHTML = `
    <div class="kv">
      <div class="kv__row">
        <span class="kv__k">Passe n° ${run.id} · ${escapeHtml(run.trigger)} · périmètre ${escapeHtml(run.scope)}</span>
        <span class="status status--${tone}">${word}</span>
      </div>
      <div class="kv__row">
        <span class="kv__k">Démarrée</span>
        <span class="kv__v">${escapeHtml(exactDate(run.started_at))}</span>
      </div>
      <div class="kv__row">
        <span class="kv__k">${run.finished_at ? "Terminée" : "En cours depuis"}</span>
        <span class="kv__v">${escapeHtml(run.finished_at ? exactDate(run.finished_at) : relTime(run.started_at))}</span>
      </div>
      <div class="kv__row">
        <span class="kv__k">Coût imputé</span>
        <span class="kv__v">${usd(run.cost_usd)}</span>
      </div>
      ${produced}
    </div>
    <div class="steps" style="margin-top:var(--s4)">${steps}</div>`;
}

// ── Dépense ─────────────────────────────────────────────────────────────

function gauge(label, spent, cap) {
  const pct = cap > 0 ? Math.min(100, (spent / cap) * 100) : 0;
  const tight = pct >= 80;
  return `<div class="kv__row" style="flex-wrap:wrap">
    <span class="kv__k">${label}</span>
    <span class="kv__v">${usd(spent)}${cap > 0 ? ` / ${usd(cap)}` : " · sans plafond"}</span>
    ${cap > 0 ? `<div class="gauge" style="flex-basis:100%">
      <div class="gauge__track"><div class="gauge__fill${tight ? " gauge__fill--alert" : ""}"
        style="width:${pct.toFixed(1)}%"></div></div></div>` : ""}
  </div>`;
}

function renderSpend(c) {
  const rows = (c.by_model_month || [])
    .sort((a, b) => b.cost_usd - a.cost_usd).slice(0, 5)
    .map((m) => `<div class="kv__row">
      <span class="kv__k">${escapeHtml(m.task || "—")}</span>
      <span class="kv__v">${usd(m.cost_usd)}</span>
      <span class="kv__note">${escapeHtml(m.model)} · ${fmtNum(m.calls)} appels ·
        ${fmtNum(m.input_tokens)} jetons entrants · ${fmtNum(m.output_tokens)} sortants</span>
    </div>`).join("");

  // Un plafond est le seul endroit de la page où une jauge dit quelque chose
  // de vrai : la valeur est bien une fraction d'un maximum connu.
  $("#spend").innerHTML = `<div class="kv">
    ${gauge("Aujourd’hui", c.day_usd, c.daily_budget_usd)}
    ${gauge("Ce mois", c.month_usd, c.monthly_budget_usd)}
    ${rows}
    ${c.events_price_unknown_month
      ? `<div class="kv__row"><span class="kv__k">Appels sans tarif connu</span>
         <span class="kv__v">${fmtNum(c.events_price_unknown_month)}</span>
         <span class="kv__note">non comptés dans le total : le plafond protège moins qu’il n’y paraît</span></div>`
      : ""}
  </div>`;
}

// ── Fraîcheur ───────────────────────────────────────────────────────────

function freshRow(label, node, extra = "") {
  const tone = node.stale ? "alert" : "ok";
  const age = node.age_hours == null ? "jamais" : `il y a ${node.age_hours} h`;
  return `<div class="kv__row">
    <span class="kv__k">${label}</span>
    <span class="kv__v">${age}</span>
    <span class="status status--${tone}" style="margin-left:var(--s3)">${node.stale ? "périmé" : "à jour"}</span>
    ${extra ? `<span class="kv__note">${extra}</span>` : ""}
  </div>`;
}

function renderFresh(f) {
  $("#fresh").innerHTML = `<div class="kv">
    ${freshRow("Collecte X", f.x,
      f.x.last_post_at ? `dernier post ${escapeHtml(relTime(f.x.last_post_at))}` : "")}
    ${freshRow("Collecte presse", f.press,
      `${fmtNum(f.press.sources_stale)} source(s) muette(s) sur ${fmtNum(f.press.sources_total)}`)}
    <div class="kv__row">
      <span class="kv__k">Seuil de péremption</span>
      <span class="kv__v">${f.threshold_hours} h</span>
      <span class="kv__note">une collecte muette est plus dangereuse qu’une collecte absente :
        elle ne se signale pas</span>
    </div>
  </div>`;
}

// ── Journal ─────────────────────────────────────────────────────────────

function renderRuns(items) {
  if (!items.length) {
    $("#runs").innerHTML = '<p class="state">Aucune passe enregistrée.</p>';
    return;
  }
  $("#runs").innerHTML = `<table class="runs">
    <thead><tr>
      <th>Passe</th><th>Départ</th><th>Statut</th><th>Étapes</th>
      <th style="text-align:right">Durée</th><th style="text-align:right">Coût</th>
    </tr></thead>
    <tbody>${items.map((r) => {
      const [tone, word] = STATUS_WORD[r.status] || ["pending", r.status];
      const total = (r.steps || []).reduce((a, s) => a + (s.duration_s || 0), 0);
      const ok = (r.steps || []).filter((s) => s.status === "ok").length;
      return `<tr>
        <td class="num">${r.id}</td>
        <td class="stamp">${escapeHtml(relTime(r.started_at))}</td>
        <td><span class="status status--${tone}">${word}</span></td>
        <td class="num">${ok}/${(r.steps || []).length}</td>
        <td class="num">${dur(total)}</td>
        <td class="num">${usd(r.cost_usd)}</td>
      </tr>`;
    }).join("")}</tbody></table>`;
}

// ── Le graphe ───────────────────────────────────────────────────────────

function renderGraph(stages) {
  // Ce que produit une étape se lit à côté d'elle. Renvoyé au bout de la ligne,
  // le mot flottait sans se rattacher à quoi que ce soit.
  $("#graph").innerHTML = `<div class="kv">${stages.map((s) => `
    <div class="kv__row" style="flex-wrap:wrap">
      <span class="kv__k" style="color:var(--ink)">${escapeHtml(s.label)}</span>
      ${s.produces ? `<span class="kv__produces">→ ${escapeHtml(s.produces)}</span>` : ""}
      <span class="kv__v"><span class="tag">${s.cost === "paid" ? "payante" : "gratuite"}</span></span>
      <span class="kv__note">${s.depends_on.length
        ? "après " + s.depends_on.map(escapeHtml).join(", ")
        : "sans prérequis"}</span>
    </div>`).join("")}</div>`;
}

// ── Chargement ──────────────────────────────────────────────────────────

async function load() {
  try {
    const [f, runs, costs, fresh, graph] = await Promise.all([
      fetchJSON("/pipeline/funnel"),
      fetchJSON("/pipeline/runs?limit=8"),
      fetchJSON("/llm/costs").catch(() => null),
      fetchJSON("/health/freshness").catch(() => null),
      fetchJSON("/pipeline/stages").catch(() => null),
    ]);

    $("#stats").textContent = renderFunnel(f);
    renderLastRun((runs.items || [])[0]);
    renderRuns(runs.items || []);
    if (costs) renderSpend(costs);
    if (fresh) renderFresh(fresh);
    if (graph) renderGraph(graph.stages || []);

    const live = $("#live");
    live.hidden = false;
    $("#liveText").textContent = `relevé ${new Date().toLocaleTimeString("fr-FR")}`;
  } catch (e) {
    $("#funnel").innerHTML =
      `<p class="state state--error">L’état du système n’a pas pu être lu (${escapeHtml(e.message)}).</p>`;
  }
}

load();
// Rafraîchissement discret : c'est ce qui rend l'autonomie visible. Suspendu
// quand l'onglet est en arrière-plan — interroger une API que personne ne
// regarde ne sert qu'à faire du bruit.
setInterval(() => { if (!document.hidden) load(); }, REFRESH_MS);
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
