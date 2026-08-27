// Le Compteur — les valeurs annoncées pour un même référent, dans le temps.
// L'écart entre deux points est le matériau du travail : on le montre, on ne le lisse pas.
// Helpers ($, fetchJSON, fmtNum, exactDate) : common.js.

const PARTY_VAR = {
  RN: "--grp-rn", UDR: "--grp-udr", FIGURE: "--grp-figure",
  "Reconquête": "--grp-figure", "Droite radicale": "--grp-figure",
};

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const colorFor = (party) => css(PARTY_VAR[party] || "--muted");

let chart;

async function loadList() {
  const el = $("#list");
  let compteurs = [];
  try {
    ({ compteurs } = await fetchJSON("/compteurs"));
  } catch (e) {
    el.innerHTML = `<p class="state state--error">Compteurs indisponibles (${e.message}).</p>`;
    return;
  }
  if (!compteurs.length) {
    el.innerHTML = `<p class="state"><span class="state__title">Aucun compteur</span>
      <span class="state__hint">Aucune valeur chiffrée n’a encore été extraite. Lance l’analyse pour peupler le relevé.</span></p>`;
    return;
  }

  el.innerHTML = compteurs.map((c) => `
    <button class="referent" data-key="${c.referent_key}" aria-pressed="false">
      <span class="referent__label">${escapeHtml(c.label)}</span>
      <span class="referent__meta">${c.n_claims} valeurs · ${c.min}–${c.max} ${escapeHtml(c.unit || "")}${
        c.spread > 0 ? ` · écart ${c.spread}` : ""}</span>
    </button>`).join("");

  el.querySelectorAll(".referent").forEach((b) => b.onclick = () => {
    el.querySelectorAll(".referent").forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
    loadCompteur(b.dataset.key);
  });
  el.querySelector(".referent").setAttribute("aria-pressed", "true");
  $("#stats").innerHTML = `<strong>${compteurs.length}</strong> référents`;
  loadCompteur(compteurs[0].referent_key);
}

async function loadCompteur(key) {
  let data;
  try {
    data = await fetchJSON(`/compteur?key=${encodeURIComponent(key)}`);
  } catch (e) {
    $("#points").innerHTML = `<p class="state state--error">Relevé indisponible (${e.message}).</p>`;
    return;
  }

  $("#title").textContent = data.label;
  $("#sub").textContent = `${data.n} valeur${data.n > 1 ? "s" : ""} annoncée${data.n > 1 ? "s" : ""} · unité : ${data.unit || "—"}`;

  const points = data.points.filter((p) => p.published_at)
    .map((p) => ({ x: p.published_at, y: p.value, _p: p }));

  chart?.destroy();
  chart = new Chart($("#chart"), {
    type: "scatter",
    data: { datasets: [{
      label: data.label,
      data: points,
      pointRadius: 6, pointHoverRadius: 9,
      backgroundColor: points.map((p) => colorFor(p._p.party)),
      borderColor: css("--surface"), borderWidth: 1.5,
    }] },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: css("--ink"), titleColor: css("--paper"), bodyColor: css("--paper"),
          padding: 10, cornerRadius: 4, displayColors: false,
          titleFont: { family: "IBM Plex Mono" }, bodyFont: { family: "IBM Plex Sans" },
          callbacks: {
            title: (i) => `${i[0].raw.y} ${data.unit || ""}`,
            label: (i) => {
              const p = i.raw._p;
              return [`${p.speaker || "locuteur inconnu"} · ${p.party || p.platform}`,
                      new Date(p.x).toLocaleDateString("fr-FR")];
            },
            afterBody: (i) => "\n" + (i[0].raw._p.verbatim || "").slice(0, 160),
          },
        },
      },
      scales: {
        x: { type: "time", time: { unit: "month" },
             grid: { color: css("--rule") },
             ticks: { color: css("--muted"), font: { family: "IBM Plex Mono", size: 11 } } },
        y: { grid: { color: css("--rule") },
             ticks: { color: css("--muted"), font: { family: "IBM Plex Mono", size: 11 } },
             title: { display: true, text: data.unit || "", color: css("--faint") } },
      },
    },
  });

  $("#points").innerHTML = data.points.map((p) => `
    <article class="entry enter" style="grid-template-columns:1fr">
      <div>
        <div class="entry__head">
          <span class="claim__value" style="color:${colorFor(p.party)}">${p.value} ${escapeHtml(data.unit || "")}</span>
          <span class="speaker">${escapeHtml(p.speaker || "locuteur inconnu")}</span>
          <span class="tag">${escapeHtml(p.party || p.platform)}</span>
          ${p.human_validated ? '<span class="tag tag--receipt">validé</span>' : ""}
          <span class="spacer"></span>
          <span class="stamp">${p.published_at ? new Date(p.published_at).toLocaleDateString("fr-FR") : "date inconnue"}</span>
        </div>
        <blockquote class="quoted">${escapeHtml((p.verbatim || "").slice(0, 240))}</blockquote>
        ${p.source_url ? `<div class="entry__foot"><span class="spacer"></span>
          <a class="source-link" href="${p.source_url}" target="_blank" rel="noopener">source ↗</a></div>` : ""}
      </div>
    </article>`).join("");
}

loadList();
