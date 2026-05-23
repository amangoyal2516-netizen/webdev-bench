# RESULTS.md — Analysis of the canonical run

## 1. Overview

**Run**: `jobs/webdev-bench-20260523-164957/` — fired on Modal at 32-way concurrency. Agent: Claude Code Opus 4.7. Twenty trials total (10 designs × 2 variants: `-oneshot` and `-iter`). Track B (LLM-as-judge) on the same Claude Opus 4.7 model used as the judge.

**Headline results**:

| Stat | Value |
|---|---|
| Track A mean (deterministic) | **0.729** |
| Track B mean (LLM judge, 1-5 anchored) | **0.838** |
| Track B − Track A gap | **+0.109** |
| Framework gate violations | **0 / 20** |

Every trial passed `framework_compliance` (no agent emitted React/Vue/JSX), so all 20 final scores are the raw weighted mean × 1.0, not deflated by the 0.3× gate.

## 2. How to read the scores

A higher score means the agent's output is closer to a pixel-perfect, exact-asset, exact-font replica of the reference. Each of the six criteria is a number in [0, 1] that ports a different sub-question:

| Criterion | Higher score means |
|---|---|
| `layout_structure` | Reference and agent renders look the same at every viewport (SSIM on full-page screenshots). |
| `component_presence` | The agent rendered the right number of major page blocks (header, hero, cards, sidebar, etc.). |
| `color_palette` | The agent's rendered palette matches in dominance and proportion (k-means + CIEDE2000 in LAB). |
| `typography` | The DOM's computed `font-family` + size + weight + line-height match per text node, area-weighted. |
| `image_content_fidelity` | Each `<img>` at each position pixel-matches the reference image (pHash) and any in-image text matches (OCR). |
| `visible_text_fidelity` | Tokenised DOM `textContent` overlaps with the reference text (Sørensen-Dice for short, ROUGE-L for long). |

The final score is a **weighted mean × multiplicative gate**:

```
final = (Σ w_i · s_i) / Σ w_i  ×  gate
```

where weights are `layout_structure: 2.5, component_presence: 2.0, color_palette: 1.5, typography: 1.5, image_content_fidelity: 1.5, visible_text_fidelity: 1.0`, and `gate ∈ {1.0, 0.3}` from `framework_compliance`. The 0.3 gate caps a framework-violator at 30% of what they would otherwise score.

### Why the two tracks aren't averaged together

Track A and Track B measure the *same six criteria* with *the same weights*, but they ask the question differently — A is pixel-deterministic, B is perceptual via an MLLM. The two scores are reported **side by side, never averaged**. A trial scoring 0.8 / 0.4 (deterministic good, perceptual harsh) describes a different agent behaviour than a trial scoring 0.6 / 0.6 (both judges middling), and averaging them would collapse two interpretable signals into one uninterpretable one.

### Reading a real example

The top-scoring trial in this run (`task_7-iter`) scored **A = 0.843, B = 0.868** — both tracks agree the agent did very well. The bottom trial (`task_5-iter`) scored **A = 0.607, B = 0.720** — both tracks agree the agent struggled (both well below the run mean), with Track B's perceptual judgement slightly more forgiving than Track A's pixel-strict measurement. When the two tracks agree, the score is trustworthy. When they disagree by > 0.1, the disagreement is itself the interesting signal (see §3 and §4).

## 3. Track A vs Track B — strengths and how they complement

### Track A's strengths

- **Deterministic and reproducible**: bit-identical scores across re-runs of the same artifact. Two grades of the same agent output always produce the same number.
- **Fast and cheap**: < 30 seconds per trial after the agent's HTML lands; no model API spend after one Playwright render pass.
- **Auditable**: every score traces back to closed-form math (SSIM, pHash, k-means + CIEDE2000, computed-style match, Hungarian-assigned macro-blocks, ROUGE-L).
- **Stays within the "no embeddings, no learned models" purity constraint** — every term is a closed-form algorithm describable in two sentences.

### Track B's strengths

- **Perceptual**: "does this look similar to a human?" is precisely the kind of judgment an MLLM is good at.
- **Semantic**: catches paraphrased body copy, hallucinated facts, missing paragraphs — drift that token-overlap metrics in Track A smooth over (its `vt_q5`, `vt_q6`, `vt_q8` carry this signal).
- **Cross-attribute holistic reasoning**: judges questions like "does the color mood match?", "is the dominant element in the same screen quadrant?", or "does the layout reflow correctly?" that closed-form math can't easily express.
- **Reads text inside images** via vision — banner copy, signage, baked-in SVG labels that Track A's DOM `textContent` can't see.
- **Atomic-question structure**: when a criterion's score is low, the verdict grid shows *which question* failed — direct traceability from headline to root cause.

### How they complement each other

Track A and Track B are two lenses on the same artifact, asking different questions about it. Track A measures **pixels and computed values**; Track B measures **perception and meaning**. The dual-track design is built around three properties of this complement:

- **Triangulation when they agree**: when both tracks score a trial similarly (|Δ| ≤ 0.1), the score is trustworthy from two independent measurement systems. `color_palette` and `component_presence` sit here in this run.
- **Disagreement as signal**: when |Δ| > 0.1 on a criterion, the gap points at the dimension where pixel-strictness and perceptual judgement legitimately diverge. In this run, that's `image_content_fidelity` (+0.305, Track B more generous), `layout_structure` (+0.175, Track B more generous), `typography` (+0.102, Track B more generous), and `visible_text_fidelity` (−0.196, *Track A* more generous because it can't catch fact drift). Each gap is interpretable and directional, not noise.
- **Independent failure modes**: a Track B API outage doesn't kill the trial — Track A still produces a valid `reward.json`. A Track A grader bug surfaces against Track B's perceptual judgement before it ships unnoticed.

The result is no single failure mode and no single measurement blindspot — for every dimension that one track can't measure cleanly, the other can.

## 4. Where the agent excels and where it struggles

Per-criterion means rank the dimensions cleanly:

| Criterion | Track A | Track B |
|---|---|---|
| `color_palette` | **0.910** | 0.947 |
| `visible_text_fidelity` | **0.902** | 0.706 |
| `component_presence` | **0.808** | 0.902 |
| `typography` | **0.746** | 0.849 |
| `layout_structure` | **0.584** | 0.758 |
| `image_content_fidelity` | **0.549** | 0.854 |

### Where agents do well

Color palette, text token overlap, component count, and (since the fonts-to-declare fix) typography family declarations. All 20 trials also passed `framework_compliance` — no agent shipped JSX, React, or a bundler. Both tracks agree on these wins.

### Where agents struggle

- **Pixel-precise layout**. SSIM stays in 0.5–0.7. The strict layout questions confirm: `ls_q14_v2` (page height ±10%) has only **1.5%** top-rate; `ls_q15` (adjacent spacing ±20%) only **0.0%**; `ls_q16` (region proportions ±10%) only **3.0%**. Agents almost never ship a page that's dimensionally exact.
- **Exact asset selection**. `image_content_fidelity` Track A 0.549 — even with the matching-by-position instruction, agents still pick a plausible-but-different photo often enough to drag the score. Track B's `img_q1_v3` (mean 3.57, 49% top-rate, 31% bottom-rate ≤ 2) registers it too.
- **Fact-level text fidelity**. Track A 0.902 vs Track B 0.706 on `visible_text_fidelity` — agents reproduce the right *words* (token overlap works), but the judge catches drift in numbers, entity names, and missing paragraphs that closed-form metrics smooth over.

### Behaviour patterns inferred from the data

1. **"Approximate, don't measure" on dimensions.** Every strict tolerance question on `layout_structure` shows top-rate under 7%. Agents reach for plausible spacing rather than computing widths from the reference.
2. **"Right kind, wrong specific" on assets.** Pixel-strict pHash diverges from holistic judge by +0.31 on `image_content_fidelity`. Agents pick from the right pool but not always the exact reference image at each position.
3. **High token overlap, lower fact fidelity.** Track A says the words are right; Track B says the meaning has drifted.

## 5. Oneshot vs iterative — does the render helper actually help?

The `-iter` variant differs from `-oneshot` only in one capability: the agent can call a `render` helper that screenshots its own HTML at a chosen viewport, and is told to use it *once per page after that page is fully written* (the soft contract documented in DESIGN.md §3).

### Render-helper usage in this run

All 10 iter agents used the render helper. Render-call counts per trial:

| Trial | Render calls | Distinct pages |
|---|---|---|
| `task_1-iter` | 6 | 6 |
| `task_2-iter` | 7 | 6 |
| `task_3-iter` | 8 | 6 |
| `task_4-iter` | 5 | 5 |
| `task_5-iter` | 5 | 5 |
| `task_6-iter` | 5 | 5 |
| `task_7-iter` | 6 | 6 |
| `task_8-iter` | 6 | 6 |
| `task_9-iter` | 5 | 5 |
| `task_10-iter` | 6 | 6 |

Eight of ten followed the contract exactly (one render per distinct page). `task_2` and `task_3` re-rendered one and two pages respectively. No agent ran a render spree — instruction-only soft enforcement held.

### Iter vs oneshot per task

| Task | Oneshot A | Iter A | ΔA | Oneshot B | Iter B | ΔB |
|---|---|---|---|---|---|---|
| `task_1` | 0.712 | 0.768 | **+0.056** | 0.886 | 0.861 | −0.025 |
| `task_2` | 0.646 | 0.801 | **+0.155** | 0.864 | 0.891 | +0.027 |
| `task_3` | 0.725 | 0.682 | −0.043 | 0.893 | 0.837 | −0.055 |
| `task_4` | 0.723 | 0.691 | −0.032 | 0.774 | 0.791 | +0.016 |
| `task_5` | 0.634 | 0.607 | −0.026 | 0.763 | 0.720 | −0.043 |
| `task_6` | 0.719 | 0.758 | **+0.039** | 0.862 | 0.878 | +0.016 |
| `task_7` | 0.781 | 0.843 | **+0.063** | 0.795 | 0.868 | +0.073 |
| `task_8` | 0.684 | 0.716 | **+0.032** | 0.871 | 0.853 | −0.018 |
| `task_9` | 0.691 | 0.752 | **+0.061** | 0.755 | 0.827 | +0.072 |
| `task_10` | 0.820 | 0.819 | −0.001 | 0.884 | 0.890 | +0.006 |
| **mean** | | | **+0.030** | | | **+0.007** |
| **iter wins** | | | **6 / 10 pairs** | | | **6 / 10 pairs** |

### What this says about the value of the render helper

The effect is **directionally positive but small**:

- Track A favours iter by **+0.030** on average — modest but real. Six of ten task pairs scored higher in the iter variant.
- Track B is effectively a tie at **+0.007** — six of ten pairs in iter's favour; wins (largest +0.073 on `task_7`) and losses (largest −0.055 on `task_3`) roughly balance in magnitude.
- Individual deltas range from −0.06 to +0.16, with no clear pattern matching task type.

The contract is the explanation. One render-and-fix pass per page is enough to catch *some* misalignments (visible spacing drift, an obviously-wrong asset, a layout that doesn't match the reference's gestalt). It is not enough to drive pixel-tight precision — the strict layout questions still saturate at < 7% top-rate on both variants. To meaningfully close the layout gap, an iterative agent would need either more compute budget per page, a tighter feedback loop (e.g., pixel-diff against the reference instead of eyeballing the screenshot), or both.

Interpretation: **a single end-of-page verification render is worth the small overhead it costs, but it isn't a substitute for the precision-grading signal that the strict layout questions surface**. The render helper is a guard-rail against gross misalignments, not a path to perfect replication.

## 6. Concrete examples

Two reference / agent pairs from this canonical run — one near the top of the score distribution, one near the bottom — to ground the abstract per-criterion numbers above in visible behaviour.

### What a high-scoring trial looks like — `task_7-iter` dashboard (A = 0.843, B = 0.868)

| Reference | Agent |
|---|---|
| ![reference](./results-screenshots/task_7-dashboard-reference.png) | ![agent](./results-screenshots/task_7-dashboard-agent.png) |

Both tracks score this trial in the 0.84-0.87 band. The agent reproduced the same dark layout, same stats-card layout in the header, same active-matters table on the left with the same shape, same upcoming-deadlines panel on the right, same recent-time-entries table below. Minor differences: a few stat labels, table chip styling, sidebar button treatment. The agent didn't pixel-match every detail, but the design's identity is clearly preserved. This is what design replication looks like when the agent does well.

### What a struggling trial looks like — `task_5-iter` board (A = 0.607, B = 0.720)

| Reference | Agent |
|---|---|
| ![reference](./results-screenshots/task_5-board-reference.png) | ![agent](./results-screenshots/task_5-board-agent.png) |

Same five-column board layout, same yellow background, same card structure with chip tags. But **the recipe images don't match the reference at all** — almost every card carries a different photo than the reference's. Card order, content, and section grouping have also shifted. This trial illustrates both failure modes simultaneously:

- **Asset mismatch**: the agent picked food-style photos from the right pool but landed on different specific files for most positions. This is exactly what Track A's pHash penalises and what the `img_q1_v3` Track B question is sensitive to. `image_content_fidelity` Track A scored 0.337 on this trial.
- **Layout drift**: the columns and grid survived, but card positions and group orderings shifted. SSIM at full-page produced a score in the 0.5-0.6 band — visible-but-not-precise replication.

The two pairs together cover the range: when agents do well, both tracks reflect it consistently; when they struggle, both tracks reflect *that* consistently too. The dual-track design is doing its job — agreement at both ends of the distribution.

## 7. Where to look next

### Agent behaviour worth more investigation

- **Exact asset selection is the hardest sub-task across the rubric.** Instruction-only guidance has clear limits — agents pick from the right pool but not always the exact reference asset at each position. Worth exploring (a) a tool that lets the agent inspect candidate assets cheaply (e.g., a helper that compares a reference crop against pool items), or (b) accepting that exact-asset selection is the hardest dimension and capturing it as a known performance floor.

- **Layout precision falls off on strict tolerance questions.** Agents reach for plausible spacing rather than pixel-measured spacing. Worth exploring whether the agent benefits from being told the reference's bbox proportions (currently hidden behind the information barrier) or being given a tool that returns concrete spacing diffs against the reference.
