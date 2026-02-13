"""Tests for file type validation (byod_cli/validation.py).

Covers extension-based validation (formats), glob-based validation (pattern),
double extensions (.fastq.gz), mixed valid/invalid files, and no-restriction plugins.
"""

from byod_cli.validation import (
    get_accepted_extensions,
    validate_files_for_plugin,
)

# ---------------------------------------------------------------------------
# Plugin input fixtures
# ---------------------------------------------------------------------------

DEMO_COUNT_INPUTS = [
    {
        "name": "input_file",
        "type": "file",
        "required": True,
        "description": "Text file to process",
        "formats": ["txt", "csv", "tsv", "log"],
    }
]

GENOMIC_QC_INPUTS = [
    {
        "name": "fastq_files",
        "type": "file",
        "pattern": "*.fastq*",
        "required": True,
        "multiple": True,
    },
    {
        "name": "quality_threshold",
        "type": "integer",
        "required": False,
        "default": 20,
    },
]

NO_RESTRICTION_INPUTS = [
    {
        "name": "any_file",
        "type": "file",
        "required": True,
    }
]


# ---------------------------------------------------------------------------
# get_accepted_extensions
# ---------------------------------------------------------------------------

class TestGetAcceptedExtensions:
    def test_demo_count_extensions(self):
        exts = get_accepted_extensions(DEMO_COUNT_INPUTS)
        assert exts == {".txt", ".csv", ".tsv", ".log"}

    def test_genomic_qc_extensions(self):
        exts = get_accepted_extensions(GENOMIC_QC_INPUTS)
        assert exts is not None
        assert ".fastq" in exts
        assert ".fastq.gz" in exts

    def test_empty_inputs(self):
        assert get_accepted_extensions([]) is None

    def test_none_inputs(self):
        # validate_files_for_plugin passes [] when no inputs
        assert get_accepted_extensions([]) is None

    def test_no_file_type_inputs(self):
        """Plugin with only non-file inputs has no restrictions."""
        inputs = [{"name": "threshold", "type": "integer"}]
        assert get_accepted_extensions(inputs) is None

    def test_no_restriction_input(self):
        """File input with no formats or pattern returns None."""
        assert get_accepted_extensions(NO_RESTRICTION_INPUTS) is None


# ---------------------------------------------------------------------------
# validate_files_for_plugin — demo-count (formats-based)
# ---------------------------------------------------------------------------

class TestValidateDemoCount:
    def test_valid_txt(self):
        errors = validate_files_for_plugin(["data.txt"], DEMO_COUNT_INPUTS)
        assert errors == []

    def test_valid_csv(self):
        errors = validate_files_for_plugin(["report.csv"], DEMO_COUNT_INPUTS)
        assert errors == []

    def test_valid_tsv(self):
        errors = validate_files_for_plugin(["results.tsv"], DEMO_COUNT_INPUTS)
        assert errors == []

    def test_valid_log(self):
        errors = validate_files_for_plugin(["app.log"], DEMO_COUNT_INPUTS)
        assert errors == []

    def test_invalid_fastq(self):
        errors = validate_files_for_plugin(["sample.fastq"], DEMO_COUNT_INPUTS)
        assert len(errors) == 1
        assert "sample.fastq" in errors[0]
        assert ".txt" in errors[0]

    def test_invalid_png(self):
        errors = validate_files_for_plugin(["photo.png"], DEMO_COUNT_INPUTS)
        assert len(errors) == 1
        assert "photo.png" in errors[0]

    def test_case_insensitive(self):
        errors = validate_files_for_plugin(["DATA.TXT"], DEMO_COUNT_INPUTS)
        assert errors == []

    def test_multiple_valid_files(self):
        errors = validate_files_for_plugin(
            ["a.txt", "b.csv", "c.tsv", "d.log"], DEMO_COUNT_INPUTS
        )
        assert errors == []

    def test_mixed_valid_invalid(self):
        errors = validate_files_for_plugin(
            ["good.txt", "bad.fastq", "ok.csv", "nope.png"], DEMO_COUNT_INPUTS
        )
        assert len(errors) == 2
        rejected_files = " ".join(errors)
        assert "bad.fastq" in rejected_files
        assert "nope.png" in rejected_files


# ---------------------------------------------------------------------------
# validate_files_for_plugin — genomic-qc (pattern-based)
# ---------------------------------------------------------------------------

class TestValidateGenomicQc:
    def test_valid_fastq(self):
        errors = validate_files_for_plugin(["reads.fastq"], GENOMIC_QC_INPUTS)
        assert errors == []

    def test_valid_fastq_gz(self):
        errors = validate_files_for_plugin(["sample.fastq.gz"], GENOMIC_QC_INPUTS)
        assert errors == []

    def test_invalid_csv(self):
        errors = validate_files_for_plugin(["data.csv"], GENOMIC_QC_INPUTS)
        assert len(errors) == 1
        assert "data.csv" in errors[0]

    def test_invalid_txt(self):
        errors = validate_files_for_plugin(["readme.txt"], GENOMIC_QC_INPUTS)
        assert len(errors) == 1

    def test_case_insensitive_pattern(self):
        errors = validate_files_for_plugin(["SAMPLE.FASTQ"], GENOMIC_QC_INPUTS)
        assert errors == []

    def test_multiple_valid_fastq(self):
        errors = validate_files_for_plugin(
            ["sample1.fastq", "sample2.fastq.gz"], GENOMIC_QC_INPUTS
        )
        assert errors == []

    def test_mixed_fastq_and_csv(self):
        errors = validate_files_for_plugin(
            ["good.fastq", "bad.csv"], GENOMIC_QC_INPUTS
        )
        assert len(errors) == 1
        assert "bad.csv" in errors[0]


# ---------------------------------------------------------------------------
# validate_files_for_plugin — no restriction
# ---------------------------------------------------------------------------

class TestValidateNoRestriction:
    def test_any_file_passes(self):
        errors = validate_files_for_plugin(["anything.xyz"], NO_RESTRICTION_INPUTS)
        assert errors == []

    def test_empty_inputs_list(self):
        errors = validate_files_for_plugin(["file.txt"], [])
        assert errors == []

    def test_no_inputs(self):
        """Plugin with no inputs at all accepts anything."""
        errors = validate_files_for_plugin(["file.txt"], [])
        assert errors == []

    def test_only_non_file_inputs(self):
        inputs = [{"name": "threshold", "type": "integer"}]
        errors = validate_files_for_plugin(["anything.bin"], inputs)
        assert errors == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestValidateEdgeCases:
    def test_empty_filenames(self):
        errors = validate_files_for_plugin([], DEMO_COUNT_INPUTS)
        assert errors == []

    def test_no_extension(self):
        errors = validate_files_for_plugin(["Makefile"], DEMO_COUNT_INPUTS)
        assert len(errors) == 1

    def test_hidden_file(self):
        errors = validate_files_for_plugin([".gitignore"], DEMO_COUNT_INPUTS)
        assert len(errors) == 1

    def test_double_extension_formats(self):
        """Double extensions should be checked when formats list includes them."""
        inputs = [{"name": "f", "type": "file", "formats": ["tar.gz"]}]
        errors = validate_files_for_plugin(["archive.tar.gz"], inputs)
        assert errors == []

    def test_fastq_gz_matches_pattern(self):
        """*.fastq* should match sample.fastq.gz."""
        errors = validate_files_for_plugin(["sample.fastq.gz"], GENOMIC_QC_INPUTS)
        assert errors == []
