# BYOD CLI

**Secure biotech data processing with zero-knowledge encryption.**

Your data is encrypted on your machine, processed inside a cryptographically attested AWS Nitro Enclave, and returned encrypted. No one — including Lablytics — can access your plaintext data.

## Install

```bash
pip install byod-cli
```

**Requirements:** Python 3.9+ and AWS credentials (`aws configure` or environment variables).

## Get Started

### 1. Sign up and get an API key

Go to **https://byod.cultivatedcode.co**, create an account, then go to **Settings > API Keys** and create a key. Copy it — it's only shown once.

### 2. Authenticate

```bash
byod auth login
```

Paste your API key when prompted (`sk_live_xxxxx`).

### 3. Set up your AWS resources (one-time)

```bash
byod setup
```

This creates a KMS key and IAM role **in your AWS account**. Only the verified Nitro Enclave can use the key to decrypt — not Lablytics, not anyone else.

### 4. Submit data

```bash
byod submit genomic-qc ./sample.fastq.gz
```

The CLI encrypts your file locally, uploads the ciphertext, and returns a job ID.

### 5. Get results

```bash
byod status <job-id>          # Check progress
byod retrieve <job-id> -o ./results/   # Download encrypted results
byod decrypt ./results/ -o ./output/   # Decrypt locally
```

That's it. Your data was never visible to anyone outside the enclave.

---

## Commands

| Command | What it does |
|---------|-------------|
| `byod auth login` | Authenticate with your API key |
| `byod auth logout` | Clear stored credentials |
| `byod auth status` | Check if you're authenticated |
| `byod setup` | Create KMS key + IAM role in your AWS account |
| `byod submit <plugin> <file>` | Encrypt and submit data for processing |
| `byod status <job-id>` | Check job status |
| `byod list` | List your jobs |
| `byod retrieve <job-id> -o <dir>` | Download encrypted results |
| `byod decrypt <dir> -o <output>` | Decrypt results locally |
| `byod plugins` | List available processing plugins |
| `byod config show` | Show current configuration |

## Plugins

| Plugin | Description | Accepts |
|--------|-------------|---------|
| `genomic-qc` | FastQC + MultiQC quality control | `.fastq`, `.fastq.gz` |
| `demo-count` | Line/word counting (for testing) | Any text file |

```bash
byod plugins   # See all available plugins
```

## Examples

```bash
# Submit a directory (auto-archived as tar.gz)
byod submit genomic-qc ./samples/

# Submit with metadata
byod submit genomic-qc ./sample.fastq.gz \
  --description "Batch 2026-02" \
  --tags experiment=exp001 \
  --tags batch=batch_a

# Submit with custom pipeline config
echo '{"min_quality": 20}' > config.json
byod submit genomic-qc ./sample.fastq.gz --config config.json

# Wait for completion (blocks until done)
byod submit genomic-qc ./sample.fastq.gz --wait --timeout 3600

# List completed jobs
byod list --status completed

# JSON output for scripting
byod list --format json

# Use API key via environment variable (useful for CI/CD)
export BYOD_API_KEY=sk_live_xxxxx
byod submit genomic-qc ./sample.fastq.gz
```

## How Security Works

```
 Your Machine                        Lablytics
┌──────────────────┐                ┌──────────────────────────┐
│ byod-cli         │  ciphertext    │ S3 (encrypted blobs)     │
│ - encrypt locally│───────────────>│          │               │
│ - decrypt locally│                │          v               │
└────────┬─────────┘                │ Nitro Enclave            │
         │                          │ - attests to your KMS key│
         v                          │ - decrypts, processes,   │
 Your AWS Account                   │   re-encrypts            │
┌──────────────────┐                │ - no network access      │
│ KMS Key          │<───────────────│                          │
│ - you own it     │  attestation   └──────────────────────────┘
│ - PCR0 condition │
└──────────────────┘
```

| Who | Can decrypt your data? | Why |
|-----|----------------------|-----|
| **You** | Yes | Your KMS key, your AWS credentials |
| **Nitro Enclave** | Yes | Cross-account role with PCR0 attestation |
| **Lablytics operators** | **No** | No access to your KMS key |
| **Lablytics infrastructure** | **No** | Attestation check blocks non-enclave access |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `BYOD_API_KEY` | API key (alternative to `byod auth login`) | — |
| `BYOD_API_URL` | Custom API endpoint | `https://byod.cultivatedcode.co` |
| `BYOD_DEBUG` | Enable debug logging (`1` or `true`) | `false` |
| `AWS_PROFILE` | AWS credentials profile | `default` |
| `AWS_REGION` | Region for KMS operations | `us-east-1` |

## Troubleshooting

**"Not authenticated"** — Run `byod auth login` with your API key from https://byod.cultivatedcode.co.

**"No KMS key configured"** — Run `byod setup` to create your KMS key and IAM role.

**"Failed to get AWS identity"** — Configure AWS credentials: `aws configure` or set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.

**"AccessDenied when creating KMS key"** — Your AWS user needs: `kms:CreateKey`, `kms:CreateAlias`, `kms:PutKeyPolicy`, `iam:CreateRole`, `iam:PutRolePolicy`.

**"Decryption failed: AccessDeniedException"** — Make sure you're using the same AWS account that ran `byod setup`. Check that the KMS key hasn't been deleted.

**Debug mode:**
```bash
byod --debug submit genomic-qc ./sample.fastq.gz
```

## Development

```bash
pip install -e ".[dev]"
pytest              # Run tests
ruff check src/     # Lint
ruff format src/    # Format
```

## License

MIT — see [LICENSE](LICENSE).
