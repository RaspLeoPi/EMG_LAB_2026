"""Versioned forearm acquisition protocol, independent of hardware and Qt."""

import math
from copy import deepcopy

from .artifacts import safe_name
from .tasks import Task

SCHEMA_VERSION = 3
PROTOCOL = "EMG_FOREARM_CAPTURE_V1"
ACTIONS = ("rest", "fist", "wrist_flexion", "wrist_extension")
NAMES = ("静息", "握拳", "屈腕", "伸腕")
SIDES = {"left": "左", "right": "右"}
POSITIONS = {
    "forearm_flexor": "前臂屈肌区（FCR 附近）",
    "forearm_extensor": "前臂伸肌区（ED 附近）",
}
TASK = Task("robot", PROTOCOL, "前臂肌电采集", ACTIONS, NAMES, (0, 1, 2, 3))


def default_placement():
    return dict(
        diagram_version=1,
        source="schematic_default",
        electrodes=[[0.5, 0.15], [0.5, 0.45]],
        diameter_mm=7,
        spacing_mm_range=[80, 100],
    )


def validate_plan(value, channel_ids=None):
    if not isinstance(value, dict) or value.get("protocol") != PROTOCOL:
        raise ValueError("前臂采集方案版本不正确。")
    p = deepcopy(value)
    if p.get("origin") not in (None, "legacy_custom_v1"):
        raise ValueError("采集来源无效。")
    subject = p.get("subject")
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 64:
        raise ValueError("请填写受试者名称（1–64 字符）。")
    safe_name(subject)
    p["subject"] = subject.strip()
    if p.get("movement_side") not in (*SIDES, "both"):
        raise ValueError("请选择本批动作侧别。")
    selected = p.get("selected_actions")
    if (
        not isinstance(selected, list)
        or not selected
        or any(a not in ACTIONS for a in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ValueError("请至少选择一个不重复的标准动作。")
    p["selected_actions"] = [a for a in ACTIONS if a in selected]
    if type(p.get("repetitions")) is not int or not 1 <= p["repetitions"] <= 9999:
        raise ValueError("重复次数应为 1–9999。")
    for key, low, high in (("action_seconds", 1, 120), ("interval_seconds", 0, 300)):
        v = p.get(key)
        if type(v) not in (int, float) or not math.isfinite(v) or not low <= v <= high:
            raise ValueError("动作时长或间隔无效。")
    if type(p.get("random_order")) is not bool:
        raise ValueError("随机顺序设置无效。")
    channels = p.get("channels")
    if (
        not isinstance(channels, list)
        or not channels
        or any(not isinstance(c, dict) for c in channels)
    ):
        raise ValueError("请配置每个实际通道的位置。")
    ids = [c.get("channel_id") for c in channels]
    if (
        any(type(i) is not int or i < 1 for i in ids)
        or len(set(ids)) != len(ids)
        or (channel_ids is not None and ids != list(channel_ids))
    ):
        raise ValueError("方案通道与当前设备不一致。")
    for c in channels:
        if c.get("side") not in SIDES or c.get("position") not in POSITIONS:
            raise ValueError("每个通道都需要选择侧别和位置。")
        g = c.get("placement", {})
        if g.get("source") == "legacy_unknown":
            if p.get("origin") != "legacy_custom_v1" or any(
                g.get(k) is not None for k in ("electrodes", "diameter_mm", "spacing_mm_range")
            ):
                raise ValueError("仅旧版迁移可使用未知电极位置。")
            continue
        points = g.get("electrodes")
        if g.get("diagram_version") != 1 or g.get("source") not in (
            "schematic_default",
            "operator_adjusted",
        ):
            raise ValueError("电极示意图版本或来源无效。")
        if (
            not isinstance(points, list)
            or len(points) != 2
            or any(
                not isinstance(pt, list)
                or len(pt) != 2
                or any(
                    type(x) not in (float, int) or not math.isfinite(x) or not 0 <= x <= 1
                    for x in pt
                )
                for pt in points
            )
        ):
            raise ValueError("电极坐标应为两个归一化位置。")
        spacing = g.get("spacing_mm_range")
        if (
            not isinstance(spacing, list)
            or len(spacing) != 2
            or any(type(x) not in (int, float) or not math.isfinite(x) or x <= 0 for x in spacing)
            or spacing[0] > spacing[1]
        ):
            raise ValueError("电极中心间距范围无效。")
        d = g.get("diameter_mm")
        if type(d) not in (int, float) or not math.isfinite(d) or d <= 0:
            raise ValueError("电极直径无效。")
    imported = p.get("origin") == "legacy_custom_v1"
    instruction_version = None if imported else 1
    if p.get("instruction_version", instruction_version) != instruction_version:
        raise ValueError("动作指引版本不支持。")
    p["instruction_version"] = instruction_version
    return p


def schedule(plan, rate, order):
    """Sample clock, end exclusive; recovery is never an action label."""
    initial, action, gap = (
        round(3 * rate),
        round(plan["action_seconds"] * rate),
        round(plan["interval_seconds"] * rate),
    )
    count = len(plan["selected_actions"])
    return [
        dict(
            trial=i + 1,
            round_index=i // count + 1,
            class_id=int(cls),
            class_name=ACTIONS[int(cls)],
            start_sample=initial + i * (action + gap),
            end_sample=initial + i * (action + gap) + action,
        )
        for i, cls in enumerate(order)
    ]


def validate_recording(meta, labels):
    if type(meta.get("schema_version")) is not int or meta["schema_version"] != SCHEMA_VERSION:
        raise ValueError("前臂数据格式版本不支持，请使用匹配版本的读取器。")
    p = validate_plan(meta["capture_plan"], meta["channel_ids"])
    rate = meta["sampling_rate"]
    if type(rate) not in (int, float) or not math.isfinite(rate) or rate <= 0:
        raise ValueError("采样率无效。")
    if p.get("origin") == "legacy_custom_v1":
        from .legacy_migration import validate_import

        validate_import(meta, labels)
        return
    if "migration" in meta:
        raise ValueError("迁移来源标记与采集方案不一致。")
    selected = [ACTIONS.index(a) for a in p["selected_actions"]]
    order = meta["actual_order"]
    n = len(selected)
    if (
        not isinstance(order, list)
        or len(order) != n * p["repetitions"]
        or any(type(c) is not int for c in order)
        or any(sorted(order[i : i + n]) != selected for i in range(0, len(order), n))
    ):
        raise ValueError("动作顺序与采集方案不一致。")
    if not p["random_order"] and order != selected * p["repetitions"]:
        raise ValueError("固定动作顺序与方案不一致。")
    if round(p["action_seconds"] * rate) < 1:
        raise ValueError("动作时长不足一个采样点。")
    expected = schedule(p, rate, order)
    if meta.get("schedule") != expected or meta.get("trial_count") != len(expected):
        raise ValueError("采集时序与方案不一致。")
    fields = ("trial", "start_sample", "end_sample", "class_id", "class_name")
    if [
        {k: r[k] for k in fields} for r in expected if r["end_sample"] <= meta["samples"]
    ] != labels:
        raise ValueError("动作标签与采集时序不一致。")
