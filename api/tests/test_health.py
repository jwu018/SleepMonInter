"""The API starts and answers /health."""

from fastapi.testclient import TestClient

from app.main import API_VERSION, app

# TestClient calls the app directly in memory: no server and no network.
client = TestClient(app)


def test_health_reports_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "night-night-api", "version": API_VERSION}


def test_unknown_route_is_404() -> None:
    assert client.get("/nope").status_code == 404


def test_cors_allows_the_local_web_app() -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
