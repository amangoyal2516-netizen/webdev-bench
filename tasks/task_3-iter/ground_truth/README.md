# Per-task ground truth

Populated by `recipe/03-package/` from the corresponding `recipe/runs/<task_id>/`
directory (produced by the author + builder + capture pipeline).

Expected contents after packaging:

```
ground_truth/
├── source/                     canonical HTML/CSS/assets (Oracle copies these to /workspace/output/)
│   ├── *.html
│   ├── styles.css
│   └── assets/                 image, font, icon files — same as agent's /workspace/output/assets/
├── screenshots/                same renders as the agent's /workspace/reference/
│   ├── desktop/<page>/{full,001,002,…}.png
│   ├── tablet/<page>/{full,001,…}.png
│   └── mobile/<page>/{full,001,…}.png
├── bboxes/                     pre-computed at recipe time
│   ├── desktop/<page>.json
│   ├── tablet/<page>.json
│   └── mobile/<page>.json
├── palette/<page>.json         k-means LAB clusters
├── typography/<page>.json      computed font/size per text node
├── images/<page>.json          per-<img> bbox + pHash
├── text/<page>.json            visible DOM textContent
└── design.json                 the original design doc (Track B reads this)
```

Harbor mounts this directory into the verifier container at
`/grading/ground_truth/`. It is **never** mounted to the agent container
(separate verifier mode), so the agent can't `cp` ground-truth
HTML into its output to cheat the score.
