"""Synthetic protocol checks; never connect a physical device or robot."""

import csv
import re
from copy import deepcopy

import numpy as np
import pytest

from emg_lab.backend.data.forearm import ForearmCaptureRun
from emg_lab.backend.data.storage import read_recording
from emg_lab.contracts.forearm import ACTIONS, PROTOCOL, TASK, default_placement


def plan_for(profile, **overrides):
    return dict(
        protocol=PROTOCOL,
        subject="受试者01",
        movement_side="both",
        channels=[
            dict(
                channel_id=c,
                side="left" if i % 2 else "right",
                position="forearm_flexor" if i % 2 else "forearm_extensor",
                placement=default_placement(),
            )
            for i, c in enumerate(profile["channel_ids"])
        ],
        selected_actions=list(ACTIONS),
        repetitions=2,
        action_seconds=1.1,
        interval_seconds=2.4,
        random_order=False,
        **overrides,
    )


@pytest.mark.parametrize("ids", [[8], [1, 3], list(range(1, 17))])
def test_roundtrip_variable_channels_and_individual_trials(tmp_path, profile, ids):
    profile = dict(profile, channel_ids=ids)
    p = plan_for(profile)
    run = ForearmCaptureRun(tmp_path, profile, p)
    expected = (
        np.random.default_rng(9).normal(size=(run.session_length, len(ids))).astype("float32")
    )
    for block in np.array_split(expected, 31):
        run.feed(block)
    meta, raw, labels = read_recording(run.run_path)
    np.testing.assert_array_equal(raw, expected)
    assert meta["completed_trials"] == meta["usable_trials"] == 8
    assert meta["capture_plan"]["channels"] == p["channels"]
    assert [r["trial"] for r in labels] == list(range(1, 9))
    assert [r["class_name"] for r in labels] == list(ACTIONS) * 2
    assert labels[0]["start_sample"] == 3000
    assert labels[1]["start_sample"] - labels[0]["end_sample"] == 2400
    assert labels[-1]["end_sample"] == len(raw)
    assert re.fullmatch(r"受试者01_\d{8}_\d{6}_\d{6}\.emg", run.run_path.name)
    assert meta["created_at"] == meta["batch_started_at"]
    from emg_lab.backend.data import catalog, transfer

    assert "CH " in catalog.describe(catalog.catalogue(tmp_path)[0])
    (tmp_path / "export").mkdir()
    exported = transfer.export_recording(run.run_path, tmp_path / "export", TASK)
    imported = transfer.import_recording(exported, tmp_path / "restored", TASK)
    assert read_recording(imported.path)[0]["record_id"] == meta["record_id"]


@pytest.mark.parametrize("gap", [0, 1.2, 3, 10])
def test_gap_countdown_and_no_trailing_gap(tmp_path, profile, gap):
    p = plan_for(profile)
    p.update(selected_actions=["rest"], repetitions=2, action_seconds=1, interval_seconds=gap)
    run = ForearmCaptureRun(tmp_path, profile, p)
    assert run.session_length == round((3 + 2 + gap) * 1000)
    run.feed(np.zeros((3000, 4), "float32"))
    assert run.status()["phase"] == "动作"
    run.feed(np.zeros((1000, 4), "float32"))
    assert run.status()["trial"] == 2
    assert run.status()["phase"] == ("动作" if gap == 0 else "准备" if gap <= 3 else "休息")
    if gap > 3:
        run.feed(np.zeros((round((gap - 3) * 1000), 4), "float32"))
        assert run.status()["phase"] == "准备" and run.status()["remaining"] == 3
    run.feed(np.zeros((run.session_length, 4), "float32"))
    assert read_recording(run.run_path)[0]["completed_trials"] == 2


def test_partial_trial_rejection_and_index(tmp_path, profile):
    p = plan_for(profile)
    run = ForearmCaptureRun(tmp_path, profile, p)
    run.feed(np.zeros((run.schedule[1]["start_sample"] + 100, 4), "float32"))
    run.reject_trial(1, "动作错误")
    run.stop()
    meta, raw, labels = read_recording(run.run_path)
    assert len(labels) == 1 and meta["completed_trials"] == 1 and meta["usable_trials"] == 0
    with run.run_path.with_suffix(".index.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2 and rows[0]["valid"] == "False"
    assert rows[1]["complete_segment"] == "False"
    assert int(rows[1]["end_sample"]) == len(raw)


def test_random_subset_preserves_codes_and_plan_snapshot(tmp_path, profile):
    p = plan_for(profile)
    p.update(selected_actions=["wrist_extension", "fist"], random_order=True)
    run = ForearmCaptureRun(tmp_path, profile, p)
    p["channels"][0]["side"] = "left"
    run.feed(np.zeros((run.session_length, 4), "float32"))
    meta, _, labels = read_recording(run.run_path)
    assert meta["capture_plan"]["channels"][0]["side"] == "right"
    assert meta["order_seed"] is not None
    assert all(sorted(meta["actual_order"][i : i + 2]) == [1, 3] for i in (0, 2))
    assert {r["class_name"] for r in labels} == {"fist", "wrist_extension"}
    from emg_lab.backend.learning.dataset import prepare_dataset

    with pytest.raises(ValueError, match="尚未配置"):
        prepare_dataset([run.run_path])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(subject=" "),
        lambda p: p.update(selected_actions=[]),
        lambda p: p.update(interval_seconds=float("nan")),
        lambda p: p.update(action_seconds=0),
        lambda p: p.update(movement_side="unknown"),
        lambda p: p["channels"].reverse(),
        lambda p: p["channels"][0].update(side=None),
        lambda p: p["channels"][0]["placement"].update(electrodes=[[2, 0], [0, 0]]),
    ],
)
def test_invalid_plan_does_not_create_files(tmp_path, profile, mutation):
    p = plan_for(profile)
    mutation(p)
    with pytest.raises(ValueError):
        ForearmCaptureRun(tmp_path, profile, p)
    assert not list(tmp_path.iterdir())


def test_windows_subject_safety_and_tampered_schedule(tmp_path, profile):
    p = plan_for(profile)
    p["subject"] = "CON"
    run = ForearmCaptureRun(tmp_path, profile, p)
    assert run.run_path.name.startswith("_CON_")
    run.stop()
    from emg_lab.contracts.forearm import validate_recording

    meta = deepcopy(run.writer.meta)
    meta["schedule"][0]["start_sample"] += 1
    with pytest.raises(ValueError):
        validate_recording(meta, [])


@pytest.fixture
def window(tmp_path, profile):
    from PySide6 import QtWidgets as W

    from emg_lab.backend.application import ApplicationService
    from emg_lab.frontend.window import MainWindow, configure_app

    app = W.QApplication.instance() or W.QApplication([])
    configure_app(app)
    service = ApplicationService(tmp_path, local_root=tmp_path / "logs", background=False)
    service.set_profile(profile)
    service._device_ready = True
    service.feed(np.zeros((1000, 4), "float32"))
    w = MainWindow(tmp_path, backend=service)
    w.timer.stop()
    w.select_task("robot")
    w.tabs.setCurrentIndex(1)
    w.group.setText("P01")
    editor = w.forearm_capture
    editor.sync_channels()
    for row in range(4):
        editor.channels.cellWidget(row, 1).setCurrentIndex(1 + row % 2)
        editor.channels.cellWidget(row, 2).setCurrentIndex(1 + row % 2)
    w.show()
    app.processEvents()
    yield w
    w.close()
    app.processEvents()


def test_ui_single_workflow_locks_and_finishes_without_scene(window, monkeypatch):
    from PySide6 import QtWidgets as W

    w = window
    monkeypatch.setattr(w.scene, "start", lambda *args: pytest.fail("Physical/3D output started"))
    assert not w.task_choice.isVisibleTo(
        w.page_scrolls["02  采集数据"].widget()
    ) and not w.experiment.isVisibleTo(w.page_scrolls["02  采集数据"].widget())
    assert w.forearm_capture.plan()["channels"][1]["side"] == "right"
    w.trial_count.setValue(1)
    w.action_seconds.setValue(1)
    w.forearm_capture.interval.setValue(0)
    assert "7 秒" in w.capture_plan.text()
    w.start_capture()
    assert not w.forearm_capture.isEnabled() and not w.group.isEnabled()
    w.backend.feed(np.zeros((3000, 4), "float32"))
    w.tick()
    assert "静息" in w.cue.text()
    w.backend.feed(np.zeros((4000, 4), "float32"))
    w.backend.poll()
    W.QApplication.processEvents()
    assert w.backend.capture is None and w.forearm_capture.isEnabled()
    w.library.refresh()
    assert any(e.meta.get("task_type") == PROTOCOL for e in w.library.entries)


def test_channel_change_without_figure_cues(window):
    e = window.forearm_capture
    assert not any(hasattr(e, name) for name in ("diagram", "guide", "preview"))
    window.backend.set_profile(dict(window.backend.profile, channel_ids=[4, 8]))
    e.sync_channels()
    assert [c["channel_id"] for c in e.values] == [4, 8]
    with pytest.raises(ValueError):
        e.plan()  # New channel 8 must be assigned explicitly.
    window.resize(950, 650)
    window.grab()  # Exercise layout at the supported small window size.


def test_frozen_v1_action_contract():
    # Golden public labels: changing these values requires a new protocol version.
    from emg_lab.contracts.forearm import ACTIONS, PROTOCOL, SCHEMA_VERSION

    assert SCHEMA_VERSION == 3
    assert PROTOCOL == "EMG_FOREARM_CAPTURE_V1"
    assert ACTIONS == ("rest", "fist", "wrist_flexion", "wrist_extension")


@pytest.mark.parametrize("version", [None, 2, 4, "3", True])
def test_unknown_forearm_schema_is_not_silently_parsed(tmp_path, profile, version):
    from emg_lab.contracts.forearm import validate_recording

    run = ForearmCaptureRun(tmp_path, profile, plan_for(profile))
    run.stop()
    meta = dict(run.writer.meta, schema_version=version)
    with pytest.raises(ValueError, match="格式版本"):
        validate_recording(meta, [])
