# Standardized forearm EMG collection

The frozen storage contract is [DATA_FORMAT_V1.md](DATA_FORMAT_V1.md). Distribute the Chinese [data guide](../data/README.md) and [standalone analysis notebook](../data/example_analysis.ipynb) with a versioned dataset manifest.

The robot workspace now collects EMG independently of robot command classes. Device connection and channel-count configuration remain on the existing device page. Training and control pages retain their existing behavior with supported legacy artifacts. This protocol deliberately produces collection-only recordings: no training mapping or continuous velocity targets are introduced.

## Operator procedure

1. Connect the device and configure the actual channel IDs.
2. Enter a subject name. For every channel, select **侧别** (左/右) and **位置** (前臂屈肌区/前臂伸肌区). Assignments are independent; multiple channels may share a region.
3. Set the movement side for the batch (左侧/右侧/双侧), independently of recording sides. Keep the inactive arm relaxed.
4. Check the channel side and position dropdowns. New channel IDs require explicit selections. Electrode-position figures and their editing controls are not shown.
5. Select any nonempty subset of 静息, 握拳, 屈腕, 伸腕. Set repetitions per action, trial duration, interval, and optional shuffled order.
6. Follow the Chinese text cues. From a relaxed neutral wrist, perform one action and hold until the relaxation cue. Keep fingers relaxed for wrist flexion/extension. Support the forearm while allowing wrist movement. Movement onset belongs to the labeled trial; no unmeasured steady-state boundary is inferred.
7. Stop early if necessary: raw data and completed action labels are retained; the CSV index also identifies partially recorded actions. Marking an invalid trial affects one action, not the complete round.

A **trial** is one action period, a **round** contains every selected action once, and a **batch** shares one subject, placement setup and movement side. The defaults are five rounds, five seconds per trial, and ten seconds between trials. Limits are 1–9999 rounds, 1–120 seconds per trial, and 0–300 seconds between trials. Fixed order is rest, fist, wrist flexion, wrist extension, restricted to the selection. Randomization permutes that selection separately for each round and records its seed and actual order.

The initial countdown is three seconds. The recovery setting is the entire gap between action periods: its final min(3, gap) seconds show preparation. There is no additional hidden preparation period or final recovery gap. Planned duration is `3 + trials * action_seconds + (trials - 1) * interval_seconds`; sample boundaries round each duration to the device sample clock. A labeled rest action is distinct from recovery.

## Stored contract

The Qt-independent contract is `emg_lab/contracts/forearm.py`; the application entry point is `ApplicationService.start_protocol_capture(plan)`. Its protocol identifier is `EMG_FOREARM_CAPTURE_V1`. The backend validates all fields and current channel order before creating a recording. The new capture runner reuses the existing raw writer and capture lifecycle without changing the legacy runner's trial semantics.

Canonical action order and IDs are always:

| ID | Stored action | Chinese display |
|---|---|---|
| 0 | `rest` | 静息 |
| 1 | `fist` | 握拳 |
| 2 | `wrist_flexion` | 屈腕 |
| 3 | `wrist_extension` | 伸腕 |

Channel `side` is `left`/`right`; `position` is independently `forearm_flexor`/`forearm_extensor`. Movement side also accepts `both`. Selecting a subset does not renumber actions. Subject names remain user-supplied Unicode strings; they are not action labels.

The plan stores subject, movement side, selected actions, repetitions, action/interval durations, randomization flag, channels and instruction version. Each channel includes its ordered physical ID, side, position, and placement: diagram version, source, two normalized `[x,y]` electrode centers, approximate diameter and center-spacing range in millimeters. The reported defaults are diameter 7 mm and spacing 80–100 mm. Physical dimensions are independent of schematic coordinates.

Archives retain `emg.bin`, `labels.csv`, and `meta.json`, including the unchanged binary header/sample layout. New metadata uses schema version 3 and `capture_only=true`, with the versioned plan, actual order, seed, planned per-trial schedule (including round indices), and rejection records. `trial_count` and completed/usable counts refer to individual actions for this protocol only. Labels contain exclusive-end sample boundaries and English action codes. The complete raw stream includes countdowns and recovery.

Files are saved below the chosen data root as `<safe-subject>/recordings/<safe-subject>_<YYYYMMDD_HHMMSS_microseconds>.emg`. The timestamp identifies batch start and includes its timezone in metadata. Windows-invalid filename characters and reserved subject names use the existing safe-name handling; the original trimmed subject remains in metadata. No experiment title or UUID is added to the basename. Internal recording identity remains a UUID. The regenerable sibling `.index.csv` includes English action codes, trial/round IDs, movement side, sample intervals, completeness, validity and channel-placement metadata.

Existing custom V1 and robot/hand recordings retain their original readers and meanings. Legacy data remains unchanged unless explicitly supplied to the [migration tool](legacy_emg_migration.md). Its imported artifacts record assumptions, inferred regions and original condition variants separately from native acquisitions.

## Placement metadata and text cues

The collection interface uses text instructions and channel side/position dropdowns. It has no action illustration, action-preview selector, electrode-placement diagram or marker-reset control.

The operator supplied the intended proximal forearm locations near flexor carpi radialis (FCR) and extensor digitorum (ED), approximately 7 mm patches, and 8–10 cm center spacing. Both patches should target the selected region on the same intended muscle. Neither region selection nor EMG amplitude proves the muscle source.

The stored placement structure is retained for artifact compatibility. New UI plans retain explicitly marked `schematic_default` coordinates; these are not operator-measured positions. Previously saved operator-adjusted metadata remains readable. Instruction version 1 continues to describe move-and-hold wrist flexion/extension with relaxed fingers and a relaxed inactive arm.

## Verification

`tests/test_forearm_capture.py` exercises variable and mixed-side channel maps, subsets, stable IDs, randomized rounds, gaps/countdowns, no trailing gap, exact raw preservation, partial trials, single-trial rejection, Windows-safe names, import/export, library summaries, training exclusion, Qt workflow locking, channel changes and absence of figure controls. Legacy backend tests remain in place; UI scene lifecycle tests use the retained hand workflow.

Run `QT_QPA_PLATFORM=offscreen uv run pytest -q` and `uv run python scripts/smoke_pipeline.py --output local/forearm-smoke`. Synthetic results verify software only. The Windows source/ZIP builder already includes the complete `emg_lab` tree, and this text-based interface needs no separate assets. Native Windows 10 layout/input, offline package execution and actual electrode/device collection still require operator verification.

Verified in this Linux workspace: full regression suite **216 passed, 3 skipped**; subsequent protocol/transfer checks **30 passed** and Qt workflow checks **35 passed**. The explicit synthetic smoke completed successfully. Ruff and whitespace checks passed. Native Windows and physical-device checks were not run.

Imported legacy recordings use a distinct validated origin, may retain repeated action variants per original round, and may have explicitly unknown placement geometry and instruction version. See the [migration contract](legacy_emg_migration.md).
