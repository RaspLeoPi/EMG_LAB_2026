"""Text-based forearm protocol editor with explicit channel placement options."""

from copy import deepcopy

from PySide6 import QtCore as C
from PySide6 import QtWidgets as W

from emg_lab.contracts.forearm import (
    ACTIONS,
    NAMES,
    POSITIONS,
    PROTOCOL,
    SIDES,
    default_placement,
    validate_plan,
)


class ForearmCaptureEditor(W.QWidget):
    changed = C.Signal()

    def __init__(self, host):
        super().__init__(host)
        self.host, self.values = host, []
        layout = W.QVBoxLayout(self)
        form = W.QFormLayout()
        self.movement_side = W.QComboBox()
        for text, code in [("左侧", "left"), ("右侧", "right"), ("双侧", "both")]:
            self.movement_side.addItem(text, code)
        self.movement_side.setCurrentIndex(1)
        self.interval = W.QDoubleSpinBox()
        self.interval.setRange(0, 300)
        self.interval.setValue(10)
        self.interval.setSuffix(" 秒（含倒计时）")
        form.addRow("本批动作侧别", self.movement_side)
        form.addRow("动作间隔", self.interval)
        layout.addLayout(form)
        actions = W.QHBoxLayout()
        self.actions = []
        for name in NAMES:
            box = W.QCheckBox(name)
            box.setChecked(True)
            box.toggled.connect(self.changed)
            self.actions.append(box)
            actions.addWidget(box)
        layout.addLayout(actions)
        instructions = W.QLabel(
            "从放松中立位动作一次，保持至放松提示。前臂支撑、手腕可自由活动；"
            "屈伸腕时手指放松，非动作侧放松。静息时自然放松，保持手腕中立。"
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        self.channels = W.QTableWidget(0, 3)
        self.channels.setHorizontalHeaderLabels(["实际通道", "侧别", "位置"])
        self.channels.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch)
        self.channels.setMaximumHeight(190)
        self.channels.verticalHeader().setDefaultSectionSize(44)
        layout.addWidget(self.channels)
        self.geometry = W.QLabel("电极直径约 7 mm；中心间距约 80–100 mm。")
        self.geometry.setWordWrap(True)
        layout.addWidget(self.geometry)
        controls = W.QHBoxLayout()
        refresh = W.QPushButton("刷新实际通道")
        refresh.clicked.connect(lambda: host.guard(self.sync_channels))
        controls.addWidget(refresh)
        layout.addLayout(controls)
        self.interval.valueChanged.connect(self.changed)
        self.movement_side.currentIndexChanged.connect(self.changed)

    def selected_ids(self):
        return [a for a, b in zip(ACTIONS, self.actions) if b.isChecked()]

    def sync_channels(self):
        profile = self.host.backend.profile
        if not profile:
            raise ValueError("请先连接设备。")
        ids = profile["channel_ids"]
        if ids == [v["channel_id"] for v in self.values]:
            return
        previous = {v["channel_id"]: v for v in self.values}
        self.values = [
            deepcopy(
                previous.get(
                    c, dict(channel_id=c, side=None, position=None, placement=default_placement())
                )
            )
            for c in ids
        ]
        self.channels.blockSignals(True)
        self.channels.setRowCount(len(ids))
        for row, value in enumerate(self.values):
            item = W.QTableWidgetItem(str(value["channel_id"]))
            item.setFlags(C.Qt.ItemIsEnabled | C.Qt.ItemIsSelectable)
            self.channels.setItem(row, 0, item)
            for column, key, choices in [(1, "side", SIDES), (2, "position", POSITIONS)]:
                box = W.QComboBox()
                box.addItem("请选择", None)
                for code, text in choices.items():
                    box.addItem(text, code)
                box.setCurrentIndex(max(0, box.findData(value[key])))
                box.currentIndexChanged.connect(
                    lambda _, r=row, k=key, b=box: self.set_value(r, k, b.currentData())
                )
                self.channels.setCellWidget(row, column, box)
        self.channels.blockSignals(False)
        self.channels.setCurrentCell(0, 0)
        self.changed.emit()

    def set_value(self, row, key, value):
        self.values[row][key] = value
        self.channels.setCurrentCell(row, 0)
        self.changed.emit()

    def plan(self):
        return validate_plan(
            dict(
                protocol=PROTOCOL,
                subject=self.host.group.text(),
                movement_side=self.movement_side.currentData(),
                channels=self.values,
                selected_actions=self.selected_ids(),
                repetitions=self.host.trial_count.value(),
                action_seconds=self.host.action_seconds.value(),
                interval_seconds=self.interval.value(),
                random_order=self.host.random_order.isChecked(),
            ),
            self.host.backend.profile["channel_ids"] if self.host.backend.profile else [],
        )
