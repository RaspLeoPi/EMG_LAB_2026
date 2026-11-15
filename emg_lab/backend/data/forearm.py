"""Sample-clock acquisition with individual trials and explicit recovery gaps."""

from datetime import datetime

import numpy as np

from emg_lab.contracts.forearm import ACTIONS, NAMES, SCHEMA_VERSION, TASK, schedule, validate_plan

from .capture import CaptureRun
from .storage import RecordingWriter, safe_name


class ForearmCaptureRun(CaptureRun):
    def __init__(self, root, profile, plan, config=None):
        from pathlib import Path

        plan = validate_plan(plan, profile["channel_ids"])
        if plan.get("origin") is not None:
            raise ValueError("旧版迁移方案不能用于启动新采集。")
        self.task, self.capture_plan = TASK, plan
        self.completed = self.stopped = False
        self.rejected_trials = {}
        self.received = 0
        self.rate = float(profile["sampling_rate"])
        if not np.isfinite(self.rate) or self.rate <= 0:
            raise ValueError("采样率无效。")
        selected = [ACTIONS.index(a) for a in plan["selected_actions"]]
        seed = int(np.random.SeedSequence().entropy) if plan["random_order"] else None
        rng = np.random.default_rng(seed)
        order = [
            int(c)
            for _ in range(plan["repetitions"])
            for c in (rng.permutation(selected) if plan["random_order"] else selected)
        ]
        self.schedule = schedule(plan, self.rate, order)
        self.trial_count = len(order)
        self.session_length = self.schedule[-1]["end_sample"]
        started = datetime.now().astimezone()
        subject = plan["subject"]
        folder = (
            Path(root)
            / safe_name(subject)
            / "recordings"
            / f"{safe_name(subject)}_{started:%Y%m%d_%H%M%S_%f}"
        )
        # Reserve the final name exclusively as well as the staging directory.
        output = Path(str(folder) + ".emg")
        if output.exists():
            raise FileExistsError("该采集文件已存在。")
        from emg_lab.signal import SignalConfig

        folder.mkdir(parents=True, exist_ok=False)
        metadata = dict(
            profile,
            preprocessing=(config or SignalConfig()).to_dict(),
            **TASK.metadata,
            schema_version=SCHEMA_VERSION,
            capture_only=True,
            capture_plan=plan,
            subject=subject,
            name=subject,
            group=subject,
            batch_started_at=started.isoformat(),
            trial_count=len(order),
            actual_order=order,
            order_seed=seed,
            random_order=plan["random_order"],
            schedule=self.schedule,
            rejected_trials=[],
        )
        labels = [
            {k: r[k] for k in ("trial", "start_sample", "end_sample", "class_id", "class_name")}
            for r in self.schedule
        ]
        self.writer = RecordingWriter(folder, metadata, labels, bundle=True)
        self.run_path = self.writer.output_path

    def status(self):
        if self.completed or self.stopped:
            return dict(
                done=True,
                command=0,
                phase="完成" if self.completed else "已结束",
                progress=self.received / self.session_length,
                capture_only=True,
            )
        count = self.writer.count
        i = next(
            (i for i, r in enumerate(self.schedule) if count < r["end_sample"]),
            len(self.schedule) - 1,
        )
        r = self.schedule[i]
        remaining_gap = (r["start_sample"] - count) / self.rate
        phase = "动作" if count >= r["start_sample"] else "准备" if remaining_gap <= 3 else "休息"
        remaining = (r["end_sample"] - count) / self.rate if phase == "动作" else remaining_gap
        return dict(
            done=False,
            command=0,
            cue=r["class_id"],
            cue_name=NAMES[r["class_id"]],
            cue_details=(
                "自然放松，手腕中立"
                if r["class_id"] == 0
                else "握拳后保持；非动作侧放松"
                if r["class_id"] == 1
                else "手指放松，屈伸腕一次后保持；非动作侧放松"
            ),
            phase=phase,
            remaining=remaining,
            progress=count / self.session_length,
            trial=r["trial"],
            trial_count=self.trial_count,
            action_index=1,
            action_count=1,
            round_index=r["round_index"],
            rejected=r["trial"] in self.rejected_trials,
            capture_only=True,
            protocol_capture=True,
            movement_side=self.capture_plan["movement_side"],
        )

    def reject_trial(self, trial, reason):
        if (
            self.completed
            or self.stopped
            or trial
            not in [r["trial"] for r in self.schedule if r["start_sample"] <= self.writer.count]
        ):
            raise ValueError("只能标记已开始的单次动作。")
        self.rejected_trials[trial] = str(reason).strip()[:200] or "人工标记"
        self.writer.meta["rejected_trials"] = [
            dict(trial=t, reason=r) for t, r in sorted(self.rejected_trials.items())
        ]
