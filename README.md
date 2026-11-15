# EMG Lab 肌电控制实验

课堂版 `2026.10.26-classroom.2`。提供设备连接、采集、训练和使用模型页面；机器人工作区的新前臂采集协议仅用于采集与导出，训练继续使用已有受支持数据。两组各 6 人，每组两条线各约 3 人。

## 开始使用

**完整离线包同时包含源码、文档、场景、驱动和 Python 运行依赖**。完整解压后按下列步骤操作，无需先安装 Python。

离线发行包完整解压后双击 `start.cmd`，首次启动自动使用随包 Python、uv 和锁定 wheel 建立本目录的 `.venv`，无需联网。安装中断可重试，修复可运行 `install.cmd`。移动文件夹后会重新建立环境；不要复制其他电脑的 `.venv`。

Windows 从 Git 克隆后，即使没有 Python 或 uv，也可双击 `install.cmd`：安装器会检查 Python 3.13 x64，必要时取回经校验的 Python，并准备项目内的 uv、.NET 8 和锁定依赖。准备过程使用直连，不使用代理；完成后双击 `start.cmd`。已有组件会复用，失败后可重跑，日志位于 `local/setup.log`。USB 驱动、系统 Visual C++/.NET Framework 与设备许可见 `drivers/README.md`，不会自动以管理员身份安装。

开发者也可自行运行：

```powershell
uv sync --locked
uv run --locked python main.py
```

目标为 Windows 10 22H2 / Windows 11 x64，需要 OpenGL 显卡驱动。用户已确认 Windows UI 可用；两个完整安装流程仍需在原生 Windows 上按验收脚本检查。

[离线发行与验收](docs/WINDOWS_RELEASE.md)记录 ZIP 构建、直连安装及验收方法，[重构报告](docs/RESTRUCTURE_REPORT.md)记录架构。源码不包含运行时或 wheelhouse；当前工作区网络阻止下载，尚未生成完整离线 ZIP。

## 课堂功能

| 方向 | 基础 | 扩展 |
| --- | --- | --- |
| 机器人 | 停止、前进、左转、右转 | 加入后退、左移、右移，共七类 |
| 灵巧手 | 停止保持、张开、握合 | 停止保持与四个官方预设姿态，共五类 |

前臂采集默认每动作重复 5 次、每次 5 秒、动作间隔 10 秒，初始准备 3 秒；可将单次动作标记无效并保留原始数据。灵巧手与旧版数据继续沿用整组动作语义。模型采用因果滤波、滑窗、一维卷积分类与稳定判定，按完整动作组划分训练、验证和测试。

采集场景演示提示动作；实时与离线推理场景由模型预测驱动。自由练习、基础评估、机器人金币任务各有独立用途。基础评估报告显示准确率、混淆、停止误触发、响应和切换统计；从数据与模型页打开或导出历史报告。

数据与模型页统一筛选、导入导出。`.emg` 包含原始信号、标签和元数据；`.emgmodel` 包含 ONNX 和模型说明。界面导出的离线实验包只包含数据/模型，配合教师发放的完整学生包使用。可运行合成 smoke 命令检查软件流程。

机器人采集页使用[标准前臂采集协议](docs/forearm_collection.md)，保存原始 `.emg` 与动作索引 CSV。旧版自由文本自定义采集数据仍可读取。

## 文档与代码

- [前臂数据格式冻结规范 V1](docs/DATA_FORMAT_V1.md)、[数据包中文说明](data/README.md)、[独立分析 notebook](data/example_analysis.ipynb)

- [操作教程](docs/USER_GUIDE.md)、[课程约定](docs/COURSE_GUIDE.md)
- [开发技术文档](docs/TECHNICAL_GUIDE.md)：链路、目录、数据结构、算法与扩展接口
- [设备驱动与安装说明](drivers/README.md)：Cometa 原厂 USB 驱动、SDK 与 Python 依赖的区别
- [金币任务规则](docs/COMPETITION.md)、[速度实验记录](docs/CONTROL_ENVELOPE_V2.md)、[手部姿态来源](docs/HAND_POSES.md)

`emg_lab/frontend/` 是 Qt 前端，`emg_lab/backend/` 是无 Qt 的后台，`emg_lab/contracts/` 是共享契约；`emg_lab/` 根部旧模块保留兼容导入，`assets/` 是场景与运控资源，`vendor/` 为设备适配依赖，`scripts/` 与 `tests/` 为检查入口，`licenses/` 保留第三方许可。个人结果保存到 `data/`，运行日志保存到 `local/`，发行包不含真实采集记录、许可凭据或个人日志。

源码目录包含应用、资源、驱动和文档；离线包另带 `.runtime/` 与 `wheelhouse/`。个人结果与运行日志在首次使用后生成，`.gitignore` 已排除这些目录。第三方来源与使用范围见 [NOTICE](NOTICE.md)。

## 验证范围

运行 `uv run python scripts/check_classroom.py --render` 检查软件与 3D，不连接硬件。自动化回归：`uv run pytest -q`；明确的合成全链路检查：`uv run python scripts/smoke_pipeline.py --output local/smoke`。合成结果仅验证软件流程。Windows 离线包用 `acceptance.cmd --relocation-test` 验证；Qt、Windows 和真实硬件检查的待办状态见重构报告。

机器人金币任务所有模型同榜；固定分类速度固定，教师验收的连续/混合方法可用较高速度上限。底层运控、种子、加速度及计时规则共同冻结。学生改进算法后仍可练习，正式比赛由教师审核并冻结版本。

机器人七类与手部五类目前仅用于仿真；手部显示是姿态运动学，未实现接触力或抓取精度测量。基础三类的定速握合加停止不等于肌电强度连续解码。真实硬件连接由教师安排；模拟、回放与采集演示不启用真机动作输出。

前臂 EMG 标准采集：受试者、每通道侧别与位置、动作侧、四种标准动作和可配置间隔，使用文字动作提示与通道位置选项。新数据仅用于采集与导出，训练适配另行开发。详见 [采集协议](docs/forearm_collection.md)。

旧版自定义 EMG 可通过[迁移工具](docs/legacy_emg_migration.md)转换为当前采集格式；保留原始数据和用力条件，并明确记录通道区域的推断依据。
