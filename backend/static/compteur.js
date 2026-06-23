// Le Compteur — scatter temporel des valeurs annoncées par référent.
const API = "";  // même origine : le backend FastAPI sert ce front

const PARTY_COLOR = {
  RN: "#2563eb", UDR: "#b45309", FIGURE: "#7c3aed",
  Reconquête: "#7c3aed", "Droite radicale": "#a855f7",
};
const colorFor = (party) => PARTY_COLOR[party] || "#9ca3af";

let chart;
const $ = (s) => document.querySelector(s);

async function loadList() {
  const res = await fetch(`${API}/compteurs`);
  const { compteurs } = await res.json();
  const el = $("#list");
  if (!compteurs.length) {
    el.innerHTML = `<p class="text-sm text-zinc-500">Aucun compteur encore. Lance l'extraction (<code>POST /extract-claims</code>).</p>`;
    return;
  }
  el.innerHTML = compteurs.map((c) => `
    <button data-key="${c.referent_key}" class="w-full text-left px-3 py-2 rounded-lg border border-[#26262b] hover:border-violet-500/50 bg-[#141417]">
      <div class="text-sm font-medium text-zinc-100">${c.label}</div>
      <div class="text-[11px] text-zinc-500 mt-0.5 flex gap-2">
        <span class="text-violet-300">${c.n_claims} valeurs</span>
        <span>·</span><span>${c.min}–${c.max} ${c.unit || ""}</span>
        ${c.spread > 0 ? `<span class="text-amber-400">écart ${c.spread}</span>` : ""}
      </div>
    </button>`).join("");
  el.querySelectorAll("button").forEach((b) => b.onclick = () => loadCompteur(b.dataset.key));
  if (compteurs.length) loadCompteur(compteurs[0].referent_key);
}

async function loadCompteur(key) {
  const res = await fetch(`${API}/compteur?key=${encodeURIComponent(key)}`);
  const data = await res.json();
  $("#title").textContent = data.label;
  $("#sub").textContent = `${data.n} valeur(s) annoncée(s) · unité : ${data.unit || "—"}`;

  const points = data.points
    .filter((p) => p.published_at)
    .map((p) => ({
      x: p.published_at, y: p.value,
      _p: p, backgroundColor: colorFor(p.party),
    }));

  if (chart) chart.destroy();
  chart = new Chart($("#chart"), {
    type: "scatter",
    data: { datasets: [{
      label: data.label, data: points,
      pointRadius: 7, pointHoverRadius: 10,
      backgroundColor: points.map((p) => p.backgroundColor),
      borderColor: "#0a0a0b", borderWidth: 1.5,
    }] },
    options: {
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          title: (items) => `${items[0].raw.y} ${data.unit || ""}`,
          label: (item) => {
            const p = item.raw._p;
            return [`${p.speaker || "—"} (${p.party || p.platform})`,
                    new Date(p.x).toLocaleDateString("fr-FR")];
          },
          afterBody: (items) => "\n" + (items[0].raw._p.verbatim || "").slice(0, 160),
        } },
      },
      scales: {
        x: { type: "time", time: { unit: "month" },
             grid: { color: "#1f1f24" }, ticks: { color: "#8a8a93" } },
        y: { grid: { color: "#1f1f24" }, ticks: { color: "#8a8a93" },
             title: { display: true, text: data.unit || "", color: "#8a8a93" } },
      },
    },
  });

  $("#points").innerHTML = data.points.map((p) => `
    <div class="rounded-lg border border-[#26262b] bg-[#141417] p-3">
      <div class="flex items-center gap-2 text-sm">
        <span class="font-semibold" style="color:${colorFor(p.party)}">${p.value} ${data.unit || ""}</span>
        <span class="text-zinc-400">${p.speaker || "—"}</span>
        <span class="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">${p.party || p.platform}</span>
        <span class="text-zinc-600 text-xs">${p.published_at ? new Date(p.published_at).toLocaleDateString("fr-FR") : ""}</span>
        ${p.human_validated ? '<span class="text-emerald-400 text-xs">✓ validé</span>' : ''}
        <div class="flex-1"></div>
        ${p.source_url ? `<a href="${p.source_url}" target="_blank" rel="noopener" class="text-[11px] text-zinc-600 hover:text-violet-300">source ↗</a>` : ""}
      </div>
      <p class="mt-1 text-[13px] text-zinc-400 italic">« ${(p.verbatim || "").slice(0, 240)} »</p>
    </div>`).join("");
}

loadList();
