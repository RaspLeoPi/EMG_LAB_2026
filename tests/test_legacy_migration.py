"""Lossless migration using synthetic, response-selective EMG; no real hardware."""

import csv
import hashlib
import json
import zipfile
from copy import deepcopy

import numpy as np
import pytest

from emg_lab.backend.data import catalog, transfer
from emg_lab.backend.data.capture import CaptureRun
from emg_lab.backend.data.capture_index import write_capture_index
from emg_lab.backend.data.migration import check_destination, prepare_migration, publish_migration
from emg_lab.backend.data.storage import read_recording
from emg_lab.contracts.forearm import TASK, default_placement, validate_plan, validate_recording
from emg_lab.signal import SignalConfig


def legacy_record(root, kind="six", reject=False, swap=False):
    profile = dict(device="Cometa", sampling_rate=1000.0, channel_ids=[3, 8], unit="synthetic_only")
    rows = [
        dict(id=f"c{i}", name=name, effort=effort, body_part="右手", save_name=name, notes="")
        for i, (name, effort) in enumerate(
            [
                ("静息", "自然放松"),
                ("握拳", "普通"),
                ("内展", "用力握拳"),
                ("外展", "用力伸直"),
                ("内展", "普通"),
                ("外展", "普通"),
            ]
        )
    ]
    selected = {"six": list(range(6)), "ordinary": [0, 1, 4, 5], "strong": [2, 3]}[kind]
    plan = dict(
        version=1,
        operator="SYNTHETIC",
        wearing="右臂",
        notes="software fixture",
        channels=[dict(channel_id=c, muscle="", notes="") for c in profile["channel_ids"]],
        conditions=rows,
        selected_ids=[rows[i]["id"] for i in selected],
    )
    run = CaptureRun(
        root,
        "OLD",
        "fixture",
        profile,
        SignalConfig(),
        trial_count=3,
        action_s=2,
        capture_plan=plan,
    )
    rng = np.random.default_rng(13)
    raw = rng.normal(size=(run.session_length, 2)).astype("float32")
    for r in run.writer.labels:
        name = rows[selected[r["class_id"]]]["name"]
        gain = [16, 2] if name == "内展" else [2, 16] if name == "外展" else [4, 4]
        if swap:
            gain.reverse()
        raw[r["start_sample"] : r["end_sample"]] *= gain
    if reject:
        run.feed(raw[:1000])
        run.reject_trial(1, "synthetic rejection")
        raw = raw[1000:]
    run.feed(raw)
    return run.run_path


def members(path):
    with zipfile.ZipFile(path) as z:
        return {k: z.read(k) for k in z.namelist()}


@pytest.mark.parametrize("kind,count", [("ordinary", 12), ("six", 18), ("strong", 6)])
@pytest.mark.parametrize("swap", [False, True])
def test_lossless_variants_and_rounds(tmp_path, kind, count, swap):
    source = legacy_record(tmp_path / "source", kind, swap=swap)
    original_bytes = source.read_bytes()
    original_csv = source.with_suffix(".index.csv").read_bytes()
    prepared = prepare_migration(source)
    output, reused = publish_migration(prepared, tmp_path / "new")
    assert not reused
    meta, raw, labels = read_recording(output)
    original, original_raw, original_labels = read_recording(source)
    np.testing.assert_array_equal(raw, original_raw)
    assert members(output)["emg.bin"] == members(source)["emg.bin"]
    assert meta["completed_trials"] == meta["usable_trials"] == len(labels) == count
    assert [r["trial"] for r in labels] == list(range(1, count + 1))
    assert [(r["start_sample"], r["end_sample"]) for r in labels] == [
        (r["start_sample"], r["end_sample"]) for r in original_labels
    ]
    assert meta["schedule"][-1]["round_index"] == original["trial_count"] == 3
    assert meta["capture_plan"]["channels"][int(swap)]["position"] == "forearm_flexor"
    assert all(
        c["placement"]["source"] == "legacy_unknown" and c["placement"]["electrodes"] is None
        for c in meta["capture_plan"]["channels"]
    )
    assert meta["capture_plan"]["instruction_version"] is None
    assert "区域标注" in catalog.describe(catalog.catalogue(tmp_path / "new")[0])
    if kind == "six":
        assert meta["actual_order"] == [0, 1, 2, 3, 2, 3] * 3
        assert {r["activation_condition"] for r in meta["schedule"]} >= {
            "ordinary",
            "strong_fist_activation",
            "strong_hand_extension_activation",
        }
    before = output.read_bytes()
    again = prepare_migration(source)
    assert again["payload"] == prepared["payload"]
    assert publish_migration(again, tmp_path / "new") == (output, True)
    assert output.read_bytes() == before
    csv_bytes = output.with_suffix(".index.csv").read_bytes()
    output.with_suffix(".index.csv").unlink()
    write_capture_index(output, meta)
    assert output.with_suffix(".index.csv").read_bytes() == csv_bytes
    with output.with_suffix(".index.csv").open(encoding="utf-8-sig") as f:
        index = list(csv.DictReader(f))
    assert len(index) == count and index[0]["source_condition_id"]
    assert (
        source.read_bytes() == original_bytes
        and source.with_suffix(".index.csv").read_bytes() == original_csv
    )
    exports = tmp_path / "exports"
    exports.mkdir()
    exported = transfer.export_recording(output, exports, TASK)
    restored = transfer.import_recording(exported, tmp_path / "restored", TASK)
    assert members(restored.path) == members(output)
    from emg_lab.backend.learning.dataset import prepare_dataset

    with pytest.raises(ValueError, match="尚未配置"):
        prepare_dataset([output])


def test_rejected_legacy_round_expands_to_actions(tmp_path):
    prepared = prepare_migration(legacy_record(tmp_path / "source", reject=True))
    output, _ = publish_migration(prepared, tmp_path / "new")
    meta, _, _ = read_recording(output)
    assert [r["trial"] for r in meta["rejected_trials"]] == list(range(1, 7))
    assert meta["completed_trials"] == 18 and meta["usable_trials"] == 12


def test_conflict_never_overwrites(tmp_path):
    prepared = prepare_migration(legacy_record(tmp_path / "source"))
    output = tmp_path / "new" / prepared["relative_path"]
    output.parent.mkdir(parents=True)
    output.write_bytes(b"existing unrelated file")
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        check_destination(prepared, tmp_path / "new")
    assert output.read_bytes() == b"existing unrelated file"


@pytest.mark.parametrize("change", ["schedule", "origin", "mapping", "region", "raw"])
def test_tampering_rejected(tmp_path, change):
    prepared = prepare_migration(legacy_record(tmp_path / "source"))
    output, _ = publish_migration(prepared, tmp_path / "new")
    payload = members(output)
    meta = json.loads(payload["meta.json"])
    if change == "schedule":
        meta["schedule"][0]["start_sample"] += 1
    elif change == "origin":
        del meta["capture_plan"]["origin"]
        for c in meta["capture_plan"]["channels"]:
            c["placement"] = default_placement()
        meta["capture_plan"]["instruction_version"] = 1
    elif change == "mapping":
        meta["migration"]["condition_mapping"]["c2"]["activation"] = "ordinary"
    elif change == "region":
        meta["capture_plan"]["channels"][0]["position"] = "forearm_extensor"
    else:
        raw = bytearray(payload["emg.bin"])
        raw[-1] ^= 1
        payload["emg.bin"] = bytes(raw)
    payload["meta.json"] = json.dumps(meta).encode()
    with zipfile.ZipFile(output, "w") as z:
        for k, v in payload.items():
            z.writestr(k, v)
    with pytest.raises(ValueError):
        read_recording(output)


def test_native_validation_stays_strict(tmp_path):
    prepared = prepare_migration(legacy_record(tmp_path / "source"))
    p = deepcopy(prepared["metadata"]["capture_plan"])
    p.pop("origin")
    with pytest.raises(ValueError):
        validate_plan(p)
    meta = deepcopy(prepared["metadata"])
    meta["capture_plan"]["origin"] = None
    meta.pop("migration")
    meta["capture_plan"]["instruction_version"] = 1
    for c in meta["capture_plan"]["channels"]:
        c["placement"] = default_placement()
    with pytest.raises(ValueError):
        validate_recording(meta, [])  # Six conditions cannot enter native four-action timing.


def test_ambiguous_signals_do_not_receive_anatomical_labels(tmp_path):
    source = legacy_record(tmp_path / "source")
    payload = members(source)
    from emg_lab.backend.data.storage import HEADER

    rows = np.frombuffer(payload["emg.bin"], dtype="<f4", offset=HEADER.size).copy().reshape(-1, 3)
    rows[:, 2] = rows[:, 1]
    payload["emg.bin"] = payload["emg.bin"][: HEADER.size] + rows.astype("<f4").tobytes()
    with zipfile.ZipFile(source, "w") as z:
        for k, v in payload.items():
            z.writestr(k, v)
    with pytest.raises(ValueError, match="区域推断"):
        prepare_migration(source)


def test_new_protocol_machine_test_is_excluded(tmp_path, profile):
    from test_forearm_capture import plan_for

    from emg_lab.backend.data.forearm import ForearmCaptureRun

    run = ForearmCaptureRun(tmp_path, profile, plan_for(profile))
    run.feed(np.zeros((run.session_length, len(profile["channel_ids"])), "float32"))
    before = hashlib.sha256(run.run_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="测试或新版"):
        prepare_migration(run.run_path)
    assert hashlib.sha256(run.run_path.read_bytes()).hexdigest() == before


def test_imported_plan_cannot_start_live_collection(tmp_path):
    from emg_lab.backend.data.forearm import ForearmCaptureRun

    prepared = prepare_migration(legacy_record(tmp_path / "source"))
    meta = prepared["metadata"]
    with pytest.raises(ValueError, match="不能用于启动"):
        ForearmCaptureRun(tmp_path / "live", meta, meta["capture_plan"])
    assert not (tmp_path / "live").exists()
