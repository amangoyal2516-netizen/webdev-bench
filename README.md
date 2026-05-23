# webdev-bench

A scalable Harbor recipe for generating RL environments that test coding agents at **design replication** of a website. Each task presents an agent with full-page screenshots of a multi-page website; the agent must reproduce the design in HTML + CSS. Functionality is out of scope — outputs are graded on what the user's eye sees.

## Documentation in this repo

| File | Purpose |
|---|---|
| `README.md` | This file — overview, setup, and commands to run the pipeline end to end |
| `DESIGN.md` | Pipeline walkthrough + design rationale — what each stage does, why it was built that way, trade-offs accepted |
| `REPORT.md` | Guide to reading the canonical HTML report — dashboard, per-task tabs, verdict grid, score interpretation |
| `RESULTS.md` | Analysis of the latest canonical run — Track A vs B comparison, where agents excel / struggle, oneshot vs iter, concrete examples |
| `CLAUDE.md` | Orientation for AI assistants (e.g. Claude Code) working in this repo |

## Latest canonical eval report

A fully-rendered HTML report for the most recent canonical run lives at:

```
eval/reports/webdev-bench-20260523-164957.html
```

The filename embeds the run's timestamp; it changes when a new canonical run is fired (we'll update this pointer when that happens). The file is self-contained — open it in any browser, no server needed.

See **`REPORT.md`** for a guide to what's in the report — dashboard layout, per-task tabs, viewport sub-tabs, the Track B verdict grid, and how to read scores.

## What's in the box

**Recipe pipeline.** An *author LLM* picks a site type (project management tool / magazine homepage / fitness tracker / nonprofit dashboard / …) from a controlled vocabulary, plus a target audience and design mood, and emits a structured `design.json` listing pages and per-page components. A *per-page builder LLM* turns the design into HTML + CSS. Assets — photos, fonts, icons, avatars — are drawn from a fixed pre-vendored pool so designs are reproducible. The capture step screenshots each page at desktop / tablet / mobile, extracts ground-truth artifacts (DOM bboxes, palette, typography, text, image pHashes), and the packager emits two Harbor tasks per design (`-oneshot` and `-iter`).

**Dual-track grading.** Every rollout produces two scores side by side, never fused:

- **Track A (deterministic).** Weighted mean of six sub-graders: `layout_structure` (SSIM on full-page screenshots), `component_presence` (macro-block geometric count match), `color_palette` (k-means in LAB + Earth-Mover's-Distance with CIEDE2000), `typography` (computed `font-family` + `font-size` + `font-weight` + `line-height` per text node, area-weighted), `image_content_fidelity` (pHash at matched bboxes + OCR on text-in-images), `visible_text_fidelity` (Sørensen-Dice for short labels, ROUGE-L for body copy). Every term is a deterministic algorithm describable in two sentences.
- **Track B (LLM-as-judge).** Same six criteria, each decomposed into an atomic question pack. Verdicts on a 1-5 anchored scale (`5` = matches indistinguishably, `1` = no match), normalised to [0, 1] via `(mean - 1) / 4`.
- **`framework_compliance` × 0.3 gate** multiplies both tracks' final scores when the agent violates the framework constraint.
- The two final scores are emitted side-by-side; |Δ| > 0.1 flags rollouts for spot review.

**Two variants per design.** Every task is packaged twice: `-oneshot` (agent writes HTML/CSS blind from screenshots) and `-iter` (agent additionally has a `render` helper for one verification screenshot per page). The A/B comparison evaluates whether minimal visual feedback meaningfully improves design replication.

See **`DESIGN.md`** for the full design walkthrough — pipeline stages, rationale behind each choice, trade-offs accepted.

## Prerequisites

### Minimum — to run eval against the 20 shipped tasks

```bash
# Clone
git clone <url> webdev-bench
cd webdev-bench

# Install Harbor + Modal extra
uv tool install harbor
uv tool install harbor-rewardkit
uv tool install --force 'harbor[modal]'

# Install + authenticate Modal CLI (one-time; opens a browser)
pip install modal
modal token new

# Create a Modal secret holding your Anthropic API key
# (referenced inside Modal containers as "anthropic-key")
modal secret create anthropic-key ANTHROPIC_API_KEY=sk-ant-...

# Set the local Anthropic key (used for local-side regrade + report paths)
export ANTHROPIC_API_KEY=sk-ant-...
```

The repo ships with **10 designs × 2 variants = 20 pre-packaged tasks** under `tasks/` (the `-oneshot` and `-iter` pair per design — see "What's in the box" above). You can run eval immediately; task generation is only needed if you want fresh designs.

### Additional — to generate new tasks

```bash
# One-time seed of the asset-pools Modal Volume with photos / fonts /
# icons / avatars from infra/assets/. Idempotent; safe to re-run.
python scripts/seed_modal_volumes.py
```

## Pipeline commands

End-to-end, the loop is: **generate tasks → run eval → re-grade (optional) → view report.**

### 1. Generate tasks

```bash
python scripts/generate_tasks.py --count 10
```

Fans out across Modal sandboxes — one sandbox per task — and pulls finished tasks back to `tasks/task_N-{oneshot,iter}/`.

| Flag | Default | Notes |
|---|---|---|
| `--count N` | required (or `--ids`) | Number of new tasks to generate. Auto-numbered from existing IDs in `--output-dir`. |
| `--ids task_2,task_7` | — | Explicit IDs to regenerate (e.g. retrying failed tasks). Skips `--count`. |
| `--start-id N` | auto | Override the auto-derived starting ID. Escape hatch. |
| `--output-dir` | `tasks/` | Batch namespace. Multiple batches can coexist in different dirs. |
| `--dry-run` | off | Show what would be done; don't call Modal. |

### 2. Run eval

```bash
# Full canonical run (all tasks, both variants, on Modal at 32-way parallel)
python scripts/run_eval.py

# Quick smoke (3 oneshot tasks)
python scripts/run_eval.py --quick

# Subset
python scripts/run_eval.py --tasks task_3,task_8 --variants oneshot

# Track A only (no API spend on Track B)
python scripts/run_eval.py --no-track-b
```

Discovers tasks, builds a `JobConfig` in memory, fires `harbor run`, and auto-renders the HTML report when done. Outputs land at `jobs/webdev-bench-<timestamp>/`.

| Flag | Default | Notes |
|---|---|---|
| `--tasks-dir` | `tasks/` | Dir to discover packaged tasks from. |
| `--variants` | `oneshot,iter` | Comma-separated subset. |
| `--tasks` | all | Comma-separated task ID subset (e.g. `task_3,task_8`). |
| `--quick` | off | Smoke against 3 oneshot tasks. |
| `--n-attempts N` | `1` | Rollouts per task. |
| `--concurrent N` | `32` | Max parallel trials on Modal. |
| `--agent` | `claude-code` | Harbor agent name. |
| `--model` | `claude-opus-4-7` | Agent model. |
| `--env` | `modal` | `modal` or `docker`. |
| `--no-track-b` | off | Skip the LLM-judge grading pass. |
| `--job-name` | auto-timestamped | Explicit job name; collides loudly if the dir exists. |
| `--dry-run` | off | Validate the JobConfig and exit without firing. |

### 3. Re-grade an existing job (no agent re-run)

Track A is deterministic and Track B is cache-keyed on content, so re-running grading after a code change is cheap. Two paths — local and Modal:

```bash
# Local — re-grades sequentially (concurrent>1 to parallelise; respects Anthropic rate limits)
python scripts/regrade_job.py jobs/<job-name>/ --backup --concurrent 4

# Modal — parallel across trials
modal run -m infra.modal.judge_app::regrade --job-dir jobs/<job-name>/
```

The local script (`scripts/regrade_job.py`):

| Flag | Default | Notes |
|---|---|---|
| `job_dir` (positional) | required | Path to `jobs/<job-name>/`. |
| `--tasks-dir` | `tasks/` | Where to look up task ground truth. |
| `--weights` | `tasks/_template/tests/_weights.toml` | Per-criterion weights. |
| `--no-track-b` | off | Skip Track B (free, fast, deterministic-only). |
| `--judge-cache-dir` | `grading/judge/_cache/` | Override the local verdict cache. |
| `--backup` | off | Save `verifier/{grading,reward}.json` as `.original-<ts>.json` before overwriting. |
| `--concurrent N` | `1` | Trials to regrade in parallel. |
| `--no-render` | off | Skip the post-regrade HTML report render. |
| `--render-all-tasks` | off | Render Diversity tab with the full dataset (not just trials present). |

### 4. Render a job's HTML report

`run_eval.py` and `regrade_job.py` both auto-render at the end. To render manually:

```bash
python eval/reports/render_report.py jobs/<job-name>/
```

Output: a self-contained HTML at `eval/reports/<job-name>.html` with per-trial Track A vs Track B scores, the verdict grid for each Track B question, and reference-vs-agent screenshot comparisons at three viewports per page.

## Key principles

- **Design only, not functionality.** Routing, accessibility tags, JS behavior, form handling — none of these are graded.
- **Dual-track grading.** Track A is fully deterministic (no embeddings, every sub-score a closed-form algorithm); Track B is an LLM-as-judge channel using atomic questions on a 1-5 anchored scale. Both scores are reported side-by-side, never fused — disagreement is itself a signal.
- **Strict information barrier.** Agent sees only screenshots, vendored assets, and `instruction.md`. Ground-truth source, pre-computed artifacts, and judge question packs are isolated in a separate verifier container.
- **Per-task vendored assets.** The agent doesn't search for images on the open web; the same vendored files are mounted to both agent and verifier.
- **Pre-computed reference data.** Bboxes, palette, typography, image pHashes, text — all computed at recipe time. The grader reads JSON; no ground-truth re-extraction at run time.
