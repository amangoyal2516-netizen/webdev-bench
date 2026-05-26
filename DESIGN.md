# webdev-bench — pipeline thought process

A walkthrough of every stage in the benchmark pipeline: what it does, key
findings, decisions made, and what changed along the way. Written as a
reasoning record, not a reference manual.

---

## 1. Task generation

### What it does

The first stage of the recipe pipeline. An *author LLM* picks a site type from a controlled vocabulary (e.g., *"Beginner-friendly impact analytics tool for small nonprofits"*) and emits a `design.json` containing:

- A 1–2 sentence site description
- A list of 5–7 pages with names, descriptions, and component lists
- An `assets_picked` list — specific icon / photo / font / avatar IDs drawn from a fixed asset pool

For each page, a *per-page builder LLM* then generates the HTML + CSS implementation, restricted to the assets in `assets_picked`. The pipeline runs on Modal — one sandbox per task, fanned out in parallel.

### Why a pre-vendored asset pool

The recipe builder draws every image, icon, font, and avatar from a fixed pool seeded once on Modal:

- Thousands of photos across diverse categories (food, architecture, nature, people, abstract textures, etc.)
- The complete Lucide icon set (~1,500+ SVGs)
- A curated set of Google Fonts (sans-serif, serif, monospace, display)
- Several hundred generated avatar variants

**Why a pool rather than letting the author/builder hit the open web:**

- **Reproducibility.** Tasks generated months apart should render byte-identically. Web URLs rot; freezing the asset universe is the only way to guarantee the reference design stays fixed.
- **Vendoring discipline.** The agent container has network open, but the design contract is *use only vendored assets*. The pool makes the contract concrete — agents reach for `./assets/lightbulb.svg`, not a CDN URL. Track A's `framework_compliance` gate flags external `<img src="...">` references.
- **Scoping what the benchmark tests.** The agent's job is to *place* the right asset at the right spot in the design — not to *find* assets from anywhere on the web. Pre-vendoring the pool keeps the test focused on perception + placement (read the reference, identify the image content, pick the matching file). Allowing open-web search would layer an orthogonal capability (browsing, retrieval, ranking) onto a benchmark that's explicitly about visual design replication.
- **Combinatorial design variety.** Each task picks ~10–30 specific assets from the pool. With ~5,000+ items in the pool, the space of distinct `assets_picked` combinations is effectively unbounded — no two generated tasks share the same visual identity even when they share the same site description type. This is the mechanism that produces design diversity at low marginal cost.
- **Author can pre-commit to a palette.** The author LLM picks both photos and a color palette *before* the per-page builder runs, so the resulting site has visual coherence (matched mood, matched accent colors, matched icon family). The builder receives a fixed asset list, which makes its prompt simpler and its output more predictable.

**What this costs the downstream agent — and why that's a feature, not a bug:**

The agent sees the SAME pre-vendored assets at task start. It must figure out which asset belongs where by inspecting the reference screenshots. This is a genuine design-replication challenge:

- Asset filenames are descriptive (`lightbulb.svg`, `food-hero-3.jpg`, `architect-portrait-7.jpg`) but rarely uniquely matchable to a specific spot in the reference. A page with three hero-quality photos in `assets_picked` forces the agent to figure out which one the reference uses where.
- The agent has to read the reference screenshot, identify the image content, then scan the assets for the closest match — a small but real perception-and-search task layered on top of the HTML/CSS generation.
- Icons multiply this difficulty: a task with 8 icons in `assets_picked` often has multiple plausible candidates per callout, button, and label.

In practice we see agents frequently pick **semantically-reasonable-but-different** images: the reference uses `food-hero-3.jpg` for the dashboard hero; the agent produces a clean dashboard but uses `food-hero-1.jpg` instead. The page looks right at a glance; Track A's `image_content_fidelity` (perceptual-hash matching against the matched `<img>` bbox) catches it as a 0 because the pixel content differs.

This isn't an accidental difficulty — it's load-bearing. Without it, the asset-picking sub-task collapses to "use whatever image"; the benchmark would lose a real dimension of design replication. The trade-off we accept: image_content_fidelity scores will be lower than the other criteria on average, even for visually good replicas.

After observing in the canonical evaluation that agents frequently picked the right *kind* of asset at each spot but the wrong specific one — and that Track A's pHash flagged this while Track B's grading was too lenient to catch it — we made the matching standard explicit in each task's `instruction.md`. The agent is now told that asset selection is graded by position-and-pixel: picking a different food photo for the hero, a different icon for the same slot, or a different avatar variant is a miss even if it looks similar at a glance. The fix targeted both sides — stricter judge grading and clearer agent guidance — and across the asset-matching sub-task, agent choices and judge verdicts moved in agreement rather than only the judge tightening.

### How we enforce diversity in generation

We initially generated tasks by calling the author LLM with the same prompt each time. Observed result: noticeable clustering of site types — multiple variations on the same handful of design ideas, near-duplicate websites across tasks. The naïve fix would be to bump sampling temperature, but **Claude Opus 4.7's API does not accept a `temperature` parameter at all** — the model runs at a fixed default and there's no knob to push it higher.

To force variety we built a **keyword taxonomy** and inject a random combination of keywords into the author prompt per task. The taxonomy covers axes like:

- **Site type** (project management tool / magazine homepage / fitness tracker / nonprofit dashboard / …)
- **Target audience** (beginner home cooks / freelance designers / small-town nonprofits / …)
- **Design mood** (calm and organized / playful and warm / editorial and serious / …)
- **Domain-specific flavor terms** (page-name hints scoped to the chosen site type)

Each task draws a fresh random combination, anchoring the author into a specific design corner. The author still has compositional freedom — the keywords are seeds, not constraints — but two tasks with different keyword draws produce visibly different sites. This is the lever that makes diverse task generation actually diverse in practice. Without it, the same Opus session produces the same handful of design ideas regardless of how many tasks we ask for.

Generation diversity is enforced at the author level — not at the post-generation level via clustering or filtering. Three sources compound:

1. **Design anchor.** The keyword taxonomy fixes each task's site type, audience, and mood.
2. **Visual identity.** The asset pool gives each task its own combination drawn from thousands of items.
3. **Structural composition.** The per-page component inventory yields a unique mix of complex components per task — data tables, card grids, timelines, dashboards, multi-step forms, etc. The design-replication problem isn't just "render this page" but "render this specific mix of components."

The three compound: same site type with different keyword + asset + component draws produces distinguishable designs without any post-hoc curation.

### Key prompt design choices

Two prompts do the heavy lifting: the author prompt that emits `design.json`, and the per-page builder prompt that emits HTML/CSS. A few non-obvious decisions in their construction:

**Author prompt:**

- **Structured JSON output is mandatory** — the author returns a strict schema (description, pages, components, allowed_frameworks, assets_picked). The recipe pipeline validates the schema before calling the builder; malformed output forces a retry. Keeps downstream code simple — no fuzzy parsing.
- **Color palette is pre-committed** alongside assets — the author chooses 4–6 colors at the design level, and per-page builders are restricted to that palette. Without this, every page would drift to its own colors and `color_palette` Track A signal would degrade across pages within a task.
- **Per-page component inventory is required.** The author lists which components each page must contain (header, hero, cards-grid, sidebar, timeline, etc.). This becomes the ground-truth list `component_presence` grades against — without an explicit inventory, "what components should be on this page" would be a judgment call rather than a fact in `design.json`.

**Builder prompt:**

- **One page per LLM call.** Each page is generated in isolation with only `design.json` + that page's spec in context. No multi-page coordination needed in a single call; an error on one page doesn't cascade across the others.
- **Asset universe is exactly `assets_picked`.** The builder cannot reach outside the list, and the prompt explicitly forbids placeholder patterns (`-fallback`, `-placeholder`, `-stub`). Combined with a validator that checks every `<img src="...">` resolves on disk, the builder produces references that always exist.
- **HTML + CSS only — no JavaScript.** The benchmark grades visual design, not behavior. No-JS means the rendered output is what's on disk; nothing happens on hover, click, or scroll. Simplifies grading: a single Playwright `page.goto + screenshot` captures the truth.
- **Canonical page filenames.** The author commits to page names (`home`, `about`, `pricing`, …) in `design.json`; the builder must use those exact names with `.html` suffix. This makes per-page grading mechanical — Track A's bbox/screenshot/text pipeline pairs `agent_output/home.html` against `ground_truth/home.html` purely by filename.

### What worked

- **Modal parallel fan-out**: many tasks generate in parallel sandboxes rather than serially, which is what makes batch generation tractable.
- **Author + per-page builder split**: author handles site personality + structure, builder handles per-page implementation in isolation. Keeps both prompts focused.
- **`assets_picked` pre-commit + builder enforcement**: the author commits to a specific asset list, then the builder is constrained to that list. Prevents agents from inventing arbitrary `<img src="...">` paths at build time.

### What didn't work / decisions made

- **Builder occasionally hallucinated icon names not in the pool.** Root cause: Lucide renamed several common icons across major versions (`home → house`, `filter → list-filter`, `edit → pencil`, `sort-asc → arrow-up-narrow-wide`, …) and the builder's training data still references the old names. **Fix**: added an aliases mapping covering 19 legacy names, and updated the builder system prompt to explicitly forbid suffix patterns like `-fallback`, `-placeholder`, `-stub`.

---

## 2. Ground truth capture

### What it does

The second stage of the recipe pipeline. Once the author + builder produce a static website (`source/*.html` + `styles.css` + `assets/`), capture loads each page in headless Chromium at three viewports and extracts everything the grader will need at run time:

- **Full-page screenshots** per (page, viewport)
- **DOM bounding boxes** per (page, viewport): every visible element's tag, position, size, class, role
- **Color palette** per page: k-means in LAB color space on the rendered screenshot
- **Typography**: computed font-family + font-size + font-weight + line-height per text node, area-weighted
- **DOM text content** per page: tokenized for downstream similarity comparison
- **Image metadata** per page: `<img>` bbox + perceptual hash per image

All shipped to the packaged task as JSON + PNGs alongside the canonical `design.json`.

### Why pre-computed, not re-rendered at grade time

Two reasons.

**Speed.** If the grader re-rendered ground truth at run time, every rollout would pay ~1-2 minutes of Playwright work just to reproduce data we already had. Pre-computing flips the trade-off — we pay the rendering cost ONCE at recipe time, then every grade reads JSON in milliseconds. This keeps Track A under 30s per rollout, which is the budget that makes fast eval iteration possible.

**Determinism.** Playwright bbox extraction is sensitive to font loading order, page-goto timing, and any non-vendored network resources. Pre-computing pins the ground truth to one canonical render, so every agent is compared against the *same* reference — not a re-rendered approximation of it that might vary across grading runs.

### Why three viewports (desktop 1440×900, tablet 768×1024, mobile 375×812)

These match Playwright's standard "desktop"/"iPad"/"iPhone 12" presets and bracket the breakpoints common in real web design (768 = Bootstrap-md threshold; 375 = iPhone-default). Three viewports gives:

- A desktop layout (the "primary" design)
- A tablet layout that exercises one breakpoint
- A mobile layout that exercises a second breakpoint and triggers most responsive collapses (hamburger nav, single-column reflow, etc.)

Two viewports would miss the tablet middle case. Four+ adds marginal signal at significant grading-time cost.

### Why full-page, not viewport-bounded

The screenshot at each viewport captures the ENTIRE scrollable page height, not just the visible window. Critical content often sits below the fold; the layout grader and the Track B judge both need to see the full design to grade fairly.

Cost: mobile full-page screenshots can stretch to 25,000+ pixels tall on content-heavy designs. The Anthropic vision API rejects images > 8000px on any dimension, so the judge client downscales anything with max-dim > 7500px before sending. Acceptable trade — losing fine detail on extremely tall mobile pages beats losing content below the fold entirely.

### Why the same evaluator both sides

The JS bbox extractor and the Playwright settings (viewport sizes, `wait_for_load_state`, font-readiness check) are byte-identical between recipe-time capture and grade-time agent extraction. If we evaluated agent and reference with different code paths, any difference between them would be ambiguous: is the agent's bbox different because the agent's HTML is different, or because the extractor was different?

Sharing the extractor pins this down. With `layout_structure` now SSIM-based on screenshots the extractor is less central there, but `component_presence` still relies on live DOM extraction and benefits directly from this invariant.

### What worked

- **Pre-computation.** Track A consistently grades a trial in under 30s once the agent's HTML is on disk. The recipe-time cost is paid once per design, never per rollout.
- **Shared extractor.** Cross-checked against Oracle (an agent that just copies the ground-truth source) — `layout_structure` scored ~1.0 on Oracle runs, confirming the extractor matches itself.
- **pHash for images.** At grade time, comparing two 64-bit hashes is essentially free.

### What didn't work / decisions made

- **Image dimension cap.** The judge API's 8000px hard ceiling forces downscaling for tall mobile screenshots. Decision: cap at 7500px max-dim, preserve aspect ratio. Loses some bottom-of-page detail at extreme heights; preferable to dropping the content entirely.
- **Considered viewport-only screenshots** to save capture time. Rejected because below-the-fold content is load-bearing for design replication.

---

## 3. Two variants per design

### What we do

Packaging takes each completed recipe run and stamps out two parallel Harbor task directories: a `-oneshot` variant and a `-iter` variant. Both variants share identical ground truth, identical grading, identical weights — the only difference is what the agent has access to inside its container.

- **`-oneshot`**: agent receives reference screenshots + an `instruction.md` describing the pages to build. No tooling beyond a shell and an editor. Agent writes HTML/CSS blind and submits whatever's in `/workspace/output/` when its budget runs out.
- **`-iter`**: same setup, plus a `render` helper script that the agent can call to screenshot its own HTML at a chosen viewport. The agent can read those screenshots back and visually compare to the reference before submitting.

### Why both — what the A/B comparison evaluates

The two variants exist to answer a specific research question: **does giving a coding agent the ability to see its own output meaningfully improve design replication?**

A naive answer is *"obviously yes — visual feedback is always helpful."* The empirical answer is less clear. Iterative agents face real costs that oneshot agents don't:

- Each render call eats budget — time spent looking at a screenshot is time not spent writing HTML
- Iteration can backfire — the agent might "improve" a perfectly fine draft into a worse one
- Comparing a screenshot to a reference is itself a noisy visual judgment task; the agent isn't immune to its own visual biases

Running both variants in the same eval campaign gives a direct comparison: same task, same model, same prompts, only the rendering tool differs. The delta in scores is a clean signal about whether the visual feedback loop is worth its cost.

### The render contract — one per page, only when complete

The render tool isn't a free-iteration sandbox. The agent is instructed via its `instruction.md` to **render each page only once, and only after the page is fully written**. The framing is *"render is your final verification pass — not a polish loop."*

This shape was chosen deliberately:

- **Unbounded rendering** risks the agent burning its 60-min budget in render → tweak → render → tweak spirals, drifting away from a good early draft.
- **Zero rendering** collapses the iter variant into oneshot — no A/B signal.
- **One render per page after completion** is the minimum useful feedback: forces the agent to commit to a draft, see it, then fix what's broken — but blocks the over-iteration failure mode.

---

## 4. Track A — the deterministic grader

### What it does

Track A is the always-on, fully-deterministic side of the dual-track grading regime. Given the agent's `/workspace/output/` and the task's pre-computed ground truth, it scores six criteria and combines them via a weighted mean × a multiplicative framework-compliance gate. No model in the loop — every sub-grader is describable in two sentences and produces bit-identical scores across runs.

The six criteria and their weights:

| Criterion | What it measures | Weight |
|---|---|---|
| `layout_structure` | Where things sit visually (graded at desktop, tablet, mobile) | 2.5 |
| `component_presence` | Whether the expected components are rendered | 2.0 |
| `color_palette` | What colors the user sees | 1.5 |
| `typography` | What fonts the user sees | 1.5 |
| `image_content_fidelity` | What images the user sees | 1.5 |
| `visible_text_fidelity` | What text the user reads | 1.0 |

Plus a `framework_compliance` gate that returns 1.0 (pass) or 0.3 (violation) — applied as a multiplier, not a weighted term.

### Why fully deterministic

Track A is the cheap, reproducible backbone. Two grading runs against the same artifacts must produce the same number to the last decimal. This rules out:

- Anything with an LLM in the loop
- Anything with learned features
- Anything with significant runtime randomness

The constraint forces every grader to be **describable in two sentences**. If a grader needs a paragraph to explain its mechanism, the design philosophy says it doesn't belong in Track A.

### Why a weighted mean × multiplicative gate

The composition is: `score = weighted_mean(6 criteria) × gate`, where `gate ∈ {1.0, 0.3}`.

**Weighted mean** rather than a learned aggregation because the weights are interpretable and stable — `layout_structure` matters 2.5× as much as `visible_text_fidelity` because layout *is* design while exact text is incidental. Tuning the weights is a conversation, not a fitting problem.

**Multiplicative gate** rather than another weighted term because `framework_compliance` is categorical, not gradient. An agent that violates the framework constraint (e.g., emits a React component for an HTML-only task) hasn't done the task — it's done a different task. We don't want a "good visual design + framework violation" rollout to outscore a "mediocre visual design + framework respected" rollout on the strength of the design alone. The 0.3 multiplier caps the violator at 30% of what the rest of the rubric would award.

### The macro/micro tension Track A is designed to land in

Some criteria measure macro features (does the page have a header? is the color palette mostly cool?). Others measure micro features (are exact font sizes within range? do specific colors match by CIEDE2000?). Track A deliberately straddles both:

- Macro signal makes Track A robust to small implementation differences. An agent using a slightly different `font-family` still scores well on `typography` if the visual class matches.
- Micro signal stops the macro from being too forgiving. An agent that renders the right *kind* of page but with wildly different colors gets caught by `color_palette` even if the layout is fine.

This is the design philosophy. The implementation reality (covered in the per-criterion section below) had to navigate one specific failure mode of this design: when a criterion's measurement is too micro (Hungarian-IoU on every DOM bbox), it punishes near-correct outputs harshly enough to lose ranking power. When too macro (one question: "does the page have a header?"), it saturates at 1.0 and stops discriminating. Each criterion is a separate tuning conversation.

---

## 5. Per-criterion deep-dive

This section walks through each of Track A's six criteria — what it measures, how it measures, and the design choices behind the mechanism. Each criterion is paired with its Track B counterpart (same question pack, atomic 1-5 scaled judge verdicts) under the same weight.

Construct-validity evidence for each criterion (oracle pass + targeted-corruption table) lives in [`grading/SENSITIVITY.md`](grading/SENSITIVITY.md), regenerated by `python grading/sensitivity.py`.

### 5.1 `layout_structure` — where things sit visually

#### What it grades

Whether the agent's page lays out content the same way the reference does — same regions in the same positions, same proportional spacing, same content density per section — at desktop, tablet, and mobile. Highest-weighted criterion (2.5) because layout is what makes a design recognisably itself.

#### Mechanism

For each (page, viewport): render the agent's HTML at the viewport via Playwright, load the pre-captured reference screenshot, resize both to a common 720px width preserving each image's own aspect ratio, pad the shorter to match the taller's height with its dominant background color, then compute `skimage.metrics.structural_similarity`. Per-page score = mean across viewports. Overall score = mean across pages.

#### Why this approach

SSIM has been the standard image-quality metric for two decades and is a single library call. It captures spacing differences, proportional drift, missing content below the fold, and broken responsive reflow directly from pixels — without needing element matching, thresholds, or DOM walking. We considered several deterministic alternatives from recent literature and chose SSIM for being the simplest one that aligns with how a human reviewer perceives layout similarity.

#### What SSIM doesn't catch

SSIM compares pixels, not DOM structure. Two pages that look identical but have radically different HTML score perfectly — fine, since the benchmark grades visual design, not markup. Element-level signal ("did the agent render the hero correctly?") is now `component_presence`'s job.

#### Closing the macro/micro gap with Track B

After observing in the canonical evaluation that Track B's `layout_structure` questions saturated at the top of the 1-5 scale while Track A's SSIM measured real positional and dimensional drift on the same trials, we tightened the question pack to require pixel-tolerance matching. The loose "approximately the same location" dominant-element check was replaced with a strict same-quadrant test; the page-height tolerance was narrowed from ±30% to ±10%; two new questions were added covering adjacent-element spacing (±20%) and region-proportion (±10%) tolerances. A per-criterion override in the judge's system prompt anchors `layout_structure` at the same strictness — "approximately matches" caps at 3, not 5. The net effect: the deterministic SSIM measurement and the judge's perceptual judgment now describe the same thing more closely.

### 5.2 `component_presence` — whether the expected components are rendered

#### What it grades

For each page, whether the components the author committed to in `design.json` (header, hero, stats-row, cards-grid, sidebar, timeline, footer, etc.) actually appear in the agent's render. Second-highest-weighted criterion (2.0) — components are the building blocks of the design, and an agent that drops one has failed at replicating that design.

#### Mechanism

A "macro-block" geometric heuristic: walk the agent's DOM via Playwright, keep block-level elements whose bbox area is between 1% and 95% of the page area, dedupe by spatial containment (drop inner blocks whose parent is already in the list). Repeat on the reference. Per-page score = `1 − |Δ| / max(N_agent, N_reference)`, where Δ is the difference in macro-block counts. Mean across pages.

#### Why this approach

The criterion can't rely on author-side class names or `data-component` tags because the agent doesn't know the reference's class naming convention (only the description and the screenshot). A purely geometric definition of "a component" — a sufficiently large block-level region — works without that coupling. The 1–95% area threshold keeps the count from being dominated by tiny icons (below the floor) or full-page wrappers (above the ceiling).

#### What this doesn't catch

Two pages with the same number of macro-blocks at the same scales score the same, even if those blocks contain wildly different content. The criterion checks *count and rough size*, not *identity*. Identity-level signal is the Track B judge's job — its `component_presence` question pack asks per-component questions like "is this card placed in the same region as in the reference?" against the design.json component list.

### 5.3 `color_palette` — what colors the user sees

#### What it grades

Whether the agent's rendered pages use the same color palette as the reference — dominant background, primary and secondary accents, overall warmth/coolness, contrast level, saturation. Weighted at 1.5; not as fundamental as layout but a major contributor to whether a design "feels" right.

#### Mechanism

For each page: k-means cluster the rendered screenshot's pixels in LAB color space with k=8 and a fixed random seed. This produces an 8-color palette per page. Compare against the reference's pre-captured palette via Earth-Mover's Distance, where the per-color-pair distance is computed using CIEDE2000 (the perceptual color-distance standard). Per-page distance → similarity via a fixed CIEDE2000 threshold. Mean across pages.

#### Why this approach

LAB space is perceptually uniform — a Euclidean step in LAB corresponds to a roughly uniform "how different do these colors look to a human" judgment, unlike RGB. K-means in LAB is the standard way to extract a representative palette from an image. EMD (rather than direct pairwise comparison) handles the case where the agent's palette has the right colors in slightly different proportions. CIEDE2000 is the most refined color-distance metric the field has produced; using it for the per-pair distance keeps the criterion grounded in perception rather than raw RGB math.

#### What this doesn't catch

Color *placement* is invisible to this criterion — if the agent and reference use the same five colors but the agent puts the orange accent on buttons while the reference uses it for headlines, the palette extraction sees the same five colors and scores high. Placement signal is the Track B judge's job (its pack asks questions like "is the accent color applied to comparable UI elements as on the reference"). The criterion also can't tell if a color is being used appropriately — bright red on a background versus on an error message both extract as "bright red present."

### 5.4 `typography` — what fonts the user sees

#### What it grades

Whether the agent's rendered text uses the same font properties as the reference — font family per region (serif vs. sans vs. mono vs. display), body and heading sizes, font weights, the visual hierarchy between headings and body. Weighted at 1.5 — the same tier as color and image fidelity; meaningful but second to layout and component structure.

#### Mechanism

For each text node visible on the page (via Playwright + `getComputedStyle`): extract `fontFamily + fontSize + fontWeight + lineHeight`. Aggregate per page, area-weighted by the text node's rendered bbox area. Compare against the reference's pre-captured typography manifest. Per-page score = fraction of area-weighted text whose computed-style tuple matches the reference's corresponding text within tolerance.

#### Why this approach

Reading `getComputedStyle` directly from the rendered DOM gives us the actual resolved font properties — what the user sees — not what's literally written in the CSS. An agent that writes `font-family: "Inter"` but doesn't include the font file falls back to the browser default, and `getComputedStyle` reports that fallback. Catching this naturally is important because font fallbacks are a common quiet failure mode. Area weighting reflects what dominates the page visually: 500px² of large heading text matters more than 50px² of small footer text, even though both are "one text node."

#### What this doesn't catch

Typography choices that look right to a human but differ in computed-style values — e.g., `Roboto` vs. `Inter` at the same size, weight, and line-height — score as a miss even though they're visually nearly indistinguishable. The Track B judge picks this up with a "font family class match" question (serif vs. sans vs. mono vs. display), which is what the human eye actually reads. The Track A check is stricter than the visual reality on purpose: it provides a clean computed-style anchor, while Track B does the visual judgment.

#### The fairness fix: declared font-family names in instruction.md

After auditing reference CSS in the canonical run, we observed that several tasks declare `@font-face { font-family: 'Fraunces'; … }` while the actual file on disk is `source-serif-4-400.woff2`. The agent had no way to derive the correct family name from screenshots or filenames alone — the typography grader was effectively testing an unwinnable sub-task. The fix: each task's `instruction.md` now includes the canonical `@font-face` declarations extracted from the reference CSS at packaging time, giving the agent the exact family names + file paths to use. The strict Track A check is preserved (computed-style still demands exact match), but the test is now fair: agents who follow the declarations score well, agents who don't are penalised for a real failure rather than an impossible identification task.

### 5.5 `image_content_fidelity` — what images the user sees

#### What it grades

For each `<img>` element the agent renders: whether the image at that bbox position contains the same visual content as the corresponding reference image. Also catches text-in-images (banner copy, embedded SVG labels). Weighted at 1.5; matters more on image-heavy pages, less on pure-text dashboards.

#### Mechanism

For each agent `<img>`: find the spatially-corresponding reference `<img>` via bbox matching. For each matched pair, compute two sub-scores: (1) a perceptual-hash distance — `pHash` of the agent's rendered image region vs. the reference's pHash (pre-computed at recipe time), Hamming distance below threshold = match; (2) OCR over both image regions via PaddleOCR, Sørensen-Dice on the extracted text strings — catches whether text baked *into* an image is content-identical. The per-image score combines these. Mean across images per page; mean across pages.

#### Why this approach

Perceptual hashing is the standard deterministic way to ask "are these two images visually the same?" — robust to small color shifts, anti-aliasing, format conversion, but sensitive to actually different content. It's also cheap: at grade time we compare two 64-bit hashes, no neural net in the loop. The OCR layer is a separate axis — many design references include text inside images (button labels rendered as part of a hero illustration, signage in a screenshot, captions baked into an SVG) and pHash by itself can't tell whether the image *says* the same thing. Combining both means the criterion catches both "wrong image" and "right image, wrong text inside it."

#### What this doesn't catch

If the agent doesn't render an `<img>` at all where the reference has one, the criterion can't grade what isn't there — that's `component_presence`'s job. The score can also be lower than the agent "deserves" when the asset-picking subtask fails: a clean dashboard that uses `food-hero-1.jpg` instead of the reference's `food-hero-3.jpg` reads visually similar but pHash flags the mismatch. We accept this as the intended cost of the asset pool design (§1) — picking the right image is part of design replication, not separable from it.

#### Closing the gap with strict identity matching

The original Track B question "Is the same photograph (matching subject and composition) visible somewhere" was interpreted by the judge as "same *kind* of photograph" — two food-hero photos both registered as a match even when their pixel content (and therefore pHash) differed. We rewrote the question to demand the *same exact photograph*, with a hard cap of 2 if the agent's image is "a different photo of the same kind of thing." A per-criterion override in the judge's system prompt anchors `image_content_fidelity` at the same strictness as pHash: a 5 requires pixel-content match. Combined with the agent-side asset-matching guidance described in §1, the result was that both tracks moved together — agent choices improved, judge grading tightened, deterministic and perceptual measurements ended up describing the same thing.

### 5.6 `visible_text_fidelity` — what text the user reads

#### What it grades

Whether the actual text on the agent's page matches the reference — headings, button labels, navigation items, body copy, numbers / dates / currencies. Weighted at 1.0 — the lowest of the six, on purpose. Exact text matters less than visual design for a replication benchmark; "headline says something" matters more than "headline says exactly this."

#### Mechanism

For each page: extract every text node's `textContent` via Playwright DOM walk. Tokenize. For short labels (≤20 words), compute Sørensen-Dice similarity against the corresponding reference text node. For longer fields, compute ROUGE-L instead — better at catching paraphrase-style drift in body copy. Per-text score is the lower of the two when both apply. Mean across text nodes on the page; mean across pages.

#### Why this approach

DOM textContent is the cleanest deterministic source for "what does the user read": rendered text after all the templating, all the CSS `::before`, all the JS interpolation has resolved. Sørensen-Dice is fast and handles short-label fuzzy match (e.g., "Sign Up" vs. "Sign up"). ROUGE-L is the standard for longer-form similarity, tolerating word reorderings and minor paraphrase that a strict equality check would reject. Taking the lower of the two on overlapping fields keeps the grader honest: the agent doesn't get credit on one metric while failing the other.

#### What this doesn't catch

Text rendered *inside images* (button labels baked into a hero illustration, captions on screenshots) is invisible to DOM textContent — that's `image_content_fidelity`'s OCR layer. Visually-emphasized words (the largest text, the boldest text, the most-colored text) aren't distinguished from any other text by this criterion; the Track B judge's `vt_q10` question covers that. The criterion also can't grade whether the agent invented facts that match the *style* of the reference but contain wrong information ("a great company" vs. "the leading provider in Texas"); the Track B judge picks that up too.

---

## 6. `framework_compliance` — the gate

### What it grades

Whether the agent honored the framework constraint declared in `design.json.allowed_frameworks`. For this benchmark, that constraint is always `["html-css"]` — the agent is expected to ship static HTML + CSS, no React, no Vue, no JS bundlers, no build step. The gate detects whether the agent's `/workspace/output/` complies, and returns either **1.0 (pass)** or **0.3 (violation)**.

The 0.3 value isn't a score — it's a *multiplier* applied to the weighted mean of the six criteria. An agent that violates the constraint can score at most 30% of what the rest of the rubric would award.

### Why multiplicative, not a weighted term

If `framework_compliance` were just another weighted criterion (e.g., weight 2.0), an agent that produced a beautiful React component for an HTML-only task would still get partial credit on every other criterion — the visual design might score well, the colors might match, the typography might be right. The weighted-mean math would award something like 0.7 even though the agent did the wrong task entirely.

The multiplicative gate prevents this: framework compliance is **categorical**. Either the agent followed the spec or it didn't. A violation drags every other criterion's contribution down by the same multiplier, so a "good visual design with framework violation" rollout can't outscore a "mediocre visual design with framework respected" rollout on the strength of the design alone.

### Why 0.3, not 0

A hard 0 ("complete failure") would discard any signal about what the agent *did* produce — useful information for debugging and for understanding agent behavior even when the constraint is missed. 0.3 keeps the signal alive while still strongly penalising the violation. A rollout that scores 0.7 on the rest of the rubric and 0.3 on the gate ends up at ~0.21 final — readable as "the agent did decent design work but missed the framework," which is the correct interpretation.

### Mechanism

File-listing + dependency-manifest inspection. The check walks `/workspace/output/` and flags violations: presence of `package.json`, `tsconfig.json`, `vite.config.js`, JSX/TSX files, references to React/Vue/Svelte/Angular in the HTML, `<script src>` tags pointing at framework CDNs, etc. Pass → 1.0; any violation → 0.3.

### What this doesn't catch

The gate is checking declared *framework* compliance, not subtler style violations. An agent that ships HTML + CSS but uses Tailwind CDN classes, or that inlines a massive `<style>` block instead of using `styles.css`, passes the gate — those are stylistic choices, not framework choices. Tighter style enforcement (if we ever want it) would live as a separate, additional grader, not as part of the gate.

---

## 7. Track B — the LLM-as-judge

### What it does

Track B is the parallel grading regime that complements Track A's deterministic measurements. Where Track A asks "what do the bbox JSONs, pixel arrays, computed styles, and pHashes say?", Track B asks "what does a vision-capable LLM say when shown the reference and the agent's screenshots side by side?".

Same six criteria as Track A. Same weights. Same `framework_compliance` gate. The two tracks produce two final scores (`score_objective` and `score_judge`) reported **side by side, never aggregated**. Disagreements between them are informative, not a problem to be averaged away.

### Why a second track at all

A purely deterministic grader is reproducible but limited. It can't easily answer questions like *"is the most visually dominant element on the agent's page in approximately the same location as the reference's?"* or *"does the agent's color mood match the reference's?"* — questions where the right answer is a perceptual judgment, not a bbox measurement.

A purely judge-based grader is the opposite: rich perceptual signal, but expensive and prone to its own biases.

The dual-track design treats them as **two independent measurement systems**. Where they agree, we have high confidence. Where they disagree, the gap is itself a signal — pointing either at a Track A measurement that's too literal (too micro), or at a Track B judge that's being too lenient (too macro). Both modes have been observed and both have been pulled back into alignment by tuning either side. The point isn't to pick a winner; it's to triangulate.

### Atomic questions, 1-5 anchored verdicts

For each criterion, a fixed question pack of atomic questions ("Is the dominant background color similar?", "Are headings rendered with the same visual hierarchy?", etc.) is answered independently. The atomicity principle: one property per question, no conjunctions, every question phrased to elicit a single judgment.

Each question is answered on a **1-5 anchored scale**:

- **5** — matches indistinguishably
- **4** — mostly matches, minor differences a casual viewer wouldn't notice
- **3** — partial match, at least one specific visible difference
- **2** — major divergence
- **1** — does not match (completely wrong, missing, or unrelated)

The scale lives in the judge's system prompt with a **load-bearing no-drift rule**: *"if you can identify any specific visible difference, the score cannot exceed 4."* This is the anchor that stops the model from defaulting everything to 5.

Per-criterion score = `(mean_raw_verdict - 1) / 4`, mapping the 1-5 scale into [0, 1] so the same weighted-mean machinery as Track A composes cleanly.

### Why 1-5 (and not binary, and not 1-10)

Originally Track B used **binary 0/1** verdicts — one digit per question. Two grading runs into the canonical eval revealed a saturation problem: most questions returned 1 for almost every trial. Atomic questions phrased as "does the agent's page have a header similar to the reference?" get yes for any page with a header, regardless of how well that header replicates the design.

Tried two responses, in order:

1. **Rewrote the questions**. Cut tautological ones, added harder ones. Helped slightly. Didn't fix the underlying problem — the binary collapse meant "close-but-wrong" and "totally wrong" both rounded to 0; "perfect" and "broadly similar" both rounded to 1.
2. **Switched the scale from binary to 1-5**. This is the real fix. The judge now has room to express degree of match without losing per-question atomicity. Yes-biased questions that previously returned 1 across the board now spread across 4 and 5 depending on whether any specific difference is visible.

Considered 1-10 but rejected it — too many buckets for the judge to anchor reliably; without strong rules per digit, judges drift to clustering at 6-8. 1-5 is the sweet spot. Five anchored buckets is what humans handle on Likert scales for a reason.

### Why batched calls, one per (criterion, page, viewport)

The naïve implementation makes one API call per (question, page, viewport) — for our setup that's ~700 serial calls per trial, each ~15s. Infeasible.

The shipped implementation batches: one API call carries the two images (reference + agent) plus all the questions for that criterion+page+viewport bundle. Returns N digits, one per question. Saves ~5-8× cost because image tokens are billed once instead of N times, and saves N-1 round trips of latency.

Atomicity is preserved at the *question level* even though transport is batched: the prompt explicitly instructs the judge that questions are independent and to apply the rubric per-question.

### Per-question caching keyed on content

Every verdict is cached locally and (when running on Modal) in a shared Volume. Cache key:

```
sha256(question_id | ref_screenshot_hash | agent_screenshot_hash | judge_model | SCALE_VERSION)
```

Five-component key means a cache hit requires **everything** to match: same question wording (versioned IDs), same reference image (byte-stable from recipe time), same agent rendering, same judge model, same scale version (`"5pt"` after the binary→1-5 switch; the old binary cache stays on disk but never collides).

This is the lever that makes "re-grading after a code change" cheap. Track A's deterministic math is essentially free to re-run. Track B with cache hits is essentially free too. Only the questions / images / model that *changed* trigger fresh API calls.

The cache discriminator is what made the scale change non-destructive: bumping `SCALE_VERSION` partitioned the cache cleanly without wiping anything. Old binary verdicts are still on disk; nothing references them, but nothing has to be deleted either.

### Robustness to transient API failures

Anthropic's API occasionally returns 529 Overloaded or rate-limit errors. The judge client implements multiple layers of robustness:

1. **SDK-level retries** (built into the Anthropic Python SDK, default ~2 attempts on transient errors)
2. **Outer exponential backoff with jitter** in the judge client (`_with_retry`, up to 5 retries, 2s → 60s)
3. **Per-criterion isolation** in the runner: one criterion's hard failure won't kill the other five
4. **Top-level isolation** in the aggregator: if Track B fails entirely, the trial still emits a valid `reward.json` with Track A only and Track B as `null`. Harbor accepts it; the trial is marked completed.

The combined effect: a five-trial 529 outage during the first canonical run took out 5/20 trials' Track B grading. After the robustness fix, no trials have lost Track B grading due to transient errors.

### Per-criterion overrides for known-lenient cases

The 1-5 scale + no-drift rule works as a general anchoring strategy, but canonical-run data surfaced two specific criteria where the judge consistently scored at the top of the scale even when Track A's deterministic measurement flagged real drift: `image_content_fidelity` (same-category-different-photo treated as a match) and `layout_structure` (sub-pixel font-hinting noise SSIM-penalises, but holistic gestalt looks fine to the judge).

For these two, the judge system prompt carries per-criterion overrides that tighten the rubric:

- For `image_content_fidelity`, a 5 requires pixel-content match (same crop, same lighting, same frame); same-category-different-photo caps at 2.
- For `layout_structure`, a 5 requires same pixel positions and dimensions within ~10% tolerance; visible positional shift or proportional difference caps at 3.

These overrides preserve the dual-track design — Track A and Track B still measure different things — but bring Track B's "5 means perfect" interpretation closer to Track A's actual measurement strictness on the two criteria where the gap was largest. The other four criteria stay on the generic anchored scale.

---

## 8. Composing the two tracks

Three decisions in how Track A and Track B are combined into headline scores worth recording. The weighted-mean × gate composition itself is mechanical; what matters is the choices we made *about* that composition.

### Shared weights between Track A and Track B

The two tracks use **identical weights** on the same six criteria. If Track A says `layout_structure` matters 2.5× as much as `visible_text_fidelity`, Track B says the same.

The reason is interpretability of disagreement. If the two tracks used different weights, a difference between `score_objective` and `score_judge` could be either (a) the two tracks measuring the same criterion differently, or (b) the two tracks weighting the criteria differently — two distinct sources of disagreement collapsed into one number. Sharing weights collapses the ambiguity: any disagreement between the two final scores reflects **measurement differences only**. That's what makes the |Δ| > 0.1 spot-review flag meaningful — it points at a specific criterion where one track sees something the other doesn't.

### Per-criterion failure is "skip", not "0"

A Track B criterion can fail for reasons unrelated to the agent's output — an API outage on that specific criterion, a malformed judge response after retries. The aggregator treats those failures as **None** (skip from the weighted mean), not as **0.0** (judge said the agent failed catastrophically).

The reason this matters: treating a Track B API failure as 0.0 would systematically penalize agents for infrastructure problems they had no role in causing. Treating it as None — skipped from the weighted mean, denominator adjusts accordingly — preserves the meaning of the remaining criteria. A trial with 5 of 6 Track B scores has a reasonable Track B headline; a trial with 0 of 6 Track B scores has `score_judge: null` and reports Track A only. This is what made Track B robustness ship-able: the dual-track design degrades gracefully under infra failure, instead of dragging the headline to zero.

### Never aggregate Track A and Track B into a single number

Tempting to take `(score_objective + score_judge) / 2` and call it "the score." We deliberately don't.

The whole point of the dual-track design is that the two tracks measure different things. Track A is the deterministic surface-feature match. Track B is the perceptual reference-match judgment. Averaging them collapses two interpretable signals into one uninterpretable one. A trial scoring 0.8 / 0.4 (Track A good, Track B harsh) and a trial scoring 0.6 / 0.6 (both tracks middling) would average to the same 0.6 — but they describe very different kinds of agent behavior. The first probably means the agent matched the surface but the perceptual judge spotted real visual divergence. The second means both tracks agree the work is mediocre.

The report shows both side by side. Downstream analysis chooses which to look at for which question. For *"did the agent technically replicate the design?"* → Track A. For *"does it perceptually look like the reference?"* → Track B. For *"are the two tracking together?"* → both, and the gap is itself the signal.
