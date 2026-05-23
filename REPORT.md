# Report format

A walkthrough of the canonical evaluation report at `eval/reports/<job-name>.html`. The report is a single self-contained HTML file with pure-CSS tabs (no JavaScript). Open it in any browser; everything stays interactive without a build step or a server.

## Top-level layout

Three tabs at the top:

1. **Dashboard** — one-line summary per trial: Track A score, Track B score, framework gate, |Δ| flag. Trials are grouped by task with the oneshot and iter variants on adjacent rows. This is the view to scan headline performance.
2. **Diversity** — horizontal carousels of full-page reference screenshots per task. A quick eyeball check that the designs span genuinely distinct styles, components, and complexity profiles.
3. **One tab per task** (`task_1`, `task_2`, …) — drill into a single design. Each task tab contains the full per-trial breakdown for both variants.

## Per-task tab structure

Inside each task tab:

### Variant sub-tabs — oneshot / iterative

Switch between the two variants of the same design. Both variants share the same reference; only the agent's HTML output differs.

### Per-trial body

For the active variant, the body shows:

- **Headline scores**: Track A (objective, deterministic), Track B (LLM-as-judge on 1-5 scale, normalised to [0, 1]), framework_compliance gate (1.0 pass / 0.3 violation).
- **Per-criterion table**: each of the 6 criteria with its Track A score and Track B score side by side. Disagreements > 0.1 are highlighted.
- **Viewport sub-tabs** (desktop / tablet / mobile) — switch between reference-vs-agent screenshot comparisons.
- **Per-question Track B verdict grid** (collapsible, per criterion).

### Viewport sub-tabs

For each viewport, two full-page screenshots are shown side by side:

- **Reference** (left) — the canonical design captured at recipe time
- **Agent** (right) — what the agent produced, freshly rendered from `artifacts/output/<page>.html`

The image strip lets you scroll both pages and visually verify what the SSIM-based `layout_structure` score reflects.

### Track B verdict grid (per criterion)

A collapsible details block expands into a grid: rows are pages (or page+viewport for per-viewport-scoped criteria, or individual components for `component_presence`); columns are the criterion's question IDs. Each cell is the judge's 1-5 verdict for that (question, context) pair, color-graded:

| Cell color | Verdict | Meaning |
|---|---|---|
| Deep green | **5** | matches indistinguishably |
| Light green | **4** | mostly matches; minor differences |
| Yellow | **3** | partial match; visible difference |
| Orange | **2** | major divergence |
| Red | **1** | no match |

The criterion's Track B score is the mean of all cells normalised via `(mean - 1) / 4`.

## Score interpretation

- **Track A and Track B are reported side by side, never averaged.** Where they agree, you have high confidence. Where they disagree by > 0.1, the trial is flagged for spot review — that gap is itself information.
- **The framework_compliance gate is multiplicative**: a trial with a violation (gate 0.3) shows a final score that's 30% of the raw weighted mean. Look at `raw_score_objective` / `raw_score_judge` for the pre-gate values.

## Regenerating the report

`run_eval.py` and `regrade_job.py` both auto-render at the end. To render manually against an existing job:

```bash
python eval/reports/render_report.py jobs/<job-name>/
```

Output: `eval/reports/<job-name>.html`.
