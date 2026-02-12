"""Tests for UI job submission routes."""

import json
import os
from unittest.mock import MagicMock, patch

from byod_cli.ui.routes.submit import _format_bytes


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


class TestFormatBytes:
    """Tests for the _format_bytes helper."""

    def test_bytes(self):
        assert _format_bytes(512) == "512 B"

    def test_kilobytes(self):
        assert _format_bytes(1536) == "1.5 KB"

    def test_megabytes(self):
        assert _format_bytes(5 * 1024 * 1024) == "5.0 MB"

    def test_gigabytes(self):
        assert _format_bytes(2 * 1024 ** 3) == "2.0 GB"

    def test_zero_bytes(self):
        assert _format_bytes(0) == "0 B"


class TestSubmitJob:
    """Tests for POST /api/submit."""

    def test_submit_unauthenticated(self, ui_client):
        resp = ui_client.post(
            "/api/submit",
            data={"plugin": "demo-count", "description": "test"},
            files=[("files", ("test.txt", b"hello", "text/plain"))],
        )
        assert resp.status_code == 401

    def test_submit_no_files(self, ui_client_authed):
        resp = ui_client_authed.post(
            "/api/submit",
            data={"plugin": "demo-count"},
        )
        assert resp.status_code == 422  # FastAPI validation error — files required

    @patch("requests.post")
    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_submit_single_file_success(
        self, MockAPIClient, mock_boto3, mock_requests_post, ui_client_authed,
    ):
        mock_client = MagicMock()

        # Mock presigned URL response
        presigned = MagicMock()
        presigned.url = "https://s3.example.com/upload"
        presigned.fields = {"key": "upload-key"}
        presigned.s3_key = "tenant/input.enc"
        mock_client.get_upload_url.return_value = presigned

        # Mock job submission response
        submission = MagicMock()
        submission.job_id = "new-job-123"
        submission.status = "submitted"
        mock_client.submit_job.return_value = submission
        MockAPIClient.return_value = mock_client

        # Mock KMS generate_data_key
        dek = os.urandom(32)
        mock_kms = MagicMock()
        mock_kms.generate_data_key.return_value = {
            "Plaintext": dek,
            "CiphertextBlob": b"wrapped-key-data",
        }
        mock_boto3.return_value = mock_kms

        # Mock S3 upload responses
        mock_upload_resp = MagicMock()
        mock_upload_resp.status_code = 204
        mock_requests_post.return_value = mock_upload_resp

        resp = ui_client_authed.post(
            "/api/submit",
            data={"plugin": "demo-count", "description": "test job"},
            files=[("files", ("sample.fastq", b"@SEQ\nATCG\n+\nIIII\n", "application/octet-stream"))],
        )

        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        event_types = [e["event"] for e in events]
        assert "progress" in event_types
        assert "complete" in event_types
        assert "error" not in event_types

        complete = next(e for e in events if e["event"] == "complete")
        assert complete["data"]["job_id"] == "new-job-123"

    @patch("requests.post")
    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_submit_multi_file_tar(
        self, MockAPIClient, mock_boto3, mock_requests_post, ui_client_authed,
    ):
        mock_client = MagicMock()
        presigned = MagicMock()
        presigned.url = "https://s3.example.com/upload"
        presigned.fields = {}
        presigned.s3_key = "tenant/input.tar.gz.enc"
        mock_client.get_upload_url.return_value = presigned

        submission = MagicMock()
        submission.job_id = "multi-job-456"
        submission.status = "submitted"
        mock_client.submit_job.return_value = submission
        MockAPIClient.return_value = mock_client

        dek = os.urandom(32)
        mock_kms = MagicMock()
        mock_kms.generate_data_key.return_value = {
            "Plaintext": dek,
            "CiphertextBlob": b"wrapped",
        }
        mock_boto3.return_value = mock_kms

        mock_upload_resp = MagicMock()
        mock_upload_resp.status_code = 204
        mock_requests_post.return_value = mock_upload_resp

        resp = ui_client_authed.post(
            "/api/submit",
            data={"plugin": "genomic-qc", "description": "multi-file"},
            files=[
                ("files", ("file1.fastq", b"@SEQ1\nATCG\n", "application/octet-stream")),
                ("files", ("file2.fastq", b"@SEQ2\nGCTA\n", "application/octet-stream")),
            ],
        )

        events = _parse_sse(resp.text)
        event_types = [e["event"] for e in events]
        assert "complete" in event_types

        # Verify the packaging stage appeared
        packaging_events = [
            e for e in events
            if e["event"] == "progress" and e["data"].get("stage") == "packaging"
        ]
        assert len(packaging_events) > 0

    def test_submit_no_kms_key_configured(self, mock_config_authed):
        """When no KMS key is in the profile, should return an error SSE event."""
        from tests.conftest import _create_test_app, _make_mock_config

        config = _make_mock_config(
            authenticated=True,
            api_key="test-key",
            profile_settings={},  # No kms_key_arn
        )
        from fastapi.testclient import TestClient

        client = TestClient(_create_test_app(config))

        with patch("byod_cli.api_client.APIClient"):
            resp = client.post(
                "/api/submit",
                data={"plugin": "demo-count"},
                files=[("files", ("test.txt", b"data", "text/plain"))],
            )

        events = _parse_sse(resp.text)
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) > 0
        assert "KMS" in error_events[0]["data"]["message"] or "kms" in error_events[0]["data"]["message"].lower()

    @patch("requests.post")
    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_submit_upload_failure(
        self, MockAPIClient, mock_boto3, mock_requests_post, ui_client_authed,
    ):
        mock_client = MagicMock()
        presigned = MagicMock()
        presigned.url = "https://s3.example.com/upload"
        presigned.fields = {}
        presigned.s3_key = "tenant/input.enc"
        mock_client.get_upload_url.return_value = presigned
        MockAPIClient.return_value = mock_client

        dek = os.urandom(32)
        mock_kms = MagicMock()
        mock_kms.generate_data_key.return_value = {
            "Plaintext": dek,
            "CiphertextBlob": b"wrapped",
        }
        mock_boto3.return_value = mock_kms

        # Upload returns error
        mock_upload_resp = MagicMock()
        mock_upload_resp.status_code = 403
        mock_requests_post.return_value = mock_upload_resp

        resp = ui_client_authed.post(
            "/api/submit",
            data={"plugin": "demo-count"},
            files=[("files", ("test.txt", b"data", "text/plain"))],
        )

        events = _parse_sse(resp.text)
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) > 0
        assert "Upload failed" in error_events[0]["data"]["message"]
