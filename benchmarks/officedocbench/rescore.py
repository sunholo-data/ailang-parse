"""Rescore an explicitly cached live run without another provider API call.

Validates the original adapter/version/input fingerprint. The parse timestamp
and adapter provenance are retained; a separate scoring timestamp/revision is
recorded. Portable normalization can use evidence already present in cached output; its
revision is recorded separately from the original provider adapter.
"""

from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import jsonschema
import eval_officedocbench as bench
from scoring import score_file
from adapters.structure import add_sheet_scopes
from structure_v2 import BENCHMARK_VERSION, has_extracted_content


def rescore(result, cache_root):
    provenance = result.get("provenance", {})
    if provenance.get("mode") not in ("live", "rescore") or not provenance.get(
        "adapter_sha256"
    ):
        raise ValueError("only an identifiable live parse can be rescored")
    schema = json.loads(
        (bench.SCRIPT_DIR / "schema/adapter_output.schema.json").read_text()
    )
    cache_dir = cache_root / result["adapter"].lower().replace(" ", "_")
    for row in result["results"]:
        if (
            row["status"] != "OK"
            and row.get("error") != "provider returned no extracted content"
        ):
            continue
        gt = json.loads((bench.GT_DIR / (row["file"] + ".json")).read_text())
        source = bench._find_test_file(row["file"])
        cache = json.loads((cache_dir / (row["file"] + ".json")).read_text())
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        fingerprint = hashlib.sha256(
            (result["version"] + provenance["adapter_sha256"] + digest).encode()
        ).hexdigest()
        if cache["fingerprint"] != fingerprint:
            raise ValueError("input or provider revision changed for " + row["file"])
        if gt.get("verification", {}).get("source_sha256", digest) != digest:
            raise ValueError("ground truth does not match source " + row["file"])
        output = cache["output"]
        if gt["format"] == "xlsx" and result["adapter"] in ("LlamaParse", "MarkItDown"):
            output = add_sheet_scopes(output)
        jsonschema.validate(output, schema)
        if not has_extracted_content(output, gt):
            row.update(status="ERROR", error="provider returned no extracted content")
            row.pop("scores", None)
        else:
            row["status"] = "OK"
            row.pop("error", None)
            row["scores"] = score_file(gt, output)
        row["parsed_at"] = cache["parsed_at"]
    provenance.update(
        benchmark_version=BENCHMARK_VERSION,
        mode="rescore",
        scored_at=datetime.now(timezone.utc).isoformat(),
        scoring_git_commit=subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=bench.REPO_DIR,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        corpus_sha256=hashlib.sha256(
            b"".join(p.read_bytes() for p in sorted(bench.GT_DIR.glob("*.json")))
        ).hexdigest(),
        normalizer_sha256=hashlib.sha256(
            (bench.SCRIPT_DIR / "adapters/structure.py").read_bytes()
        ).hexdigest(),
        scorer_sha256=hashlib.sha256(
            (bench.SCRIPT_DIR / "scoring.py").read_bytes()
            + (bench.SCRIPT_DIR / "structure_v2.py").read_bytes()
        ).hexdigest(),
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--output-cache", type=Path, required=True)
    args = parser.parse_args()
    for path in sorted(args.results_dir.glob("*/results.json")):
        result = rescore(json.loads(path.read_text()), args.output_cache)
        path.write_text(json.dumps(result, indent=2) + "\n")
        print(
            result["adapter"],
            sum(r["status"] == "OK" for r in result["results"]),
            "/",
            len(result["results"]),
        )


if __name__ == "__main__":
    main()
