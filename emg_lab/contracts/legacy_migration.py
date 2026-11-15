"""Validation of legacy-import provenance; native acquisition remains unchanged."""

import hashlib
import json
import uuid

from .acquisition import CUSTOM_CAPTURE, selected_conditions, validate_recording_annotations
from .forearm import ACTIONS

ORIGIN = "legacy_custom_v1"
ACTIVATIONS = (
    "natural_rest",
    "ordinary",
    "unspecified",
    "strong_fist_activation",
    "strong_hand_extension_activation",
)
LABEL_FIELDS = ("trial", "start_sample", "end_sample", "class_id", "class_name")


def migrated_schedule(source, mapping):
    conditions = selected_conditions(source["capture_plan"])
    if set(mapping) != {c["id"] for c in conditions}:
        raise ValueError("迁移条件映射不完整。")
    for item in mapping.values():
        if item.get("action") not in ACTIONS or item.get("activation") not in ACTIVATIONS:
            raise ValueError("迁移动作或激活条件无效。")
    rate = source["sampling_rate"]
    prepare, action, rest = [
        round(source[k] * rate) for k in ("prepare_seconds", "action_seconds", "rest_seconds")
    ]
    result = []
    for i, cls in enumerate(source["actual_order"]):
        condition = conditions[cls]
        mapped = mapping[condition["id"]]
        start = i * (prepare + action + rest) + prepare
        result.append(
            dict(
                trial=i + 1,
                round_index=i // len(conditions) + 1,
                start_sample=start,
                end_sample=start + action,
                class_id=ACTIONS.index(mapped["action"]),
                class_name=mapped["action"],
                source_condition_id=condition["id"],
                activation_condition=mapped["activation"],
            )
        )
    return result


def validate_import(meta, labels):
    migration = meta.get("migration", {})
    if migration.get("version") != 1 or migration.get("origin") != ORIGIN:
        raise ValueError("迁移来源版本无效。")
    source = migration["source_metadata"]
    if source.get("task_type") != CUSTOM_CAPTURE or source.get("capture_only") is not True:
        raise ValueError("迁移来源不是旧版自定义采集。")
    from .tasks import task_from_metadata

    task_from_metadata(source)
    source_labels = migration["source_labels"]
    validate_recording_annotations(source, source_labels)
    for row in source_labels:
        if row["class_name"] != source["classes"][row["class_id"]]:
            raise ValueError("迁移来源标签编号不一致。")
    for key in (
        "sampling_rate",
        "channel_ids",
        "device",
        "unit",
        "samples",
        "created_at",
        "duration",
        "complete",
        "finalized",
        "preprocessing",
        "signal_type",
    ):
        if meta.get(key) != source.get(key):
            raise ValueError(f"迁移改变了来源字段：{key}。")
    for key in ("source_archive_sha256", "source_emg_bin_sha256", "settings_sha256"):
        digest = migration.get(key)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("迁移缺少有效来源哈希。")
    p = meta["capture_plan"]
    settings = dict(
        version=1,
        source_archive_sha256=migration["source_archive_sha256"],
        subject=p["subject"],
        movement_side=p["movement_side"],
        positions=[c["position"] for c in p["channels"]],
        condition_mapping=migration["condition_mapping"],
    )
    digest = hashlib.sha256(
        json.dumps(settings, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode(
            "utf-8"
        )
    ).hexdigest()
    expected_id = uuid.uuid5(uuid.NAMESPACE_URL, f"emg-lab:legacy-migration:{digest}").hex
    if (
        migration["settings_sha256"] != digest
        or meta.get("record_id") != expected_id
        or migration.get("source_record_id") != source.get("record_id")
        or any(meta.get(k) != p["subject"] for k in ("subject", "name", "group"))
        or any(c["side"] != p["movement_side"] for c in p["channels"])
    ):
        raise ValueError("迁移身份或区域映射与来源配置不一致。")

    expected = migrated_schedule(source, migration["condition_mapping"])
    selected = [a for a in ACTIONS if a in {r["class_name"] for r in expected}]
    if (
        p["selected_actions"] != selected
        or p["repetitions"] != source["trial_count"]
        or p.get("repetition_unit") != "legacy_condition_round"
        or p["random_order"] != source["random_order"]
        or p["action_seconds"] != source["action_seconds"]
        or p["interval_seconds"] != source["prepare_seconds"] + source["rest_seconds"]
        or meta.get("order_seed") != source.get("order_seed")
        or meta.get("random_order") != source["random_order"]
        or meta.get("batch_started_at") != source["created_at"]
    ):
        raise ValueError("迁移方案与来源不一致。")
    if (
        meta.get("schedule") != expected
        or meta.get("actual_order") != [r["class_id"] for r in expected]
        or meta.get("trial_count") != len(expected)
    ):
        raise ValueError("迁移时序与来源不一致。")
    complete = [r for r in expected if r["end_sample"] <= source["samples"]]
    if [{k: r[k] for k in LABEL_FIELDS} for r in complete] != labels:
        raise ValueError("迁移标签与来源时序不一致。")
    rejected = {r["trial"]: r["reason"] for r in source.get("rejected_trials", [])}
    expected_rejected = [
        dict(trial=r["trial"], reason=rejected[r["round_index"]])
        for r in expected
        if r["round_index"] in rejected
    ]
    if meta.get("rejected_trials") != expected_rejected:
        raise ValueError("迁移未保留原始无效标记。")
    if meta.get("completed_trials") != len(complete) or meta.get("usable_trials") != sum(
        r["round_index"] not in rejected for r in complete
    ):
        raise ValueError("迁移动作计数无效。")
