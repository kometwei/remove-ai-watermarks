"""Tests for the SynthID corpus ingestion script."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

# scripts/ is not an installed package; add it to the path for import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import synthid_corpus

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"


def _manifest_rows(root: Path) -> list[dict[str, str]]:
    with open(root / "manifest.csv", newline="") as f:
        return list(csv.DictReader(f))


@pytest.mark.skipif(not SAMPLES_DIR.exists(), reason="data/samples not present")
class TestIngest:
    def test_ingest_openai_flags_synthid_metadata(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(
            synthid_corpus.cli,
            ["ingest", str(SAMPLES_DIR / "chatgpt-1.png"), "--label", "pos", "--root", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output

        rows = _manifest_rows(tmp_path)
        assert len(rows) == 1
        row = rows[0]
        assert row["label"] == "pos"
        assert row["synthid_metadata"] == "yes"
        assert int(row["width"]) > 0
        assert int(row["height"]) > 0
        # The copied file lands under images/pos/ with a sha-prefixed name.
        assert (tmp_path / "images" / "pos" / row["filename"]).exists()

    def test_ingest_firefly_not_flagged(self, tmp_path: Path):
        runner = CliRunner()
        runner.invoke(
            synthid_corpus.cli,
            ["ingest", str(SAMPLES_DIR / "firefly-1.png"), "--label", "neg", "--root", str(tmp_path)],
        )
        rows = _manifest_rows(tmp_path)
        assert len(rows) == 1
        assert rows[0]["synthid_metadata"] == ""  # Adobe signs C2PA but not SynthID

    def test_ingest_dedupes_by_sha256(self, tmp_path: Path):
        runner = CliRunner()
        args = ["ingest", str(SAMPLES_DIR / "chatgpt-1.png"), "--label", "pos", "--root", str(tmp_path)]
        runner.invoke(synthid_corpus.cli, args)
        runner.invoke(synthid_corpus.cli, args)  # second time: duplicate
        assert len(_manifest_rows(tmp_path)) == 1

    def test_status_on_empty_corpus(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(synthid_corpus.cli, ["status", "--root", str(tmp_path)])
        assert result.exit_code == 0
        assert "empty" in result.output.lower()
