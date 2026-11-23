# Project Design

The visual brief for the HTML report that `rqh report` writes. Direction and References name the
style and the reference design systems the report was designed against (spec decision D25).

Version: 1
Direction: taste:brutalist-skill:swiss-industrial-print
References: reference:ibm, reference:clickhouse

## Palette
Mostly monochrome with one signal colour. Light: paper #F4F4F0, band #EAE8E3, ink #111110, secondary ink #4F4F49, hairlines #B3B1A7 and #D6D4CA, signal red #E61919 (text-safe #C41212, on-signal #FFFFFF). Dark: #121212 / #1B1B1A / #EDEDE7 / #AEAEA5 / #4A4A46 / #2C2C2A, signal #FF2A2A (text #FF5A4F). Variants: baseline = ink, first control = signal, further controls = greys #77776F and lighter; variants also differ by dash pattern and marker shape. Signal red is reserved for the headline risk reduction, the YOLO tag, the p90 marker and the worst-tail bars, never for decoration. All colours are CSS custom properties on :root; an org theme may override only the signal colour, logo and display name.

## Typography
System stacks only, no web fonts. Display: Arial Black / Helvetica Neue heavy at 900 with tight negative tracking (-0.04em to -0.05em) for headline figures and section headers; body: Helvetica Neue / Arial / system sans at 15px, 1.42 line height; labels, ticks, kickers and metadata: ui-monospace uppercase at 10-11px with 0.06-0.08em tracking. Extreme scale contrast: the hero figure is clamp(4rem, 12.5vw, 9.5rem); summary figures clamp(2.6rem, 6.4vw, 5rem). Tabular numerals everywhere. Headers state messages, not labels.

## Layout
Rigid 12-column modular grid, max width 1240px, 16px gutters on phones. Sections are numbered 01-09 with a large section number in the left column and content in the right; flush-left ragged-right text, no centred blocks. Structure comes from rules, not boxes: 3px ink rule above key bands, 2px under the masthead, 1px hairlines between cells, zero border radius, no shadows, no gradients. Charts are technical drawings: hairline axes, monospace ticks, direct labels instead of legends, figure captions as FIG. 0N. Grid items set min-width: 0; wide charts and tables scroll inside their own box, never the page. Print-first: @page margin 12mm, light palette, appendix expanded, controls hidden, sensible breaks between sections.

## Motion
None by default. Interactive feedback only: hover readouts and focus states appear instantly; no scroll-reveal, no animated counters, no transitions longer than 120ms. prefers-reduced-motion removes all transitions.

## Accessibility
Text contrast at least 4.5:1 in both themes (signal text uses the text-safe red). Headings in order h1 to h3; every chart is an inline SVG with title and desc, and its key values are also in text or a table. Controls (threshold input, variant toggle, details) are keyboard reachable with a 3px signal-colour focus outline. Variants never rely on colour alone. Works at 375px with no horizontal page scroll.

## 3D Intent
None. The report has no 3D content.

## Custom Brief
The report is evidence: it must read as precise, sober and reproducible, look excellent printed to PDF, and keep every number traceable to the run summary. Approved concept: design/concepts/report.html (rendered from sample data); the production template in src/rqharness/report/ follows it.
