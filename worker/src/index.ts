/**
 * Adaptateur Cloudflare Worker (Tier 3).
 * Rôle : recevoir le webhook Green API, répondre 200 tout de suite, puis transmettre les messages utiles
 * au cœur Python (chat_rodi.server, /core/event) via waitUntil. La logique métier reste en Python.
 * Ce fichier n'implémente pas de règles de prix ni de commande.
 */
export interface Env {
  KV: KVNamespace;
  CORE_URL: string;          // URL publique du cœur Python (variable, non secrète)
  WEBHOOK_TOKEN: string;     // secret : jeton Authorization (Green API -> Worker, et Worker -> cœur)
  AFI_CHAT_ID: string;
  GREEN_API_URL: string;
  GREEN_API_INSTANCE_ID: string;
  GREEN_API_TOKEN: string;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** Filtre : seulement les textes entrants individuels. */
function extractText(payload: any): { chatId: string; text: string; messageId: string } | null {
  if (payload?.typeWebhook !== "incomingMessageReceived") return null;
  const chatId: string = payload?.senderData?.chatId ?? "";
  if (!chatId || chatId.endsWith("@g.us")) return null;
  if (payload?.messageData?.typeMessage !== "textMessage") return null;
  const text: string = payload?.messageData?.textMessageData?.textMessage ?? "";
  if (!text) return null;
  return { chatId, text: text.slice(0, 1000), messageId: String(payload.idMessage ?? "") };
}

/** Compte les messages par client sur 1 heure (fenêtre fixe, KV). */
async function withinRate(env: Env, chatId: string, limit = 20): Promise<boolean> {
  const hour = Math.floor(Date.now() / 3600000);
  const key = `rate:${chatId}:${hour}`;
  const n = parseInt((await env.KV.get(key)) ?? "0", 10);
  if (n >= limit) return false;
  await env.KV.put(key, String(n + 1), { expirationTtl: 7200 });
  return true;
}

async function forwardToCore(env: Env, event: unknown) {
  const res = await fetch(`${env.CORE_URL.replace(/\/$/, "")}/core/event`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${env.WEBHOOK_TOKEN}` },
    body: JSON.stringify(event),
  });
  if (!res.ok) console.error("core error", res.status);
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (request.method === "GET") return json({ ok: true });
    if (request.method !== "POST") return new Response("method not allowed", { status: 405 });
    if (request.headers.get("Authorization") !== `Bearer ${env.WEBHOOK_TOKEN}`) {
      return new Response("unauthorized", { status: 401 });
    }
    let payload: any = {};
    try { payload = await request.json(); } catch { return json({ ok: true, ignored: "json" }); }
    const msg = extractText(payload);
    if (!msg) return json({ ok: true, ignored: true });

    // Dédoublonnage : un idMessage déjà vu est ignoré (fenêtre 24 h)
    if (msg.messageId) {
      const seen = await env.KV.get(`msg:${msg.messageId}`);
      if (seen) return json({ ok: true, duplicate: true });
      await env.KV.put(`msg:${msg.messageId}`, "1", { expirationTtl: 86400 });
    }
    const isAfi = msg.chatId === env.AFI_CHAT_ID;
    if (!isAfi && !(await withinRate(env, msg.chatId))) {
      ctx.waitUntil(sendGreen(env, msg.chatId, "Vous avez atteint la limite de messages pour l'instant."));
      return json({ ok: true, limited: true });
    }
    // Traitement en arrière-plan : réponse HTTP 200 immédiate
    ctx.waitUntil(forwardToCore(env, { chatId: msg.chatId, text: msg.text, messageId: msg.messageId,
                                      role: isAfi ? "gerant" : "client" }));
    return json({ ok: true });
  },
};

/** Envoi direct (rate limit) via Green API sendMessage. Les identifiants viennent des secrets. */
async function sendGreen(env: Env, chatId: string, message: string) {
  const url = `${env.GREEN_API_URL}/waInstance${env.GREEN_API_INSTANCE_ID}/sendMessage/${env.GREEN_API_TOKEN}`;
  await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
                     body: JSON.stringify({ chatId, message }) });
}
