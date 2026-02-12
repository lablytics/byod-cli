"""Tests for UI job routes."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestListJobs:
    """Tests for GET /api/jobs."""

    def test_list_jobs_unauthenticated(self, ui_client):
        resp = ui_client.get("/api/jobs")
        assert resp.status_code == 401

    @patch("byod_cli.api_client.APIClient")
    def test_list_jobs_success(self, MockAPIClient, ui_client_authed):
        mock_client = MagicMock()
        mock_client.list_jobs.return_value = [
            {"job_id": "j1", "status": "completed", "plugin_name": "demo-count"},
            {"job_id": "j2", "status": "processing", "plugin_name": "genomic-qc"},
        ]
        MockAPIClient.return_value = mock_client

        resp = ui_client_authed.get("/api/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["job_id"] == "j1"

    @patch("byod_cli.api_client.APIClient")
    def test_list_jobs_with_filters(self, MockAPIClient, ui_client_authed):
        mock_client = MagicMock()
        mock_client.list_jobs.return_value = []
        MockAPIClient.return_value = mock_client

        resp = ui_client_authed.get("/api/jobs?limit=10&status=completed&plugin=demo-count")
        assert resp.status_code == 200
        mock_client.list_jobs.assert_called_once_with(
            limit=10, status="completed", plugin="demo-count",
        )

    @patch("byod_cli.api_client.APIClient")
    def test_list_jobs_api_error(self, MockAPIClient, ui_client_authed):
        mock_client = MagicMock()
        mock_client.list_jobs.side_effect = Exception("Service unavailable")
        MockAPIClient.return_value = mock_client

        resp = ui_client_authed.get("/api/jobs")
        assert resp.status_code == 502
        assert "Service unavailable" in resp.json()["detail"]


class TestGetJob:
    """Tests for GET /api/jobs/{job_id}."""

    @patch("byod_cli.api_client.APIClient")
    def test_get_job_success(self, MockAPIClient, ui_client_authed):
        mock_client = MagicMock()
        mock_client.get_job_status.return_value = {
            "job_id": "j1",
            "status": "completed",
            "plugin_name": "demo-count",
        }
        MockAPIClient.return_value = mock_client

        resp = ui_client_authed.get("/api/jobs/j1")
        assert resp.status_code == 200
        assert resp.json()["job_id"] == "j1"

    @patch("byod_cli.api_client.APIClient")
    def test_get_job_api_error(self, MockAPIClient, ui_client_authed):
        mock_client = MagicMock()
        mock_client.get_job_status.side_effect = Exception("Not found")
        MockAPIClient.return_value = mock_client

        resp = ui_client_authed.get("/api/jobs/nonexistent")
        assert resp.status_code == 502


class TestListResults:
    """Tests for GET /api/jobs/{job_id}/results."""

    def test_list_results_not_found(self, ui_client_authed):
        resp = ui_client_authed.get("/api/jobs/no-such-job/results")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_list_results_success(self, ui_client_authed):
        with tempfile.TemporaryDirectory() as tmp:
            results_base = Path(tmp)
            job_id = "test-job-123"
            decrypted_dir = results_base / job_id / "decrypted"
            decrypted_dir.mkdir(parents=True)

            # Create some test result files
            (decrypted_dir / "report.html").write_text("<html>report</html>")
            (decrypted_dir / "data.csv").write_text("col1,col2\n1,2\n")

            with patch("byod_cli.ui.routes.jobs.RESULTS_BASE", results_base):
                resp = ui_client_authed.get(f"/api/jobs/{job_id}/results")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["files"]) == 2
                names = [f["name"] for f in data["files"]]
                assert "report.html" in names
                assert "data.csv" in names

    def test_list_results_nested_files(self, ui_client_authed):
        with tempfile.TemporaryDirectory() as tmp:
            results_base = Path(tmp)
            decrypted_dir = results_base / "nested-job" / "decrypted"
            sub_dir = decrypted_dir / "subdir"
            sub_dir.mkdir(parents=True)
            (sub_dir / "nested.txt").write_text("nested content")

            with patch("byod_cli.ui.routes.jobs.RESULTS_BASE", results_base):
                resp = ui_client_authed.get("/api/jobs/nested-job/results")
                assert resp.status_code == 200
                files = resp.json()["files"]
                assert len(files) == 1
                assert "subdir/nested.txt" in files[0]["path"] or "subdir\\nested.txt" in files[0]["path"]


class TestGetResultFile:
    """Tests for GET /api/jobs/{job_id}/results/file."""

    def test_get_result_file_success(self, ui_client_authed):
        with tempfile.TemporaryDirectory() as tmp:
            results_base = Path(tmp)
            decrypted_dir = results_base / "file-job" / "decrypted"
            decrypted_dir.mkdir(parents=True)
            (decrypted_dir / "output.txt").write_text("hello world")

            with patch("byod_cli.ui.routes.jobs.RESULTS_BASE", results_base):
                resp = ui_client_authed.get("/api/jobs/file-job/results/file?path=output.txt")
                assert resp.status_code == 200
                assert resp.text == "hello world"

    def test_get_result_file_not_found(self, ui_client_authed):
        with tempfile.TemporaryDirectory() as tmp:
            results_base = Path(tmp)
            decrypted_dir = results_base / "file-job" / "decrypted"
            decrypted_dir.mkdir(parents=True)

            with patch("byod_cli.ui.routes.jobs.RESULTS_BASE", results_base):
                resp = ui_client_authed.get("/api/jobs/file-job/results/file?path=missing.txt")
                assert resp.status_code == 404

    def test_get_result_file_path_traversal(self, ui_client_authed):
        with tempfile.TemporaryDirectory() as tmp:
            results_base = Path(tmp)
            decrypted_dir = results_base / "traversal-job" / "decrypted"
            decrypted_dir.mkdir(parents=True)

            # Create a file outside the decrypted dir
            (results_base / "secret.txt").write_text("secret data")

            with patch("byod_cli.ui.routes.jobs.RESULTS_BASE", results_base):
                resp = ui_client_authed.get(
                    "/api/jobs/traversal-job/results/file?path=../../secret.txt"
                )
                assert resp.status_code == 400
                assert "Invalid" in resp.json()["detail"]

    def test_get_result_file_download(self, ui_client_authed):
        with tempfile.TemporaryDirectory() as tmp:
            results_base = Path(tmp)
            decrypted_dir = results_base / "dl-job" / "decrypted"
            decrypted_dir.mkdir(parents=True)
            (decrypted_dir / "data.csv").write_text("a,b\n1,2\n")

            with patch("byod_cli.ui.routes.jobs.RESULTS_BASE", results_base):
                resp = ui_client_authed.get(
                    "/api/jobs/dl-job/results/file?path=data.csv&download=true"
                )
                assert resp.status_code == 200
                assert "attachment" in resp.headers.get("content-disposition", "")

    def test_job_id_path_traversal(self, ui_client_authed):
        """Verify path traversal via job_id is blocked."""
        with tempfile.TemporaryDirectory() as tmp:
            results_base = Path(tmp)
            with patch("byod_cli.ui.routes.jobs.RESULTS_BASE", results_base):
                resp = ui_client_authed.get("/api/jobs/../../etc/results")
                # Should be 404 (sanitized job_id won't match any real directory)
                assert resp.status_code in (400, 404)


class TestGetResults:
    """Tests for POST /api/jobs/{job_id}/get (SSE stream)."""

    @patch("byod_cli.api_client.APIClient")
    def test_get_results_job_not_completed(self, MockAPIClient, ui_client_authed):
        mock_client = MagicMock()
        mock_client.get_job_status.return_value = {"status": "processing"}
        MockAPIClient.return_value = mock_client

        resp = ui_client_authed.post("/api/jobs/j1/get")
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) > 0
        assert "not completed" in error_events[0]["data"]["message"]

    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_get_results_success(self, MockAPIClient, mock_boto3, ui_client_authed):
        import os

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        mock_client = MagicMock()
        mock_client.get_job_status.return_value = {"status": "completed"}
        mock_client.get_download_url.return_value = "https://s3.example.com/presigned"

        # Create encrypted test data
        key = os.urandom(32)
        nonce = os.urandom(12)
        aesgcm = AESGCM(key)
        plaintext = b"result data content"
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        encrypted_data = nonce + ciphertext

        def mock_download(url, path):
            if "output_key" in str(path) or "key" in str(path):
                Path(path).write_bytes(b"wrapped-key-data")
            else:
                Path(path).write_bytes(encrypted_data)

        mock_client.download_file.side_effect = mock_download

        # Mock tenant config
        tenant_config = MagicMock()
        tenant_config.customer_kms_key_arn = "arn:aws:kms:us-east-1:123:key/test"
        tenant_config.kms_key_arn = None
        tenant_config.region = "us-east-1"
        mock_client.get_tenant_config.return_value = tenant_config
        MockAPIClient.return_value = mock_client

        # Mock KMS decrypt
        mock_kms = MagicMock()
        mock_kms.decrypt.return_value = {"Plaintext": key}
        mock_boto3.return_value = mock_kms

        with tempfile.TemporaryDirectory() as tmp:
            results_base = Path(tmp)
            with patch("byod_cli.ui.routes.jobs.RESULTS_BASE", results_base):
                resp = ui_client_authed.post("/api/jobs/success-job/get")
                assert resp.status_code == 200
                events = _parse_sse(resp.text)

                # Should have progress events and a complete event
                event_types = [e["event"] for e in events]
                assert "progress" in event_types
                assert "complete" in event_types
                assert "error" not in event_types

    @patch("byod_cli.api_client.APIClient")
    def test_get_results_download_failure(self, MockAPIClient, ui_client_authed):
        mock_client = MagicMock()
        mock_client.get_job_status.return_value = {"status": "completed"}
        mock_client.get_download_url.side_effect = Exception("Access denied")
        MockAPIClient.return_value = mock_client

        with tempfile.TemporaryDirectory() as tmp:
            results_base = Path(tmp)
            with patch("byod_cli.ui.routes.jobs.RESULTS_BASE", results_base):
                resp = ui_client_authed.post("/api/jobs/fail-job/get")
                events = _parse_sse(resp.text)
                error_events = [e for e in events if e["event"] == "error"]
                assert len(error_events) > 0


def _parse_sse(text: str) -> list:
    """Parse SSE text into a list of {event, data} dicts."""
    events = []
    current_event = None
    current_data = None

    for line in text.split("\n"):
        if line.startswith("event: "):
            current_event = line[7:]
        elif line.startswith("data: "):
            current_data = line[6:]
        elif line == "" and current_event and current_data:
            try:
                events.append({"event": current_event, "data": json.loads(current_data)})
            except json.JSONDecodeError:
                events.append({"event": current_event, "data": current_data})
            current_event = None
            current_data = None

    return events
