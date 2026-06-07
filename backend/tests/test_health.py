def test_health_ok(client):
    """Health endpoint returns 200 and reports both service and DB as ok."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


def test_health_no_auth_required(client):
    """Health endpoint is publicly accessible — no Authorization header needed."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
