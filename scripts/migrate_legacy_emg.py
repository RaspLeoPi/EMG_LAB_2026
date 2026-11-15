"""Explicit-source legacy migration with a local report; defaults to a dry run."""

import argparse
import csv
import json
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from emg_lab.backend.data import catalog, transfer
from emg_lab.backend.data.capture_index import write_capture_index
from emg_lab.backend.data.migration import (
    check_destination,
    json_bytes,
    prepare_migration,
    publish_migration,
    sha256,
)
from emg_lab.backend.data.storage import read_recording, recording_metadata
from emg_lab.contracts.forearm import TASK


def snapshot(paths):
    return {str(p.resolve()): sha256(p.read_bytes()) for p in paths if p.is_file()}


def assert_unchanged(hashes):
    if any(
        not Path(p).is_file() or sha256(Path(p).read_bytes()) != digest
        for p, digest in hashes.items()
    ):
        raise ValueError("已有数据文件发生变化，验证失败。")


def verify_output(prepared, output, checks_root):
    source = prepared["source"]
    source_meta, _, source_labels = read_recording(source)
    meta, _, labels = read_recording(output)
    with zipfile.ZipFile(output) as archive:
        if archive.read("emg.bin") != prepared["payload"]["emg.bin"]:
            raise ValueError("迁移后的原始二进制数据与来源不同。")
    assert [(r["start_sample"], r["end_sample"]) for r in labels] == [
        (r["start_sample"], r["end_sample"]) for r in source_labels
    ]
    assert len(labels) == len(source_labels)
    checks_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="migration-check-", dir=checks_root) as folder:
        folder = Path(folder)
        regenerated = write_capture_index(folder / output.name, meta)
        assert regenerated.read_bytes() == output.with_suffix(".index.csv").read_bytes()
        export_folder = folder / "exports"
        export_folder.mkdir()
        exported = transfer.export_recording(output, export_folder, TASK)
        restored = transfer.import_recording(exported, folder / "restored", TASK)
        restored_meta, _, restored_labels = read_recording(restored.path)
        assert restored_meta == meta and restored_labels == labels
    # Reader validation hashes the complete binary member, including header and sample clock.
    assert (
        meta["migration"]["source_emg_bin_sha256"]
        == prepared["metadata"]["migration"]["source_emg_bin_sha256"]
    )
    entry = next(e for e in catalog.catalogue(output.parents[2]) if e.identity == meta["record_id"])
    description = catalog.describe(entry)
    assert "区域标注" in description
    return dict(
        output=str(output.resolve()),
        source=str(source.resolve()),
        subject=meta["subject"],
        movement_side=meta["capture_plan"]["movement_side"],
        source_record_id=source_meta["record_id"],
        record_id=meta["record_id"],
        source_sha256=meta["migration"]["source_archive_sha256"],
        output_sha256=sha256(output.read_bytes()),
        emg_bin_sha256=meta["migration"]["source_emg_bin_sha256"],
        labels=len(labels),
        samples=meta["samples"],
        duration_seconds=meta["duration"],
        channels=meta["capture_plan"]["channels"],
        inference=meta["migration"]["region_inference"],
        raw_bytes_preserved=True,
        sample_boundaries_preserved=True,
        index_regeneration=True,
        library_visible=True,
        import_export_roundtrip=True,
    )


def report_markdown(records, preserved, excluded):
    lines = [
        "# Legacy EMG migration report",
        "",
        f"Generated: {datetime.now().astimezone().isoformat()}",
        "",
        f"Converted **{len(records)} recordings / {sum(r['labels'] for r in records)} action trials**. "
        "Original archives and sidecars remain unchanged. The recent machine test was excluded.",
        "",
        "## Inferred channel regions",
        "",
        "| Subject | Arm | Start | Flexor | Extensor | Sensitivity checks | Robust-bin checks | Minimum relative selectivity |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in records:
        e = r["inference"]
        lines.append(
            f"| {r['subject']} | {r['movement_side']} | {Path(r['output']).stem.split('_', 1)[-1]} | CH{e['flexor_channel']} | CH{e['extensor_channel']} | {e['sensitivity_comparisons']} | {e['robust_bin_comparisons']} | {e['minimum_relative_selectivity']:.2f}× |"
        )
    lines += [
        "",
        "All checks support the listed assignment. These are functional region inferences, not verified muscle locations or calibrated probabilities.",
        "",
        "## Method and assumptions",
        "",
        "Use the existing continuous causal 20–450 Hz band-pass. Compare paired inward/outward action RMS within each channel, then compare those ratios between channels, avoiding a simple comparison of sensor gains. Repeat with/without 50 Hz notch and onset/end trims of 0/0, 0.5/0.25 and 1/0.5 seconds. Independently check medians of 100 ms RMS bins. Require consistent direction and at least twofold relative selectivity in every comparison; this is a descriptive acceptance rule, not an anatomical confidence interval.",
        "",
        "Ordinary and stronger conditions are paired separately. All five original rounds are retained. No classifier was trained and no trials were discarded based on amplitude.",
        "",
        "- Subject IDs are taken from the legacy operator field; participant identity is not independently established.",
        "- Arm side comes from selected conditions and wearing notes. Unselected stale conditions do not override the active side.",
        "- 内展 → wrist_flexion; 外展 → wrist_extension is the explicit semantic assumption. Signal patterns alone cannot resolve a simultaneous swap of action and muscle identities.",
        "- Channel regions are inferred from the data. Exact FCR/ED placement, electrode coordinates, diameter and spacing remain unknown for these historical files.",
        "- Historical instruction version is unknown. Strong fist/hand-extension activation remains a per-trial annotation and is not treated as the current relaxed-finger instruction.",
        "",
        "## Converted artifacts",
        "",
        "| Source | Converted archive | Action trials |",
        "|---|---|---:|",
    ]
    for r in records:
        lines.append(f"| {Path(r['source']).name} | {r['output']} | {r['labels']} |")
    lines += [
        "",
        "Each archive has a matching `.index.csv`. Original creation time, complete raw binary member (including header and sample-clock column), sample rate, channel order, labels' sample boundaries and validity are retained. Individual trials have new sequential IDs; original rounds and condition IDs remain in the schedule/provenance.",
        "",
        "The six-condition recording retains six trials per original round with four canonical actions. Its repetitions field describes legacy condition rounds; ordinary and stronger trials remain distinct through activation annotations. Converted records remain collection-only and are excluded from training.",
        "",
        "## Verification",
        "",
        "- Reader validation, byte preservation, exact interval/count preservation: passed for every output.",
        "- Library listing/descriptions, import/export and index regeneration: passed for every output.",
        "- Deterministic rerun: outputs reused without rewriting archive bytes; conflicting destinations are rejected.",
        f"- Existing file SHA256 checks: {len(preserved)} files unchanged.",
        "- No physical device or robot output was activated.",
        "",
        "Excluded existing recordings:",
        "",
    ]
    lines += [f"- `{p}`" for p in excluded]
    lines += ["", "## SHA256 inventory", "", "| File | SHA256 |", "|---|---|"]
    lines += [f"| {p} | `{h}` |" for p, h in sorted(preserved.items())]
    lines += [f"| {r['output']} | `{r['output_sha256']}` |" for r in records]
    lines += [
        "",
        "Detailed measurements, channel maps, source/output identities and hashes are in `results.json`; per-trial annotations are in `trials.csv`.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        nargs="+",
        required=True,
        help="Exact source allowlist; no automatic data discovery",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument(
        "--apply", action="store_true", help="Publish converted copies; otherwise inspect only"
    )
    args = parser.parse_args()
    if args.apply and not args.report_root:
        parser.error("--apply requires --report-root")
    sources = sorted({p.resolve() for p in args.source})
    if len(sources) != len(args.source):
        parser.error("Duplicate source paths are not allowed")
    existing = list(args.output_root.rglob("*.emg")) + list(args.output_root.rglob("*.index.csv"))
    preserved = snapshot(existing + sources + [p.with_suffix(".index.csv") for p in sources])
    prepared = [prepare_migration(p) for p in sources]
    outputs = [check_destination(p, args.output_root) for p in prepared]
    if len({str(p.resolve()) for p in outputs}) != len(outputs):
        raise ValueError("Sources resolve to conflicting output filenames")
    assert_unchanged(preserved)
    if not args.apply:
        print(
            json.dumps(
                dict(
                    dry_run=True,
                    recordings=len(prepared),
                    action_trials=sum(p["metadata"]["labels"] for p in prepared),
                    outputs=[str(p) for p in outputs],
                    mappings=[p["metadata"]["migration"]["region_inference"] for p in prepared],
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    args.report_root.mkdir(parents=True, exist_ok=True)
    records = []
    for p in prepared:
        output, reused = publish_migration(p, args.output_root)
        row = verify_output(p, output, args.report_root / "checks")
        before = sha256(output.read_bytes())
        assert publish_migration(p, args.output_root) == (output, True)
        assert sha256(output.read_bytes()) == before
        row["reused"] = reused
        records.append(row)
    assert_unchanged(preserved)
    excluded = [
        str(p.resolve())
        for p in existing
        if p.suffix == ".emg"
        and p.resolve() not in sources
        and recording_metadata(p).get("task_type") != "EMG_CUSTOM_CAPTURE_V1"
        and not recording_metadata(p).get("migration")
    ]
    results = dict(
        version=1,
        records=records,
        preserved_file_hashes=preserved,
        excluded_recordings=excluded,
        source_files_unchanged=True,
        raw_bytes_preserved=True,
        passed=True,
    )
    (args.report_root / "results.json").write_bytes(json_bytes(results))
    (args.report_root / "report.md").write_text(
        report_markdown(records, preserved, excluded), encoding="utf-8"
    )
    trial_rows = []
    for p in prepared:
        for r in p["metadata"]["schedule"]:
            trial_rows.append(
                dict(subject=p["metadata"]["subject"], record_id=p["metadata"]["record_id"], **r)
            )
    with (args.report_root / "trials.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(trial_rows[0]))
        w.writeheader()
        w.writerows(trial_rows)
    print(
        json.dumps(
            dict(
                passed=True,
                recordings=len(records),
                action_trials=sum(r["labels"] for r in records),
                reused=sum(r["reused"] for r in records),
                report=str(args.report_root / "report.md"),
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
