"""File type validation for plugin workflows.

Validates filenames against a plugin's declared input spec from plugin.yaml.
Supports both extension-based (formats) and glob-based (pattern) validation.
"""

import fnmatch
from pathlib import PurePosixPath


def get_accepted_extensions(plugin_inputs: list[dict]) -> set[str] | None:
    """Extract accepted file extensions from plugin input spec.

    Only considers inputs with type "file".

    Returns a set of lowercase extensions with dots (e.g., {'.txt', '.csv'})
    or None if the plugin accepts any file type (no file inputs have
    formats/pattern restrictions).
    """
    if not plugin_inputs:
        return None

    extensions: set[str] = set()
    has_file_constraint = False

    for inp in plugin_inputs:
        if inp.get("type") != "file":
            continue

        formats = inp.get("formats", [])
        pattern = inp.get("pattern")

        if formats:
            has_file_constraint = True
            for fmt in formats:
                extensions.add(f".{fmt.lower()}")
        elif pattern:
            has_file_constraint = True
            extensions.update(_extensions_from_pattern(pattern))

    return extensions if has_file_constraint else None


def _extensions_from_pattern(pattern: str) -> set[str]:
    """Derive file extensions from a glob pattern for UI display.

    E.g., "*.fastq*" -> {".fastq", ".fastq.gz", ".fq", ".fq.gz"}
    This is a best-effort mapping for common bioinformatics patterns.
    """
    if "fastq" in pattern.lower():
        return {".fastq", ".fastq.gz", ".fq", ".fq.gz"}
    # For other patterns, extract the extension from the pattern itself
    # e.g., "*.csv" -> {".csv"}
    if pattern.startswith("*.") and "*" not in pattern[2:] and "?" not in pattern[2:]:
        return {pattern[1:].lower()}  # "*.csv" -> ".csv"
    return set()


def validate_files_for_plugin(
    filenames: list[str],
    plugin_inputs: list[dict],
) -> list[str]:
    """Validate filenames against plugin input requirements.

    Args:
        filenames: List of filenames to validate.
        plugin_inputs: The plugin's ``inputs`` list from plugin.yaml.

    Returns:
        List of error messages (empty means all valid).
        Handles both ``formats`` (list of extensions) and
        ``pattern`` (glob like ``*.fastq*``) specs.
    """
    if not plugin_inputs:
        return []

    # Collect all file-type input constraints
    file_constraints: list[dict] = [
        inp for inp in plugin_inputs if inp.get("type") == "file"
    ]
    if not file_constraints:
        return []

    errors: list[str] = []

    for fname in filenames:
        if _file_matches_any_constraint(fname, file_constraints):
            continue
        # Build a human-readable description of what's accepted
        accepted = _describe_accepted(file_constraints)
        errors.append(f"'{fname}' is not an accepted file type. Expected: {accepted}")

    return errors


def _file_matches_any_constraint(filename: str, constraints: list[dict]) -> bool:
    """Check if a filename matches at least one file input constraint."""
    for inp in constraints:
        formats = inp.get("formats", [])
        pattern = inp.get("pattern")

        if formats:
            if _matches_formats(filename, formats):
                return True
        elif pattern:
            if _matches_pattern(filename, pattern):
                return True
        else:
            # No restriction on this input — matches anything
            return True

    return False


def _matches_formats(filename: str, formats: list[str]) -> bool:
    """Check if filename extension matches any of the allowed formats.

    Handles double extensions like .fastq.gz by checking both
    the last extension and the last two extensions.
    """
    lower = filename.lower()
    allowed = {fmt.lower() for fmt in formats}

    # Check last extension: "data.csv" -> "csv"
    ext = PurePosixPath(lower).suffix.lstrip(".")
    if ext in allowed:
        return True

    # Check double extension: "sample.fastq.gz" -> "fastq.gz"
    suffixes = PurePosixPath(lower).suffixes
    if len(suffixes) >= 2:
        double_ext = "".join(suffixes[-2:]).lstrip(".")
        if double_ext in allowed:
            return True

    return False


def _matches_pattern(filename: str, pattern: str) -> bool:
    """Check if filename matches a glob pattern using fnmatch."""
    return fnmatch.fnmatch(filename.lower(), pattern.lower())


def _describe_accepted(constraints: list[dict]) -> str:
    """Build a human-readable description of accepted file types."""
    parts: list[str] = []
    for inp in constraints:
        formats = inp.get("formats", [])
        pattern = inp.get("pattern")
        if formats:
            parts.append(", ".join(f".{f}" for f in formats))
        elif pattern:
            parts.append(f"files matching {pattern}")
    return " or ".join(parts) if parts else "any file"
