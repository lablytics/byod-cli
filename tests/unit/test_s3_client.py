"""Tests for S3Client (byod_cli/s3_client.py) with moto-mocked AWS.

Covers job submission, status checking, result download, decryption,
and job listing — all against mock S3/KMS backends.
"""

import json
import os

import boto3
import pytest
from moto import mock_aws

from byod_cli.s3_client import S3Client

REGION = "us-east-1"
DATA_BUCKET = "test-data"
RESULTS_BUCKET = "test-results"


@pytest.fixture
def aws_env(monkeypatch):
    """Set dummy AWS creds for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


@pytest.fixture
def kms_key_id(aws_env):
    """Create a KMS key in moto and return its ID."""
    with mock_aws():
        kms = boto3.client("kms", region_name=REGION)
        resp = kms.create_key(Description="test key")
        yield resp["KeyMetadata"]["KeyId"]


@pytest.fixture
def s3_buckets(aws_env):
    """Create S3 buckets in moto."""
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=DATA_BUCKET)
        s3.create_bucket(Bucket=RESULTS_BUCKET)
        yield


@pytest.fixture
def s3_client(aws_env):
    """Return an S3Client inside a moto context."""
    with mock_aws():
        # Create resources
        kms = boto3.client("kms", region_name=REGION)
        key_resp = kms.create_key(Description="test key")
        key_id = key_resp["KeyMetadata"]["KeyId"]

        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=DATA_BUCKET)
        s3.create_bucket(Bucket=RESULTS_BUCKET)

        client = S3Client(
            region=REGION,
            data_bucket=DATA_BUCKET,
            results_bucket=RESULTS_BUCKET,
            kms_key_id=key_id,
        )
        yield client


# ---------------------------------------------------------------------------
# Submit job
# ---------------------------------------------------------------------------

class TestSubmitJob:
    def test_returns_job_id(self, s3_client, temp_dir):
        sample = temp_dir / "input.txt"
        sample.write_text("hello world")
        job_id = s3_client.submit_job(sample, "demo-count")
        assert job_id.startswith("demo-count-")

    def test_uploads_encrypted_data(self, s3_client, temp_dir):
        sample = temp_dir / "input.txt"
        sample.write_text("hello world")
        job_id = s3_client.submit_job(sample, "demo-count")

        # Verify objects exist in S3
        s3 = s3_client.s3
        input_obj = s3.get_object(Bucket=DATA_BUCKET, Key=f"data/{job_id}/input.enc")
        assert len(input_obj["Body"].read()) > 0

    def test_uploads_wrapped_key(self, s3_client, temp_dir):
        sample = temp_dir / "input.txt"
        sample.write_text("hello world")
        job_id = s3_client.submit_job(sample, "demo-count")

        s3 = s3_client.s3
        key_obj = s3.get_object(Bucket=DATA_BUCKET, Key=f"data/{job_id}/wrapped_key.bin")
        assert len(key_obj["Body"].read()) > 0

    def test_uploads_manifest(self, s3_client, temp_dir):
        sample = temp_dir / "input.txt"
        sample.write_text("hello world")
        job_id = s3_client.submit_job(sample, "demo-count")

        s3 = s3_client.s3
        manifest_obj = s3.get_object(Bucket=DATA_BUCKET, Key=f"jobs/{job_id}.json")
        manifest = json.loads(manifest_obj["Body"].read())
        assert manifest["job_id"] == job_id
        assert manifest["plugin_name"] == "demo-count"

    def test_directory_submission(self, s3_client, temp_dir):
        input_dir = temp_dir / "inputs"
        input_dir.mkdir()
        (input_dir / "a.txt").write_text("file a")
        (input_dir / "b.txt").write_text("file b")
        job_id = s3_client.submit_job(input_dir, "genomic-qc")
        assert job_id.startswith("genomic-qc-")


# ---------------------------------------------------------------------------
# Job status
# ---------------------------------------------------------------------------

class TestGetJobStatus:
    def test_submitted_status(self, s3_client, temp_dir):
        sample = temp_dir / "input.txt"
        sample.write_text("data")
        job_id = s3_client.submit_job(sample, "demo-count")
        status = s3_client.get_job_status(job_id)
        assert status["status"] in ("submitted", "processing")
        assert status["plugin"] == "demo-count"

    def test_completed_status(self, s3_client, temp_dir):
        sample = temp_dir / "input.txt"
        sample.write_text("data")
        job_id = s3_client.submit_job(sample, "demo-count")

        # Simulate results appearing
        s3_client.s3.put_object(
            Bucket=RESULTS_BUCKET,
            Key=f"results/{job_id}/output.enc",
            Body=b"encrypted-result",
        )

        status = s3_client.get_job_status(job_id)
        assert status["status"] == "completed"

    def test_not_found_status(self, s3_client):
        status = s3_client.get_job_status("nonexistent-job")
        assert status["status"] == "not_found"


# ---------------------------------------------------------------------------
# Download results
# ---------------------------------------------------------------------------

class TestDownloadResults:
    def test_downloads_files(self, s3_client, temp_dir):
        """Place mock results in S3, then download them."""
        job_id = "test-job-dl"

        # Place encrypted result and wrapped key
        s3_client.s3.put_object(
            Bucket=RESULTS_BUCKET,
            Key=f"results/{job_id}/output.enc",
            Body=b"encrypted-output-data",
        )
        s3_client.s3.put_object(
            Bucket=RESULTS_BUCKET,
            Key=f"results/{job_id}/output_key.bin",
            Body=b"wrapped-key-bytes",
        )

        # Also need a job manifest
        s3_client.s3.put_object(
            Bucket=DATA_BUCKET,
            Key=f"jobs/{job_id}.json",
            Body=json.dumps({"job_id": job_id, "plugin_name": "demo"}).encode(),
        )

        output = temp_dir / "results"
        s3_client.download_results(job_id, output)

        assert (output / "output.enc").exists()
        assert (output / "output_key.bin").exists()
        assert (output / "results-manifest.json").exists()

    def test_missing_results_raises(self, s3_client, temp_dir):
        with pytest.raises(FileNotFoundError, match="No results found"):
            s3_client.download_results("missing-job", temp_dir / "out")


# ---------------------------------------------------------------------------
# Decrypt results
# ---------------------------------------------------------------------------

class TestDecryptResults:
    def test_roundtrip(self, s3_client, temp_dir):
        """Submit, simulate enclave processing, download, decrypt."""
        sample = temp_dir / "input.txt"
        sample.write_text("secret data")
        job_id = s3_client.submit_job(sample, "demo-count")

        # Read the encrypted data and wrapped key that were uploaded
        enc_resp = s3_client.s3.get_object(
            Bucket=DATA_BUCKET, Key=f"data/{job_id}/input.enc"
        )
        encrypted_data = enc_resp["Body"].read()

        wrap_resp = s3_client.s3.get_object(
            Bucket=DATA_BUCKET, Key=f"data/{job_id}/wrapped_key.bin"
        )
        wrapped_key = wrap_resp["Body"].read()

        # Simulate the enclave: put back the same encrypted data and key
        # (in reality the enclave re-encrypts, but for testing we reuse)
        s3_client.s3.put_object(
            Bucket=RESULTS_BUCKET,
            Key=f"results/{job_id}/output.enc",
            Body=encrypted_data,
        )
        s3_client.s3.put_object(
            Bucket=RESULTS_BUCKET,
            Key=f"results/{job_id}/output_key.bin",
            Body=wrapped_key,
        )

        # Download
        dl_dir = temp_dir / "downloaded"
        s3_client.download_results(job_id, dl_dir)

        # Decrypt
        output_path = temp_dir / "decrypted.txt"
        result = s3_client.decrypt_results(dl_dir, output_path)

        assert output_path.exists()
        assert result["decrypted_size"] == len(b"secret data")

    def test_missing_manifest_raises(self, s3_client, temp_dir):
        with pytest.raises(FileNotFoundError, match="Results manifest not found"):
            s3_client.decrypt_results(temp_dir / "empty", temp_dir / "out.txt")


# ---------------------------------------------------------------------------
# List jobs
# ---------------------------------------------------------------------------

class TestListJobs:
    def test_empty(self, s3_client):
        jobs = s3_client.list_jobs()
        assert jobs == []

    def test_lists_submitted_jobs(self, s3_client, temp_dir):
        sample = temp_dir / "input.txt"
        sample.write_text("data")
        job_id = s3_client.submit_job(sample, "demo-count")
        jobs = s3_client.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["job_id"] == job_id
        assert jobs[0]["plugin"] == "demo-count"

    def test_respects_limit(self, s3_client, temp_dir):
        sample = temp_dir / "input.txt"
        sample.write_text("data")
        for _ in range(5):
            s3_client.submit_job(sample, "demo-count")
        jobs = s3_client.list_jobs(limit=3)
        assert len(jobs) == 3


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class TestEncryptDecryptHelper:
    def test_roundtrip(self):
        key = os.urandom(32)
        plaintext = b"Hello, moto!"
        encrypted = S3Client._encrypt(plaintext, key)
        decrypted = S3Client._decrypt(encrypted, key)
        assert decrypted == plaintext
