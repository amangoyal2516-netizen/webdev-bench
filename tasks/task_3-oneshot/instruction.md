# Replicate the website shown in the reference screenshots

You will see reference screenshots of a multi-page website. Your job is to reproduce the design as faithfully as possible in **html-css**. Functionality is out of scope — only what the user's eye sees is graded.

## What the site is

Landing and onboarding site for a contract review API that lets developers integrate AI-powered legal clause analysis into their apps — marketing pages plus a multi-step integration wizard

## Files you can see (read-only)

- `/workspace/reference/{desktop,tablet,mobile}/<page>/full.png` — full-page reference at each viewport.
- `/workspace/reference/{desktop,tablet,mobile}/<page>/001.png`, `002.png`, … — viewport-height slices of the same render, top → bottom in scroll order. Read these in order for high-resolution detail.
- `/workspace/output/assets/` — image, font, and icon files the design uses. **Pre-populated for you.** Use only these — don't fetch external assets from the internet, and don't add to, remove, or overwrite files in this directory.

> **Match every asset by position, not by category.** For each spot where the reference shows an asset — image, icon, avatar, or font — use the **same exact asset file** the reference uses at that position. Not just any plausible asset of the same kind. The graders compare asset choices against the reference per-position:
>
> - **Images**: picking a different food photo for the hero, even if it looks similar, is a miss (`image_content_fidelity` uses pHash by bbox).
> - **Icons**: picking a different SVG (e.g., `bell.svg` when the reference uses `bell-ringing.svg`) is a miss.
> - **Avatars**: picking a different avatar variant at each user-list slot is a miss.
> - **Fonts**: using a different font family than the reference's (e.g., Roboto when the reference uses Inter) is a miss even if it looks similar — `typography` reads computed `font-family` exactly.
>
> Read the reference screenshots carefully to identify which exact asset is at each position, then use that exact file from `assets/`.
- `/workspace/instruction.md` — this file.

## Files you write

- `/workspace/output/<name>.html` — one HTML file per canonical page name listed below.
- `/workspace/output/styles.css` — your stylesheet.
- Reference vendored assets as `./assets/<filename>` (your HTML and the `assets/` directory both live under `/workspace/output/`, so a relative `./assets/<file>` resolves correctly).

## Canonical page filenames

You must produce **exactly** these HTML files — filenames matter, the grader pairs your pages to references by name.

- `home.html` — Marketing landing page introducing the contract review API to engineering teams at law-adjacent companies
- `wizard.html` — Five-step integration wizard that walks a developer from account creation to a first successful API call
- `wizard-keys.html` — Penultimate wizard step where the developer generates API credentials and tests a sandbox call
- `pricing.html` — Pricing page comparing self-serve plans and an enterprise tier with a usage estimator
- `docs.html` — Documentation reading view for a single API reference page
- `customers.html` — Customer stories index page showcasing how legal-tech and ops teams use the API

## Framework constraint

You are allowed to use: **html-css**.

For `html-css`: produce static HTML files + a single CSS stylesheet. No JS frameworks (React, Vue, Solid, Svelte, Preact, Lit, Alpine, htmx). No build step. No `package.json`, `tsconfig.json`, `vite.config.*`, `next.config.*`, or `node_modules/`. The `framework_compliance` gate caps your final reward at 30% if you violate this.



## Fonts to declare

The reference uses these `@font-face` rules. Use them as-is in your CSS — the family name is what the `typography` grader reads via `getComputedStyle()`, and it doesn't always match the filename:

```css
@font-face { font-family: 'Inter'; src: url('./assets/fonts/inter/inter-400.woff2') format('woff2'); font-weight: 400; font-style: normal; }
@font-face { font-family: 'Inter'; src: url('./assets/fonts/inter/inter-500.woff2') format('woff2'); font-weight: 500; font-style: normal; }
@font-face { font-family: 'Inter'; src: url('./assets/fonts/inter/inter-700.woff2') format('woff2'); font-weight: 700; font-style: normal; }
@font-face { font-family: 'JetBrains Mono'; src: url('./assets/fonts/jetbrains-mono/jetbrains-mono-400.woff2') format('woff2'); font-weight: 400; font-style: normal; }
@font-face { font-family: 'JetBrains Mono'; src: url('./assets/fonts/jetbrains-mono/jetbrains-mono-700.woff2') format('woff2'); font-weight: 700; font-style: normal; }
```

## How you'll be graded

Your output is compared to the reference on six dimensions, each in [0, 1]:

1. **`layout_structure`** — SSIM between agent's and reference's full-page screenshots at desktop / tablet / mobile, downsampled to a common width. Weight 2.5.
2. **`component_presence`** — whether the expected components render. Weight 2.0.
3. **`color_palette`** — k-means in LAB color space + Earth-Mover's-Distance vs reference. Weight 1.5.
4. **`typography`** — font-family + font-size per text node, area-weighted. Weight 1.5.
5. **`image_content_fidelity`** — perceptual hash of each `<img>` region matched against the reference. Weight 1.5.
6. **`visible_text_fidelity`** — Sørensen-Dice over tokenized DOM textContent. Weight 1.0.

Final reward = `weighted_mean(6 sub-scores) × framework_compliance_gate`.

A second, parallel **Track B** score is produced by an MLLM judge running atomic questions on a 1-5 scale against the same screenshots — same weights, same gate, reported side-by-side. You don't need to do anything different for Track B; it scores the same artifacts.

Now study the references and start writing HTML + CSS in `/workspace/output/`.
