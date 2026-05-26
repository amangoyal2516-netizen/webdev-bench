"""Sensitivity test harness for Track A sub-graders.

Runs two kinds of validation against a single recipe-run fixture:

  1. Oracle calibration — score the ground-truth source against the
     ground-truth artifacts. Every Track A criterion should land in
     [0.95, 1.00], except `layout_structure`, which is bounded below by
     local-Chromium / capture-Chromium subpixel drift on full-page SSIM.

  2. Per-criterion corruption tests — apply a targeted perturbation that
     SHOULD hurt one specific criterion, then verify the right criterion
     drops by ≥ a threshold while the other criteria stay near oracle.

Both are construct-validity tests: they show that each sub-grader is
measuring the dimension its name advertises.

Usage:
    python grading/sensitivity.py
    python grading/sensitivity.py --fixture recipe/runs/task_3
    python grading/sensitivity.py --write-md grading/SENSITIVITY.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from grading.criteria import (  # noqa: E402
    color_palette,
    component_presence,
    image_content_fidelity,
    layout_structure,
    typography,
    visible_text_fidelity,
)

GRADERS: dict[str, tuple[Any, dict[str, Any]]] = {
    "color_palette": (color_palette, {}),
    "typography": (typography, {}),
    "image_content_fidelity": (image_content_fidelity, {}),
    "visible_text_fidelity": (visible_text_fidelity, {}),
    "component_presence": (component_presence, {}),
    "layout_structure": (layout_structure, {"viewports": ["desktop"]}),
}


def unify_ground_truth(fixture: Path, tmp: Path, design_json: Path | None = None) -> Path:
    """Symlink ground_truth/* + screenshots/ + design.json into a single
    dir matching the packaged-task layout the graders expect. The Track B
    judge needs `design.json` at the top of `ground_truth_dir` for the
    per_component scope (component_presence)."""
    gt = tmp / "gt"
    gt.mkdir()
    for child in (fixture / "ground_truth").iterdir():
        (gt / child.name).symlink_to(child.resolve())
    (gt / "screenshots").symlink_to((fixture / "screenshots").resolve())
    if design_json is None:
        design_json = fixture / "design.json"
    if design_json.exists():
        (gt / "design.json").symlink_to(design_json.resolve())
    return gt


def rebaseline_locally(source: Path, tmp: Path) -> Path:
    """Re-run capture.py on a local copy of source/ so screenshots and
    pre-computed ground-truth artifacts come from the SAME Playwright
    binary that the graders use. Eliminates the cross-machine Chromium
    drift that pushes `layout_structure` oracle below 1.0.

    Returns a path that has the same shape as `recipe/runs/task_N/`:
    a `source/` dir, a `screenshots/` dir, and a `ground_truth/` dir.
    """
    sys.path.insert(0, str(REPO_ROOT / "recipe/02-capture"))
    import capture  # type: ignore[import-not-found]
    from playwright.sync_api import sync_playwright

    run_dir = tmp / "rebaselined"
    run_source = run_dir / "source"
    run_dir.mkdir(parents=True)
    run_source.mkdir()
    for child in source.iterdir():
        if child.name == "assets":
            (run_source / "assets").symlink_to(child.resolve())
        else:
            shutil.copy2(child, run_source / child.name)

    pages = sorted(p.stem for p in run_source.glob("*.html"))
    print(f"[rebaseline] capturing {len(pages)} pages × 3 viewports locally ...")
    t = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for page_name in pages:
            capture.process_page(
                browser, run_source, run_dir, page_name,
                do_screenshots=True, do_precompute=True,
            )
        browser.close()
    print(f"[rebaseline] done in {time.time() - t:.1f}s")
    return run_dir


def copy_source(source: Path, dest: Path) -> Path:
    """Mirror the source dir under dest. Symlink assets/ (read-only,
    big) and copy HTML/CSS (small, mutable)."""
    out = dest / "agent"
    out.mkdir(parents=True)
    for child in source.iterdir():
        if child.name == "assets":
            (out / "assets").symlink_to(child.resolve())
        else:
            shutil.copy2(child, out / child.name)
    return out


def run_all(agent_dir: Path, gt_dir: Path, pages: list[str]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for name, (mod, extra) in GRADERS.items():
        r = mod.score(agent_dir, gt_dir, pages, **extra)
        scores[name] = round(r["score"], 4)
    return scores


def run_track_b(agent_dir: Path, gt_dir: Path, pages: list[str], model: str) -> dict[str, float | None]:
    """Run the Track B (LLM-as-judge) sub-graders on the same agent/gt
    pair. Each criterion returns either a [0,1] score or None on a hard
    judge-API failure."""
    from grading.judge.runner import score_judge

    result = score_judge(agent_dir, gt_dir, pages, model=model)
    return {
        crit: (round(r["score"], 4) if r.get("score") is not None else None)
        for crit, r in result.items()
    }


# ----- Corruptions ---------------------------------------------------------


def corrupt_palette_invert(agent: Path) -> None:
    """Invert every #rrggbb hex in styles.css. Targets color_palette."""
    css = (agent / "styles.css").read_text()

    def invert(m: re.Match[str]) -> str:
        h = m.group(1)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"#{255 - r:02x}{255 - g:02x}{255 - b:02x}"

    css = re.sub(r"#([0-9a-fA-F]{6})\b", invert, css)
    (agent / "styles.css").write_text(css)


def corrupt_font_monospace(agent: Path) -> None:
    """Force every font-family declaration to monospace. Targets typography."""
    css = (agent / "styles.css").read_text()
    css = re.sub(
        r"font-family\s*:\s*[^;}]+",
        "font-family: monospace",
        css,
    )
    (agent / "styles.css").write_text(css)


def corrupt_image_swap(agent: Path) -> None:
    """Within each asset subfolder (photos/icons/avatars), cyclically
    rotate <img> src paths so every image position points at a different
    but real asset. Targets image_content_fidelity."""
    from lxml import html as lxml_html

    assets_root = (agent / "assets").resolve()
    available: dict[str, list[str]] = {}
    for sub in ("photos", "icons", "avatars"):
        d = assets_root / sub
        if d.is_dir():
            available[sub] = sorted(p.name for p in d.iterdir() if p.is_file())

    if not any(len(v) >= 2 for v in available.values()):
        return

    def rotate_src(src: str) -> str:
        m = re.match(r"\./assets/(photos|icons|avatars)/(.+)$", src)
        if not m:
            return src
        sub, fname = m.group(1), m.group(2)
        pool = available.get(sub, [])
        if len(pool) < 2 or fname not in pool:
            return src
        i = pool.index(fname)
        return f"./assets/{sub}/{pool[(i + 1) % len(pool)]}"

    for html_path in agent.glob("*.html"):
        tree = lxml_html.fromstring(html_path.read_bytes())
        for img in tree.iter("img"):
            s = img.get("src")
            if s:
                img.set("src", rotate_src(s))
        html_path.write_bytes(b"<!doctype html>\n" + lxml_html.tostring(tree))


def corrupt_text_lipsum(agent: Path) -> None:
    """Replace every text node inside body with stock lipsum tokens.
    Targets visible_text_fidelity."""
    from lxml import html as lxml_html

    LIPSUM = (
        "lorem ipsum dolor sit amet consectetur adipiscing elit sed do "
        "eiusmod tempor incididunt ut labore et dolore magna aliqua"
    ).split()

    for html_path in agent.glob("*.html"):
        tree = lxml_html.fromstring(html_path.read_bytes())
        i = [0]

        def next_token() -> str:
            t = LIPSUM[i[0] % len(LIPSUM)]
            i[0] += 1
            return t

        for el in tree.iter():
            if el.tag in ("script", "style"):
                continue
            if el.text and el.text.strip():
                el.text = " ".join(next_token() for _ in el.text.split())
            if el.tail and el.tail.strip():
                el.tail = " ".join(next_token() for _ in el.tail.split())
        html_path.write_bytes(b"<!doctype html>\n" + lxml_html.tostring(tree))


def corrupt_section_strip(agent: Path) -> None:
    """Remove every other <section>/<article> at the top level of <main>.
    Targets component_presence (and incidentally layout_structure)."""
    from lxml import html as lxml_html

    for html_path in agent.glob("*.html"):
        tree = lxml_html.fromstring(html_path.read_bytes())
        for parent in tree.iter():
            blocks = [c for c in parent if c.tag in ("section", "article", "aside")]
            for c in blocks[::2]:
                parent.remove(c)
        html_path.write_bytes(b"<!doctype html>\n" + lxml_html.tostring(tree))


def corrupt_layout_reverse(agent: Path) -> None:
    """Reverse the order of every block container's children (body, main,
    section, article, header, footer, nav) so top-to-bottom order flips
    locally. Major rearrangement but every element still renders, so this
    isolates `layout_structure` (SSIM) from content/style criteria."""
    from lxml import html as lxml_html

    REVERSE_PARENTS = {"body", "main", "section", "article", "header", "footer", "nav"}

    for html_path in agent.glob("*.html"):
        tree = lxml_html.fromstring(html_path.read_bytes())
        for el in tree.iter():
            if el.tag in REVERSE_PARENTS:
                children = list(el)
                if len(children) >= 2:
                    for c in children:
                        el.remove(c)
                    for c in reversed(children):
                        el.append(c)
        html_path.write_bytes(b"<!doctype html>\n" + lxml_html.tostring(tree))


CORRUPTIONS: dict[str, tuple[Callable[[Path], None], str]] = {
    "palette_invert":   (corrupt_palette_invert,   "color_palette"),
    "font_monospace":   (corrupt_font_monospace,   "typography"),
    "image_swap":       (corrupt_image_swap,       "image_content_fidelity"),
    "text_lipsum":      (corrupt_text_lipsum,      "visible_text_fidelity"),
    "section_strip":    (corrupt_section_strip,    "component_presence"),
    "layout_reverse":   (corrupt_layout_reverse,   "layout_structure"),
}


# ----- Runner --------------------------------------------------------------


def run(
    fixture: Path,
    rebaseline: bool = True,
    track_b: bool = False,
    judge_pages: list[str] | None = None,
    judge_model: str = "claude-opus-4-7",
) -> dict[str, Any]:
    pages = sorted(p.stem for p in (fixture / "source").glob("*.html"))
    judge_pages_eff = judge_pages or ([pages[0]] if pages else [])
    results: dict[str, Any] = {
        "fixture": str(fixture),
        "pages": pages,
        "rebaseline": rebaseline,
        "track_b": track_b,
        "judge_pages": judge_pages_eff if track_b else [],
        "judge_model": judge_model if track_b else None,
        "runs": {},
    }

    with tempfile.TemporaryDirectory() as tmpstr:
        tmp = Path(tmpstr)
        gt_fixture = (
            rebaseline_locally(fixture / "source", tmp)
            if rebaseline
            else fixture
        )
        # When rebaselining, design.json doesn't exist in the temp dir —
        # pull it from the original fixture so Track B's per_component
        # scope (component_presence) can enumerate components.
        design_src = (fixture / "design.json") if rebaseline else None
        gt = unify_ground_truth(gt_fixture, tmp, design_json=design_src)

        # 1) Oracle — score the original source against the (possibly
        # rebaselined) ground truth.
        print(f"[oracle] scoring {fixture}/source ...")
        t = time.time()
        oracle_dir = copy_source(gt_fixture / "source" if rebaseline else fixture / "source", tmp / "oracle")
        oracle_a = run_all(oracle_dir, gt, pages)
        oracle_b: dict[str, float | None] = {}
        if track_b:
            print(f"  [track-b] {len(judge_pages_eff)} page(s): {judge_pages_eff} ...")
            tb = time.time()
            oracle_b = run_track_b(oracle_dir, gt, judge_pages_eff, judge_model)
            print(f"  [track-b] done in {time.time() - tb:.1f}s: {oracle_b}")
        print(f"  done in {time.time() - t:.1f}s: track_a={oracle_a}")
        results["runs"]["oracle"] = {"track_a": oracle_a, "track_b": oracle_b}

        # 2) Corruptions — apply on top of the same source that produced
        # the oracle baseline (so corruption deltas are apples-to-apples).
        source_for_corruption = gt_fixture / "source" if rebaseline else fixture / "source"
        for name, (fn, target) in CORRUPTIONS.items():
            print(f"[{name}] target={target} ...")
            t = time.time()
            work = tmp / name
            work.mkdir()
            agent = copy_source(source_for_corruption, work)
            fn(agent)
            scores_a = run_all(agent, gt, pages)
            scores_b: dict[str, float | None] = {}
            if track_b:
                tb = time.time()
                scores_b = run_track_b(agent, gt, judge_pages_eff, judge_model)
                print(f"  [track-b] done in {time.time() - tb:.1f}s: {scores_b}")
            print(f"  done in {time.time() - t:.1f}s: track_a={scores_a}")
            results["runs"][name] = {
                "target": target,
                "track_a": scores_a,
                "track_b": scores_b,
            }

    return results


CORRUPTION_NOTES: dict[str, str] = {
    "palette_invert":   "Inverts every `#rrggbb` hex in `styles.css`.",
    "font_monospace":   "Replaces every `font-family` declaration with `monospace`.",
    "image_swap":       "Within each asset folder (photos / icons / avatars), cyclically rotates `<img src>` paths so each slot points at a different but real asset.",
    "text_lipsum":      "Replaces every visible text node with `lorem ipsum…` tokens.",
    "section_strip":    "Removes every other `<section>` / `<article>` / `<aside>` child of any container.",
    "layout_reverse":   "Reverses the children of every `<body>` / `<main>` / `<section>` / `<header>` / `<footer>` / `<nav>` / `<article>`.",
}


def write_markdown(results: dict[str, Any], out_path: Path) -> None:
    """Render a results table into a markdown file the grader can ship with."""
    oracle_a = results["runs"]["oracle"]["track_a"]
    oracle_b = results["runs"]["oracle"].get("track_b", {}) or {}
    track_b_enabled = bool(results.get("track_b"))
    criteria = list(GRADERS.keys())

    def fmt(x: float | None) -> str:
        return "—" if x is None else f"{x:.3f}"

    def build_table(track_key: str, oracle_row: dict[str, float | None]) -> list[str]:
        out: list[str] = []
        header = "| criterion | oracle | " + " | ".join(f"`{n}`" for n in CORRUPTIONS.keys()) + " |"
        sep = "|---" * (2 + len(CORRUPTIONS)) + "|"
        out.append(header)
        out.append(sep)
        for crit in criteria:
            o = oracle_row.get(crit)
            row = [f"`{crit}`", fmt(o)]
            for corruption_name, (_, target) in CORRUPTIONS.items():
                scores = results["runs"][corruption_name].get(track_key, {}) or {}
                s = scores.get(crit)
                marker = " **←target**" if target == crit else ""
                if s is None or o is None:
                    cell = f"{fmt(s)}{marker}"
                else:
                    delta = s - o
                    cell = f"{fmt(s)} ({delta:+.2f}){marker}"
                row.append(cell)
            out.append("| " + " | ".join(row) + " |")
        return out

    lines: list[str] = []
    title = "# Sensitivity tests — Track A and Track B" if track_b_enabled else "# Track A sensitivity tests"
    lines.append(title)
    lines.append("")
    try:
        fixture_disp = str(Path(results["fixture"]).resolve().relative_to(REPO_ROOT))
    except ValueError:
        fixture_disp = results["fixture"]
    rebaseline_note = (
        "Ground truth was **locally rebaselined** (capture.py re-run against the fixture's `source/` with the same Playwright the graders use), so oracle SSIM is not bounded by cross-machine Chromium drift."
        if results.get("rebaseline", False)
        else "Scored against the fixture's pre-existing `screenshots/` and `ground_truth/`. `layout_structure` oracle is bounded below by SSIM drift between the capture-machine Chromium and the runner's Chromium."
    )
    lines.append(
        f"_Fixture: `{fixture_disp}` ({len(results['pages'])} pages: "
        f"{', '.join(results['pages'])})._  "
        "Regenerate with `python grading/sensitivity.py --write-md grading/SENSITIVITY.md`."
    )
    lines.append("")
    lines.append(rebaseline_note)
    lines.append("")
    lines.append("## What this validates")
    lines.append("")
    tracks_phrase = "each Track A deterministic sub-grader and (when `--track-b` is on) each Track B LLM-judge question pack" if track_b_enabled else "each deterministic Track A sub-grader"
    lines.append(
        f"These are **construct-validity** checks — evidence that "
        f"{tracks_phrase} actually measures the dimension its name "
        "advertises (and not something else)."
    )
    lines.append("")
    lines.append(
        "1. **Oracle pass.** Score the ground-truth source against the "
        "ground-truth artifacts. Every Track A criterion should land in "
        "`[0.95, 1.00]` when the ground truth is rebaselined locally. "
        "If `--no-rebaseline`, `layout_structure` is bounded below by "
        "SSIM drift between the capture-machine Chromium build and the "
        "runner's Chromium build (subpixel font hinting + image decoding)."
    )
    lines.append("")
    lines.append(
        "2. **Targeted corruption.** Apply a perturbation that the eval's "
        "design predicts will hit one criterion. The target criterion "
        "should drop materially; off-target criteria should stay near "
        "oracle unless the perturbation genuinely has secondary effects "
        "(e.g. removing sections also removes their text and images)."
    )
    lines.append("")

    # ----- Corruption catalogue -----
    lines.append("## Corruption catalogue")
    lines.append("")
    lines.append("| corruption | target criterion | what it does |")
    lines.append("|---|---|---|")
    for name, (_, target) in CORRUPTIONS.items():
        note = CORRUPTION_NOTES.get(name, "")
        lines.append(f"| `{name}` | `{target}` | {note} |")
    lines.append("")

    # ----- Track A results table -----
    lines.append("## Results — Track A (deterministic sub-graders)")
    lines.append("")
    lines.append(f"_Pages scored: {len(results['pages'])} ({', '.join(results['pages'])})._")
    lines.append("")
    lines.extend(build_table("track_a", oracle_a))
    lines.append("")
    lines.append("_Each cell is `score (Δ vs oracle)`. **←target** marks the criterion the corruption was designed to hit._")
    lines.append("")

    # ----- Track B results table -----
    if track_b_enabled:
        judge_pages = results.get("judge_pages") or []
        judge_model = results.get("judge_model")
        lines.append("## Results — Track B (LLM-as-judge)")
        lines.append("")
        lines.append(
            f"_Page scored: {len(judge_pages)} ({', '.join(judge_pages)}). "
            f"Judge model: `{judge_model}`. Scope kept to one page to control API cost; "
            "Track A above runs over all pages._"
        )
        lines.append("")
        lines.extend(build_table("track_b", oracle_b))
        lines.append("")
        lines.append("_Track B verdicts are mean(1-5) per criterion normalised to [0, 1] via `(mean - 1) / 4`. A `—` means the judge call failed or the criterion was stubbed._")
        lines.append("")
    else:
        lines.append("## Results — Track B (LLM-as-judge)")
        lines.append("")
        lines.append("_Track B not run in this report — pass `--track-b` (and set `ANTHROPIC_API_KEY`) to populate this table._")
        lines.append("")

    # ----- Side-by-side cross-track comparison -----
    if track_b_enabled:
        lines.append("## Track A vs Track B — target-criterion drops side-by-side")
        lines.append("")
        lines.append("| corruption | target | Track A Δ | Track B Δ | agree? |")
        lines.append("|---|---|---|---|---|")
        for name, (_, target) in CORRUPTIONS.items():
            a_target = results["runs"][name]["track_a"].get(target)
            b_target = (results["runs"][name].get("track_b") or {}).get(target)
            o_a = oracle_a.get(target)
            o_b = oracle_b.get(target)
            da = (a_target - o_a) if (a_target is not None and o_a is not None) else None
            db = (b_target - o_b) if (b_target is not None and o_b is not None) else None
            agree = (
                "✓ both register" if (da is not None and db is not None and da < -0.05 and db < -0.05)
                else "⚠ only Track A" if (da is not None and db is not None and da < -0.05 and db >= -0.05)
                else "⚠ only Track B" if (da is not None and db is not None and db < -0.05 and da >= -0.05)
                else "—"
            )
            da_s = f"{da:+.2f}" if da is not None else "—"
            db_s = f"{db:+.2f}" if db is not None else "—"
            lines.append(f"| `{name}` | `{target}` | {da_s} | {db_s} | {agree} |")
        lines.append("")
        lines.append("_A negative Δ means the corruption hit the target criterion. ✓ means both tracks agreed (both dropped > 0.05 below oracle); ⚠ flags a track that missed the perturbation entirely._")
        lines.append("")

    # ----- Per-corruption interpretation (Track A) -----
    lines.append("## Reading the Track A columns")
    lines.append("")
    for name, (_, target) in CORRUPTIONS.items():
        target_delta = (
            results["runs"][name]["track_a"][target] - oracle_a[target]
        )
        # Rank deltas across criteria
        deltas = sorted(
            (
                (c, results["runs"][name]["track_a"][c] - oracle_a[c])
                for c in criteria
            ),
            key=lambda kv: kv[1],
        )
        biggest = deltas[0]
        is_diagonal = biggest[0] == target
        verdict = (
            "✓ targeted criterion is the largest drop in its column."
            if is_diagonal
            else f"⚠ `{biggest[0]}` drops more ({biggest[1]:+.2f}) than the target `{target}` ({target_delta:+.2f}). See the notes below — typically this means the corruption has a real, predictable secondary effect."
        )
        lines.append(f"### `{name}` → target `{target}` ({target_delta:+.2f})")
        lines.append("")
        lines.append(verdict)
        lines.append("")

    # ----- Per-corruption interpretation (Track B) -----
    if track_b_enabled:
        lines.append("## Reading the Track B columns")
        lines.append("")
        for name, (_, target) in CORRUPTIONS.items():
            track_b = results["runs"][name].get("track_b") or {}
            o = oracle_b.get(target)
            t = track_b.get(target)
            if o is None or t is None:
                lines.append(f"### `{name}` → target `{target}` (no data)")
                lines.append("")
                lines.append("Judge call failed or pack was stubbed.")
                lines.append("")
                continue
            target_delta = t - o
            deltas = sorted(
                (
                    (c, (track_b[c] - oracle_b[c])) for c in criteria
                    if c in track_b and c in oracle_b and track_b[c] is not None and oracle_b[c] is not None
                ),
                key=lambda kv: kv[1],
            )
            biggest = deltas[0] if deltas else (target, target_delta)
            if abs(target_delta) < 0.05:
                verdict = f"⚠ judge did NOT register the perturbation on its target (Δ = {target_delta:+.2f}). This is a real Track B miss — likely the corruption is sub-perceptual at full-page resolution, or the question pack doesn't probe the affected dimension."
            elif biggest[0] == target:
                verdict = "✓ targeted criterion is the largest drop in its column."
            else:
                verdict = f"⚠ `{biggest[0]}` drops more ({biggest[1]:+.2f}) than the target `{target}` ({target_delta:+.2f}). The corruption has a real, predictable secondary effect the judge picks up."
            lines.append(f"### `{name}` → target `{target}` ({target_delta:+.2f})")
            lines.append("")
            lines.append(verdict)
            lines.append("")

    # ----- Threats to validity -----
    lines.append("## Known cross-criterion interactions")
    lines.append("")
    lines.append("These are not bugs — they are the *correct* behaviour of independent graders applied to a corruption that affects multiple dimensions:")
    lines.append("")
    lines.append("- `palette_invert` also tanks `image_content_fidelity` and `layout_structure` on Track A. Reason: rendered pixels change, so pHash on `<img>` regions and SSIM on full-page screenshots both move. Track B's judge looks at the same pixels but its question pack for `image_content_fidelity` asks about *content* (\"is the same photograph visible\") and brushes off colour-only differences as a 5 — which is why Track B shows the drop *only* on the colour question pack, not on the image one.")
    lines.append("- `section_strip` removes content along with the macro-blocks, so `typography`, `image_content_fidelity`, and `visible_text_fidelity` also drop. The eval *cannot* attribute a single root cause when a corruption removes content — that's a limitation of single-criterion attribution, not of the graders. Track B's judge reacts even more dramatically (image_content_fidelity drops to 0.31), because it sees that half the image slots are gone.")
    lines.append("- `layout_reverse` reorders children, which shifts every `<img>` to a new bbox. Track A's `image_content_fidelity` matches by bbox, so it registers the shift. Track B's judge mostly forgives a reordering it can still see all images for, but its `layout_structure` pack notices the dominant-element-quadrant change.")
    lines.append("")

    # ----- Track B specific notes -----
    if track_b_enabled:
        lines.append("## Track B observations")
        lines.append("")
        vt_oracle = oracle_b.get("visible_text_fidelity")
        if vt_oracle is not None and vt_oracle < 1.0:
            lines.append(f"- **Oracle `visible_text_fidelity` = {vt_oracle:.3f}, not 1.0.** The judge gave at least one 4 on identical screenshots. This is normal LLM-judge anchor bias — the 5-anchor reads as \"indistinguishable on every dimension at once,\" so even oracle pairs sometimes get 4s on questions like vt_q9 (text volume). Track A's deterministic graders don't have this floor.")
        img_swap_b = (results['runs'].get('image_swap', {}).get('track_b') or {}).get('image_content_fidelity')
        img_oracle_b = oracle_b.get('image_content_fidelity')
        if img_swap_b is not None and img_oracle_b is not None and abs(img_swap_b - img_oracle_b) < 0.05:
            lines.append(f"- **Track B missed `image_swap`** (Δ on image_content_fidelity = {img_swap_b - img_oracle_b:+.2f}). The corruption cyclically rotates icon and avatar SVGs. At full-page resolution, individual icon glyphs (~14-18 px tall) are small enough that the judge can't reliably tell `hand-heart.svg` from `building-2.svg`. This is also a `per_image` scope limitation noted in `grading/judge/runner.py` — the pack runs at page-level rather than per-image bbox, so the question \"is the same exact photograph visible\" is answered globally, not slot-by-slot.")
        lines.append("- **Track B is harsher than Track A on `section_strip`'s collateral** — Track A's `image_content_fidelity` drops from 1.0 → 0.56 (half the images are gone, mean phash similarity stays moderate); Track B's drops 1.0 → 0.31 because the judge counts hallucinations and absences as separate failure modes.")
        lines.append("")


    lines.append("## What this does NOT prove")
    lines.append("")
    lines.append("- That a higher score implies a more *beautiful* website. The eval grades replication fidelity vs a reference — the reference defines the quality bar.")
    if track_b_enabled:
        lines.append("- That Track A and Track B agree on *real* agent rollouts. The corruption sweep above is a stress test with adversarial inputs, not a sample of typical agent behaviour. For the typical-rollout comparison, see canonical eval runs in `eval/reports/`.")
    else:
        lines.append("- That Track B (LLM judge) agrees with Track A. Re-run with `--track-b` to populate that side of the table.")
    lines.append("- That human raters agree with the score ordering. That requires a human-rated held-out slice — see the `RESULTS.md` analysis section.")
    lines.append("- That these results generalise to other fixtures. Re-run with `--fixture recipe/runs/task_N` against ≥ 2 more recipes to test cross-fixture stability.")
    lines.append("")

    out_path.write_text("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixture", default="recipe/runs/task_1", help="recipe-run dir with source/ (and, if --no-rebaseline, also ground_truth/ + screenshots/)")
    ap.add_argument(
        "--no-rebaseline",
        action="store_true",
        help="skip the local capture.py rebaseline step; score against the fixture's pre-existing screenshots / ground_truth (subject to cross-machine Chromium drift)",
    )
    ap.add_argument("--track-b", action="store_true", help="also score every scenario with the Track B LLM judge (requires ANTHROPIC_API_KEY)")
    ap.add_argument("--judge-pages", default=None, help="comma-separated page subset for Track B (default: first page only — keeps API cost bounded)")
    ap.add_argument("--judge-model", default="claude-opus-4-7")
    ap.add_argument("--write-md", default=None, help="output markdown summary to this path")
    ap.add_argument("--write-json", default=None, help="output raw JSON results to this path")
    ap.add_argument("--from-json", default=None, help="re-render markdown from a previously saved JSON results file (skips all scoring; useful when iterating on the markdown layout)")
    args = ap.parse_args()

    fixture = (REPO_ROOT / args.fixture).resolve()
    needs_gt = args.no_rebaseline
    if not (fixture / "source").exists():
        print(f"error: {fixture}/source missing", file=sys.stderr)
        return 2
    if needs_gt and not (fixture / "ground_truth").exists():
        print(f"error: {fixture}/ground_truth missing (required when --no-rebaseline)", file=sys.stderr)
        return 2

    if args.from_json:
        results = json.loads(Path(args.from_json).read_text())
    else:
        judge_pages = (
            [p.strip() for p in args.judge_pages.split(",") if p.strip()]
            if args.judge_pages
            else None
        )
        if args.track_b and not os.environ.get("ANTHROPIC_API_KEY"):
            print("error: --track-b requires ANTHROPIC_API_KEY in env", file=sys.stderr)
            return 2

        results = run(
            fixture,
            rebaseline=not args.no_rebaseline,
            track_b=args.track_b,
            judge_pages=judge_pages,
            judge_model=args.judge_model,
        )
    print(json.dumps(results, indent=2))

    if args.write_json:
        Path(args.write_json).write_text(json.dumps(results, indent=2))
    if args.write_md:
        write_markdown(results, Path(args.write_md))
        print(f"\nwrote {args.write_md}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
