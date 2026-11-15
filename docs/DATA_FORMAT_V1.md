# 前臂 EMG 数据格式契约 V1（冻结版）

契约修订：1.0，2026-11-15。本文是当前前臂数据的规范；[采集说明](forearm_collection.md)描述操作，[迁移说明](legacy_emg_migration.md)描述历史来源。分发给分析人员的中文说明与独立示例位于 [data/README.md](../data/README.md) 和 [example_analysis.ipynb](../data/example_analysis.ipynb)。

## 1 版本与演进规则

当前格式由以下标识共同确定：

| 标识 | 固定值 / 含义 |
|---|---|
| `schema_version` | 整数 `3`，容器内元数据布局 |
| `signal_type` | `emg` |
| `task_type` / `capture_plan.protocol` | `EMG_FOREARM_CAPTURE_V1` |
| `target` | `robot`，表示所属工作区，不表示已建立机器人训练映射 |
| `capture_only` | `true`，当前应用拒绝将其直接用于训练/控制 |
| `capture_plan.origin` | 缺省/`null`：原生采集；`legacy_custom_v1`：历史迁移 |

这些字段、下述类别顺序、时间区间定义、通道列顺序及 trial 语义在 V1 中不得改变。新增动作、重排类别、改变单位/二进制布局/标签语义或修改已有字段含义时，必须发布新协议/必要的新 schema、对应读取器与显式迁移工具；不得覆盖已有文件或沿用 V1 标识。未知版本应报错，不能按“最新格式”猜测解析。允许添加不改变现有语义的可选元数据，必须同时记录其定义及缺省含义；旧读取器可忽略这类扩展。

中文只用于界面、解释或保留的历史自由文本。规范动作、侧别、区域和激活条件使用下述英文代码。用户输入的受试者标识可以是 Unicode 字符串，不能把它当作动作标签或自动映射为姓名。

## 2 文件、身份与发布

一个批次对应一个 `<safe-subject>_<YYYYMMDD_HHMMSS_microseconds>.emg`。文件名来自批次开始时间，时区以元数据 ISO 时间为准。路径通常为 `<subject>/recordings/`；Windows 非法文件名字符按现有规则处理。身份依据 `record_id`，不能依赖文件名或绝对路径。分发时可移动文件，但不得修改归档内元数据“修正路径”。

`.emg` 是 ZIP，恰好包含 `emg.bin`、`labels.csv`、`meta.json` 三个成员；不包含 Python、pickle、模型权重或外部依赖文件。同名 `.index.csv` 是可重建的派生索引，UTF-8 BOM、CSV 布尔值为 `True`/`False`；归档内标签与元数据才是事实来源。索引缺失不代表原始信号丢失，冲突时应重新生成索引，不能反向用索引覆盖归档。

原始采集/迁移文件只读。分析结果、过滤后数组、特征、模型和日志写入显式选择的输出目录。发布数据时生成 `dataset_manifest.json`，固定相对路径、`record_id`、归档/索引 SHA256、格式版本和数据集版本；清单仅用于本次数据集快照，不改变 `.emg` 格式。新增记录或更改文件后发布新的数据集版本，不悄悄替换旧版本。数据文件、真实清单和分析输出不提交 Git；仅分发说明和无输出的通用 notebook 可纳入版本控制。

## 3 二进制布局与时间轴

`emg.bin` 头固定为 53 字节，小端，Python `struct.Struct('<iiiii10s15sd')`：

| 字节偏移 | 类型 | 含义 |
|---:|---|---|
| 0 | int32 | 头长度，53 |
| 4 | int32 | 通道数 C |
| 8 | int32 | 兼容通道掩码，不代替 `channel_ids` |
| 12 | int32 | 取整采样率，不代替精确 `sampling_rate` |
| 16 | int32 | 实际样本行数 N |
| 20 | bytes[10] | 日期，兼容字段 |
| 30 | bytes[15] | 时间，兼容字段 |
| 45 | float64 | 时长，N / sampling_rate |

头后是小端 float32，逐行存储 `[N, C+1]`；第 0 列为兼容的相对秒数，第 1…C 列是原始信号，严格对应 `meta.channel_ids` 顺序。元数据中的 `sampling_rate` 为精确 Hz，`unit` 为原始数值的单位声明；例如 `SDK raw` 不能当作 µV 或力。不同设备、单位、采样率的数据不得未经说明直接合并。

**分析时间轴使用样本编号 `n / sampling_rate`。** float32 时间列有舍入误差，不能用时间戳浮点相等比较来切标签，也不能据此宣称设备没有丢包。数据必须是有限数，通道数、样本数、头长度与负载字节数相符。

## 4 固定标签与通道信息

| class_id | class_name | 中文含义 |
|---:|---|---|
| 0 | `rest` | 静息 |
| 1 | `fist` | 握拳 |
| 2 | `wrist_flexion` | 屈腕 |
| 3 | `wrist_extension` | 伸腕 |

`classes` 始终为上表四个代码的有序列表；选取动作子集时不重新编号。不要按某文件出现的类别排序，也不要把它们解释为旧机器人 `left/right/forward` 命令。

`labels.csv` 列固定为 `trial,start_sample,end_sample,class_id,class_name`。`trial` 是批次内从 1 开始的单次动作标识，完整时间区间是 **`[start_sample, end_sample)`**，用 `raw[start:end]` 切片。文件中只写入完整动作区间；提前结束的半段动作仍在原始流中，其不完整状态可见于派生索引。标签不重叠；准备与恢复间隔没有动作标签，尤其不能自动标成 `rest`。无效动作的原始样本/标签仍保留，排除规则来自 `rejected_trials`。

`capture_plan.channels` 与 `channel_ids` 一一对应且同序，每项包含 `channel_id`、`side`（`left/right`）、`position`（`forearm_flexor/forearm_extensor`）及 `placement`。动作侧 `movement_side` 为 `left/right/both`，独立于记录通道侧别；可以记录非动作侧。不同 channel ID 不等于不同解剖区域，同一个 channel ID 在不同人/佩戴中也不保证相同位置。

`placement.source=schematic_default` 的坐标只是旧界面/方案保留的示意默认值；`operator_adjusted` 也是示意坐标，不是已测量的解剖定位。迁移的 `legacy_unknown` 下坐标、直径和间距为 null，不得补成当前默认测量值。`position_source=inferred_functional_region` 表示由动作响应推断，不能当作经确认的具体 FCR/ED 肌肉定位。保留来源字段和推断证据。

## 5 必需元数据与两种来源

| 字段组 | 约定 |
|---|---|
| `record_id`, `subject`, `name`, `group` | 前臂数据中 name/group 与 subject 一致，record_id 才是不可变身份 |
| `created_at`, `batch_started_at` | 带时区 ISO 开始时间；迁移保留来源开始时间 |
| `device`, `sampling_rate`, `channel_ids`, `unit` | 设备与样本解释规则，不通过动作幅值猜测单位 |
| `samples`, `duration`, `labels` | 实际样本行数、秒、完整标签条数 |
| `complete`, `finalized` | 是否完成计划、是否已保存完成；二者不等价 |
| `trial_count`, `completed_trials`, `usable_trials` | 计划单次动作数、已完整记录数、其中未拒绝的完整动作数 |
| `capture_plan` | 受试者、动作侧、通道、选中动作、重复/时序、来源、指令版本 |
| `actual_order`, `order_seed`, `random_order` | 每次动作的实际 class_id 顺序、随机种子和顺序模式 |
| `schedule` | 所有计划动作：trial、round_index、class_id/name、样本边界 |
| `rejected_trials` | `[{'trial': int, 'reason': str}, ...]`；缺省空列表 |
| `preprocessing` | 原采集方案的滤波/窗口配置快照；**不表示 emg.bin 已经过滤** |

**原生采集：** 一轮含每个选中动作一次；`repetitions` 是轮数（也等于每个选中动作的计划次数）。初始准备 3 秒，动作长度与间隔分别按采样率取整；间隔包含倒计时，末尾无额外间隔。`instruction_version=1` 为从中立位动作一次后保持、屈伸腕手指放松、非动作侧放松。原生 schedule 必须与这些规则和实际顺序完全一致。

**历史迁移：** `origin=legacy_custom_v1`，`repetition_unit=legacy_condition_round`，`repetitions` 表示原始条件轮数，不能推导每个合并后的 canonical 动作次数。一个原始轮可以含两个屈腕、两个伸腕等变体；必须读取 schedule 和标签，不能用 `len(selected_actions) * repetitions` 重建其区间。`instruction_version=null` 表示历史指令版本未知。逐动作保留 `source_condition_id` 和 `activation_condition`，可为 `natural_rest/ordinary/unspecified/strong_fist_activation/strong_hand_extension_activation`。不能把普通与加强激活无记录地混为同一实验条件。原生记录通常没有这两个字段，缺失不等于“普通用力”。

迁移顶层 `migration` 包含版本、原始身份/文件哈希、原始元数据/标签、条件翻译、配置哈希、动作响应推断证据及假设。原始旧整轮拒绝标记已展开成单次动作标记；`round_index` 保留原轮信息。原生文件与迁移文件的解析分支必须明确，不能通过缺字段猜测来源。

## 6 分析与未来训练约定

- 对整个记录按原顺序执行一次因果滤波；每个记录重置状态，动作边界不重置。示例复用现有四阶带通 + Q=30 陷波实现；原始数组不覆盖。不使用未来样本过滤后再声称在线可用。
- 从完整、未拒绝的标签生成窗口；窗口完整位于所属动作段内。不把间隔混入动作，不悄悄截断/插值补足不完整段。
- 窗口最小身份为 `(record_id, trial, start_sample, end_sample)`；保留 subject、origin、round_index、movement_side、activation_condition、source_condition_id、通道顺序、单位与原始文件哈希。
- 在切窗前固定划分。为保持历史整轮约束，示例按 `(record_id, round_index)` 分组，同一轮的全部动作及其重叠窗口进入同一集合；原生单 trial 也不得拆分。跨佩戴/跨受试者泛化分别需要整记录/整受试者留出。不得把这些不同问题的成绩互相替代。
- 标准化、特征选择、降维、数据增强统计量只用训练集合拟合。验证/测试集合只应用已拟合参数。保留划分清单、随机种子、过滤配置、窗口参数、特征名/单位和代码版本。
- 受试者、佩戴、记录、动作侧、激活变体、通道位置来源是混杂因素。默认先逐记录分析；跨记录合并需明确设备/单位/采样率、通道对齐与条件语义，不按列号简单拼接。
- 当前应用的 `capture_only=true` 训练门禁保持不变；notebook 只演示特征和防泄漏划分，不训练机器人模型、不建立控制映射。分类动作标签不能伪造 `(vx,vy,yaw)` 连续回归真值。

## 7 验证与变更入口

项目读取器 `emg_lab.backend.data.storage.read_recording()` 是完整应用校验入口。分发 notebook 内含独立的只读基础读取器，无需项目/Qt/SDK；它校验发布哈希、版本、二进制结构、通道、标签、schedule 和迁移原始二进制哈希，不替代项目对完整迁移来源链的校验。数据发布前先用项目读取器验证，再固定清单。

`contracts/forearm.py` 的 `SCHEMA_VERSION/PROTOCOL/ACTIONS` 是代码常量；测试固定 V1 公开标签和值，并验证未知 schema 不会被默默解析。修改格式前应先定义新版本和兼容策略，再修改写入器/读取器/迁移工具/说明和 notebook；不得为方便训练而就地重写已分发的标签、trial 或通道含义。
