from fastapi.testclient import TestClient

from app.main import create_app


def test_frontend_helper_is_served_as_javascript(tmp_path):
    """Module scripts are rejected when Windows serves an unknown suffix as plain text."""
    with TestClient(create_app(f"sqlite:///{tmp_path / 'assets.db'}")) as client:
        response = client.get('/static/trip-ui.js')
        assert response.status_code == 200
        assert 'javascript' in response.headers['content-type']
