"""Serveur FastAPI.
- GET  /           : page d'accueil HTML (statut en direct, liens utiles). Aucun secret affiché.
- GET  /health     : statut JSON.
- POST /webhook    : webhook Green API direct (format Green), jeton Authorization vérifié.
- POST /core/event : entrée appelée par l'adaptateur Cloudflare Worker (format plat), même jeton.
Réponse HTTP 200 immédiate ; traitement en arrière-plan.
Lancer : uvicorn chat_rodi.server:app --port 8080
"""
import hmac
import logging

from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.responses import HTMLResponse

from .webhook_core import config, handle_event

app = FastAPI(title="Chat-Rodi")
log = logging.getLogger("chat_rodi")

HOME_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chat-Rodi | Boutique Dantokpa</title>
<style>
  :root { color-scheme: light dark; --bg:#fbf7f1; --card:#ffffff; --ink:#1f1a17; --muted:#6b625b; --accent:#c2410c; --ok:#15803d; --bad:#b91c1c; --line:#e7e0d7; }
  @media (prefers-color-scheme: dark) { :root { --bg:#14110f; --card:#1f1a17; --ink:#f5efe8; --muted:#a79d93; --accent:#fb923c; --line:#332d28; } }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; background:var(--bg); color:var(--ink); min-height:100vh; }
  header { padding:48px 24px 24px; max-width:960px; margin:0 auto; }
  .eyebrow { color:var(--accent); font-weight:600; letter-spacing:.08em; text-transform:uppercase; font-size:12px; }
  h1 { margin:8px 0 8px; font-size:clamp(28px,4vw,40px); line-height:1.15; }
  .lead { color:var(--muted); margin:0; max-width:640px; line-height:1.6; }
  main { max-width:960px; margin:0 auto; padding:0 24px 56px; display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); }
  .card { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:20px; }
  .card h2 { font-size:15px; margin:0 0 12px; }
  .status { display:flex; align-items:center; gap:10px; font-size:18px; font-weight:600; }
  .dot { width:12px; height:12px; border-radius:50%; background:var(--muted); flex:none; }
  .dot.ok { background:var(--ok); } .dot.bad { background:var(--bad); }
  .muted { color:var(--muted); font-size:14px; line-height:1.5; margin:8px 0 0; }
  a.btn { display:inline-block; margin:4px 8px 0 0; padding:9px 14px; border-radius:10px; border:1px solid var(--line); color:var(--ink); text-decoration:none; font-size:14px; }
  a.btn:hover { border-color:var(--accent); color:var(--accent); }
  code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size:13px; background:transparent; border:1px solid var(--line); border-radius:6px; padding:1px 6px; }
  footer { text-align:center; color:var(--muted); font-size:12px; padding:0 24px 32px; }
</style>
</head>
<body>
<header>
  <div class="eyebrow">Boutique Afi | Dantokpa</div>
  <h1>Chat-Rodi, vendeur WhatsApp</h1>
  <p class="lead">Service d'accueil et de vente automatisé. Cette page affiche l'état du service en direct. Les points d'entrée techniques sont listés ci-dessous.</p>
</header>
<main>
  <section class="card">
    <h2>Statut du service</h2>
    <div class="status"><span id="dot" class="dot"></span><span id="state">Vérification...</span></div>
    <p class="muted" id="detail">Interrogation de /health</p>
  </section>
  <section class="card">
    <h2>Points d'entrée</h2>
    <a class="btn" href="/health">/health</a>
    <a class="btn" href="/docs">Documentation API</a>
    <a class="btn" href="/openapi.json">OpenAPI</a>
    <p class="muted"><code>POST /webhook</code> et <code>POST /core/event</code> exigent un jeton d'autorisation. Ils ne sont pas accessibles depuis cette page.</p>
  </section>
  <section class="card">
    <h2>Pour tester</h2>
    <p class="muted">Ouvrir <code>/health</code> doit afficher <code>{"ok": true}</code>. Une requête POST sans jeton sur <code>/webhook</code> doit renvoyer 401.</p>
  </section>
</main>
<footer>Chat-Rodi | Vercel</footer>
<script>
  (async function () {
    var dot = document.getElementById('dot');
    var state = document.getElementById('state');
    var detail = document.getElementById('detail');
    try {
      var r = await fetch('/health', { cache: 'no-store' });
      var j = await r.json();
      if (r.ok && j && j.ok === true) {
        dot.className = 'dot ok'; state.textContent = 'En ligne';
        detail.textContent = 'Le serveur répond correctement (/health).';
      } else {
        dot.className = 'dot bad'; state.textContent = 'Anomalie';
        detail.textContent = 'Réponse inattendue de /health (HTTP ' + r.status + ').';
      }
    } catch (e) {
      dot.className = 'dot bad'; state.textContent = 'Hors ligne';
      detail.textContent = 'Impossible de joindre /health.';
    }
  })();
</script>
</body>
</html>
"""


def _safe_handle(payload: dict):
    try:
        log.info("event %s", handle_event(payload))
    except Exception as e:  # journal interne seulement, rien n'est renvoyé au client
        log.exception("erreur de traitement: %s", e.__class__.__name__)


def _authorized(request: Request, cfg: dict) -> bool:
    if not cfg["webhook_token"]:
        return False  # refus par défaut si le jeton n'est pas configuré
    expected = f"Bearer {cfg['webhook_token']}"
    return hmac.compare_digest(request.headers.get("authorization", ""), expected)


async def _json(request: Request) -> dict:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(HOME_HTML)


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    cfg = config()
    if not _authorized(request, cfg):
        return Response(status_code=401)
    background.add_task(_safe_handle, await _json(request))
    return {"ok": True}


@app.post("/core/event")
async def core_event(request: Request, background: BackgroundTasks):
    cfg = config()
    if not _authorized(request, cfg):
        return Response(status_code=401)
    e = await _json(request)
    if not e.get("chatId") or not e.get("text"):
        return {"ok": True, "ignored": True}
    # Reconstruit le format Green API pour passer par le même chemin de traitement
    green_like = {"typeWebhook": "incomingMessageReceived", "idMessage": str(e.get("messageId", "")),
                  "senderData": {"chatId": e["chatId"]},
                  "messageData": {"typeMessage": "textMessage", "textMessageData": {"textMessage": str(e["text"])}}}
    background.add_task(_safe_handle, green_like)
    return {"ok": True}


@app.get("/health")
async def health():
    return {"ok": True}
