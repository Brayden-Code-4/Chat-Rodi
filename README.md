<img width="511" height="1080" alt="image" src="https://github.com/user-attachments/assets/a623bb70-b441-4ebd-9466-735de74271a3" />



# Chat-Rodi : vendeur WhatsApp intelligent pour la boutique d'Afi (Dantokpa)

Chat-Rodi répond aux clients de la boutique sur WhatsApp : il cherche les produits, vérifie le stock,
calcule les frais de livraison, convertit les montants et prépare les commandes. Une commande n'est
enregistrée qu'après la confirmation du client ET la validation d'Afi (ou de son gérant).

> Statut : code écrit et prêt, mais non exécuté dans l'environnement de rédaction (aucun interpréteur Python
> disponible à ce moment). Lancez les tests (section 6) avant toute mise en service. Le déploiement réel
> (Green API, Cloudflare, numéro WhatsApp) nécessite des comptes et une approbation explicite, voir section 8.


État du Déploiement et Connectivité WhatsApp
Architecture Multi-Agents (SMA) : Opérationnelle (FastAPI, boucle ReAct, agents Gérant, Vendeur, Logisticien, Rédacteur)
Déploiement Cloud : En ligne et vérifié sur Vercel (endpoints / et /health actifs)
Catalogue Dantokpa & Devises : Intégrés avec conversion dynamique (XOF/EUR/USD/NGN)
Passerelle WhatsApp (Green API) : La logique webhook est prête. L'instance WhatsApp a été mise en pause et déconnectée en production pour préserver le numéro personnel face au volume élevé de messages entrants
Mise en service finale : Nécessite uniquement la reconnexion d'un numéro WhatsApp dédié et la synchronisation des variables d'environnement (GREEN_API_TOKEN, WEBHOOK_TOKEN)

## 1. Architecture

```
chat_rodi/
  domain.py      catalogue, stock initial, zones et frais (source unique de vérité)
  tools.py       les 5 outils nommés verbe_objet
  agent.py       mono-agent : penser -> agir -> observer -> évaluer (MAX_STEPS = 8)
  multi.py       multi-agent : Gérant -> Vendeur, Logisticien, Rédacteur
  evaluator.py   évaluateur déterministe (toujours) + juge LLM Rodium (si configuré)
  fx.py          taux de change temps réel (open.er-api.com)
  rodium.py      client LLM Rodium (variables d'environnement)
  store.py       persistance JSON atomique, historique borné, idempotence
  webhook_core.py logique webhook Green API (filtres, doublons, limites, approbation Afi)
  server.py      FastAPI : POST /webhook, POST /core/event, GET /health
  cli.py         commandes locales chat et compare
worker/          adaptateur Cloudflare Worker (TypeScript), Tier 3
tests/           scénarios prescrits, sécurité, webhook, serveur
```

La logique métier reste en Python. Le Worker ne fait que recevoir, filtrer, dédoublonner et transmettre.

## 2. Les 5 outils (nom, rôle, entrées, sorties)

| Outil | Rôle | Entrées | Sortie principale |
|---|---|---|---|
| `chercher_produits` | Trouve les produits du message et leur quantité | texte | liste `{id, nom, prix, quantite_demandee}` |
| `verifier_stock` | Compare la quantité au stock, propose des alternatives en rupture | `produit_id`, `quantite` | `disponible`, `stock`, `alternatives` |
| `frais_livraison` | Frais et délai pour une zone desservie | `zone` | `frais`, `delai` (24 à 48 h), ou zones desservies si hors liste |
| `convertir_devise` | Convertit un montant FCFA (EUR, NGN, USD) au taux réel | `montant`, `devise` | `resultat`, `taux`, `source` |
| `creer_commande` | Enregistre la commande et décrémente le stock | `client_id`, `lignes`, `zone`, `client_confirmed`, `manager_approved` | `statut`, `commande` ou `raison` |

`creer_commande` refuse si la confirmation client ou la validation gérant manque, si le stock est
insuffisant, ou si la zone n'est pas desservie. Un refus est renvoyé comme observation, jamais ignoré.

## 3. Catalogue et règles (rappel)

| Code | Produit | Prix (FCFA) | Stock initial |
|---|---|---|---|
| P01 | Pagne wax 6 yards | 12 000 | 14 |
| P02 | Chemise bazin homme | 18 500 | 3 |
| P03 | Sac en raphia | 7 500 | 0 |
| P04 | Sandales en cuir | 9 000 | 8 |
| P05 | Robe en wax | 22 000 | 5 |
| P06 | Beurre de karité 500 g | 3 500 | 40 |

Frais : Cotonou 1 000, Akpakpa 1 000, Fidjrossè 1 500, Calavi 2 000, Porto-Novo 3 000, Ouidah 3 500.
Délai : 24 à 48 h. Autres zones : non desservies. Total = articles + frais de livraison, rien d'autre.

## 4. Les trois niveaux (tiers)

- Tier 1 : mono-agent en local avec boucle penser/agir/observer/évaluer (`chat_rodi/agent.py`).
- Tier 2 : multi-agent Gérant, Vendeur, Logisticien, Rédacteur (`chat_rodi/multi.py`), et comparaison.
- Tier 3 : webhook Green API en production (`chat_rodi/server.py`, `chat_rodi/webhook_core.py`) et
  adaptateur Cloudflare Worker (`worker/`), avec validation par Afi sur WhatsApp.

## 5. Évaluation

- Déterministe, toujours active : chaque nombre de la réponse doit provenir des faits (catalogue, frais,
  stock, totaux, taux). Une rupture doit citer une alternative. La réponse doit faire moins de 80 mots.
  Un total attendu doit apparaître.
- Juge LLM Rodium, seulement si `RODIUM_API_KEY`, `RODIUM_BASE_URL` et `RODIUM_MODEL` sont définis.
  Il applique les mêmes critères et renvoie `{"ok", "critique"}`. Si le juge échoue, le contrôle déterministe reste.
- En cas d'échec, Rodium réécrit la réponse avec la critique, au plus `MAX_STEPS` tours. Sans clé, ou si
  tout échoue, la réponse déterministe (`compose`) est utilisée. Elle est sûre par construction.

## 6. Installation et tests

Prérequis : Python 3.10 ou plus.

```bash
git clone https://github.com/Brayden-Code-4/Chat-Rodi.git
cd Chat-Rodi
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # remplir seulement si besoin (sans clé, tout tourne en mode déterministe)
pytest -q
```

Les tests tournent hors-ligne : taux de change depuis `tests/fixtures/fx_rates.json`, Rodium désactivé,
webhook en mode dry-run (aucun message réel envoyé).

## 7. Commandes CLI

```bash
# Mono-agent avec trace lisible
python -m chat_rodi.cli chat --mode single --client demo --message "2 pagnes livraison Cotonou, prix en euros ?"

# Multi-agent
python -m chat_rodi.cli chat --mode multi --client demo --message "Je veux 1 sac en raphia livraison Akpakpa"

# Simuler la validation gérant (oui/non) après une demande confirmée
python -m chat_rodi.cli chat --mode single --client afi --message "2 robes et 1 sac en raphia livraison Calavi" --approve oui

# Comparaison mono/multi sur les 3 scénarios prescrits (JSON)
python -m chat_rodi.cli compare

# Serveur webhook local
uvicorn chat_rodi.server:app --port 8080
```

## 8. Déploiement

### 8.1 Green API (instance de test)
1. Créer un compte sur https://green-api.com et une instance de test.
2. Lier le numéro WhatsApp de test (scan du QR code dans le tableau de bord).
3. Noter `idInstance` (-> `GREEN_API_INSTANCE_ID`) et `apiTokenInstance` (-> `GREEN_API_TOKEN`).
4. Dans les paramètres de l'instance, activer les notifications entrantes (incomingMessageReceived) et
   définir l'URL de webhook (voir 8.2 ou 8.3). Définir un jeton d'autorisation et le mettre dans `WEBHOOK_TOKEN`.
5. Renseigner `AFI_CHAT_ID` avec l'identifiant WhatsApp d'Afi au format `<numéro>@c.us`.
   Ce chat peut seul valider ou refuser les commandes.

Les noms d'endpoints et de champs Green API utilisés (`sendMessage`, `typeWebhook`, `messageData`, `senderData`) n'ont pas été vérifiés contre la documentation officielle : contrôlez-les avant mise en production.
`senderData`) suivent la documentation Green API. Vérifiez-les dans la doc officielle avant mise en production.

### 8.2 Serveur Python (option simple)
```bash
export WEBHOOK_TOKEN=... GREEN_API_INSTANCE_ID=... GREEN_API_TOKEN=... AFI_CHAT_ID=...
uvicorn chat_rodi.server:app --host 0.0.0.0 --port 8080
```
URL du webhook : `https://<votre-domaine>/webhook`. L'hébergement public est une décision à valider.

### 8.3 Cloudflare Worker (Tier 3)
1. Créer un compte Cloudflare, puis `cd worker && npm install`.
2. Créer le KV : `npx wrangler kv namespace create CHAT_RODI_KV`, puis reporter l'identifiant dans `wrangler.toml`.
3. Définir les secrets (jamais dans le dépôt) :
   `npx wrangler secret put WEBHOOK_TOKEN`, `GREEN_API_INSTANCE_ID`, `GREEN_API_TOKEN`, `AFI_CHAT_ID`.
4. Définir `CORE_URL` vers le cœur Python déployé (8.2) dans `wrangler.toml` ([vars]), non secret.
5. `npx wrangler deploy`. Le webhook Green API devient `https://chat-rodi.<compte>.workers.dev/`.
6. Le Worker utilise KV pour l'idempotence (`msg:<id>`, 24 h) et la limite de débit (`rate:<chat>:<heure>`).
   Limite : KV n'est pas transactionnel. Pour un usage plus strict, utilisez un Durable Object (non implémenté).
   Le stockage des commandes reste dans le cœur Python (JSON), non dans KV.

### 8.4 Tests de production à exécuter
1. Envoyer depuis un numéro client de test : `2 pagnes livraison Cotonou` -> réponse avec total 25000 FCFA.
2. Envoyer `Vous livrez à Lomé ?` -> réponse de zone non desservie, aucun frais.
3. Envoyer `1 sac en raphia Akpakpa` -> rupture et alternative Sandales en cuir.
4. Envoyer `2 robes et 1 sac en raphia Calavi`, puis `je confirme` -> Afi reçoit le récapitulatif REQ-xxxx.
5. Depuis le numéro de test non autorisé, envoyer `OUI REQ-0001` -> aucune commande créée.
6. Depuis le chat d'Afi, envoyer `OUI REQ-0001` : commande enregistrée et client notifié. Pour 2 robes plus 1 raphia à Calavi, le total attendu est 46000 FCFA (le sac en rupture n'est pas commandé).
7. Rejouer le même webhook (même idMessage) -> aucun second traitement.
8. Envoyer un message dans un groupe ou une image -> ignoré avec HTTP 200.

## 9. Trace attendue (illustration, pas une sortie réelle : à vérifier avec la commande ci-dessous)

Exécution : `chat --mode single --message "2 robes et 1 sac en raphia livraison Calavi"`. Sortie attendue
(les valeurs de stock et de totaux viennent du code et du store) :

```
(La trace exacte dépend du code ; lancez la commande pour la voir.)
[02] agir      chercher_produits(requete='2 robes et 1 sac en raphia livraison Calavi')
[03] observer  chercher_produits -> produits P05 (2), P03 (1)
[04] agir      verifier_stock(produit_id='P05', quantite=2)
[05] observer  verifier_stock -> disponible True (stock 5)
[06] agir      verifier_stock(produit_id='P03', quantite=1)
[07] observer  verifier_stock -> disponible False, alternatives [Sandales en cuir]
[08] agir      frais_livraison(zone='calavi')
[09] observer  frais_livraison -> 2000 FCFA
[10] évaluer   tentative 1 -> OK
```

Total : 2 x 22 000 + 2 000 = 46 000 FCFA (le sac en raphia n'est pas inclus, il est en rupture).

## 10. Comparaison mono-agent et multi-agent

Cette table est un gabarit : elle n'a pas encore été mesurée. Lancez `chat_rodi.cli compare` (0 appel LLM sans clé Rodium).
Les valeurs de temps varient selon la machine : relancez la commande pour votre propre mesure.

| Scénario | Mode | Réponse correcte (3 critères) | Appels outils | Appels LLM | Temps (s) | Coût Rodium |
|---|---|---|---|---|---|---|
| S1 pagnes en EUR | mono | oui (total 25 000, EUR) | à mesurer | 0 sans clé | à mesurer | [à renseigner] |
| S1 pagnes en EUR | multi | oui | à mesurer | 0 sans clé | à mesurer | [à renseigner] |
| S2 Lomé | mono | oui | à mesurer | 0 sans clé | à mesurer | [à renseigner] |
| S2 Lomé | multi | oui | à mesurer | 0 sans clé | à mesurer | [à renseigner] |
| S3 raphia rupture | mono | oui (alternative) | à mesurer | 0 sans clé | à mesurer | [à renseigner] |
| S3 raphia rupture | multi | oui | à mesurer | 0 sans clé | à mesurer | [à renseigner] |

Les colonnes « à mesurer » ne sont pas remplies : je n'ai pas pu exécuter le code. Remplissez-les avec
`python -m chat_rodi.cli compare`. Le coût Rodium reste à renseigner d'après leur grille tarifaire.

Conclusion (hypothèse de conception, à confirmer par mesure) : le multi-agent ajoute des appels internes et de la latence sans changer les résultats sur ces
trois scénarios, qui sont déterministes et courts. Il n'est utile que si la séparation des rôles devient
nécessaire (plusieurs canaux, équipes distinctes, ou règles de livraison plus complexes).

## 11. Ce qui reste à configurer par l'utilisateur

- Compte Green API, instance de test, numéro WhatsApp de test lié (action de l'utilisateur).
- Compte Cloudflare, si le Tier 3 Worker est déployé. Création du KV et des secrets.
- Clé et endpoint Rodium (`RODIUM_API_KEY`, `RODIUM_BASE_URL`, `RODIUM_MODEL`). Le schéma de l'API n'a pas été
  vérifié : `chat_rodi/rodium.py` suppose une API compatible OpenAI (`/chat/completions`). À confirmer.
- Captures d'écran WhatsApp : à produire par l'utilisateur après déploiement de test.
- Approbation explicite avant toute publication externe.
