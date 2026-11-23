# Report concept brief

Three design spikes of the same report, each in a different visual direction, so the maintainer can pick one (spec decision D25). Every spike uses **identical content and data**; only the visual direction differs.

## Inputs

- `design/concepts/sample-data.json`: computed by a toy simulation of a fictional company. Every number shown must be read from this file. Embed it verbatim in the page as `<script type="application/json" id="rq-data">…</script>` and derive display values in JavaScript, or pre-compute them by hand from the file. Never invent a figure.
- The spec, `specs/v1-harness.md`: § Constraints, § Component contracts → `render_report`, and AC21–AC25 describe what the real report must do.

## Hard rules (every spike)

1. **One self-contained HTML file.** No network requests of any kind: no CDN, no web fonts, no external images. Use system font stacks only, e.g. `ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif`, `ui-serif, Georgia, "Times New Roman", serif` and `ui-monospace, "SF Mono", Consolas, monospace`. Citation links (`https://…` anchors in the provenance table) are the only URLs allowed.
2. Include `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'">`.
3. **Charts are inline SVG.** The main charts must be visible with JavaScript disabled: render a static SVG first, from the data, either hand-computed or generated at load time with a `<noscript>` fallback of the static SVG. Preferably draw the SVG directly in markup. JavaScript then *enhances* it: hover readouts, the variant toggle, the threshold input.
4. **Light and dark.** Colours are CSS custom properties on `:root`, redefined under `@media (prefers-color-scheme: dark)`. `body` has an explicit background.
5. **Print.** An `@media print` block: light colours, no interactive controls, the appendix expanded, sensible page breaks.
6. **Responsive.** Works from 375 px to 1440 px wide with no horizontal page scroll.
7. **Accessible.** Real headings in order, sufficient contrast, chart `<title>`/`<desc>` or `aria-label`, focusable controls, no information carried by colour alone (variants also differ by line style or marker).
8. Show a small **"Sample data: fictional company"** marker in the header so the concept is never mistaken for a real report.
9. Wording: say "estimate", never "SWAG". Describe the method as "FAIR-aligned". Keep copy short and plain; headers state messages ("Phishing-resistant MFA pays for itself ten times over"), not labels ("Variants").
10. File size under 400 KB.

## Content, in this order (spec AC22)

1. **Hero.** The one-sentence takeaway. Suggested: *"Credential phishing costs Northwind an estimated $2.1M a year; phishing-resistant MFA would cut that by about two-thirds for $120k a year."* Recompute the figures from the data and round sensibly. Also: the scenario title; the org and run meta (version, date, route YOLO); a **YOLO banner**: "Benchmark-based estimate. Not yet validated against Northwind's own data."; the **data-quality grade** (C) with its score, visually prominent but not alarming.
2. **Summary cards (4–5).** Baseline expected annual loss (mean); 1-in-10-year loss (p90); P(annual loss > $1M); risk reduction from the best variant; return on control for MFA.
3. **Loss exceedance curve.** All three variants overlaid, x = annual loss (log scale works well), y = probability of exceeding. Include a **threshold input**: the reader types an amount, and the page shows P(loss > X) per variant, interpolated from the `lec` points, with a marker on the chart. Hover shows the readout.
4. **Distribution.** A histogram of baseline annual loss, from `histogram`, with mean and p90 marked. A variant toggle switches which variant's histogram is shown.
5. **What drives this.** A tornado or sorted bar of `parameters[].contribution`, each bar labelled with its provenance tier (internal data, SME estimate, benchmark, assumption).
6. **Controls compared.** A table or cards per variant: mean, p90, ALE reduction, annual cost, return on control. The header states the message.
7. **Scenario.** Threat actor, asset, method, loss event (from `scenario`).
8. **Provenance.** A table of every parameter: label, PERT (min / mode / max with units: currency or events per year or probability), tier, and source (with citation link when `url` exists).
9. **Technical appendix.** Collapsed by default (`<details>`): n, seed, package version, NumPy version, inputs hash, PERT method, the methodology disclosure "Loss magnitudes use Beta-PERT distributions (gamma = 4) elicited per FAIR-aligned loss form.", and the full percentile table per variant.
10. **Last section: "What to collect to improve the degree of accuracy".** The three `collect_next` items, each with its parameter, current tier, priority, the system of record, the owner role, the exact ask, and the suggested connectors. Frame it as an actionable checklist that ends the report.

## Formatting

- Money: `$2.09M`, `$729k`, `$120k`; percentages to whole numbers except small ones (`3.2%`); return on control as `10.3×`.
- Use tabular numerals for all figures.
- Variant colours must remain distinguishable in both themes and in greyscale print.
