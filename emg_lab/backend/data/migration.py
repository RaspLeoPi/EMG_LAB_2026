"""Lossless, auditable legacy EMG conversion. No device or robot dependencies."""

import csv
import hashlib
import io
import json
import uuid
import zipfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import numpy as np

from emg_lab.backend.learning.signal import SignalConfig, SignalFilter
from emg_lab.contracts.acquisition import CUSTOM_CAPTURE, selected_conditions
from emg_lab.contracts.forearm import (
    ACTIONS,
    PROTOCOL,
    SCHEMA_VERSION,
    TASK,
    validate_plan,
    validate_recording,
)
from emg_lab.contracts.legacy_migration import LABEL_FIELDS, ORIGIN, migrated_schedule

from .capture_index import write_capture_index
from .storage import read_recording, safe_name

VERSION = 1
MEMBERS = ("emg.bin", "labels.csv", "meta.json")


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode(
        "utf-8"
    )


def translate_condition(condition):
    name, effort = condition["name"], condition.get("effort", "")
    if name == "静息":
        return dict(action="rest", activation="natural_rest")
    if name == "握拳":
        action = "fist"
    elif name.startswith("内展"):
        action = "wrist_flexion"
    elif name.startswith("外展"):
        action = "wrist_extension"
    else:
        raise ValueError(f"无法翻译旧动作：{name}")
    if "用力握拳" in effort or "用力握拳" in name:
        activation = "strong_fist_activation"
    elif "用力伸直" in effort or "用力伸直" in name:
        activation = "strong_hand_extension_activation"
    elif effort == "普通":
        activation = "ordinary"
    elif not effort:
        activation = "unspecified"
    else:
        raise ValueError(f"无法翻译旧激活条件：{effort}")
    return dict(action=action, activation=activation)


def infer_side(meta, conditions):
    def side(text):
        left, right = "左" in text, "右" in text
        return "left" if left and not right else "right" if right and not left else None

    evidence = [side(c.get("body_part", "")) for c in conditions]
    evidence.append(side(meta["capture_plan"].get("wearing", "")))
    found = {s for s in evidence if s is not None}
    if len(found) != 1:
        raise ValueError("旧版动作侧别缺失或相互矛盾。")
    return found.pop()


def infer_regions(meta, raw, labels, conditions, mapping):
    """Contrast within-channel flexion/extension ratios, not cross-channel gain."""
    if len(meta["channel_ids"]) != 2:
        raise ValueError("自动区域推断目前要求恰好两个通道。")
    pairs = []
    for k, c in enumerate(conditions):
        mapped = mapping[c["id"]]
        if mapped["action"] != "wrist_flexion":
            continue
        strong = mapped["activation"].startswith("strong_")
        candidates = [
            j
            for j, d in enumerate(conditions)
            if mapping[d["id"]]["action"] == "wrist_extension"
            and mapping[d["id"]]["activation"].startswith("strong_") == strong
        ]
        if len(candidates) != 1:
            raise ValueError("无法匹配屈腕与伸腕条件。")
        pairs.append((k, candidates[0]))
    if not pairs:
        raise ValueError("需要屈腕与伸腕动作才能推断区域。")
    rate = meta["sampling_rate"]
    observations, robust = [], []
    condition_metrics = []
    for notch in (True, False):
        filtered = (
            SignalFilter(rate, 2, SignalConfig(**dict(meta["preprocessing"], notch=notch)))
            .process(raw)
            .astype(float)
        )
        for trim in ((0, 0), (0.5, 0.25), (1, 0.5)):
            rms, bins = {}, {}
            for cls in range(len(conditions)):
                rows, robust_rows = [], []
                for row in labels:
                    if row["class_id"] != cls:
                        continue
                    start = row["start_sample"] + round(trim[0] * rate)
                    end = row["end_sample"] - round(trim[1] * rate)
                    z = filtered[start:end]
                    block = round(0.1 * rate)
                    if len(z) < block:
                        raise ValueError("动作片段不足以推断通道区域。")
                    rows.append(np.sqrt(np.mean(z * z, axis=0)))
                    windows = z[: len(z) // block * block].reshape(-1, block, 2)
                    robust_rows.append(
                        np.median(np.sqrt(np.mean(windows * windows, axis=1)), axis=0)
                    )
                rms[cls], bins[cls] = np.array(rows), np.array(robust_rows)
                if notch and trim == (0.5, 0.25):
                    condition_metrics.append(
                        dict(
                            condition_id=conditions[cls]["id"],
                            **mapping[conditions[cls]["id"]],
                            median_rms=np.median(rows, axis=0).tolist(),
                            rms_by_round=rms[cls].tolist(),
                        )
                    )
            for flex, ext in pairs:
                if rms[flex].shape != rms[ext].shape or not rms[flex].size:
                    raise ValueError("屈腕与伸腕重复次数不一致。")
                ratio = np.log2(np.maximum(rms[flex], 1e-12) / np.maximum(rms[ext], 1e-12))
                observations.extend((ratio[:, 0] - ratio[:, 1]).tolist())
                if notch and trim == (0.5, 0.25):
                    ratio = np.log2(np.maximum(bins[flex], 1e-12) / np.maximum(bins[ext], 1e-12))
                    robust.extend((ratio[:, 0] - ratio[:, 1]).tolist())
    all_scores = np.array(observations + robust)
    # A conservative descriptive rule, not a calibrated anatomical probability.
    if not (np.all(all_scores > 1) or np.all(all_scores < -1)):
        raise ValueError("区域推断不一致或相对选择性不足；需要人工核查。")
    flex_column = 0 if all_scores[0] > 0 else 1
    positions = ["forearm_flexor" if i == flex_column else "forearm_extensor" for i in range(2)]
    evidence = dict(
        method="paired_movement_selectivity_v1",
        status="inferred_functional_region",
        flexor_channel=meta["channel_ids"][flex_column],
        extensor_channel=meta["channel_ids"][1 - flex_column],
        channel_order=meta["channel_ids"],
        trim_seconds=[[0, 0], [0.5, 0.25], [1, 0.5]],
        notch_settings=[True, False],
        sensitivity_comparisons=len(observations),
        robust_bin_comparisons=len(robust),
        all_comparisons_agree=True,
        minimum_relative_selectivity=float(2 ** np.min(np.abs(all_scores))),
        threshold_relative_selectivity=2,
        log2_channel0_minus_channel1=observations,
        robust_log2_channel0_minus_channel1=robust,
        condition_metrics=condition_metrics,
        limitation="Functional region inference conditional on action semantics; exact muscle and electrode geometry are unverified.",
    )
    return positions, evidence


def prepare_migration(source):
    """Read and validate one source; prepare deterministic bytes without writing."""
    source = Path(source)
    archive_bytes = source.read_bytes()
    source_hash = sha256(archive_bytes)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        if set(archive.namelist()) != set(MEMBERS) or len(archive.namelist()) != 3:
            raise ValueError("来源文件包成员不正确。")
        raw_bytes = archive.read("emg.bin")
    original, raw, labels = read_recording(source)
    if sha256(source.read_bytes()) != source_hash:
        raise ValueError("来源在读取期间发生改变。")
    if (
        original.get("task_type") != CUSTOM_CAPTURE
        or original.get("device") != "Cometa"
        or not original.get("complete")
    ):
        raise ValueError("仅迁移已完成的旧版 Cometa 自定义采集；测试或新版数据不在范围内。")
    conditions = selected_conditions(original["capture_plan"])
    mapping = {c["id"]: translate_condition(c) for c in conditions}
    subject = original["capture_plan"]["operator"].strip()
    side = infer_side(original, conditions)
    positions, evidence = infer_regions(original, raw, labels, conditions, mapping)
    channels = [
        dict(
            channel_id=ch,
            side=side,
            position=pos,
            position_source="inferred_functional_region",
            placement=dict(
                source="legacy_unknown", electrodes=None, diameter_mm=None, spacing_mm_range=None
            ),
        )
        for ch, pos in zip(original["channel_ids"], positions)
    ]
    settings = dict(
        version=VERSION,
        source_archive_sha256=source_hash,
        subject=subject,
        movement_side=side,
        positions=positions,
        condition_mapping=mapping,
    )
    settings_hash = sha256(json_bytes(settings))
    identity = uuid.uuid5(uuid.NAMESPACE_URL, f"emg-lab:legacy-migration:{settings_hash}").hex
    schedule = migrated_schedule(original, mapping)
    plan = validate_plan(
        dict(
            protocol=PROTOCOL,
            origin=ORIGIN,
            subject=subject,
            movement_side=side,
            channels=channels,
            selected_actions=[a for a in ACTIONS if a in {r["class_name"] for r in schedule}],
            repetitions=original["trial_count"],
            repetition_unit="legacy_condition_round",
            action_seconds=original["action_seconds"],
            interval_seconds=original["prepare_seconds"] + original["rest_seconds"],
            random_order=original["random_order"],
            instruction_version=None,
        ),
        original["channel_ids"],
    )
    rejected = {r["trial"]: r["reason"] for r in original.get("rejected_trials", [])}
    converted_labels = [
        {k: r[k] for k in LABEL_FIELDS} for r in schedule if r["end_sample"] <= original["samples"]
    ]
    sidecar = source.with_suffix(".index.csv")
    migration = dict(
        version=VERSION,
        origin=ORIGIN,
        source_filename=source.name,
        source_record_id=original["record_id"],
        source_archive_sha256=source_hash,
        source_emg_bin_sha256=sha256(raw_bytes),
        source_sidecar_sha256=sha256(sidecar.read_bytes()) if sidecar.exists() else None,
        source_metadata=deepcopy(original),
        source_labels=labels,
        condition_mapping=mapping,
        settings_sha256=settings_hash,
        region_inference=evidence,
        assumptions=dict(
            subject="legacy_operator_field",
            side="selected_conditions_and_wearing_note",
            action_semantics="inward_is_wrist_flexion_outward_is_wrist_extension",
            physical_electrode_geometry="unknown",
            original_instruction_version="unknown",
        ),
    )
    meta = {
        k: deepcopy(original[k])
        for k in (
            "device",
            "sampling_rate",
            "channel_ids",
            "unit",
            "preprocessing",
            "signal_type",
            "complete",
            "finalized",
            "samples",
            "duration",
            "created_at",
        )
    }
    meta.update(
        TASK.metadata,
        schema_version=SCHEMA_VERSION,
        capture_only=True,
        capture_plan=plan,
        subject=subject,
        name=subject,
        group=subject,
        batch_started_at=original["created_at"],
        record_id=identity,
        trial_count=len(schedule),
        actual_order=[r["class_id"] for r in schedule],
        order_seed=original.get("order_seed"),
        random_order=original["random_order"],
        schedule=schedule,
        rejected_trials=[
            dict(trial=r["trial"], reason=rejected[r["round_index"]])
            for r in schedule
            if r["round_index"] in rejected
        ],
        labels=len(converted_labels),
        completed_trials=len(converted_labels),
        usable_trials=sum(
            r["end_sample"] <= original["samples"] and r["round_index"] not in rejected
            for r in schedule
        ),
        migration=migration,
    )
    validate_recording(meta, converted_labels)
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=LABEL_FIELDS)
    writer.writeheader()
    writer.writerows(converted_labels)
    started = datetime.fromisoformat(original["created_at"])
    basename = f"{safe_name(subject)}_{started:%Y%m%d_%H%M%S_%f}.emg"
    return dict(
        source=source,
        relative_path=Path(safe_name(subject)) / "recordings" / basename,
        metadata=meta,
        payload={
            "emg.bin": raw_bytes,
            "labels.csv": text.getvalue().encode(),
            "meta.json": json_bytes(meta),
        },
    )


def check_destination(prepared, output_root):
    output = Path(output_root) / prepared["relative_path"]
    if output.exists():
        with zipfile.ZipFile(output) as archive:
            if set(archive.namelist()) != set(MEMBERS) or any(
                archive.read(k) != v for k, v in prepared["payload"].items()
            ):
                raise ValueError(f"目标已存在且内容冲突，未覆盖：{output}")
    return output


def publish_migration(prepared, output_root):
    output = check_destination(prepared, output_root)
    reused = output.exists()
    if not reused:
        output.parent.mkdir(parents=True, exist_ok=True)
        handle = output.open("xb")
        try:
            with handle, zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_STORED) as archive:
                for name, value in prepared["payload"].items():
                    archive.writestr(name, value)
            read_recording(output)
        except BaseException:
            output.unlink(missing_ok=True)
            raise
    else:
        read_recording(output)
    write_capture_index(output, prepared["metadata"])
    return output, reused
