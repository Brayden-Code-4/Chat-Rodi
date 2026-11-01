"""Évaluateurs de qualité.
1) Déterministe (toujours actif) : nombres justifiés par les FAITS, alternative en cas de rupture,
   moins de 80 mots, total présent quand une commande est chiffrée.
2) LLM juge (Rodium, seulement si configuré) : mêmes critères, réponse JSON {"ok", "critique"}.
"""
import json
import re

from . import domain as d

MAX_WORDS = 80
CRITERIA = (
    "Critères : (1) aucun prix, stock, frais, taux ou total qui ne figure pas dans les FAITS fournis ; "
    "(2) si un produit est en rupture, la réponse propose une alternative listée dans les FAITS ; "
    "(3) moins de 80 mots ; (4) ton court, style WhatsApp, en français."
)
REWRITE_SYSTEM = ("Tu es le vendeur WhatsApp de la boutique d'Afi. Réécris la réponse en français, court "
                  "(moins de 80 mots), sans aucun chiffre absent des FAITS. Ne jamais inventer de prix, stock, "
                  "frais ou taux. En cas de rupture, proposer une alternative des FAITS.")
# Nombres toujours légitimes : identifiants et durées de livraison
BASE_NUMBERS = {24, 48} | set(d.FEES.values()) | {p["prix"] for p in d.CATALOG.values()} \
    | set(d.INITIAL_STOCK.values())


def _numbers(text: str):
    text = re.sub(r"\bP\d{2}\b|\b[A-Z]{3}-\d{4}\b", " ", text)   # identifiants (P05, CMD-0001, REQ-0001)
    text = re.sub(r"(?<=\d)[ .,](?=\d{3}\b)", "", text)           # 46 000 -> 46000
    return {int(float(n)) for n in re.findall(r"\d+(?:\.\d+)?", text)}


def _walk(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)
    else:
        yield obj


def evaluate_deterministic(reply: str, facts: dict) -> list:
    problems = []
    allowed = set(BASE_NUMBERS)
    for v in _walk(facts):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            allowed.add(int(round(v)))
    unknown = sorted(n for n in _numbers(reply) if n not in allowed and n >= 10)
    if unknown:
        problems.append(f"nombres non justifiés par les faits : {unknown}")
    if len(reply.split()) >= MAX_WORDS:
        problems.append("réponse trop longue (80 mots ou plus)")
    for rupture in facts.get("ruptures", []):
        if rupture.get("alternatives") and not any(a["nom"] in reply for a in rupture["alternatives"]):
            problems.append(f"rupture de {rupture['nom']} sans alternative proposée")
    if facts.get("total") is not None and facts.get("commande_statut") != "enregistree":
        if str(facts["total"]) not in re.sub(r"\s", "", reply) and not facts.get("ruptures"):
            problems.append("total attendu absent de la réponse")
    return problems


def evaluate_llm(client, reply: str, facts: dict):
    """Renvoie (ok, critique). Lève une exception si Rodium échoue ou répond mal (géré par l'appelant)."""
    system = ("Tu es un évaluateur qualité pour un vendeur WhatsApp. " + CRITERIA +
              ' Réponds uniquement par JSON : {"ok": true|false, "critique": "..."}.')
    user = f"FAITS : {json.dumps(facts, ensure_ascii=False)}\nRÉPONSE : {reply}"
    raw = client.chat(system, user)
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("juge LLM : pas de JSON")
    data = json.loads(m.group(0))
    return bool(data.get("ok")), str(data.get("critique", ""))
