"""Tests for UI plugin listing routes."""

from unittest.mock import MagicMock, patch


class TestListPlugins:
    """Tests for GET /api/plugins."""

    def test_list_plugins_unauthenticated(self, ui_client):
        resp = ui_client.get("/api/plugins")
        assert resp.status_code == 401

    @patch("byod_cli.api_client.APIClient")
    def test_list_plugins_success(self, MockAPIClient, ui_client_authed):
        mock_client = MagicMock()
        mock_client.list_plugins.return_value = [
            {"name": "genomic-qc", "description": "Quality control"},
            {"name": "demo-count", "description": "Line counting"},
        ]
        MockAPIClient.return_value = mock_client

        resp = ui_client_authed.get("/api/plugins")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["name"] == "genomic-qc"
        assert data[1]["name"] == "demo-count"

    @patch("byod_cli.api_client.APIClient")
    def test_list_plugins_api_error(self, MockAPIClient, ui_client_authed):
        mock_client = MagicMock()
        mock_client.list_plugins.side_effect = Exception("Connection refused")
        MockAPIClient.return_value = mock_client

        resp = ui_client_authed.get("/api/plugins")
        assert resp.status_code == 502
        assert "Connection refused" in resp.json()["detail"]
