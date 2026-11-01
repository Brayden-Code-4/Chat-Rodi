import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
FIX = os.path.join(os.path.dirname(__file__), "fixtures", "fx_rates.json")


@pytest.fixture(autouse=True)
def offline_env(monkeypatch, tmp_path):
    """Tests hors-ligne : taux en fixture, Rodium désactivé, webhook en dry-run, store jetable."""
    monkeypatch.setenv("FX_RATES_FILE", FIX)
    for k in ["RODIUM_API_KEY", "RODIUM_BASE_URL", "RODIUM_MODEL", "GREEN_API_INSTANCE_ID", "GREEN_API_TOKEN",
              "WEBHOOK_TOKEN", "AFI_CHAT_ID"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("STORE_PATH", str(tmp_path / "store.json"))


@pytest.fixture
def store(tmp_path):
    from chat_rodi.store import JsonStore
    return JsonStore(str(tmp_path / "store.json"))


@pytest.fixture
def cfg(tmp_path):
    return {"green_url": "http://unused", "instance": "", "token": "", "webhook_token": "",
            "afi_chat": "AFI@c.us", "store": str(tmp_path / "store.json")}
