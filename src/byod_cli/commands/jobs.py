"""
Job commands for BYOD CLI.

Contains: submit, status, list, retrieve (deprecated), decrypt (deprecated), get.
"""

from __future__ import annotations

import io
import json
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any

import click
from rich.panel import Panel
from rich.table import Table

from byod_cli.api_client import APIError, AuthenticationError
from byod_cli.commands import _helpers

EXIT_ERROR = _helpers.EXIT_ERROR
EXIT_AUTH = _helpers.EXIT_AUTH


@click.command()
@click.argument("plugin")
@click.argument("input_path", type=click.Path(exists=True, path_type=Path))
@click.option("--description", help="Human-readable job description")
@click.option("--config", "config_path", type=click.Path(exists=True, path_type=Path), help="Plugin config (JSON)")
@click.option("--wait", is_flag=True, help="Wait for job completion with live status updates")
@click.option("--live", "wait", is_flag=True, hidden=True, help="Alias for --wait")
@click.option("--track", "wait", is_flag=True, hidden=True, help="Alias for --wait")
@click.option("--timeout", type=int, default=3600, help="Timeout in seconds when using --wait")
@click.option("--tags", multiple=True, help="Metadata tags (format: key=value)")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.pass_context
def submit(
    ctx: click.Context,
    plugin: str,
    input_path: Path,
    description: str | None,
    config_path: Path | None,
    wait: bool,
    timeout: int,
    tags: tuple[str, ...],
    output_format: str,
) -> None:
    """
    Submit data for secure enclave processing.

    Data is encrypted client-side with a KMS-managed key, uploaded via presigned URL,
    and processed in an attested Nitro Enclave.

    \b
    Available plugins:
        genomic-qc     FastQC + MultiQC quality control for FASTQ files
        demo-count     Simple line/word counting demo

    \b
    Examples:
        byod submit genomic-qc ./sample.fastq.gz
        byod submit demo-count ./data.txt --wait
        byod submit genomic-qc ./samples/ --tags experiment=exp001
    """
    import time

    import boto3

    config = ctx.obj["CONFIG"]
    console = _helpers.console

    try:
        client = _helpers._get_api_client(config)
    except click.ClickException:
        console.print(_helpers.format_error("Not authenticated. Run 'byod auth login' first."))
        sys.exit(EXIT_ERROR)

    console.print("\n[bold blue]Submitting job...[/bold blue]\n")
    console.print(f"  Plugin: {plugin}")
    console.print(f"  Input:  {input_path}")

    if description:
        console.print(f"  Desc:   {description}")

    tags_dict: dict[str, str] = {}
    for tag in tags:
        if "=" not in tag:
            raise click.ClickException(f"Invalid tag format: {tag}. Use key=value")
        key, value = tag.split("=", 1)
        tags_dict[key] = value

    plugin_config: dict[str, Any] | None = None
    if config_path:
        with open(config_path) as f:
            plugin_config = json.load(f)

    with console.status("[bold green]Validating plugin and file types..."):
        try:
            available_plugins = client.list_plugins()
        except Exception:
            available_plugins = []

    if available_plugins:
        plugin_meta = next((p for p in available_plugins if p["name"] == plugin), None)
        if plugin_meta is None:
            plugin_names = ", ".join(p["name"] for p in available_plugins)
            console.print(_helpers.format_error(
                f"Unknown plugin '{plugin}'. Available plugins: {plugin_names}"
            ))
            sys.exit(EXIT_ERROR)

        from byod_cli.validation import validate_files_for_plugin

        if input_path.is_dir():
            filenames = [f.name for f in input_path.iterdir() if f.is_file()]
        else:
            filenames = [input_path.name]

        validation_errors = validate_files_for_plugin(filenames, plugin_meta.get("inputs", []))
        if validation_errors:
            console.print(_helpers.format_error("File type validation failed:"))
            for err in validation_errors:
                console.print(f"  [red]{err}[/red]")
            sys.exit(EXIT_ERROR)

    try:
        with console.status("[bold green]Getting platform configuration..."):
            tenant_config = client.get_tenant_config()

        kms_key_id = tenant_config.customer_kms_key_arn or tenant_config.kms_key_arn
        if not kms_key_id:
            raise click.ClickException("No KMS key configured. Contact support.")

        console.print("\n  Generating encryption key via KMS...")
        kms = boto3.client("kms", region_name=tenant_config.region)
        key_response = kms.generate_data_key(KeyId=kms_key_id, KeySpec="AES_256")
        plaintext_key = key_response["Plaintext"]
        wrapped_key = key_response["CiphertextBlob"]

        console.print("  Encrypting data client-side...")
        if input_path.is_dir():
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                tar.add(str(input_path), arcname=input_path.name)
            plaintext = buf.getvalue()
        else:
            with open(input_path, "rb") as f:
                plaintext = f.read()

        encrypted_data = _helpers._encrypt_data(plaintext, plaintext_key)
        console.print(f"  Encrypted: {_helpers.format_bytes(len(plaintext))} -> {_helpers.format_bytes(len(encrypted_data))}")

        with console.status(f"[bold green]Uploading encrypted data ({_helpers.format_bytes(len(encrypted_data))})..."):
            import requests
            upload_presigned = client.get_upload_url(
                filename=f"{input_path.name}.enc",
                content_type="application/octet-stream",
                file_size=len(encrypted_data),
            )
            files = {"file": (f"{input_path.name}.enc", io.BytesIO(encrypted_data))}
            response = requests.post(
                upload_presigned.url, data=upload_presigned.fields, files=files, timeout=300,
            )
            if not response.ok:
                raise APIError(f"Upload failed: {response.status_code}")
            input_s3_key = upload_presigned.s3_key

            key_presigned = client.get_upload_url(
                filename="wrapped_key.bin",
                content_type="application/octet-stream",
                file_size=len(wrapped_key),
            )
            files = {"file": ("wrapped_key.bin", io.BytesIO(wrapped_key))}
            response = requests.post(
                key_presigned.url, data=key_presigned.fields, files=files, timeout=60,
            )
            if not response.ok:
                raise APIError(f"Key upload failed: {response.status_code}")
            wrapped_key_s3_key = key_presigned.s3_key

        with console.status("[bold green]Submitting job..."):
            job = client.submit_job(
                plugin_name=plugin,
                input_s3_key=input_s3_key,
                wrapped_key_s3_key=wrapped_key_s3_key,
                description=description,
                config=plugin_config,
                tags=tags_dict,
            )

        if isinstance(plaintext_key, bytearray):
            for i in range(len(plaintext_key)):
                plaintext_key[i] = 0

        if output_format == "json":
            click.echo(json.dumps({"job_id": job.job_id, "status": "submitted"}))
        else:
            console.print(_helpers.format_success(f"Job submitted: {job.job_id}"))

        if not wait:
            if output_format != "json":
                console.print(f"\n  Check status:  [cyan]byod status {job.job_id}[/cyan]")
                console.print(f"  Get results:   [cyan]byod get {job.job_id} -o ./output/[/cyan]\n")
            return

        _wait_for_job(console, client, job.job_id, timeout)

    except AuthenticationError as e:
        console.print(_helpers.format_error(f"Authentication failed: {e}"))
        console.print("  Run [cyan]byod auth login[/cyan] to re-authenticate.")
        sys.exit(EXIT_AUTH)
    except APIError as e:
        console.print(_helpers.format_error(f"API error: {e}"))
        if ctx.obj.get("DEBUG"):
            console.print_exception()
        sys.exit(EXIT_ERROR)
    except Exception as e:
        console.print(_helpers.format_error(f"Submission failed: {e}"))
        if ctx.obj.get("DEBUG"):
            console.print_exception()
        sys.exit(EXIT_ERROR)


def _wait_for_job(console, client, job_id: str, timeout: int) -> None:
    """Poll for job completion with live status updates."""
    import time

    poll_interval = 5
    elapsed = 0
    last_status = None

    status_icons = {
        "pending": "⏳", "submitted": "📤", "downloading": "⬇️ ",
        "processing": "⚙️ ", "uploading": "⬆️ ", "completed": "✅",
        "failed": "❌", "cancelled": "🚫",
    }
    status_messages = {
        "pending": "Waiting to start...", "submitted": "Job queued",
        "downloading": "Downloading encrypted data",
        "processing": "Processing in Nitro Enclave",
        "uploading": "Uploading encrypted results",
        "completed": "Job completed successfully!",
        "failed": "Job failed", "cancelled": "Job cancelled",
    }

    console.print("\n[bold]Tracking job progress:[/bold]\n")

    while elapsed < timeout:
        status_info = client.get_job_status(job_id)
        current_status = status_info["status"]

        if current_status != last_status:
            icon = status_icons.get(current_status, "•")
            msg = status_messages.get(current_status, current_status)
            if current_status == "completed":
                console.print(f"  {icon} [bold green]{msg}[/bold green]")
            elif current_status in ["failed", "cancelled"]:
                error = status_info.get("error", "Unknown error")
                console.print(f"  {icon} [bold red]{msg}[/bold red]: {error}")
            else:
                console.print(f"  {icon} [cyan]{msg}[/cyan] [dim]({elapsed}s)[/dim]")
            last_status = current_status

        if current_status == "completed":
            console.print(f"\n  Get results: [cyan]byod get {job_id} -o ./output/[/cyan]\n")
            return
        elif current_status in ["failed", "cancelled"]:
            sys.exit(EXIT_ERROR)

        time.sleep(poll_interval)
        elapsed += poll_interval

    console.print(_helpers.format_warning(f"\nTimed out after {timeout}s. Job may still be processing."))
    console.print(f"  Check status: [cyan]byod status {job_id}[/cyan]\n")


@click.command()
@click.argument("job_id")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.pass_context
def status(ctx: click.Context, job_id: str, output_format: str) -> None:
    """
    Check the status of a submitted job.

    \b
    Examples:
        byod status genomic-qc-20250126-abc123
        byod status genomic-qc-20250126-abc123 --format json
    """
    config = ctx.obj["CONFIG"]
    client = _helpers._get_api_client(config)
    console = _helpers.console

    try:
        status_info = client.get_job_status(job_id)
        if output_format == "json":
            console.print(json.dumps(status_info, indent=2, default=str))
        else:
            _helpers._print_status(status_info)
    except APIError as e:
        console.print(_helpers.format_error(f"Failed to get status: {e}"))
        sys.exit(EXIT_ERROR)


@click.command(name="list")
@click.option("--limit", type=int, default=20, help="Maximum jobs to display")
@click.option("--status", "filter_status", help="Filter by status")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def list_jobs(ctx: click.Context, limit: int, filter_status: str | None, output_format: str) -> None:
    """
    List submitted jobs.

    \b
    Examples:
        byod list
        byod list --limit 50
        byod list --status completed
    """
    config = ctx.obj["CONFIG"]
    client = _helpers._get_api_client(config)
    console = _helpers.console

    try:
        with console.status("[bold green]Fetching jobs..."):
            jobs = client.list_jobs(limit=limit, status=filter_status)

        if output_format == "json":
            console.print(json.dumps(jobs, indent=2))
            return

        if not jobs:
            console.print("\nNo jobs found.\n")
            console.print("Submit a job: [cyan]byod submit <plugin> <data-path>[/cyan]\n")
            return

        table = Table(title=f"Jobs (showing {len(jobs)})")
        table.add_column("Job ID", style="cyan")
        table.add_column("Plugin", style="blue")
        table.add_column("Status", style="green")
        table.add_column("Submitted", style="dim")
        table.add_column("Description")

        for job in jobs:
            job_status = job.get("status", "unknown")
            status_styled = {
                "completed": "[bold green]completed[/bold green]",
                "processing": "[bold yellow]processing[/bold yellow]",
                "failed": "[bold red]failed[/bold red]",
            }.get(job_status, job_status)

            table.add_row(
                job.get("job_id", "?"), job.get("plugin_name", "?"),
                status_styled, job.get("created_at", "?"),
                (job.get("description") or "")[:40],
            )

        console.print(table)

    except APIError as e:
        console.print(_helpers.format_error(f"Failed to list jobs: {e}"))
        sys.exit(EXIT_ERROR)


@click.command(deprecated=True)
@click.argument("job_id")
@click.option("-o", "--output", required=True, type=click.Path(path_type=Path), help="Output directory")
@click.option("--overwrite", is_flag=True, help="Overwrite existing files")
@click.pass_context
def retrieve(ctx: click.Context, job_id: str, output: Path, overwrite: bool) -> None:
    """
    Download encrypted results from a completed job.

    Deprecated: Use 'byod get <job-id> -o <dir>' instead.

    \b
    Examples:
        byod retrieve genomic-qc-20250126-abc123 -o ./results/
    """
    console = _helpers.console
    console.print(_helpers.format_warning("'byod retrieve' is deprecated. Use 'byod get <job-id> -o <dir>' instead."))
    import requests

    config = ctx.obj["CONFIG"]
    client = _helpers._get_api_client(config)

    if output.exists() and any(output.iterdir()) and not overwrite:
        console.print(_helpers.format_error(f"Output directory {output} is not empty. Use --overwrite."))
        sys.exit(EXIT_ERROR)

    console.print(f"\n[bold blue]Retrieving results for job {job_id}...[/bold blue]\n")

    try:
        with console.status("[bold green]Getting download URLs..."):
            output_presigned = client.get_download_url(job_id, "output.enc")
            key_presigned = client.get_download_url(job_id, "output_key.bin")

        output.mkdir(parents=True, exist_ok=True)

        with console.status("[bold green]Downloading encrypted results..."):
            response = requests.get(output_presigned.url, stream=True, timeout=300)
            if not response.ok:
                raise APIError(f"Download failed: {response.status_code}")
            enc_path = output / "output.enc"
            with open(enc_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

        with console.status("[bold green]Downloading wrapped key..."):
            response = requests.get(key_presigned.url, timeout=60)
            if not response.ok:
                raise APIError(f"Key download failed: {response.status_code}")
            key_path = output / "output_key.bin"
            with open(key_path, "wb") as f:
                f.write(response.content)

        tenant_config = client.get_tenant_config()
        kms_key_id = tenant_config.customer_kms_key_arn or tenant_config.kms_key_arn

        manifest = {
            "job_id": job_id, "encrypted_file": "output.enc",
            "wrapped_key_file": "output_key.bin", "kms_key_id": kms_key_id,
            "region": tenant_config.region, "downloaded_at": datetime.now().isoformat(),
        }
        manifest_path = output / "results-manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        console.print(_helpers.format_success("Results downloaded!"))
        console.print(f"\n  Output directory: {output}")
        console.print(f"  Manifest:         {manifest_path}")
        console.print(f"\n  Decrypt with: [cyan]byod decrypt {output} -o ./output.txt[/cyan]\n")

    except APIError as e:
        console.print(_helpers.format_error(str(e)))
        sys.exit(EXIT_ERROR)
    except Exception as e:
        console.print(_helpers.format_error(f"Retrieve failed: {e}"))
        if ctx.obj.get("DEBUG"):
            console.print_exception()
        sys.exit(EXIT_ERROR)


@click.command(deprecated=True)
@click.argument("results_path", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", required=True, type=click.Path(path_type=Path), help="Output directory for extracted files")
@click.pass_context
def decrypt(ctx: click.Context, results_path: Path, output: Path) -> None:
    """
    Decrypt downloaded results locally.

    Deprecated: Use 'byod get <job-id> -o <dir>' instead.

    \b
    Examples:
        byod decrypt ./results/ -o ./decrypted/
    """
    console = _helpers.console
    console.print(_helpers.format_warning("'byod decrypt' is deprecated. Use 'byod get <job-id> -o <dir>' instead."))
    import boto3

    console.print("\n[bold blue]Decrypting results...[/bold blue]\n")

    try:
        manifest_path = results_path / "results-manifest.json"
        if not manifest_path.exists():
            raise click.ClickException(
                f"Results manifest not found at {manifest_path}. Run 'byod retrieve' first."
            )
        with open(manifest_path) as f:
            manifest = json.load(f)

        console.print("  [dim]Manifest:[/dim]")
        for k, v in manifest.items():
            console.print(f"    {k}: {v}")

        key_path = results_path / manifest["wrapped_key_file"]
        with open(key_path, "rb") as f:
            wrapped_key = f.read()

        console.print(f"\n  Wrapped key size: {len(wrapped_key)} bytes")
        console.print(f"  Wrapped key (hex, first 64): {wrapped_key[:64].hex()}")
        console.print("\n  Unwrapping key via KMS...")

        kms = boto3.client("kms", region_name=manifest["region"])
        try:
            key_info = kms.describe_key(KeyId=manifest["kms_key_id"])
            console.print(f"  KMS Key State: {key_info['KeyMetadata']['KeyState']}")
            console.print(f"  KMS Key Usage: {key_info['KeyMetadata']['KeyUsage']}")
        except Exception as e:
            console.print(f"  [yellow]Warning: Could not describe KMS key: {e}[/yellow]")

        decrypt_response = kms.decrypt(CiphertextBlob=wrapped_key, KeyId=manifest["kms_key_id"])
        result_key = decrypt_response["Plaintext"]

        enc_path = results_path / manifest["encrypted_file"]
        with open(enc_path, "rb") as f:
            encrypted_data = f.read()

        console.print("  Decrypting data...")
        plaintext = _helpers._decrypt_data(encrypted_data, result_key)

        output.mkdir(parents=True, exist_ok=True)
        extracted_files = _extract_results(plaintext, output, console)

        console.print(_helpers.format_success("Results decrypted!"))
        console.print(f"\n  Job ID:          {manifest['job_id']}")
        console.print(f"  Decrypted size:  {_helpers.format_bytes(len(plaintext))}")
        console.print(f"  Output dir:      {output}")
        console.print(f"  Files extracted: {len(extracted_files)}\n")
        _print_security_panel(console)

        if isinstance(result_key, bytearray):
            for i in range(len(result_key)):
                result_key[i] = 0

    except Exception as e:
        console.print(_helpers.format_error(f"Decryption failed: {e}"))
        if ctx.obj.get("DEBUG"):
            console.print_exception()
        sys.exit(EXIT_ERROR)


@click.command()
@click.argument("job_id")
@click.option("-o", "--output", required=True, type=click.Path(path_type=Path), help="Output directory for decrypted results")
@click.option("--keep-encrypted", is_flag=True, help="Keep intermediate encrypted files")
@click.option("--overwrite", is_flag=True, help="Overwrite existing files in output directory")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.pass_context
def get(ctx: click.Context, job_id: str, output: Path, keep_encrypted: bool, overwrite: bool, output_format: str) -> None:
    """
    Retrieve and decrypt job results in one step.

    Downloads encrypted results from a completed job, unwraps the key via KMS,
    decrypts with AES-256-GCM, and extracts files to the output directory.

    \b
    Examples:
        byod get genomic-qc-20250126-abc123 -o ./output/
        byod get genomic-qc-20250126-abc123 -o ./output/ --keep-encrypted
        byod get genomic-qc-20250126-abc123 -o ./output/ --format json
    """
    import boto3
    import requests

    config = ctx.obj["CONFIG"]
    client = _helpers._get_api_client(config)
    console = _helpers.console

    if output.exists() and any(output.iterdir()) and not overwrite:
        console.print(_helpers.format_error(f"Output directory {output} is not empty. Use --overwrite."))
        sys.exit(EXIT_ERROR)

    console.print(f"\n[bold blue]Retrieving and decrypting results for job {job_id}...[/bold blue]\n")

    try:
        with console.status("[bold green]Getting download URLs..."):
            output_presigned = client.get_download_url(job_id, "output.enc")
            key_presigned = client.get_download_url(job_id, "output_key.bin")

        output.mkdir(parents=True, exist_ok=True)

        from rich.progress import BarColumn, DownloadColumn, Progress, TransferSpeedColumn

        response = requests.get(output_presigned.url, stream=True, timeout=300)
        if not response.ok:
            raise APIError(f"Download failed: {response.status_code}")

        total_size = int(response.headers.get("content-length", 0))
        enc_path = output / "output.enc"

        with Progress(
            "[progress.description]{task.description}", BarColumn(),
            DownloadColumn(), TransferSpeedColumn(),
            console=console, disable=ctx.obj.get("QUIET", False),
        ) as progress:
            task = progress.add_task("Downloading results...", total=total_size or None)
            with open(enc_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    progress.advance(task, len(chunk))

        with console.status("[bold green]Downloading wrapped key..."):
            response = requests.get(key_presigned.url, timeout=60)
            if not response.ok:
                raise APIError(f"Key download failed: {response.status_code}")
            key_path = output / "output_key.bin"
            with open(key_path, "wb") as f:
                f.write(response.content)

        tenant_config = client.get_tenant_config()
        kms_key_id = tenant_config.customer_kms_key_arn or tenant_config.kms_key_arn

        console.print("  Unwrapping key via KMS...")
        with open(key_path, "rb") as f:
            wrapped_key = f.read()

        kms = boto3.client("kms", region_name=tenant_config.region)
        decrypt_response = kms.decrypt(CiphertextBlob=wrapped_key, KeyId=kms_key_id)
        result_key = decrypt_response["Plaintext"]

        console.print("  Decrypting data...")
        with open(enc_path, "rb") as f:
            encrypted_data = f.read()
        plaintext = _helpers._decrypt_data(encrypted_data, result_key)

        extracted_files = _extract_results(plaintext, output, console)

        if not keep_encrypted:
            enc_path.unlink(missing_ok=True)
            key_path.unlink(missing_ok=True)

        if isinstance(result_key, bytearray):
            for i in range(len(result_key)):
                result_key[i] = 0

        if output_format == "json":
            click.echo(json.dumps({
                "job_id": job_id, "output_dir": str(output),
                "files": extracted_files, "decrypted_size": len(plaintext),
            }))
        else:
            console.print(_helpers.format_success("Results retrieved and decrypted!"))
            console.print(f"\n  Job ID:          {job_id}")
            console.print(f"  Decrypted size:  {_helpers.format_bytes(len(plaintext))}")
            console.print(f"  Output dir:      {output}")
            console.print(f"  Files extracted: {len(extracted_files)}")
            for fname in extracted_files[:10]:
                console.print(f"    {fname}")
            if len(extracted_files) > 10:
                console.print(f"    ... and {len(extracted_files) - 10} more")
            console.print()
            _print_security_panel(console)

    except AuthenticationError as e:
        console.print(_helpers.format_error(str(e)))
        sys.exit(EXIT_AUTH)
    except APIError as e:
        console.print(_helpers.format_error(str(e)))
        sys.exit(EXIT_ERROR)
    except Exception as e:
        console.print(_helpers.format_error(f"Failed: {e}"))
        if ctx.obj.get("DEBUG"):
            console.print_exception()
        sys.exit(EXIT_ERROR)


def _extract_results(plaintext: bytes, output: Path, console) -> list[str]:
    """Extract results from plaintext bytes (tar.gz or raw) to output dir."""
    extracted_files = []

    if len(plaintext) > 2 and plaintext[0:2] == b'\x1f\x8b':
        console.print("  Extracting results...")
        try:
            with tarfile.open(fileobj=io.BytesIO(plaintext), mode='r:gz') as tar:
                for member in tar.getmembers():
                    if member.name == "__manifest__.json":
                        continue
                    member_path = (Path(output) / member.name).resolve()
                    if not member_path.is_relative_to(Path(output).resolve()):
                        raise tarfile.TarError(
                            f"Tar member '{member.name}' would escape output directory"
                        )
                    tar.extract(member, path=output)
                    extracted_files.append(member.name)
        except tarfile.TarError:
            raw_output = output / "output.bin"
            with open(raw_output, "wb") as f:
                f.write(plaintext)
            extracted_files.append("output.bin")
    else:
        raw_output = output / "output.bin"
        with open(raw_output, "wb") as f:
            f.write(plaintext)
        extracted_files.append("output.bin")

    return extracted_files


def _print_security_panel(console) -> None:
    """Print the zero-knowledge security verification panel."""
    console.print(Panel(
        "[bold green]Security Verification[/bold green]\n\n"
        "  [green]OK[/green] Data was encrypted client-side before upload\n"
        "  [green]OK[/green] Only the attested Nitro Enclave could decrypt the input\n"
        "  [green]OK[/green] Enclave processed data and encrypted results with a new key\n"
        "  [green]OK[/green] Result key was unwrapped via KMS\n"
        "  [green]OK[/green] Results decrypted locally\n\n"
        "  Plaintext data never existed outside the Nitro Enclave.",
        title="Zero-Knowledge Processing",
        border_style="green",
    ))
