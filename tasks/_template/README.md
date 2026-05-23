# Harbor task template

Canonical layout for one webdev-bench Harbor task. The packager
(`recipe/03-package/package.py`) stamps out 20 of these per eval
campaign — **10 designs × 2 variants**.

This README itself is **not copied** into packaged tasks — it documents
the template scaffold for repo readers, not the task it produces.

The two variants per design (`<task_id>-oneshot` and `<task_id>-iter`)
intentionally differ in only two places — the agent-facing surface:

| File | `-oneshot` value | `-iter` value |
|---|---|---|
| `environment/Dockerfile` | `FROM webdev-bench/base-html-css-oneshot:latest` | `FROM webdev-bench/base-html-css-iter:latest` |
| `instruction.md` | (no iter-tools section) | mentions the `render` helper at `/usr/local/bin/render` |

`ground_truth/`, `tests/`, and `solution/solve.sh` are byte-identical
between the two variants. `task.toml` and
`task_config.json` are functionally identical but legitimately carry
the variant token in their identifier fields (`task.toml.id =
"task_N-oneshot"` / `"task_N-iter"`, `task_config.json.variant =
"oneshot"` / `"iter"`).

Placeholders in this template are written as `{{ NAME }}`. The packager
substitutes them at copy time:

| Placeholder | Source |
|---|---|
| `{{ TASK_ID }}` | `task_1`, `task_2`, … (sequential) |
| `{{ VARIANT }}` | `oneshot` or `iter` |
| `{{ DESIGN_DESCRIPTION }}` | from `recipe/runs/<task_id>/design.json` `description` |
| `{{ PAGES_LIST }}` | bullet list of canonical page filenames |
| `{{ ALLOWED_FRAMEWORKS }}` | from design doc — `html-css` |
| `{{ BASE_IMAGE }}` | `base-html-css-oneshot` or `base-html-css-iter` |
| `{{ ITER_TOOLS_SECTION }}` | empty for oneshot; tools blurb for iter |

## Verifier ↔ task layout

At eval time, Harbor's separate-mode verifier mounts the task directory
and the agent's output into the verifier container as:

```
/grading/
  agent_output/          ← copied by Harbor from the agent container's /workspace/output/
  ground_truth/          ← this task's ground_truth/
  task_config.json       ← this task's task_config.json
  tests/                 ← this task's tests/
  grading/               ← the project-wide grading/ package (criteria, gates, aggregator)
```

The per-criterion `tests/<name>/check.py` files use these conventional
paths to find the agent output, ground truth, and the shared grader code.
