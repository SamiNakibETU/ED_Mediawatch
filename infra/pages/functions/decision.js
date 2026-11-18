// Décision d'un relecteur sur un écart, version en ligne (Cloudflare Pages).
//
// Le site en ligne est figé ; les décisions ne peuvent pas écrire en base. Elles attendent
// dans l'espace KV `DECISIONS`, une clé par décision (l'historique reste), jusqu'à ce que
// `python -m src.scripts.rapatrier_decisions` les ramène sur le poste de Sami.
//
// Le relecteur est identifié par Cloudflare Access, jamais par ce que la page envoie : on
// vérifie le jeton signé `Cf-Access-Jwt-Assertion` contre les clés publiques de l'équipe
// Access (variable ACCESS_TEAM, ex. « terranova » pour terranova.cloudflareaccess.com).
// Sans Access configuré, la fonction refuse tout : elle ne s'ouvre jamais par défaut.

const STATUTS = ["a_relire", "confirme", "ecarte"];

const b64url = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/").padEnd(s.length + (4 - (s.length % 4)) % 4, "=")), (c) => c.charCodeAt(0));

async function relecteur(request, env) {
  const jwt = request.headers.get("Cf-Access-Jwt-Assertion");
  if (!jwt || !env.ACCESS_TEAM) return null;
  const [h, p, sig] = jwt.split(".");
  if (!sig) return null;
  const entete = JSON.parse(new TextDecoder().decode(b64url(h)));
  const certs = await (await fetch(`https://${env.ACCESS_TEAM}.cloudflareaccess.com/cdn-cgi/access/certs`)).json();
  const jwk = (certs.keys || []).find((k) => k.kid === entete.kid);
  if (!jwk) return null;
  const cle = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", cle, b64url(sig), new TextEncoder().encode(`${h}.${p}`));
  if (!ok) return null;
  const charge = JSON.parse(new TextDecoder().decode(b64url(p)));
  if (charge.exp && charge.exp * 1000 < Date.now()) return null;
  if (env.ACCESS_AUD && ![].concat(charge.aud || []).includes(env.ACCESS_AUD)) return null;
  return charge.email || null;
}

export async function onRequestPost({ request, env }) {
  const qui = await relecteur(request, env).catch(() => null);
  if (!qui) return new Response("relecteur non identifié (Cloudflare Access)", { status: 401 });
  let d;
  try { d = await request.json(); } catch { return new Response("JSON attendu", { status: 400 }); }
  const ecart = Number(d.ecart);
  if (!Number.isInteger(ecart) || ecart <= 0) return new Response("écart inconnu", { status: 400 });
  if (!STATUTS.includes(d.statut)) return new Response("statut inconnu", { status: 400 });
  const quand = new Date().toISOString();
  const decision = { ecart, statut: d.statut, note: String(d.note || "").slice(0, 2000), relecteur: qui, quand };
  await env.DECISIONS.put(`decision:${ecart}:${quand}`, JSON.stringify(decision));
  return Response.json({ id: ecart, statut: d.statut });
}
