"""The API has no login, so it must only answer this machine's own pages (Host and Origin guard)."""


def test_loopback_host_allowed(client):
    for host in ("localhost:8787", "127.0.0.1:8787", "[::1]:8787"):
        assert client.get("/api/status", headers={"Host": host}).status_code == 200


def test_foreign_host_refused(client):        # DNS rebinding: attacker.example resolves to 127.0.0.1
    r = client.get("/api/status", headers={"Host": "attacker.example:8787"})
    assert r.status_code == 403


def test_cross_site_write_refused(client):
    for origin in ("https://evil.example", "null"):
        r = client.post("/api/uploads", headers={"Origin": origin})
        assert r.status_code == 403 and "cross-site" in r.json()["detail"]


def test_same_machine_origin_allowed(client):
    r = client.post("/api/uploads", headers={"Origin": "http://localhost:5173"})
    assert r.status_code != 403                # (the upload itself fails validation: no file)


def test_extra_host_from_env(client, monkeypatch):
    monkeypatch.setenv("ATOM_ALLOWED_HOSTS", "atom.lan")
    assert client.get("/api/status", headers={"Host": "atom.lan"}).status_code == 200
