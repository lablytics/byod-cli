"""Tests for UI settings/profile routes."""


from fastapi.testclient import TestClient


class TestListProfiles:
    """Tests for GET /api/settings/profiles."""

    def test_list_profiles(self, ui_client_authed):
        resp = ui_client_authed.get("/api/settings/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "default"
        assert data[0]["active"] is True
        assert data[0]["has_api_key"] is True

    def test_list_profiles_multiple(self, mock_config_authed):
        from tests.conftest import _create_test_app

        mock_config_authed.list_profiles.return_value = ["default", "staging"]
        client = TestClient(_create_test_app(mock_config_authed))

        resp = client.get("/api/settings/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = [p["name"] for p in data]
        assert "default" in names
        assert "staging" in names


class TestActivateProfile:
    """Tests for POST /api/settings/profiles/{name}/activate."""

    def test_activate_profile_success(self, ui_client_authed):
        resp = ui_client_authed.post("/api/settings/profiles/default/activate")
        assert resp.status_code == 200
        assert resp.json()["active"] == "default"

    def test_activate_profile_not_found(self, ui_client_authed, mock_config_authed):
        mock_config_authed.profile_exists.return_value = False

        resp = ui_client_authed.post("/api/settings/profiles/nonexistent/activate")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]


class TestGetConfig:
    """Tests for GET /api/settings/config."""

    def test_get_config(self, ui_client_authed):
        resp = ui_client_authed.get("/api/settings/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_profile"] == "default"
        assert data["api_key_set"] is True
        assert "api_url" in data
        assert "config_path" in data

    def test_get_config_no_api_key(self, ui_client):
        resp = ui_client.get("/api/settings/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_key_set"] is False
