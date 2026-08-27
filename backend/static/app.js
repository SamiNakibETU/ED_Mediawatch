// Registre des prises de parole sur X. Helpers : common.js.

const GROUPS = {
  ALL: { label: "Toutes", color: "var(--muted)" },
  RN: { label: "RN", color: "var(--grp-rn)" },
  UDR: { label: "UDR", color: "var(--grp-udr)" },
  FIGURE: { label: "Figures", color: "var(--grp-figure)" },
};

const state = {
  group: "ALL", hideRT: false, search: "", theme: null, subtheme: null,
  offset: 0, limit: 25, total: 0, loading: false, done: false,
};

const feedEl = $("#feed");
const sentinel = $("#sentinel");

function avatar(p) {
  const color = (GROUPS[p.group_code] || GROUPS.ALL).color;
  const initials = p.full_name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  const fallback = `<div class="initials" style="background:${color}">${initials}</div>`;
  const src = p.photo_url || (p.handle ? `https://unavatar.io/x/${p.handle}?fallback=false` : "");
  return src
    ? `<img class="entry__avatar" src="${src}" alt="" loading="lazy" width="44" height="44"
         onerror="this.outerHTML=this.dataset.fb" data-fb='${fallback}' />`
    : fallback;
}

function linkify(s) {
  return escapeHtml(s)
    .replace(/(https?:\/\/\S+)/g, '<a class="link" href="$1" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|\s)@(\w{1,15})/g, '$1<span class="handle">@$2</span>');
}

// Étiquettes : famille, parti à la date du propos, identité à confirmer.
function tags(it, p) {
  const g = GROUPS[p.group_code] || GROUPS.ALL;
  const out = [`<span class="tag tag--group" style="--grp-color:${g.color}">${g.label}</span>`];

  const fam = (p.famille || "").trim();
  if (fam && !["", g.label.toLowerCase(), "officiel", "groupe"].includes(fam.toLowerCase())) {
    out.push(`<span class="tag">${escapeHtml(fam)}</span>`);
  }
  const at = (it.party_at_date || "").trim();
  const known = [g.label, p.famille || "", p.group_code].map((s) => s.toLowerCase());
  if (at && !known.includes(at.toLowerCase())) {
    out.push(`<span class="tag" title="Parti à la date du propos">${escapeHtml(at)}</span>`);
  }
  if (p.verif === "a_confirmer") {
    out.push('<span class="tag" title="Identité non confirmée">identité à confirmer</span>');
  }
  return out.join("");
}

function metrics(it) {
  const parts = [];
  if (it.likes != null) parts.push(`<span><b>${fmtNum(it.likes)}</b> j’aime</span>`);
  if (it.retweets != null) parts.push(`<span><b>${fmtNum(it.retweets)}</b> RT</span>`);
  if (it.replies != null) parts.push(`<span><b>${fmtNum(it.replies)}</b> rép.</span>`);
  if (it.views != null) parts.push(`<span><b>${fmtNum(it.views)}</b> vues</span>`);
  return parts.length ? `<span class="metrics">${parts.join("")}</span>` : "";
}

function entry(it) {
  const p = it.personality;
  const kind = it.is_retweet ? "retweet" : it.is_reply ? "réponse"
    : it.post_type === "quote" ? "citation" : "";
  const role = [p.role, [p.departement, p.circo].filter(Boolean).join(" ")].filter(Boolean);
  const foot = [
    kind ? `<span class="tag">${kind}</span>` : "",
    it.theme ? `<span class="tag tag--theme">${escapeHtml(it.theme)}</span>` : "",
    (it.archived_at || it.snapshot_url) ? '<span class="tag tag--receipt" title="Copie archivée">reçu</span>' : "",
    metrics(it),
  ].filter(Boolean).join("");

  return `<article class="entry enter">
    <div>${avatar(p)}</div>
    <div>
      <div class="entry__head">
        <span class="speaker">${escapeHtml(p.full_name)}</span>
        ${p.handle ? `<a class="handle" href="https://x.com/${p.handle}" target="_blank" rel="noopener">@${p.handle}</a>` : ""}
        ${tags(it, p)}
        <span class="spacer"></span>
        <a class="stamp" href="${it.url}" target="_blank" rel="noopener" title="${exactDate(it.published_at)}">${relTime(it.published_at)}</a>
      </div>
      ${role.length ? `<p class="entry__role">${role.map(escapeHtml).join(" · ")}</p>` : ""}
      <p class="prose">${linkify(it.content)}</p>
      ${it.quoted_content
        ? `<blockquote class="quoted">${escapeHtml(it.quoted_content)}${it.quoted_handle ? ` — @${escapeHtml(it.quoted_handle)}` : ""}</blockquote>` : ""}
      ${it.media_url
        ? `<a href="${it.url}" target="_blank" rel="noopener"><img class="entry__media" src="${it.media_url}" alt="" loading="lazy" onerror="this.remove()" /></a>` : ""}
      <div class="entry__foot">${foot}<span class="spacer"></span>
        <a class="source-link" href="${it.url}" target="_blank" rel="noopener">source ↗</a>
      </div>
    </div>
  </article>`;
}

async function load(reset = false) {
  if (state.loading || (state.done && !reset)) return;
  state.loading = true;
  if (reset) { state.offset = 0; state.done = false; feedEl.innerHTML = ""; }
  sentinel.className = "state";
  sentinel.textContent = "Chargement…";

  const params = new URLSearchParams({
    limit: state.limit, offset: state.offset, include_retweets: (!state.hideRT).toString(),
  });
  if (state.group !== "ALL") params.set("group", state.group);
  if (state.search.trim()) params.set("q", state.search.trim());
  if (state.theme) params.set("theme", state.theme);
  if (state.subtheme) params.set("subtheme", state.subtheme);

  try {
    const data = await fetchJSON(`/feed?${params}`);
    state.total = data.total;
    feedEl.insertAdjacentHTML("beforeend", data.items.map(entry).join(""));
    state.offset += data.items.length;
    state.done = state.offset >= data.total || !data.items.length;
    sentinel.innerHTML = state.done
      ? (state.total
        ? `fin du registre · ${fmtNum(state.total)} entrées`
        : `<span class="state__title">Aucune entrée</span><span class="state__hint">Aucun propos ne correspond à ce filtre. Élargis la famille ou le thème.</span>`)
      : "";
    $("#stats").innerHTML = `<strong>${fmtNum(state.total)}</strong> entrées`;
  } catch (e) {
    sentinel.className = "state state--error";
    sentinel.textContent = `Le registre n’a pas pu être chargé (${e.message}). Vérifie que le backend répond.`;
  } finally {
    state.loading = false;
  }
}

function renderFilters() {
  $("#groupFilters").innerHTML = Object.entries(GROUPS).map(([k, g]) =>
    `<button class="filter" data-g="${k}" aria-pressed="${state.group === k}">${g.label}</button>`).join("");
  document.querySelectorAll("#groupFilters .filter").forEach((b) =>
    b.onclick = () => { state.group = b.dataset.g; renderFilters(); load(true); });
}

$("#hideRT").onchange = (e) => { state.hideRT = e.target.checked; load(true); };
let searchTimer;
$("#search").oninput = (e) => {
  clearTimeout(searchTimer); state.search = e.target.value;
  searchTimer = setTimeout(() => load(true), 250);
};

infiniteScroll(sentinel, () => load());
themeTree($("#themeTree"), {
  source: "posts",
  onSelect: ({ theme, subtheme }) => { state.theme = theme; state.subtheme = subtheme; load(true); },
});
renderFilters();
load(true);
