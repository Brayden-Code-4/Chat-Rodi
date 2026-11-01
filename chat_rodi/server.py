"""Serveur FastAPI.
- POST /webhook    : webhook Green API direct (format Green), jeton Authorization vérifié.
- POST /core/event : entrée appelée par l'adaptateur Cloudflare Worker (format plat), même jeton.
Réponse HTTP 200 immédiate ; traitement en arrière-plan.
Lancer : uvicorn chat_rodi.server:app --port 8080
"""
import hmac
import logging

from fastapi import BackgroundTasks, FastAPI, Request, Response

from .webhook_core import config, handle_event

app = FastAPI(title="Chat-Rodi")
log = logging.getLogger("chat_rodi")


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
