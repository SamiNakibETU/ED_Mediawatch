"""timeline_ed : ordre des comptes et envoi idempotent de l'historique par les pages de profil."""

import json

from src.scripts import historique_x as hx
from src.scripts import timeline_ed as t


def test_new_accounts_come_first(monkeypatch, tmp_path):
    etat = tmp_path / "etat.json"
    etat.write_text(json.dumps({"MLP_officiel": {}}), encoding="utf-8")
    monkeypatch.setattr(t, "HISTORIQUE", etat)
    monkeypatch.setattr(t, "comptes_du_pool", lambda: ["MLP_officiel", "BrunoClavet", "J_Bardella"])
    assert t.ordre() == ["BrunoClavet", "J_Bardella", "MLP_officiel"]


def test_send_only_what_was_not_sent(monkeypatch, tmp_path):
    monkeypatch.setattr(t, "SORTIE", tmp_path)
    monkeypatch.setattr(t, "ENVOI", tmp_path / "envoi.json")
    monkeypatch.setattr(hx, "VIA", hx.VIA)                   # restauré après le test
    sent = []
    monkeypatch.setattr(hx, "envoyer", lambda tweets, jeton: sent.append(len(tweets)) or len(tweets))
    f = tmp_path / "BrunoClavet.ndjson"
    f.write_text("\n".join(json.dumps({"url": f"u{i}"}) for i in range(3)) + "\n", encoding="utf-8")
    assert t.envoyer_tout("jeton") == 3
    assert t.envoyer_tout("jeton") == 0                      # rien de neuf : rien n'est renvoyé
    with f.open("a", encoding="utf-8") as out:
        out.write(json.dumps({"url": "u3"}) + "\n")
    assert t.envoyer_tout("jeton") == 1
    assert sent == [3, 1] and hx.VIA == "xitter-profil"
