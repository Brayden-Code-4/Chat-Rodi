"""Chargement minimal de .env (bibliothèque standard). Ne remplace jamais une variable déjà définie."""
import os


def load_env(path: str = None) -> None:
    path = path or os.path.join(os.getcwd(), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
