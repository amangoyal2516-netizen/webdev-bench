"""recipe/02-capture/capture.py

Render every page in a recipe run dir at 3 viewports, save screenshots,
and extract the grader's reference values (bboxes, palette, typography,
images, text) to ground_truth/.

This is done **once at recipe time**. The grader at eval time reads
these JSONs and re-extracts the agent's values to compare.

Expected input layout (created by the builder, with assets nested under source/):

    <run_dir>/
      source/{home,about,…}.html
      source/styles.css
      source/assets/{photos,icons,fonts,avatars}/...    ← vendored, nested in source/

Output layout (created here):

    <run_dir>/
      screenshots/
        desktop/{home,…}/
          full.png                  ← stitched full-page (grader reference; palette/pHash)
          001.png, 002.png, …       ← viewport-height slices (agent reference)
        tablet/{…}/{full,001,…}.png
        mobile/{…}/{full,001,…}.png
      ground_truth/
        bboxes/{desktop,tablet,mobile}/{home,…}.json
        typography/{home,…}.json    ← desktop computed styles, area-weighted
        text/{home,…}.json          ← visible DOM textContent
        images/{home,…}.json        ← per-<img> bbox + pHash
        palette/{home,…}.json       ← k-means in LAB on the desktop full.png

Usage:

    python recipe/02-capture/capture.py recipe/runs/task_1/
    python recipe/02-capture/capture.py recipe/runs/task_1/ --pages home,about
    python recipe/02-capture/capture.py recipe/runs/task_1/ --no-screenshots
    python recipe/02-capture/capture.py recipe/runs/task_1/ --no-precompute

Heavy imports (Playwright, scipy, sklearn, scikit-image, imagehash, Pillow)
are deferred until first use so this module imports cheaply for --help.
Requires: pip install playwright Pillow numpy scipy scikit-learn scikit-image
          imagehash; then `playwright install chromium`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# 1440×900 / 768×1024 / 375×812 — common desktop/tablet/mobile breakpoints.
VIEWPORTS: dict[str, tuple[int, int]] = {
    "desktop": (1440, 900),
    "tablet": (768, 1024),
    "mobile": (375, 812),
}

PALETTE_K = 8            # k-means cluster count
PALETTE_SAMPLES = 5000   # subsample for speed on big screenshots


# ---------------------------------------------------------------------------
# DOM extractors — JS snippets evaluated inside the page.
# All coords are document-relative (scrollY-adjusted) so they line up with
# the full-page screenshot.
# ---------------------------------------------------------------------------


_JS_BBOXES = """
() => {
    const out = [];
    const sx = window.scrollX, sy = window.scrollY;
    for (const el of document.querySelectorAll('*')) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) continue;
        out.push({
            tag: el.tagName.toLowerCase(),
            id: el.id || null,
            cls: (typeof el.className === 'string' && el.className) ? el.className : null,
            role: el.getAttribute('role') || null,
            data_component: el.getAttribute('data-component') || null,
            x: r.x + sx,
            y: r.y + sy,
            w: r.width,
            h: r.height,
        });
    }
    return out;
}
"""

_JS_TYPOGRAPHY = """
() => {
    const out = [];
    const walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT,
        { acceptNode: n => n.textContent && n.textContent.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT }
    );
    const seen = new Set();
    while (walker.nextNode()) {
        const node = walker.currentNode;
        const el = node.parentElement;
        if (!el || seen.has(el)) continue;
        seen.add(el);
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const cs = getComputedStyle(el);
        out.push({
            tag: el.tagName.toLowerCase(),
            font_family: cs.fontFamily,
            font_size_px: parseFloat(cs.fontSize),
            font_weight: cs.fontWeight,
            line_height: cs.lineHeight,
            area: r.width * r.height,
            text_len: node.textContent.trim().length,
        });
    }
    return out;
}
"""

_JS_TEXT = """
() => ({ text: (document.body.innerText || '').trim() })
"""

_JS_IMAGES = """
() => {
    const out = [];
    const sx = window.scrollX, sy = window.scrollY;
    for (const img of document.querySelectorAll('img')) {
        const r = img.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        out.push({
            src: img.getAttribute('src'),
            alt: img.getAttribute('alt') || '',
            x: r.x + sx,
            y: r.y + sy,
            w: r.width,
            h: r.height,
        });
    }
    return out;
}
"""


# ---------------------------------------------------------------------------
# Pillow / sklearn / imagehash work (lazy imports)
# ---------------------------------------------------------------------------


def slice_into_chunks(full_path: Path, viewport_height: int) -> int:
    """Slice a full-page screenshot into viewport-height PNG chunks for the
    agent's reference. Chunks are saved as 001.png, 002.png, … alongside
    `full.png`. Returns the number of chunks written.

    The last chunk is shorter than `viewport_height` if the page doesn't
    divide evenly. We slice rather than re-render because slicing is ~100×
    faster and gives bit-identical content to the full-page screenshot
    (no risk of dynamic content shifting between captures).
    """
    from PIL import Image

    img = Image.open(full_path)
    w, h = img.size
    out_dir = full_path.parent
    n = 0
    for i, y0 in enumerate(range(0, h, viewport_height), start=1):
        y1 = min(y0 + viewport_height, h)
        chunk = img.crop((0, y0, w, y1))
        chunk.save(out_dir / f"{i:03d}.png")
        n += 1
    return n


def compute_image_signatures(images_meta: list[dict], full_page_png: Path) -> list[dict]:
    """Crop each image's bbox out of the full-page screenshot and record
    two signals for the image_content_fidelity grader:

      - `phash` — DCT perceptual hash (structural content).
      - `lab_mean` — mean CIE-LAB color of the crop (catches content
        swaps where structure is preserved but pixels aren't — e.g. a
        1×1 grey PNG stretched over an icon bbox, which has near-uniform
        pHash similar to the original icon but a wildly different mean
        color).

    LAB values are standard CIELAB. Pillow's `convert("LAB")` packs L
    into 0–255 (scale ×2.55) and stores a/b unoffset as signed values
    in a uint8 buffer (so a negative chroma reads as e.g. 240 for -16).
    We reinterpret the uint8 buffer as int8 for a/b before averaging,
    then scale L back to 0–100.
    """
    from PIL import Image
    import imagehash
    import numpy as np

    img = Image.open(full_page_png).convert("RGB")
    img_w, img_h = img.size
    out = []
    for im in images_meta:
        x = max(0, int(round(im["x"])))
        y = max(0, int(round(im["y"])))
        w = max(1, int(round(im["w"])))
        h = max(1, int(round(im["h"])))
        x2 = min(img_w, x + w)
        y2 = min(img_h, y + h)
        if x2 <= x or y2 <= y:
            out.append({**im, "phash": None, "lab_mean": None, "phash_error": "bbox outside screenshot"})
            continue
        try:
            crop = img.crop((x, y, x2, y2))
            ph = str(imagehash.phash(crop))
            lab_buf = np.asarray(crop.convert("LAB"))  # uint8, shape HxWx3
            # L: scale 0-255 → 0-100; a/b: reinterpret as signed int8.
            L_mean = float(lab_buf[..., 0].astype(np.float32).mean()) * 100.0 / 255.0
            a_mean = float(lab_buf[..., 1].view(np.int8).astype(np.float32).mean())
            b_mean = float(lab_buf[..., 2].view(np.int8).astype(np.float32).mean())
            lab_mean = [round(L_mean, 2), round(a_mean, 2), round(b_mean, 2)]
            out.append({**im, "phash": ph, "lab_mean": lab_mean})
        except Exception as e:
            out.append({**im, "phash": None, "lab_mean": None, "phash_error": f"{type(e).__name__}: {e}"})
    return out


def compute_palette(full_page_png: Path, k: int = PALETTE_K, n_samples: int = PALETTE_SAMPLES) -> list[dict]:
    """k-means in LAB color space on a subsample of pixels.

    Returns a list of clusters sorted by weight (largest first), each with
    the centroid as `hex` (sRGB) and `lab` (CIE-LAB), plus a `weight`
    fraction of pixels assigned to that cluster.
    """
    from PIL import Image
    import numpy as np
    from skimage.color import rgb2lab, lab2rgb
    from sklearn.cluster import KMeans

    img = np.array(Image.open(full_page_png).convert("RGB"), dtype=np.float32) / 255.0
    pixels = img.reshape(-1, 3)

    rng = np.random.default_rng(42)
    if len(pixels) > n_samples:
        idx = rng.choice(len(pixels), n_samples, replace=False)
        pixels = pixels[idx]

    lab = rgb2lab(pixels.reshape(1, -1, 3)).reshape(-1, 3)

    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    km.fit(lab)

    sizes = np.bincount(km.labels_, minlength=k) / len(km.labels_)
    centers_rgb = lab2rgb(km.cluster_centers_.reshape(1, -1, 3)).reshape(-1, 3)
    centers_rgb = np.clip(centers_rgb, 0.0, 1.0)

    palette = []
    for hex_idx in range(k):
        r, g, b = (centers_rgb[hex_idx] * 255).astype(int)
        palette.append({
            "hex": f"#{r:02x}{g:02x}{b:02x}",
            "weight": float(sizes[hex_idx]),
            "lab": [float(v) for v in km.cluster_centers_[hex_idx]],
        })
    palette.sort(key=lambda p: -p["weight"])
    return palette


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def discover_pages(source_dir: Path) -> list[str]:
    return sorted(p.stem for p in source_dir.glob("*.html"))


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _wait_for_ready(page) -> None:
    """Wait for network-idle + web-font loading so the screenshot/extraction is stable."""
    page.wait_for_load_state("networkidle")
    try:
        page.evaluate(
            "() => (document.fonts && document.fonts.ready) ? document.fonts.ready : null"
        )
    except Exception:
        # Some pages have no document.fonts; ignore.
        pass


def process_page(
    browser,
    source_dir: Path,
    run_dir: Path,
    page_name: str,
    *,
    do_screenshots: bool,
    do_precompute: bool,
) -> dict[str, Any]:
    html_path = source_dir / f"{page_name}.html"
    if not html_path.exists():
        return {"page": page_name, "error": f"missing {html_path}"}

    result: dict[str, Any] = {"page": page_name, "viewports": {}}
    desktop_screenshot: Path | None = None
    images_meta: list[dict] | None = None

    for vp_name, (w, h) in VIEWPORTS.items():
        ctx = browser.new_context(viewport={"width": w, "height": h})
        page = ctx.new_page()
        page.goto(f"file://{html_path.resolve()}")
        _wait_for_ready(page)

        # Per-viewport screenshots — full-page + viewport-height chunks
        if do_screenshots:
            page_dir = run_dir / "screenshots" / vp_name / page_name
            page_dir.mkdir(parents=True, exist_ok=True)
            full_path = page_dir / "full.png"
            page.screenshot(path=str(full_path), full_page=True)
            n_chunks = slice_into_chunks(full_path, viewport_height=h)
            result["viewports"].setdefault(vp_name, {})["chunks"] = n_chunks
            if vp_name == "desktop":
                desktop_screenshot = full_path

        # Per-viewport bboxes (layout differs across viewports)
        if do_precompute:
            bboxes = page.evaluate(_JS_BBOXES)
            _write(run_dir / "ground_truth" / "bboxes" / vp_name / f"{page_name}.json", bboxes)
            result["viewports"].setdefault(vp_name, {})["bboxes"] = len(bboxes)

        # Once-per-page extractions (do them on the desktop viewport)
        if do_precompute and vp_name == "desktop":
            typo = page.evaluate(_JS_TYPOGRAPHY)
            _write(run_dir / "ground_truth" / "typography" / f"{page_name}.json", typo)
            result["typography_nodes"] = len(typo)

            text = page.evaluate(_JS_TEXT)
            _write(run_dir / "ground_truth" / "text" / f"{page_name}.json", text)
            result["text_chars"] = len(text.get("text", ""))

            images_meta = page.evaluate(_JS_IMAGES)
            result["images_count"] = len(images_meta)

        ctx.close()

    # Things that need the desktop screenshot — done after the viewport loop
    if do_precompute and desktop_screenshot and images_meta is not None:
        images_with_signatures = compute_image_signatures(images_meta, desktop_screenshot)
        _write(run_dir / "ground_truth" / "images" / f"{page_name}.json", images_with_signatures)

        palette = compute_palette(desktop_screenshot)
        _write(run_dir / "ground_truth" / "palette" / f"{page_name}.json", palette)
        result["palette_size"] = len(palette)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("run_dir", help="path to a recipe/runs/task_N/ directory (must contain source/*.html)")
    ap.add_argument("--pages", default=None, help="comma-separated page names (default: every *.html in source/)")
    ap.add_argument("--no-screenshots", action="store_true", help="skip screenshots; only precompute ground-truth JSONs")
    ap.add_argument("--no-precompute", action="store_true", help="skip ground-truth extraction; only screenshots")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    source_dir = run_dir / "source"
    if not source_dir.is_dir():
        print(f"error: {source_dir} does not exist", file=sys.stderr)
        return 2

    pages = (
        [p.strip() for p in args.pages.split(",") if p.strip()]
        if args.pages
        else discover_pages(source_dir)
    )
    if not pages:
        print(f"error: no .html files in {source_dir}", file=sys.stderr)
        return 2

    do_screenshots = not args.no_screenshots
    do_precompute = not args.no_precompute
    if not (do_screenshots or do_precompute):
        print("error: --no-screenshots and --no-precompute leaves nothing to do", file=sys.stderr)
        return 2

    print(
        f"capturing {len(pages)} page(s) × {len(VIEWPORTS)} viewport(s) "
        f"from {source_dir}  (screenshots={do_screenshots}, precompute={do_precompute})"
    )

    # Lazy-import Playwright so --help doesn't pay for it.
    from playwright.sync_api import sync_playwright

    t_total = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for page_name in pages:
            t_page = time.time()
            try:
                result = process_page(
                    browser, source_dir, run_dir, page_name,
                    do_screenshots=do_screenshots,
                    do_precompute=do_precompute,
                )
            except Exception as e:
                print(f"  {page_name}: ERROR {type(e).__name__}: {e}", file=sys.stderr)
                continue
            elapsed = time.time() - t_page

            if "error" in result:
                print(f"  {page_name}: {result['error']}")
                continue

            vp_parts = []
            for vp, v in result.get("viewports", {}).items():
                pieces = []
                if "chunks" in v:
                    pieces.append(f"{v['chunks']}ch")
                if "bboxes" in v:
                    pieces.append(f"{v['bboxes']}b")
                vp_parts.append(f"{vp}=[{','.join(pieces)}]")
            vp_str = ", ".join(vp_parts) or "no-output"
            extras = ""
            if do_precompute:
                extras = (
                    f" | typo={result.get('typography_nodes', '-')}"
                    f" text={result.get('text_chars', '-')}c"
                    f" imgs={result.get('images_count', '-')}"
                    f" palette={result.get('palette_size', '-')}"
                )
            print(f"  {page_name}: {elapsed:>4.1f}s | {vp_str}{extras}")
        browser.close()

    print(f"\ndone in {time.time() - t_total:.1f}s → {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
