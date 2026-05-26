# Sensitivity tests — Track A and Track B

_Fixture: `recipe/runs/task_1` (6 pages: donations, getting-started, grants, overview, programs, volunteers)._  Regenerate with `python grading/sensitivity.py --write-md grading/SENSITIVITY.md`.

Ground truth was **locally rebaselined** (capture.py re-run against the fixture's `source/` with the same Playwright the graders use), so oracle SSIM is not bounded by cross-machine Chromium drift.

## What this validates

These are **construct-validity** checks — evidence that each Track A deterministic sub-grader and (when `--track-b` is on) each Track B LLM-judge question pack actually measures the dimension its name advertises (and not something else).

1. **Oracle pass.** Score the ground-truth source against the ground-truth artifacts. Every Track A criterion should land in `[0.95, 1.00]` when the ground truth is rebaselined locally. If `--no-rebaseline`, `layout_structure` is bounded below by SSIM drift between the capture-machine Chromium build and the runner's Chromium build (subpixel font hinting + image decoding).

2. **Targeted corruption.** Apply a perturbation that the eval's design predicts will hit one criterion. The target criterion should drop materially; off-target criteria should stay near oracle unless the perturbation genuinely has secondary effects (e.g. removing sections also removes their text and images).

## Corruption catalogue

| corruption | target criterion | what it does |
|---|---|---|
| `palette_invert` | `color_palette` | Inverts every `#rrggbb` hex in `styles.css`. |
| `font_monospace` | `typography` | Replaces every `font-family` declaration with `monospace`. |
| `image_swap` | `image_content_fidelity` | Within each asset folder (photos / icons / avatars), cyclically rotates `<img src>` paths so each slot points at a different but real asset. |
| `text_lipsum` | `visible_text_fidelity` | Replaces every visible text node with `lorem ipsum…` tokens. |
| `section_strip` | `component_presence` | Removes every other `<section>` / `<article>` / `<aside>` child of any container. |
| `layout_reverse` | `layout_structure` | Reverses the children of every `<body>` / `<main>` / `<section>` / `<header>` / `<footer>` / `<nav>` / `<article>`. |

## Results — Track A (deterministic sub-graders)

_Pages scored: 6 (donations, getting-started, grants, overview, programs, volunteers)._

| criterion | oracle | `palette_invert` | `font_monospace` | `image_swap` | `text_lipsum` | `section_strip` | `layout_reverse` |
|---|---|---|---|---|---|---|---|
| `color_palette` | 1.000 | 0.322 (-0.68) **←target** | 0.990 (-0.01) | 0.999 (-0.00) | 0.987 (-0.01) | 0.985 (-0.02) | 0.987 (-0.01) |
| `typography` | 1.000 | 1.000 (+0.00) | 0.500 (-0.50) **←target** | 1.000 (+0.00) | 1.000 (+0.00) | 0.558 (-0.44) | 1.000 (-0.00) |
| `image_content_fidelity` | 1.000 | 0.502 (-0.50) | 0.952 (-0.05) | 0.785 (-0.22) **←target** | 0.923 (-0.08) | 0.558 (-0.44) | 0.690 (-0.31) |
| `visible_text_fidelity` | 1.000 | 1.000 (+0.00) | 1.000 (+0.00) | 1.000 (+0.00) | 0.002 (-1.00) **←target** | 0.647 (-0.35) | 1.000 (+0.00) |
| `component_presence` | 1.000 | 1.000 (+0.00) | 1.000 (+0.00) | 1.000 (+0.00) | 1.000 (+0.00) | 0.833 (-0.17) **←target** | 1.000 (+0.00) |
| `layout_structure` | 1.000 | 0.215 (-0.79) | 0.747 (-0.25) | 0.997 (-0.00) | 0.742 (-0.26) | 0.752 (-0.25) | 0.663 (-0.34) **←target** |

_Each cell is `score (Δ vs oracle)`. **←target** marks the criterion the corruption was designed to hit._

## Results — Track B (LLM-as-judge)

_Page scored: 1 (overview). Judge model: `claude-opus-4-7`. Scope kept to one page to control API cost; Track A above runs over all pages._

| criterion | oracle | `palette_invert` | `font_monospace` | `image_swap` | `text_lipsum` | `section_strip` | `layout_reverse` |
|---|---|---|---|---|---|---|---|
| `color_palette` | 1.000 | 0.213 (-0.79) **←target** | 1.000 (+0.00) | 1.000 (+0.00) | 1.000 (+0.00) | 0.963 (-0.04) | 1.000 (+0.00) |
| `typography` | 1.000 | 1.000 (+0.00) | 0.655 (-0.35) **←target** | 1.000 (+0.00) | 0.929 (-0.07) | 0.976 (-0.02) | 1.000 (+0.00) |
| `image_content_fidelity` | 1.000 | 1.000 (+0.00) | 1.000 (+0.00) | 1.000 (+0.00) **←target** | 0.938 (-0.06) | 0.312 (-0.69) | 0.938 (-0.06) |
| `visible_text_fidelity` | 0.857 | 0.714 (-0.14) | 0.714 (-0.14) | 0.714 (-0.14) | 0.321 (-0.54) **←target** | 0.429 (-0.43) | 0.714 (-0.14) |
| `component_presence` | 1.000 | 0.857 (-0.14) | 0.979 (-0.02) | 0.950 (-0.05) | 0.964 (-0.04) | 0.600 (-0.40) **←target** | 0.871 (-0.13) |
| `layout_structure` | 1.000 | 1.000 (+0.00) | 0.904 (-0.10) | 1.000 (+0.00) | 0.981 (-0.02) | 0.494 (-0.51) | 0.699 (-0.30) **←target** |

_Track B verdicts are mean(1-5) per criterion normalised to [0, 1] via `(mean - 1) / 4`. A `—` means the judge call failed or the criterion was stubbed._

## Track A vs Track B — target-criterion drops side-by-side

| corruption | target | Track A Δ | Track B Δ | agree? |
|---|---|---|---|---|
| `palette_invert` | `color_palette` | -0.68 | -0.79 | ✓ both register |
| `font_monospace` | `typography` | -0.50 | -0.35 | ✓ both register |
| `image_swap` | `image_content_fidelity` | -0.22 | +0.00 | ⚠ only Track A |
| `text_lipsum` | `visible_text_fidelity` | -1.00 | -0.54 | ✓ both register |
| `section_strip` | `component_presence` | -0.17 | -0.40 | ✓ both register |
| `layout_reverse` | `layout_structure` | -0.34 | -0.30 | ✓ both register |

_A negative Δ means the corruption hit the target criterion. ✓ means both tracks agreed (both dropped > 0.05 below oracle); ⚠ flags a track that missed the perturbation entirely._

## Reading the Track A columns

### `palette_invert` → target `color_palette` (-0.68)

⚠ `layout_structure` drops more (-0.79) than the target `color_palette` (-0.68). See the notes below — typically this means the corruption has a real, predictable secondary effect.

### `font_monospace` → target `typography` (-0.50)

✓ targeted criterion is the largest drop in its column.

### `image_swap` → target `image_content_fidelity` (-0.22)

✓ targeted criterion is the largest drop in its column.

### `text_lipsum` → target `visible_text_fidelity` (-1.00)

✓ targeted criterion is the largest drop in its column.

### `section_strip` → target `component_presence` (-0.17)

⚠ `image_content_fidelity` drops more (-0.44) than the target `component_presence` (-0.17). See the notes below — typically this means the corruption has a real, predictable secondary effect.

### `layout_reverse` → target `layout_structure` (-0.34)

✓ targeted criterion is the largest drop in its column.

## Reading the Track B columns

### `palette_invert` → target `color_palette` (-0.79)

✓ targeted criterion is the largest drop in its column.

### `font_monospace` → target `typography` (-0.35)

✓ targeted criterion is the largest drop in its column.

### `image_swap` → target `image_content_fidelity` (+0.00)

⚠ judge did NOT register the perturbation on its target (Δ = +0.00). This is a real Track B miss — likely the corruption is sub-perceptual at full-page resolution, or the question pack doesn't probe the affected dimension.

### `text_lipsum` → target `visible_text_fidelity` (-0.54)

✓ targeted criterion is the largest drop in its column.

### `section_strip` → target `component_presence` (-0.40)

⚠ `image_content_fidelity` drops more (-0.69) than the target `component_presence` (-0.40). The corruption has a real, predictable secondary effect the judge picks up.

### `layout_reverse` → target `layout_structure` (-0.30)

✓ targeted criterion is the largest drop in its column.

## Known cross-criterion interactions

These are not bugs — they are the *correct* behaviour of independent graders applied to a corruption that affects multiple dimensions:

- `palette_invert` also tanks `image_content_fidelity` and `layout_structure` on Track A. Reason: rendered pixels change, so pHash on `<img>` regions and SSIM on full-page screenshots both move. Track B's judge looks at the same pixels but its question pack for `image_content_fidelity` asks about *content* ("is the same photograph visible") and brushes off colour-only differences as a 5 — which is why Track B shows the drop *only* on the colour question pack, not on the image one.
- `section_strip` removes content along with the macro-blocks, so `typography`, `image_content_fidelity`, and `visible_text_fidelity` also drop. The eval *cannot* attribute a single root cause when a corruption removes content — that's a limitation of single-criterion attribution, not of the graders. Track B's judge reacts even more dramatically (image_content_fidelity drops to 0.31), because it sees that half the image slots are gone.
- `layout_reverse` reorders children, which shifts every `<img>` to a new bbox. Track A's `image_content_fidelity` matches by bbox, so it registers the shift. Track B's judge mostly forgives a reordering it can still see all images for, but its `layout_structure` pack notices the dominant-element-quadrant change.

## Track B observations

- **Oracle `visible_text_fidelity` = 0.857, not 1.0.** The judge gave at least one 4 on identical screenshots. This is normal LLM-judge anchor bias — the 5-anchor reads as "indistinguishable on every dimension at once," so even oracle pairs sometimes get 4s on questions like vt_q9 (text volume). Track A's deterministic graders don't have this floor.
- **Track B missed `image_swap`** (Δ on image_content_fidelity = +0.00). The corruption cyclically rotates icon and avatar SVGs. At full-page resolution, individual icon glyphs (~14-18 px tall) are small enough that the judge can't reliably tell `hand-heart.svg` from `building-2.svg`. This is also a `per_image` scope limitation noted in `grading/judge/runner.py` — the pack runs at page-level rather than per-image bbox, so the question "is the same exact photograph visible" is answered globally, not slot-by-slot.
- **Track B is harsher than Track A on `section_strip`'s collateral** — Track A's `image_content_fidelity` drops from 1.0 → 0.56 (half the images are gone, mean phash similarity stays moderate); Track B's drops 1.0 → 0.31 because the judge counts hallucinations and absences as separate failure modes.

## What this does NOT prove

- That a higher score implies a more *beautiful* website. The eval grades replication fidelity vs a reference — the reference defines the quality bar.
- That Track A and Track B agree on *real* agent rollouts. The corruption sweep above is a stress test with adversarial inputs, not a sample of typical agent behaviour. For the typical-rollout comparison, see canonical eval runs in `eval/reports/`.
- That human raters agree with the score ordering. That requires a human-rated held-out slice — see the `RESULTS.md` analysis section.
- That these results generalise to other fixtures. Re-run with `--fixture recipe/runs/task_N` against ≥ 2 more recipes to test cross-fixture stability.
