#!/usr/bin/env bash
# render <html_path> <desktop|tablet|mobile>
#
# Screenshots an HTML file at one of three viewports and writes the PNG to
# STDOUT. Typical use from the agent's shell:
#
#   render output/home.html desktop > /tmp/home-desktop.png
#   render output/home.html tablet  > /tmp/home-tablet.png
#   render output/home.html mobile  > /tmp/home-mobile.png
#
# The agent then reads the PNG back into its context (multimodal vision)
# to compare against /workspace/reference/<page>_<viewport>.png.
#
# Viewport sizes match the grader's capture (see recipe/02-capture and
# grading/criteria/*) so the screenshot the agent sees is the same shape
# the grader sees: desktop=1440x900, tablet=768x1024, mobile=375x812.
# Full-page mode is on so the agent inspects everything below the fold.

set -euo pipefail

HTML="${1:?usage: render <html_path> <desktop|tablet|mobile>}"
VIEWPORT="${2:?usage: render <html_path> <desktop|tablet|mobile>}"

case "$VIEWPORT" in
    desktop) W=1440; H=900 ;;
    tablet)  W=768;  H=1024 ;;
    mobile)  W=375;  H=812 ;;
    *) echo "render: unknown viewport '$VIEWPORT' (use desktop|tablet|mobile)" >&2; exit 2 ;;
esac

python - "$HTML" "$W" "$H" <<'PY'
import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

html, w, h = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])

async def shoot():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": w, "height": h})
        page = await ctx.new_page()
        await page.goto("file://" + str(Path(html).resolve()))
        await page.wait_for_load_state("networkidle")
        png = await page.screenshot(full_page=True)
        sys.stdout.buffer.write(png)
        await browser.close()

asyncio.run(shoot())
PY
