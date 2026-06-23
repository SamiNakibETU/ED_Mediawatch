// Validation des incohérences — file human-in-the-loop.
const API = "";  // même origine : le backend FastAPI sert ce front

const TYPE = {
  1: { label: "Revirement", color: "#ef4444" },
  2: { label: "Intra-parti", color: "#f59e0b" },
  3: { label: "Inter-partis", color: "#a855f7" },
  4: { label: "Écart programme", color: "#3b82f6" },
  5: { label: "Fact-check", color: "#14b8a6" },
  6: { label: "Variance", color: "#9ca3af" },
};
const PARTY_COLOR = { RN: "#2563eb", UDR: "#b45309", Reconquête: "#7c3aed" };

const state = { type: null };
const $ = (s) => document.querySelector(s);

function claimCard(c, side) {
  const who = c.speaker_name || c.party || "source presse";
  const date = c.published_at ? new Date(c.published_at).toLocaleDateString("fr-FR") : "—";
  const txt = c.canonical || c.verbatim;
  return `<div class="flex-1 rounded-lg border border-[#26262b] bg-[#141417] p-3">
    <div class="flex items-baseline gap-2">
      <span class="text-lg font-semibold" style="color:${PARTY_COLOR[c.party] || '#e4e4e7'}">${c.qty_value}${c.qty_unit ? " " + c.qty_unit : ""}</span>
      <span class="text-sm text-zinc-300">${who}</span>
      <span class="text-xs text-zinc-600">· ${date}</span>
    </div>
    <p class="mt-1.5 text-[13px] text-zinc-400 italic leading-snug">« ${(txt || "").slice(0, 220)} »</p>
  </div>`;
}

async function loadTypes() {
  const counts = {};
  for (const t of [null, 1, 2, 3, 6]) {
    const q = new URLSearchParams({ status: "pending", limit: 1 });
    if (t) q.set("type", t);
    const d = await (await fetch(`${API}/contradictions?${q}`)).json();
    counts[t ?? "all"] = d.total;
  }
  $("#typePills").innerHTML = [["all", "Toutes", null], ...[1, 2, 3, 6].map((t) => [t, TYPE[t].label, t])]
    .map(([key, label, t]) => {
      const active = state.type === t;
      const col = t ? TYPE[t].color : "#a1a1aa";
      return `<button data-t="${t ?? ''}" class="text-xs px-2.5 py-1 rounded-full border"
        style="${active ? `background:${col}1a;border-color:${col}66;color:${col}` : "border-color:#26262b;color:#8a8a93"}">
        ${label} <span class="opacity-60">${counts[key] ?? 0}</span></button>`;
    }).join("");
  document.querySelectorAll("#typePills button").forEach((b) =>
    b.onclick = () => { state.type = b.dataset.t ? +b.dataset.t : null; loadTypes(); load(); });
}

async function load() {
  const q = new URLSearchParams({ status: "pending", limit: 100 });
  if (state.type) q.set("type", state.type);
  const data = await (await fetch(`${API}/contradictions?${q}`)).json();
  $("#stats").innerHTML = `<span class="text-amber-300 font-medium">${data.total}</span> en attente`;
  const list = $("#list");
  if (!data.items.length) {
    list.innerHTML = "";
    $("#empty").classList.remove("hidden");
    $("#empty").textContent = "Aucune incohérence en attente. Lance la détection (POST /detect-contradictions).";
    return;
  }
  $("#empty").classList.add("hidden");
  list.innerHTML = data.items.map((c) => {
    const t = TYPE[c.type] || TYPE[6];
    return `<article class="card-enter rounded-xl border border-[#26262b] bg-[#0f0f12] p-4" data-id="${c.id}">
      <div class="flex items-center gap-2 mb-3">
        <span class="text-[11px] font-medium px-2 py-0.5 rounded" style="color:${t.color};background:${t.color}1a">${t.label}</span>
        <span class="text-[11px] text-zinc-500">score ${c.score}</span>
        <span class="text-[11px] text-zinc-600">· ${c.referent_key || ""}</span>
        <div class="flex-1"></div>
        <button data-act="confirm" class="text-xs px-3 py-1.5 rounded-lg bg-emerald-600/20 text-emerald-300 hover:bg-emerald-600/30">✓ Confirmer</button>
        <button data-act="reject" class="text-xs px-3 py-1.5 rounded-lg bg-zinc-700/40 text-zinc-300 hover:bg-zinc-700/60">✗ Écarter</button>
      </div>
      <div class="flex flex-col sm:flex-row items-stretch gap-2">
        ${claimCard(c.claim_a, "a")}
        <div class="grid place-items-center text-zinc-600 font-bold px-1">≠</div>
        ${claimCard(c.claim_b, "b")}
      </div>
      <p class="mt-2 text-[11px] text-zinc-600">${c.rationale || ""}</p>
    </article>`;
  }).join("");

  list.querySelectorAll("article").forEach((el) => {
    el.querySelectorAll("button[data-act]").forEach((b) =>
      b.onclick = () => validate(el.dataset.id, b.dataset.act, el));
  });
}

async function validate(id, decision, el) {
  el.style.opacity = "0.4";
  try {
    await fetch(`${API}/contradictions/${id}/validate?decision=${decision}`, { method: "POST" });
    el.remove();
    loadTypes();
    load();
  } catch {
    el.style.opacity = "1";
  }
}

loadTypes();
load();
