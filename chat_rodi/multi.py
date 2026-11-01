"""Mode multi-agent : Gérant (orchestrateur) -> Vendeur (catalogue, stock, commandes) ;
Logisticien (livraison, devises) ; Rédacteur (sans outil, mise en forme seulement).
Les sous-agents ne renvoient que des résumés. Le Gérant fait l'évaluation finale."""
import time

from . import domain as d
from . import tools as t
from .agent import Trace, _call, compose, handle_confirmation
from .evaluator import evaluate_deterministic, evaluate_llm
from .rodium import RodiumClient


class Vendeur:
    """Outils : chercher_produits, verifier_stock (puis creer_commande via le Gérant)."""
    name = "Vendeur"

    def __init__(self, store, trace):
        self.store, self.trace = store, trace

    def inspecter(self, message):
        lignes, ruptures, produits = [], [], []
        for p in _call(self.store, self.trace, "chercher_produits", requete=message)["produits"]:
            produits.append(p)
            st = _call(self.store, self.trace, "verifier_stock", produit_id=p["id"], quantite=p["quantite_demandee"])
            if st["disponible"]:
                lignes.append({"id": p["id"], "qty": p["quantite_demandee"]})
            else:
                ruptures.append({"nom": st["nom"], "id": p["id"], "stock": st["stock"],
                                 "alternatives": st.get("alternatives", [])})
        return {"produits": produits, "lignes": lignes, "ruptures": ruptures}


class Logisticien:
    """Outils : frais_livraison, convertir_devise."""
    name = "Logisticien"

    def __init__(self, store, trace):
        self.store, self.trace = store, trace

    def livrer(self, message, lignes):
        out = {"zone": None, "frais": None, "hors_zone": None, "conversion": None, "devise_erreur": None}
        zone, unsup = d.find_zone(message), d.find_unsupported(message)
        if unsup and not zone:
            out["hors_zone"] = unsup.capitalize()
        elif zone:
            out["zone"] = zone
            out["frais"] = _call(self.store, self.trace, "frais_livraison", zone=zone)["frais"]
        devise = d.find_currency(message)
        if devise and lignes and zone:
            conv = _call(self.store, self.trace, "convertir_devise", montant=d.subtotal(lignes), devise=devise)
            if conv.get("ok"):
                out["conversion"] = conv
            else:
                out["devise_erreur"] = conv.get("erreur")
        return out


class Redacteur:
    """Aucun outil. Met en forme les faits fournis par le Gérant (réponse déterministe)."""
    name = "Redacteur"

    def rediger(self, facts):
        return compose(facts)


class Gerant:
    name = "Gérant"

    def __init__(self, store, trace, rodium, manager_gate):
        self.store, self.trace, self.rodium, self.manager_gate = store, trace, rodium, manager_gate
        self.vendeur = Vendeur(store, trace)
        self.logisti = Logisticien(store, trace)
        self.redac = Redacteur()

    def traiter(self, client_id, message):
        self.trace.add("penser", "Gérant : délègue au Vendeur (catalogue, stock) puis au Logisticien (livraison, devise)")
        inv = self.vendeur.inspecter(message)
        self.trace.add("observer", "résumé Vendeur", {"lignes": inv["lignes"], "ruptures": [r["nom"] for r in inv["ruptures"]]})
        log = self.logisti.livrer(message, inv["lignes"])
        self.trace.add("observer", "résumé Logisticien", {k: log[k] for k in ("zone", "frais", "hors_zone")})
        facts = {"produits": inv["produits"], "lignes": inv["lignes"], "ruptures": inv["ruptures"],
                 "zone": log["zone"], "frais": log["frais"], "hors_zone": log["hors_zone"],
                 "conversion": log["conversion"], "devise_erreur": log["devise_erreur"],
                 "injection": d.looks_like_injection(message)}
        if d.is_confirmation(message) and not inv["lignes"]:
            from .agent import load_pending_into_facts
            load_pending_into_facts(self.store, client_id, facts)
        if inv["lignes"] and log["zone"]:
            facts["sous_total"] = d.subtotal(inv["lignes"])
            facts["total"] = d.total(inv["lignes"], log["zone"])
            self.store.data["pending"][client_id] = {"pid": self.store.next_id("REQ"),
                                                     "lignes": inv["lignes"], "zone": log["zone"]}
            self.store.save()
            facts["commande_statut"] = "en_attente"
        if d.is_confirmation(message) and client_id in self.store.data["pending"]:
            handle_confirmation(self.store, self.trace, client_id, facts, self.manager_gate)
        reply = self.redac.rediger(facts)
        problems = evaluate_deterministic(reply, facts)
        if self.rodium.enabled and not problems:
            try:
                ok, critique = evaluate_llm(self.rodium, reply, facts)
                problems = [] if ok else [critique]
            except Exception as e:
                self.trace.add("évaluer", f"juge LLM en échec ({e.__class__.__name__})")
        self.trace.add("évaluer", "Gérant (évaluation finale)", problems or "OK")
        return reply, facts, problems


def run_multi(store, client_id, message, manager_gate=None, rodium=None, verbose=False) -> dict:
    start = time.time()
    trace = Trace(verbose)
    rodium = rodium or RodiumClient()
    before = rodium.calls
    reply, facts, problems = Gerant(store, trace, rodium, manager_gate).traiter(client_id, message)
    store.add_history(client_id, "client", message)
    store.add_history(client_id, "vendeur", reply)
    store.save()
    return {"reply": reply, "facts": facts, "trace": trace.steps, "llm_calls": rodium.calls - before,
            "elapsed_s": round(time.time() - start, 4), "evaluations": [{"attempt": 1, "problems": problems}],
            "tool_calls": sum(1 for s in trace.steps if s["phase"] == "agir")}
