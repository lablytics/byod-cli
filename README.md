# BYOD CLI

Command-line interface for the Lablytics BYOD (Bring Your Own Data) platform.

Process sensitive biotech data with zero-knowledge encryption. Your data is encrypted client-side, processed inside a cryptographically attested AWS Nitro Enclave, and returned encrypted. **No one—including Lablytics—can access your plaintext data.**

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Complete Setup Guide](#complete-setup-guide)
- [Commands Reference](#commands-reference)
- [Security Model](#security-model)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

---

## Installation

### From PyPI (Recommended)

```bash
pip install byod-cli
```

### From Source

```bash
cd byod-cli
pip install -e .

# With development dependencies
pip install -e ".[dev]"
```

### Prerequisites

- Python 3.10+
- AWS credentials configured (`~/.aws/credentials` or environment variables)
- A Lablytics account with API key

---

## Quick Start

```bash
# 1. Authenticate with your API key
byod auth login

# 2. Set up your AWS resources (one-time)
byod setup

# 3. Submit data for processing
byod submit genomic-qc ./sample.fastq.gz

# 4. Check job status
byod status <job-id>

# 5. Download and decrypt results
byod retrieve <job-id> -o ./results/
byod decrypt ./results/ -o ./decrypted/
```

---

## Complete Setup Guide

### Step 1: Create a Lablytics Account

1. Go to https://app.lablytics.io and sign up
2. Verify your email address
3. Log in to the dashboard

### Step 2: Generate an API Key

1. In the dashboard, go to **Settings** → **API Keys**
2. Click **Create New Key**
3. Copy the key (it's shown only once!)
4. Store it securely

### Step 3: Authenticate the CLI

```bash
byod auth login
# Enter your API key when prompted: sk_live_xxxxx
```

You should see:
```
✓ Authentication successful!

  Organization: Acme Biotech
  Tenant ID:    tenant_abc123xyz
  Region:       us-east-1

Ready to submit jobs!
```

### Step 4: Set Up AWS Resources

This creates a KMS key and IAM role in YOUR AWS account:

```bash
byod setup
```

**What this creates:**

| Resource | Purpose |
|----------|---------|
| KMS Key | Encrypts your data. Only the Nitro Enclave can decrypt. |
| IAM Role | Allows the enclave to use your KMS key with attestation |
| Key Alias | `alias/byod-{tenant_id}` for easy identification |

**Output:**
```
Setting up AWS resources for BYOD...

Fetching enclave configuration...
  Tenant ID: tenant_abc123xyz
  Enclave PCR0: a1b2c3d4e5f6...

Checking AWS credentials...
  AWS Account: 123456789012
  Region: us-east-1

Creating cross-account IAM role...
  Role: arn:aws:iam::123456789012:role/BYODEnclaveRole-tenant_abc123

Creating KMS key with attestation policy...
  KMS Key: arn:aws:kms:us-east-1:123456789012:key/xxx-xxx
  Alias: alias/byod-tenant_abc123

Attaching KMS permissions to role...
  Attached BYODKMSAccess policy

Registering with Lablytics...
  Registration complete

============================================================
✓ Setup complete!
============================================================

Resources created:
  KMS Key:  arn:aws:kms:us-east-1:123456789012:key/xxx-xxx
  IAM Role: arn:aws:iam::123456789012:role/BYODEnclaveRole-tenant_abc123

Security guarantees:
  ✓ Only YOU can manage/delete the KMS key
  ✓ Only the Nitro Enclave (with PCR0 verification) can decrypt
  ✓ Lablytics operators cannot access your data

Ready to submit jobs!
```

### Step 5: Submit Your First Job

```bash
# Submit a FASTQ file for quality control
byod submit genomic-qc ./sample.fastq.gz

# Or submit with a description and tags
byod submit genomic-qc ./sample.fastq.gz \
  --description "Sample batch 2024-01" \
  --tags experiment=exp001 \
  --tags batch=batch_a
```

### Step 6: Monitor and Retrieve Results

```bash
# Check status
byod status genomic-qc-20260208-abc123

# List all your jobs
byod list

# Download encrypted results when complete
byod retrieve genomic-qc-20260208-abc123 -o ./results/

# Decrypt locally (extracts to directory)
byod decrypt ./results/ -o ./qc_report/
```

---

## Commands Reference

### Authentication

| Command | Description |
|---------|-------------|
| `byod auth login` | Authenticate with API key |
| `byod auth logout` | Clear stored credentials |
| `byod auth status` | Check authentication status |

### Setup

| Command | Description |
|---------|-------------|
| `byod setup` | Create KMS key and IAM role in your AWS account |
| `byod setup --region us-west-2` | Create resources in a specific region |

### Jobs

| Command | Description |
|---------|-------------|
| `byod submit <plugin> <path>` | Submit data for processing |
| `byod status <job-id>` | Check job status |
| `byod list` | List all your jobs |
| `byod retrieve <job-id> -o <dir>` | Download encrypted results |
| `byod decrypt <dir> -o <output>` | Decrypt results locally |

### Utilities

| Command | Description |
|---------|-------------|
| `byod plugins` | List available pipeline plugins |
| `byod config show` | Display current configuration |
| `byod --version` | Show CLI version |
| `byod --help` | Show help for any command |

---

## Security Model

### How It Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ YOUR MACHINE                                                                │
│                                                                             │
│  ~/.aws/credentials ◄─── Your AWS creds (standard AWS config)              │
│         │                                                                   │
│         ▼                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ byod-cli                                                            │   │
│  │                                                                     │   │
│  │  byod auth login     → Authenticate with Lablytics API             │   │
│  │  byod setup          → Create KMS key + IAM role in YOUR account   │   │
│  │  byod submit <file>  → Encrypt locally, upload to Lablytics S3     │   │
│  │  byod status <job>   → Check job progress                          │   │
│  │  byod retrieve <job> → Download encrypted results                  │   │
│  │  byod decrypt <dir>  → Decrypt locally with YOUR KMS key           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
          │                           │
          │ API Key                   │ Presigned URLs
          ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LABLYTICS INFRASTRUCTURE                                                    │
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────────┐  │
│  │ Dashboard    │    │ S3 Buckets   │    │ Orchestrator + Enclave      │  │
│  │ (read-only)  │    │ (encrypted   │    │                              │  │
│  │              │    │  data only)  │    │  Assumes cross-account role │  │
│  │ - Job status │    │              │    │  Enclave decrypts via KMS   │  │
│  │ - Logs       │    │              │    │  with attestation (PCR0)    │  │
│  └──────────────┘    └──────────────┘    └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Who Can Access Your Data?

| Actor | Can Encrypt | Can Decrypt | How |
|-------|-------------|-------------|-----|
| You (CLI) | ✓ Yes | ✓ Yes | Your own AWS credentials |
| Nitro Enclave | ✓ Yes | ✓ Yes | Cross-account role + PCR0 attestation |
| Lablytics Orchestrator | ✓ Yes | **No** | Can assume role but no attestation |
| Lablytics Dashboard | No | **No** | No access to KMS |
| Lablytics Operators | No | **No** | No access to keys or data |

### Security Guarantees

1. **Customer-owned KMS key**: The key lives in YOUR AWS account
2. **Attestation-based decrypt**: Only the verified Nitro Enclave can decrypt
3. **ExternalId protection**: Each tenant has a unique ExternalId
4. **No plaintext transit**: Data is encrypted before leaving your machine
5. **No network in enclave**: The enclave has no internet—data flows via vsock

---

## Examples

### Submit a Single File

```bash
byod submit genomic-qc ./sample.fastq.gz
```

### Submit a Directory

```bash
# The CLI will tar.gz the directory automatically
byod submit genomic-qc ./samples/
```

### Submit with Custom Config

```bash
# Create a config file
echo '{"min_quality": 20, "trim_adapters": true}' > config.json

# Submit with config
byod submit genomic-qc ./sample.fastq.gz --config config.json
```

### Wait for Job Completion

```bash
# Block until job finishes (with 1-hour timeout)
byod submit genomic-qc ./sample.fastq.gz --wait --timeout 3600
```

### Check Multiple Jobs

```bash
# List recent jobs
byod list

# List only completed jobs
byod list --status completed

# List in JSON format for scripting
byod list --format json
```

### Retrieve and Decrypt in One Script

```bash
#!/bin/bash
JOB_ID=$1

# Wait for completion
while true; do
  STATUS=$(byod status $JOB_ID --format json | jq -r '.status')
  if [ "$STATUS" = "completed" ]; then
    break
  elif [ "$STATUS" = "failed" ]; then
    echo "Job failed!"
    exit 1
  fi
  sleep 30
done

# Download and decrypt (auto-extracts to directory)
byod retrieve $JOB_ID -o ./results/
byod decrypt ./results/ -o ./output/
```

### Use Environment Variables

```bash
# Set API key via environment (useful for CI/CD)
export BYOD_API_KEY=sk_live_xxxxx
export BYOD_DEBUG=1  # Enable debug logging

byod submit genomic-qc ./sample.fastq.gz
```

---

## Available Plugins

| Plugin | Description | Input Types |
|--------|-------------|-------------|
| `genomic-qc` | FastQC + MultiQC quality control | `.fastq`, `.fastq.gz`, `.fq`, `.fq.gz` |
| `demo-count` | Simple line/word counting demo | Any text file |

List all available plugins:
```bash
byod plugins
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `BYOD_API_KEY` | API key (alternative to `byod auth login`) | - |
| `BYOD_API_URL` | Custom API URL (for self-hosted) | `https://api.lablytics.io` |
| `BYOD_DEBUG` | Enable debug logging (`1` or `true`) | `false` |
| `AWS_PROFILE` | AWS credentials profile to use | `default` |
| `AWS_REGION` | AWS region for KMS operations | `us-east-1` |

---

## Troubleshooting

### "Not authenticated"

**Problem**: CLI cannot find valid credentials.

**Solution**:
```bash
byod auth login
# Enter your API key from the dashboard
```

### "No KMS key configured"

**Problem**: You haven't run the setup command.

**Solution**:
```bash
byod setup
```

### "Failed to get AWS identity"

**Problem**: AWS credentials are not configured.

**Solution**: Configure AWS credentials using one of:
```bash
# Option 1: AWS CLI
aws configure

# Option 2: Environment variables
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...

# Option 3: ~/.aws/credentials file
[default]
aws_access_key_id = AKIA...
aws_secret_access_key = ...
```

### "AccessDenied when creating KMS key"

**Problem**: Your AWS user lacks permissions.

**Solution**: Ensure your AWS user has these permissions:
- `kms:CreateKey`
- `kms:CreateAlias`
- `kms:PutKeyPolicy`
- `iam:CreateRole`
- `iam:PutRolePolicy`
- `iam:TagRole`

### "Job stuck in processing"

**Problem**: Job is taking longer than expected.

**Solution**:
1. Check status: `byod status <job-id>`
2. View logs in dashboard: https://app.lablytics.io/jobs/<job-id>
3. Large files take longer—genomic QC for a 10GB file may take 30+ minutes

### "Decryption failed: AccessDeniedException"

**Problem**: KMS won't release the key.

**Possible causes**:
1. Wrong AWS credentials—ensure you're using the same account as setup
2. Key was deleted—check AWS KMS console
3. Role was modified—re-run `byod setup`

### Debug Mode

Enable verbose logging for troubleshooting:
```bash
byod --debug submit genomic-qc ./sample.fastq.gz
# or
export BYOD_DEBUG=1
byod submit genomic-qc ./sample.fastq.gz
```

---

## Configuration Files

The CLI stores configuration in `~/.byod/`:

```
~/.byod/
├── config.json       # API key, URL, active profile
└── profiles/         # Per-tenant profiles (auto-created)
```

View current config:
```bash
byod config show
```

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src/

# Linting
ruff check src/

# Format code
ruff format src/
```

---

## Support

- **Documentation**: https://docs.lablytics.io/cli
- **Dashboard**: https://app.lablytics.io
- **Issues**: https://github.com/lablytics/byod-platform/issues
- **Email**: support@lablytics.io

---

## License

MIT
