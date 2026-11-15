# 前臂 EMG 数据包：格式约定与分析入口

本目录可单独发给分析同学。当前冻结格式为 **`schema_version=3` + `EMG_FOREARM_CAPTURE_V1`**。接口修订 1.0（2026-11-15）。请保持 `.emg` 原文件只读，结果保存到 notebook 中指定的输出目录。

## 快速开始

1. 保留本说明、`example_analysis.ipynb`、`dataset_manifest.json`，以及清单列出的 `.emg` 和同名 `.index.csv` 的相对目录结构。
2. 在 VS Code/Jupyter 中打开 notebook，选择安装了 NumPy、SciPy 的 Python 内核。Matplotlib 用于绘图；未安装时仍可运行校验、统计、特征和划分单元。
3. 在 notebook 的配置单元确认 `DATA_ROOT`、`OUTPUT_ROOT`。从数据目录或项目根目录运行均可；数据移动到其他地方后也可以显式填写路径。
4. 从上到下运行。默认严格使用发布清单并验证 SHA256；读取失配时报错，不自动换文件或继续混入测试数据。

使用仓库 uv 环境可直接执行基础分析；Jupyter/VS Code 内核是独立的编辑器运行组件。仓库环境若需要交互内核/绘图，可以使用 `uv run --with ipykernel --with matplotlib python -m ipykernel install --user --name emg-analysis`，再在编辑器中选择该内核。仅收到数据文件夹的同学可在自己的 uv 项目中声明 `numpy`、`scipy`，按需要加入 `ipykernel`、`matplotlib`；无需机器人、Qt、Windows SDK 或完整仓库。离线机器需预先准备这些分析依赖。Windows 下载依赖前，按直连安装约定在 PowerShell 清除代理变量：`Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY -ErrorAction SilentlyContinue`（Windows 环境变量名不区分大小写）。

## 发布清单与本次数据范围

`dataset_manifest.json` 是本次发布快照：有数据集 ID、清单版本、格式标识，以及每个归档的相对路径、`record_id`、SHA256、原始二进制 SHA256、同名索引路径/哈希。以清单为准选择数据，不用目录中文件名的先后顺序判断版本。

本次清单仅列迁移后的 **7 份真实 Cometa 记录 / 140 次完整动作**。`G01/` 中是保留的历史原件；它们与迁移副本含相同原始信号，不能重复计入样本。近期模拟设备测试及 `analysis_outputs/` 不属于本次发布范围。分发时只复制清单列出的文件、本说明、notebook 和清单；无需发送历史原件或模拟测试目录。仅分发数据文件夹也不需要外部迁移报告才能读取。

新增真实数据时应先校验归档、明确录制来源/单位/侧别，再生成新的清单版本；不要把新文件悄悄加入旧清单。未提供清单时，notebook 允许显式关闭清单模式并筛选当前协议真实记录，但这种探索模式不构成已固定的数据集版本。

### 清单字段示意

以下是结构模板，哈希和身份占位符必须替换为真实值；不能把模板当作发布清单。

```json
{
  "manifest_version": 1,
  "dataset_id": "forearm-example-v1",
  "format": {"schema_version": 3, "task_type": "EMG_FOREARM_CAPTURE_V1"},
  "recordings": [{
    "path": "P01/recordings/P01_20261115_140000_000000.emg",
    "record_id": "<归档内的 record_id>",
    "sha256": "<完整归档的 SHA256>",
    "emg_bin_sha256": "<归档内 emg.bin 的 SHA256>",
    "index_path": "P01/recordings/P01_20261115_140000_000000.index.csv",
    "index_sha256": "<同名索引的 SHA256>"
  }]
}
```

路径使用相对于数据包根目录的 `/` 分隔路径，哈希使用小写十六进制。清单可附加创建时间、subject、origin、completed_trials 等描述字段；读取以归档中的身份/标签为准。索引若列入清单，分发时必须同时携带并匹配哈希。清单以外的文件不自动加入分析。

## 文件里有什么

`.emg` 是 ZIP，恰好有 `emg.bin`、`labels.csv`、`meta.json`：

- `emg.bin`：53 字节小端头 `<iiiii10s15sd`，其后为小端 float32 `[N,C+1]`。第一列是兼容秒数，后续 C 列严格对应 `meta.channel_ids` 顺序。头字段依次为头长度、通道数、兼容掩码、取整采样率、样本行数、日期[10]、时间[15]、时长 float64。精确采样率/单位/通道顺序以元数据为准。
- `labels.csv`：`trial,start_sample,end_sample,class_id,class_name`。样本编号从 0 开始，区间是 **左闭右开**，用 `raw[start_sample:end_sample]` 切片；`trial` 从 1 开始，每个表示一个动作。
- `meta.json`：设备、受试者、通道侧别/区域、采样率/单位、版本、实际顺序、计划动作 schedule、完成状态、拒绝标记、原生/迁移来源及迁移证据。

时间轴用 `np.arange(N)/sampling_rate` 构建，不用 float32 时间列做相等匹配。原始值单位若为 `SDK raw`，不能直接写成微伏或力。`preprocessing` 是方案快照，**不代表保存的原始数据已过滤**。

同名 `.index.csv` 是可重建的派生索引：有 trial、round_index、动作、动作侧、样本区间/秒、完整性、有效性、拒绝原因、通道 JSON；迁移记录还包含 `source_condition_id`、`activation_condition`。半段动作可能出现在索引中，但不会成为完整标签。归档内的 metadata/labels 是权威来源。

## 固定标签与通道含义

| ID | 英文标签 | 中文 |
|---:|---|---|
| 0 | `rest` | 静息 |
| 1 | `fist` | 握拳 |
| 2 | `wrist_flexion` | 屈腕 |
| 3 | `wrist_extension` | 伸腕 |

只选部分动作时仍使用这些 ID，不重新排序/编号。准备和动作间隔不等于静息动作，不能把未标记区域全部标成 `rest`。

每个通道记录独立 `side=left/right`、`position=forearm_flexor/forearm_extensor`；动作侧 `movement_side=left/right/both` 与传感器侧别独立。不能凭 channel ID 或矩阵列号跨受试者对齐肌肉。迁移数据的区域标记来自运动响应推断，`position_source=inferred_functional_region`；它不是精确 FCR/ED 定位。`placement.source=legacy_unknown` 时几何字段为 null；`schematic_default` 也不是实测位置。

## 原生与迁移的差别

| 项目 | 原生采集 | 历史迁移 |
|---|---|---|
| `capture_plan.origin` | 缺省或 null | `legacy_custom_v1` |
| 一次 trial | 一个动作 | 一个原始动作片段，重新分配单次 ID |
| `round_index` | 选中动作各一次的轮 | 保留的原始条件轮，可能含多个同方向变体 |
| `repetitions` | 每个动作的次数/轮数 | 原条件轮数；`repetition_unit=legacy_condition_round` |
| `instruction_version` | 1 | null（历史指令未知） |
| 激活条件 | 通常未单独存储 | `natural_rest/ordinary/unspecified/strong_fist_activation/strong_hand_extension_activation` |

迁移前的“内展/外展”按明确假设对应屈腕/伸腕；原中文条件和翻译在 `migration` 中保留。普通与加强激活不要无记录合并。原生缺少激活字段也不等于历史“普通”。Notebook 把缺失的原生条件显示为分析用 `protocol_default`，此值不是新增的存储标签。

`complete` 表示是否按计划录完，`finalized` 表示已保存完成；提前结束仍可能有可用动作。`schedule` 包含所有计划动作，`labels.csv` 仅含已完整记录的动作。`rejected_trials` 保留无效 trial 和原因，不删除原始波形；分析时用完整标签并排除拒绝 ID。`trial_count/completed_trials/usable_trials` 分别是计划、已完成、有效的单次动作数。

## 示例分析和防止训练泄漏

Notebook 演示：发布清单和格式校验 → 通道/条件摘要 → 整记录因果滤波 → 可选波形/功率谱图 → 逐动作 RMS/MAV → 分组划分 → 段内滑窗 → 仅训练集拟合标准化 → 导出可追溯 CSV/JSON。

默认只对一个选中的记录做特征/划分，避免不同通道顺序、采样率、单位直接混合。先按 `(record_id, round_index)` 固定分组，再切窗，同一轮中的全部动作及其重叠窗口进入同一集合。研究跨记录/佩戴/受试者泛化时，应改成整记录或整受试者留出。划分目的、种子、各集合完整组 ID、参数和输入哈希必须随结果保留。验证/测试数据不能参与均值、标准差、特征选择或降维拟合。

示例不训练模型，也不宣称分类准确率。当前应用保留 `capture_only=true` 门禁；将来训练适配应显式处理激活条件、未知/推断位置和通道语义。不得将这些分类标签伪造成连续机器人速度真值。

## 版本冻结规则

V1 的类别顺序、单位声明、样本索引、通道列顺序和原生/迁移语义不得就地改变。新动作或不兼容字段含义必须新建协议版本与读取器，并生成新数据集版本。未知版本应拒绝，不静默猜测。读取代码应保留不认识的可选元数据，不能据此重写原件。

完整规范在仓库的 `docs/DATA_FORMAT_V1.md`；本说明已包含数据包独立分析所需的核心约定。项目读取器还会检查完整迁移来源链，notebook 独立读取器主要校验格式、发布哈希、样本、标签/schedule 和迁移原始二进制哈希，不能替代发布前的完整校验。
