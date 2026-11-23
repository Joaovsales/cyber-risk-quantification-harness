# Reading the report

A reader opens `report.html` in any browser and sees the takeaway, summary cards, the loss exceedance curve, the
distribution, the drivers, the variants comparison, the scenario, the sources, a collapsed appendix and "What to
collect to improve the degree of accuracy". The page works without JavaScript, fits a 375 px phone, and runs one
inlined script for the interactive parts.

## Sub-features

- `sections` render in the fixed order, numbered 01–09, with the appendix collapsed. The page title ends with
  "/ risk report".
- `charts`: the LEC (every variant) and one histogram per variant are static inline `svg[role=img]` (4 for the
  sample); the drivers bars are HTML (`.tb` spans), not SVG.
- `mobile` has no page-level horizontal scroll at 375 px.
- `collect` names the three highest-priority inputs, each with an owner role, a system of record and, when the
  profile knows it, a person.
- `interactive` covers the LEC hover readout (`#lec-cursor`), the threshold input (`#thr-in`, with `#thr-help` and
  `#thr-lbl`) and the variant toggle (radio inputs `input[name=hv]` in `fieldset#hv-toggle`, which show one
  `#hists .hist` and hide the rest with `.is-hidden`).
- `theme` covers the org accent and logo through custom properties only (`--sig` and friends), the org badge in the
  masthead (`.org`), plus light/dark via `prefers-color-scheme`.
- `csp` allows only the inlined script, by its SHA-256; nothing loads from the network.

## How to get to it (user POV)

- Open `.riskquant/runs/<id>/v<N>/report.html` in a browser (double-click or `file://`).
- Print it from the browser.

## Driving it with verify.py and a browser

Preconditions:

- A `verify.py run` is ok, and `verify.py serve <run_dir>` has printed a `url`. Open it in a Chromium-family browser
  and run each expression in the DevTools console, or through an agent's browser tool (navigate, JavaScript, resize).

- **Static.** `summary.json` has `section_order`, `section_numbers`, `title_suffix`, `appendix_collapsed`,
  `static_charts_present` (4) and `collect_requests` (3) passing.
- **Open.** The tab title ends with "/ risk report".
- **Order.** `[...document.querySelectorAll('[data-section]')].map(e => e.dataset.section)` returns the ten sections
  in order, and `[...document.querySelectorAll('.sec-no')].map(e => e.textContent)` returns `01` to `09`.
- **Script.** `document.documentElement.classList.contains('js')` is true.
- **Mobile.** Set the viewport to 375×812, then `[innerWidth, document.documentElement.scrollWidth]`. The two values
  are equal.
- **Collect.** The "What to collect" section has three `#s09 li.ck` items, each showing "Owner" and "System of
  record".
- **Threshold.** Type `750k` into `#thr-in` (from a script: set `value`, then dispatch an `input` event). The
  per-variant "Chance annual loss exceeds" values change (80%/26%/13% to 88%/39%/22% for the sample) and `#thr-lbl`
  reads `$750k`. Type `abc`: `#thr-help` has the class `err` and asks for an amount such as 750k, 1.5M or 2000000.
- **Variant toggle.** Click the second radio in `#hv-toggle`. `document.querySelector('#hv-toggle input:checked').value`
  is `mfa`, and `[...document.querySelectorAll('#hists .hist:not(.is-hidden)')].map(h => h.dataset.variant)` is
  `["mfa"]`.
- **Theme.** `getComputedStyle(document.documentElement).getPropertyValue('--sig').trim()` is `#E61919` with
  `prefers-color-scheme: light` and `#FF2A2A` with `dark`. On a `verify.py run --profile
  tests/routing/fixtures/org-profile.yaml` run it is `#1F6FEB` in light mode, and `.org` reads "Northwind".
- **Visual.** Look at `evidence/report-desktop-1280.png` and `evidence/report-mobile-375.png` and compare them with
  `design/concepts/report.html`.
- **Reset.** Return the viewport to its normal size.

## Gotchas

- A `file://` page is a static snapshot that some browser tools cannot read or script. Always use `verify.py serve`.
- A browser pane may be narrower than 375 px, so measure after setting the viewport, not from a screenshot.
- The LEC SVG is wider than 375 px inside its own scroll container. Only `documentElement.scrollWidth` counts.
- The CSP blocks injected network requests and iframes inside the report, so measure the page directly.
- There is no `aria-pressed` anywhere: the toggle is a radio group, so read `checked`, not a pressed state.
- Headless Chromium will not lay out narrower than about 500 px. A plain `--window-size=375,…` screenshot shows a wider
  layout cropped at 375 and looks like overflow. `verify.py` therefore frames the report in a 375 px iframe; the live
  `scrollWidth` measurement stays authoritative.
- Headless Edge may render the screenshots in the dark scheme. That is the page following `prefers-color-scheme`,
  not a bug.
