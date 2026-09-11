"""Basic health check tests."""

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_root_redirects_to_ui():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_api_docs_follow_enable_flag():
    """/docs, /redoc and /openapi.json are only served when ENABLE_API_DOCS."""
    expected = 200 if settings.ENABLE_API_DOCS else 404
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == expected, path
