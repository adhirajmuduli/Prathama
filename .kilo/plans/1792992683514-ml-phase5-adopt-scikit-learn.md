# Phase 5 ML plan — adopt scikit-learn (+xgboost, shap); build our own experiment control

## Decision (answer to "from scratch or import an open-source project?")

**Adopt the open-source library, not a whole project, and do not reimplement estimators.**

The rebuild plan already fixes this: `trendsmapp_rebuild_and_publication_grade_plan.md:87`
declares scikit-learn as the framework, and line 610 states verbatim: "`ml/models.py` imports
documented estimators. It does not copy Random Forest, XGBoost, or gradient-boosting source code."

Grounding:

- Deps are already declared and locked in `backend/pyproject.toml`: `scikit-learn>=1.6,<2.0`,
  `xgboost>=2.1,<4.0`, `shap>=0.46,<1.0`, plus numpy/scipy/pandas. Current scikit-learn is
  1.9.x (BSD license, NumPy/SciPy foundation, institutionally supported) — the de-facto
  standard for controlled tabular ML: preprocessing (`ColumnTransformer`/`Pipeline`), model
  selection (CV / grid search), metrics, and the approved estimators.
- Whole-project AutoML (AutoGluon 1.6 / H2O / FLAML) is the wrong layer: it does its own feature
  engineering, HPO, ensembling, and deployment, which conflicts with the plan's invariants
  (§7.5): declared split families with API rejection of incompatible combinations (line 1243,
  e.g. random row splitting for an unseen-station claim), fold-local preprocessing fitted only
  on inner-train, per-fold artifacts, final refit only after evaluation, fixed seeds, per-run
  manifest. AutoML hides exactly the controls a publication-grade study must expose.
- MLOps frameworks (MLflow) are out of scope for a research pipeline; manifests, hashes, and
  provenance events already cover tracking. Revisit only if a hosted registry is later required.
- Building estimators from scratch would discard community-reviewed code and reintroduce bugs;
  the plan forbids copying estimator source.

**What we build ourselves (thin, on top of the library):** the experiment-control layer in
`ml/` and `explainability/` (plan §5.3). Estimators, preprocessing transforms, and metrics come
from scikit-learn / xgboost / shap via adapters in `ml/models.py`.

## Approved model identifiers (plan §5.3)

`mean_baseline`, `station_climatology`, `seasonal_climatology` (baselines, ours),
`elastic_net`, `random_forest`, `extra_trees`, `hist_gradient_boosting` (scikit-learn),
`xgboost` (XGBRegressor via its sklearn-compatible API). CatBoost later via the same registry
only if categorical handling is central to an experiment.

## Task contract (plan §7.5) — every ML run declares

target parameter, prediction unit, prediction setting (known-station temporal / unseen-station
spatial / future-period forecasting / missing-observation reconstruction), eligible date range,
eligible stations/sectors, feature list, lag policy, missing-data policy, QC/exclusion policy,
outer evaluation strategy, inner tuning strategy, candidate models, search budget, primary metric,
random seed, uncertainty method, explanation methods. Each prediction setting has an allowed
split family; the API rejects incompatible combinations (422).

## New domain enums (add to `backend/src/trendsmapp/domain/enums.py`)

`ModelFamily` (identifiers above), `PredictionSetting` (4 settings), `SplitStrategy`
(station_group, spatial_block, leave_year_out, rolling_origin, sector, combined, random_row —
with per-setting allowed families), `UncertaintyMethod` (bootstrap_ensemble, quantile),
`ExplanationMethod` (permutation, shap_tree, partial_dependence).

## Module task list (plan §5.3 `ml/` + `explainability/`)

1. `ml/models.py` — functional estimator registry + adapters; imports documented estimators only; capability metadata (SHAP-tree support, feature limits).
2. `ml/baselines.py` — mean / median / station climatology / seasonal climatology / persistence.
3. `ml/preprocessing.py` — sklearn `ColumnTransformer`/`Pipeline`; fold-local fit only.
4. `ml/splits.py` — the six split generators; setting↔split-family compatibility validation.
5. `ml/search.py` — bounded, seeded hyperparameter search on the inner split within budget.
6. `ml/training.py` — outer evaluation → inner tuning per fold → fold artifacts → aggregate metrics → final refit after evaluation → seeds → failure reporting.
7. `ml/metrics.py` — regression metrics, bootstrap CIs, fold aggregation, subgroup metrics.
8. `ml/uncertainty.py` — bootstrap ensemble / quantile intervals + empirical coverage.
9. `ml/artifacts.py` — safe model serialization, feature schema, environment metadata, hashes, load-time compatibility checks.
10. `ml/pipeline.py` — task validation → features with lineage → feature-table hash → splits → training → metrics → uncertainty → explanation dispatch → result storage.
11. `explainability/{permutation,shap_values,effects,stability,payloads,pipeline}.py` — held-out permutation importance (repeated seeds); SHAP for fitted tree models with bounded background/sample + shape/additivity checks (plan line 1392); PDP/ALE only when configured and valid; stability across folds/years/sectors; renderer-neutral payloads; pipeline records limitations instead of silently substituting methods.

## API / worker

- `contracts/tasks.py` (versioned ML task recipe, same pattern as `contracts/recipes.py`);
  `api/routers/models.py` — `POST /api/v1/models` (validate task + sealed dataset version, enqueue TRAIN job), `GET /api/v1/models/{run_id}` + metrics + explanations.
- `services/model_training.py` — TrainWorkflow (JobType.TRAIN already exists in the enum), registered in `build_default_registry()`.

## Invariants to enforce in code + tests

- Preprocessing fitted on inner-train only, per fold; no future/test information in features.
- Split-family compatibility rejected at task validation.
- Seed recorded and used for every stochastic step; same seed+data+recipe → same metrics (determinism test).
- Every ML model compared against the relevant baselines; final refit only after evaluation completes.
- Model package stores feature schema + hashes + environment; load-time compatibility check.
- SHAP only for supported fitted tree models, bounded by MAX_SHAP_ROWS (2000) and background size.
- No placeholder branches; capabilities list only what is implemented and tested.

## Validation plan

- Unit: split generators (train/test key disjointness per fold; unseen-station claim has disjoint stations); baselines vs hand-computed values; preprocessing fold-locality; metrics vs hand-computed; determinism under fixed seed; artifact round-trip + tamper detection.
- E2E: upload fixture → seal version → POST model task (unseen-station setting + station-group split) → worker TRAIN job → run succeeded with fold metrics + baseline comparison + SHAP payload; incompatible setting → 422.
- Gates: ruff/format/mypy strict; pytest coverage ≥90% overall (contracts/hashing/normalization ≥95%); contract snapshot + compatibility note updated; no-stub scan; wheel build/import.

## Risks / open questions

- Keep xgboost CPU-only in CI; record device in the environment capture.
- Bound SHAP cost via MAX_SHAP_ROWS and background size; skip with a recorded limitation rather than stall.
- Quantile uncertainty needs a quantile-loss regressor (sklearn HistGradientBoostingRegressor loss="quantile"); add to the registry when that uncertainty method is selected.
