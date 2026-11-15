# Legacy custom-capture migration

The resulting artifact contract is frozen in [DATA_FORMAT_V1.md](DATA_FORMAT_V1.md), including the separate native/imported trial semantics. The shareable [data guide](../data/README.md) and [analysis notebook](../data/example_analysis.ipynb) preserve condition variants and inferred-position status.

The migration tool converts completed Cometa `EMG_CUSTOM_CAPTURE_V1` recordings into collection-only `EMG_FOREARM_CAPTURE_V1` artifacts. It preserves the complete `emg.bin` member byte for byte, including the binary header and sample-clock column. Original files and sidecars remain untouched. It never opens a device or robot output, and it does not train a classifier.

## Run

Use this repository's uv environment and pass an explicit source allowlist. The default is a dry run; it validates sources, computes region evidence and checks destination conflicts without creating outputs.

```sh
uv run python scripts/migrate_legacy_emg.py --source <first.emg> <second.emg> --output-root data
uv run python scripts/migrate_legacy_emg.py --source <first.emg> <second.emg> --output-root data --report-root local/emg-migration --apply
```

On Windows the same commands work with explicit paths. A recent native-format machine test is rejected as a migration input. The script does not discover or convert other recordings automatically. Synthetic fixtures used in automated tests are not evidence of actual muscle placement.

Converted files appear in `<output-root>/<subject>/recordings/<subject>_<original-start-timestamp>.emg`, with a matching `.index.csv`. Originals remain under their previous group, so the library can show both originals and converted copies; filter by subject to select the new copies. The report directory contains `report.md`, `results.json` and `trials.csv`. Temporary import/export checks are confined to that report directory and removed afterward.

## Interpretation and inference

Subject codes come from the legacy `operator` field. These are legacy identifiers, not independently verified participant identities. Arm side comes from selected action conditions and the wearing note; stale, unselected rows do not determine the side. Inconsistent available side annotations cause conversion to fail.

The action mapping is explicit: 静息 → `rest`, 握拳 → `fist`, 内展 → `wrist_flexion`, 外展 → `wrist_extension`. The last two mappings assume the operator's inward/outward labels described wrist bending. Signal responses cannot independently establish action semantics.

For each recorded condition, the tool continuously applies the existing causal filter and computes RMS in each action period. It compares the flexion/extension ratio within each channel, then compares those ratios between channels. This avoids simply labeling the higher-gain sensor as a particular muscle. Ordinary and stronger variants are compared separately. Sensitivity checks use full intervals, 0.5/0.25-second trimming and 1/0.5-second trimming, with and without the 50 Hz notch. A second statistic uses median 100 ms RMS bins. All comparisons must agree and exceed a fixed twofold relative-selectivity threshold. Ambiguous recordings fail rather than receiving an automatic region label.

This threshold is a descriptive acceptance rule, not a calibrated anatomical probability. Stored evidence identifies the result as `inferred_functional_region`, with method version, all comparison scores, per-condition/per-round RMS, and the minimum relative selectivity. `forearm_flexor` and `forearm_extensor` describe inferred functional regions; they do not prove exact FCR/ED electrode locations. Historical electrode coordinates, diameter and spacing remain null with `placement.source=legacy_unknown`. Current UI defaults are not copied into historical measurements.

The physiological limitations are consistent with [SENIAM electrode-placement guidance](https://seniam.org/fixation.htm): electrode geometry and orientation are independent recording information. Exact historical attachment cannot be recovered from these signals alone.

## Artifact contract and validation

The Qt-independent legacy contract is `emg_lab/contracts/legacy_migration.py`. The backend's `prepare_migration()` reads and validates a source and returns deterministic metadata/payload bytes; `publish_migration()` writes or reuses an identical converted artifact. The CLI performs preflight for every supplied source before publishing any of them. Real-data conversions and their evidence live under ignored `data/` and `local/`, not in source control.

The container and raw sample layout are unchanged. New metadata uses schema version 3, the existing canonical four-action task, `capture_only=true`, and `capture_plan.origin=legacy_custom_v1`. Each action interval gets a unique sequential trial ID. Original condition rounds are retained in `schedule.round_index` and original labels in provenance. For imports, plan `repetitions` means **legacy condition rounds**, explicitly identified by `repetition_unit=legacy_condition_round`. It does not assert equal counts for the four collapsed canonical actions. Native live capture retains its strict one-selected-action-per-round rules and cannot be started with an imported plan.

Original stronger activation is stored as `strong_fist_activation` or `strong_hand_extension_activation`; `ordinary`, `unspecified` and `natural_rest` remain distinct. Both ordinary and stronger wrist movements may share one canonical action ID while retaining different `source_condition_id` and `activation_condition` annotations. These fields appear in the index CSV as well. The six-condition case therefore keeps six intervals per original round without merging intervals or discarding conditions. Instruction version is null for imports because the original instruction sequence was not versioned; the current relaxed-finger guidance is not retroactively asserted.

Provenance includes original metadata/labels, source identity, source archive/raw/sidecar hashes, the exact condition mapping, assumptions and inference evidence. Converted IDs use deterministic UUID5 values derived from the source archive hash and versioned mapping settings. Changing source content or mapping produces a different identity. A same-name conflicting destination is rejected, never overwritten. Identical reruns reuse archive bytes and can regenerate a missing index.

The recording reader validates imported schedules against the original legacy annotation rules and the stored condition mapping. It verifies identity/settings consistency, original timing/profile fields, expanded rejection flags, complete/usable trial counts and the raw-member hash. Native validation is not relaxed: migration provenance is mandatory for the import branch, and surplus/repeated canonical conditions still fail native timing validation. Converted records remain excluded from training until a separate training adaptation is implemented.

## Checks

`tests/test_legacy_migration.py` covers ordinary, stronger-only and six-condition fixtures; either channel orientation; exact raw bytes/sample boundaries; unknown geometry; per-trial annotations; inherited invalid rounds; identity/idempotency; destination conflicts; tampered raw data/provenance; import/export; index regeneration; ambiguous-response rejection; and exclusion of native machine tests. Existing capture, storage, library and transfer tests continue to cover their original behavior.

For an actual migration, the CLI verifies all existing archives and CSV hashes under the output root, each converted file through the current reader and library catalogue, regenerated indexes and temporary import/export round trips. It verifies deterministic reuse a second time before reporting success. It does not claim Windows GUI or physical-device acceptance.
