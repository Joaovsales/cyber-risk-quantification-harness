# Sample run: credential phishing leading to business email compromise

A two-variant sample for the fictional organisation Northwind Analytics. It is the run behind the
sample report published on GitHub Pages. The rendered `report.html` is not committed; build it:

```bash
mkdir sample && cd sample
rqh init
mkdir .riskquant/runs/credential-phishing-bec
cp ../examples/credential-phishing-bec/scenario.yaml ../examples/credential-phishing-bec/inputs.yaml .riskquant/runs/credential-phishing-bec/
cp ../examples/credential-phishing-bec/org-profile.yaml .riskquant/org-profile.yaml
rqh validate credential-phishing-bec
rqh run confirm credential-phishing-bec --route yolo --n 50000 --seed 20261109
rqh finalize credential-phishing-bec
rqh report credential-phishing-bec
```

The report is written to `.riskquant/runs/credential-phishing-bec/v1/report.html`. The seed is
fixed, so the same files give the same numbers and the same report.

- `scenario.yaml`: the scenario and its two variants.
- `inputs.yaml`: the estimates (minimum, most likely, maximum) with their provenance.
- `org-profile.yaml`: the organisation profile (name, theme, people, systems).
