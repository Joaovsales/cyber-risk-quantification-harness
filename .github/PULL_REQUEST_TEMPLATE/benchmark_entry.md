## New or changed benchmark entry

Entry file: `src/rqharness/data/benchmarks/<scenario_type>/<entry_id>.yaml`

### Citation

- [ ] `source.url` is the canonical `https://` page or file of the publisher (no shortener, no search-engine or cache link)
- [ ] `source.title` names the publisher, the report and its edition or year
- [ ] The citation was opened and the figure read on that page; nothing is from memory or a secondary article
- [ ] `source.retrieved_at` and `captured_at` are the date you read it

### Value

- [ ] `period` is the time the figure covers, not the publication date
- [ ] `note` explains how `min`, `mode` and `max` map from the source (stated, derived or analyst assumption)
- [ ] `unit` is `USD` for money (or the matching unit for the parameter family), and any currency conversion is stated in `note`
- [ ] `parameter_family` matches what the figure measures (for example a mean recovery cost is `primary_loss.response`, not a ransom)

### Applicability

- [ ] `segment` (`industry`, `size_band`) and `scenario_tags` use the shared vocabulary
- [ ] `source.applicability_note` says who was surveyed and where the figure fits poorly
- [ ] Applicability rating: high / medium / low, with a one-line reason: <!-- fill in -->

### Checks

- [ ] `rqh library validate` passes on the new file
- [ ] The linkcheck workflow passes (run it from the Actions tab with "Run workflow")
- [ ] `python -m pytest tests/benchmarks -q` passes
- [ ] No paywalled content is copied, and no personal or non-public data is included
