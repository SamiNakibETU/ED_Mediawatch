// Accès réservé à ED Mediawatch en ligne : authentification HTTP de base, sur toutes les pages,
// tous les fichiers et la fonction des décisions. Même principe que l'atlas des paiements (IRIS).
//
// Un compte par relecteur : le secret RELECTEURS du projet Pages est un JSON
// {"nom": "<sha256 hex du mot de passe>"}, posé par `publier_site --relecteur NOM`.
// Le nom du relecteur suit la requête (`data.relecteur`) : c'est lui qui signe une décision.
// Tant que le secret n'est pas défini, tout est refusé.

const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");

export async function onRequest({ request, env, next, data }) {
  let comptes = {};
  try { comptes = JSON.parse(env.RELECTEURS || "{}"); } catch { comptes = {}; }
  const recu = request.headers.get("Authorization") || "";
  let qui = null;
  if (recu.startsWith("Basic ")) {
    try {
      const [u, ...p] = atob(recu.slice(6)).split(":");
      const attendu = comptes[u];
      if (attendu) {
        const h = hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(p.join(":"))));
        if (h === attendu) qui = u;
      }
    } catch { qui = null; }
  }
  if (!qui) {
    return new Response("Accès réservé aux relecteurs d'ED Mediawatch.", { status: 401, headers: {
      "WWW-Authenticate": 'Basic realm="ED Mediawatch", charset="UTF-8"', "Content-Type": "text/plain; charset=utf-8",
      "X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store" } });
  }
  data.relecteur = qui;
  const reponse = await next();
  const r = new Response(reponse.body, reponse);
  r.headers.set("X-Robots-Tag", "noindex, nofollow");
  r.headers.set("Cache-Control", "private, no-store");
  return r;
}
