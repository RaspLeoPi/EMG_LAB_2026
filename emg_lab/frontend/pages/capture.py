"""CapturePage: desktop presentation and application-port calls."""

from __future__ import annotations

from emg_lab.frontend.components import (
    ACTION_SECONDS,
    PREPARE_SECONDS,
    REST_SECONDS,
    QtCore,
    W,
    WaveformPreview,
    button,
    card,
    details,
    fields,
    label,
    row,
    safe_name,
    text_label,
)


class CapturePage:
    def make_capture_page(self):
        layout = self.page(
            "02  采集数据",
            "跟随提示，采集动作数据",
            "填写本次数据的名称与组别，再按屏幕提示完成动作。结束后自动保存。",
        )
        self.capture_settings, settings = card("采集设置")
        layout.addWidget(self.capture_settings)
        self.task_choice = W.QComboBox()
        self.sync_capture_choices(self.task)
        self.task_choice.currentIndexChanged.connect(
            lambda: self.guard(lambda: self.choose_task(self.task_choice))
        )
        self.preset_task_field = fields(("任务方案", self.task_choice))
        settings.addLayout(self.preset_task_field)
        self.group = W.QLineEdit("G01")
        self.group.setMaxLength(40)
        self.experiment = W.QLineEdit("方向控制练习")
        self.experiment.setMaxLength(60)
        self.subject_fields = fields(("受试者名称", self.group))
        settings.addLayout(self.subject_fields)
        self.experiment_fields = fields(("数据名称", self.experiment))
        settings.addLayout(self.experiment_fields)
        self.group.clear()
        self.group.setMaxLength(64)
        self.group.textChanged.connect(self.name_preview)
        self.experiment.textChanged.connect(self.name_preview)
        self.trial_count = W.QSpinBox()
        self.trial_count.setRange(1, 9999)
        self.trial_count.setValue(5)
        self.trial_count.setSuffix(" 组")
        self.action_seconds = W.QDoubleSpinBox()
        self.action_seconds.setRange(1, 10)
        self.action_seconds.setValue(ACTION_SECONDS)
        self.action_seconds.setSuffix(" 秒")
        self.scene_check = W.QCheckBox("独立窗口显示机器人示范")
        self.scene_check.setChecked(True)
        self.scene_check.toggled.connect(self.update_hand_views)
        controls = fields(("动作组数", self.trial_count), ("每个动作持续", self.action_seconds))
        controls.addWidget(self.scene_check, 1, QtCore.Qt.AlignBottom)
        settings.addLayout(controls)
        self.random_order = W.QCheckBox("随机动作顺序")
        self.random_order.setToolTip("每组仍包含全部类别。先按固定顺序熟悉动作，再勾选随机采集。")
        settings.addWidget(self.random_order)
        self.collection_notes_button = button(
            "采集记录…", lambda: self.guard(self.edit_collection_notes)
        )
        self.legacy_notes_panel = W.QWidget()
        legacy_notes_layout = row(
            self.collection_notes_button,
            text_label("选填操作者、通道位置与动作约定；同一佩戴可沿用，随数据一起带走。"),
            1,
        )
        self.legacy_notes_panel.setLayout(legacy_notes_layout)
        settings.addWidget(self.legacy_notes_panel)
        from emg_lab.frontend.forearm_capture import ForearmCaptureEditor

        self.forearm_capture = ForearmCaptureEditor(self)
        self.forearm_capture.changed.connect(self.update_capture_plan)
        settings.addWidget(self.forearm_capture)
        self.forearm_capture.setVisible(False)
        self.capture_plan = text_label("")
        settings.addWidget(self.capture_plan)
        self.trial_count.valueChanged.connect(self.update_capture_plan)
        self.action_seconds.valueChanged.connect(self.update_capture_plan)
        self.group.textChanged.connect(self.update_capture_plan)
        self.path_preview = text_label("")
        self.path_preview.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        storage_info, storage_body = details("保存位置与命名规则")
        storage_body.addWidget(self.path_preview)
        storage_body.addWidget(
            button("打开数据目录", lambda: self.open_folder(self.backend.root)),
            0,
            QtCore.Qt.AlignLeft,
        )
        settings.addWidget(storage_info)
        self.cue = label("准备就绪后，开始采集")
        self.cue.setObjectName("cueBanner")
        self.cue.setAlignment(QtCore.Qt.AlignCenter)
        self.cue.setMinimumHeight(44)
        layout.addWidget(self.cue)
        self.capture_progress = W.QProgressBar()
        self.capture_progress.setRange(0, 1000)
        self.capture_progress.setValue(0)
        self.capture_progress.setFixedWidth(170)
        self.capture_status = text_label("准备时放松；动作提示出现后，完成助教约定的肌肉动作。")
        self.reject_trial_button = button(
            "标记本组无效", lambda: self.guard(self.reject_current_trial)
        )
        self.reject_trial_button.setToolTip(
            "保留原始信号；训练和基础评估跳过这一组。结束后另采一组补足。"
        )
        layout.addLayout(row(self.capture_status, self.capture_progress, self.reject_trial_button))
        panel, body = card("采集波形")
        self.capture_waveform = WaveformPreview(compact=True)
        body.addWidget(self.capture_waveform)
        self.capture_health = text_label("连接后先观察波形，再开始采集。")
        body.addWidget(self.capture_health)
        layout.addWidget(panel, 1)
        self.capture_start = button("开始采集并保存", lambda: self.guard(self.start_capture), True)
        self.capture_stop = button("提前结束并保存", self.stop_capture)
        self.capture_next = button("下一步：训练模型 →", self.capture_next_step)
        self.page_actions["02  采集数据"].addLayout(
            row(
                self.capture_start,
                self.capture_stop,
                1,
                self.capture_next,
            )
        )
        self.name_preview()
        self.update_capture_plan()

    def capture_next_step(self):
        if self.forearm_capture_active():
            self.open_library("recording")
        else:
            self.refresh_data()
            self.tabs.setCurrentIndex(2)

    def forearm_capture_active(self):
        return self.task.key == "robot"

    def update_capture_mode(self):
        if not hasattr(self, "forearm_capture"):
            return
        custom = self.forearm_capture_active()
        for index in range(self.experiment_fields.count()):
            widget = self.experiment_fields.itemAt(index).widget()
            if widget:
                widget.setVisible(not custom)
        self.subject_fields.itemAt(0).widget().findChild(W.QLabel).setText(
            "受试者名称" if custom else "组别 / 学号"
        )
        self.trial_count.setSuffix(" 次 / 动作" if custom else " 组")
        self.action_seconds.setMaximum(120 if custom else 10)
        self.reject_trial_button.setText("标记本次动作无效" if custom else "标记本组无效")
        self.reject_trial_button.setToolTip(
            "保留原始信号，标记当前动作。" if custom else "标记当前整组动作。"
        )
        self.page_hints["02  采集数据"].setText(
            "填写受试者与通道位置，选择动作并跟随提示。静息动作与动作间隔分别记录。"
            if custom
            else "跟随提示完成当前任务动作。"
        )
        self.forearm_capture.setVisible(custom)
        self.page_titles["02  采集数据"].setText(
            "前臂肌电采集" if custom else "跟随提示，采集动作数据"
        )
        self.capture_next.setText("查看采集数据 →" if custom else "下一步：训练模型 →")
        self.scene_check.setVisible(not custom)
        self.legacy_notes_panel.setVisible(not custom)
        self.task_choice.setEnabled(not custom)
        self.task_choice.setVisible(not custom)
        for index in range(self.preset_task_field.count()):
            widget = self.preset_task_field.itemAt(index).widget()
            if widget:
                widget.setVisible(not custom)
        if custom and self.backend.profile:
            self.forearm_capture.sync_channels()
        self.name_preview()
        self.update_capture_plan()
        self.update_controls()

    def update_capture_plan(self):
        count = self.trial_count.value()
        if not hasattr(self, "capture_plan"):
            return
        actions = (
            len(self.forearm_capture.selected_ids())
            if self.forearm_capture_active()
            else len(self.task.classes)
        )
        if self.forearm_capture_active():
            n = count * actions
            seconds = round(
                3
                + n * self.action_seconds.value()
                + max(0, n - 1) * self.forearm_capture.interval.value()
            )
            self.capture_plan.setText(
                f"本批 {count} 轮、{n} 次动作，预计 {seconds:g} 秒。初始准备 3 秒；间隔包含倒计时；末次动作后结束。"
            )
            return
        seconds = round(
            count * actions * (self.action_seconds.value() + PREPARE_SECONDS + REST_SECONDS)
        )
        self.capture_plan.setText(f"本次 {count} 组、{count * actions} 个动作，预计 {seconds} 秒。")

    def name_preview(self):
        if self.forearm_capture_active():
            self.path_preview.setText(
                "保存为：<受试者>_<批次开始时间（含微秒）>.emg，另附同名 .index.csv。"
            )
            return
        try:
            group, title = safe_name(self.group.text()), safe_name(self.experiment.text())
            self.path_preview.setText(
                f"将保存为一份“{title}”数据，归入 {group}。时间和文件编号自动添加。"
                + (
                    " 自定义采集同时生成同名 .index.csv；动作名称与备注保存在原始文件内。"
                    if self.forearm_capture_active()
                    else ""
                )
            )
        except ValueError as exc:
            self.path_preview.setText(str(exc))
