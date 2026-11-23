# Benchmark library review sheet (slice 11, AC18)

Drafted 2026-11-10 for maintainer approval before any skill uses these entries. Every figure was read on the
source page or in the report file I fetched; nothing is from memory or from a secondary article. Entry files:
`src/rqharness/data/benchmarks/<scenario_type>/<entry_id>.yaml`. Amounts are USD. 18 entries, 2 to 3 per type.

How to read confidence: **high** = the mode is a figure stated verbatim and the measure fits the family;
**medium** = figure verified but the measure is a proxy or the range is partly derived; **low** = verified figure,
weak fit to the family, or the range is mostly my assumption. Recommend rejecting low entries unless you accept the caveat.

## Caveats that apply to many rows

- **Widened ranges (IBM rows).** IBM states only a mean. min and max are 0.5x and 2x the mean, an analyst assumption, not source data. The mode is real.
- **UK survey rows (CSBS).** The figures are the share of UK businesses hit in the prior 12 months, used as an annual event rate. min = all businesses, mode = medium (50-249 staff), max = large (250+). Attempts count, not only losses.
- **IBM landing page.** `ibm.com/reports/data-breach` now shows the 2026 edition. I read the 2025 edition figures in a copy of the report (31-page PDF hosted by a law firm, not IBM), so please confirm them against IBM's own 2025 PDF before approval.
- **Kensington URL** is the publisher's own PDF white paper; I found no landing page I could fetch (the press release returned 403).
- IBM, FBI and Coveware figures are means or medians of skewed data; none gives a distribution.

## Entries

| entry_id | type | family | min / mode / max | segment | source and URL | where in source | conf. |
|---|---|---|---|---|---|---|---|
| ransomware-recovery-cost-sophos-2025 | ransomware | primary_loss.response | 765,000 / 1,530,000 / 2,730,000 USD | any, mid_market | Sophos State of Ransomware 2025; sophos.com/en-us/blog/the-state-of-ransomware-2025 | Blog section "The business and human consequences of ransomware": mean recovery cost 1.53M, down from 2.73M; survey 3,400, 100-5,000 employees | medium (min is my assumption) |
| ransomware-ransom-payment-median-coveware-2025 | ransomware | primary_loss.response | 140,000 / 270,000 / 400,000 USD | any, any | Coveware quarterly reports; coveware.com/ransomware-quarterly-reports | Posts Q3 2025 (median 140,000), Q2 2025 (400,000), Q3 2026 (400,000); mode is my midpoint | medium-low |
| ransomware-annual-prevalence-uk-csbs-2026 | ransomware | frequency.lef | 0.01 / 0.03 / 0.07 per year | any, any | UK Cyber Security Breaches Survey 2025/2026; gov.uk/government/statistics/cyber-security-breaches-survey-20252026/... | Section 4.2, Figure 4.4 "Devices targeted with ransomware": 1% / 3% medium / 7% large | medium |
| business-email-compromise-loss-per-complaint-fbi-ic3-2024 | BEC | primary_loss.replacement | 125,613 / 129,192 / 137,134 USD | any, any | FBI IC3 2024 Internet Crime Report; ic3.gov/AnnualReport/Reports | Report PDF: loss by crime type p.10 and p.19 (USD 2,770,151,146; 2023 2,946,830,270; 2022 2,742,354,049); complaint counts p.18 (21,442; 21,489; 21,832). I divided | medium (mean, not median) |
| business-email-compromise-impersonation-contact-uk-csbs-2026 | BEC | frequency.contact | 0.12 / 0.38 / 0.47 per year | any, any | UK CSBS 2025/2026 (URL above) | Section 4.2, Figure 4.4 "People impersonating organisation or staff": 12% / 38% / 47% | low (impersonation is broader than BEC) |
| credential-phishing-click-rate-baseline-knowbe4-2025 | credential phishing | vulnerability.probability | 0.331 / 0.331 / 0.419 | any, any | KnowBe4 2025 Phishing By Industry Benchmarking Report; knowbe4.com/resources/reports/2025-phishing-by-industry-benchmarking | Landing page key findings: baseline phish-prone 33.1%; healthcare and pharma 41.9%; 62,400 organisations | medium-low (simulation, vendor data) |
| credential-phishing-account-takeover-uk-csbs-2026 | credential phishing | frequency.lef | 0.02 / 0.05 / 0.05 per year | any, any | UK CSBS 2025/2026 (URL above) | Section 4.2, Figure 4.4 "Takeovers or attempted takeovers": 2% / 5% / 5% | low (not tied to phishing) |
| credential-phishing-phishing-vector-breach-cost-ibm-2025 | credential phishing | primary_loss.response | 2,400,000 / 4,800,000 / 9,600,000 USD | any, any | IBM Cost of a Data Breach 2025; ibm.com/reports/data-breach | Report p.4 key findings and p.9 Figure 9: phishing vector 4.80M, 16% of breaches | medium (range widened) |
| third-party-breach-supply-chain-vector-breach-cost-ibm-2025 | third-party breach | primary_loss.response | 2,455,000 / 4,910,000 / 9,820,000 USD | any, any | IBM Cost of a Data Breach 2025 (URL above) | Report p.4 key findings and p.9 Figure 9: supply chain compromise 4.91M, 15% of breaches | medium (range widened) |
| third-party-breach-third-party-share-verizon-2025 | third-party breach | vulnerability.probability | 0.15 / 0.30 / 0.30 | any, any | Verizon 2025 DBIR press release; verizon.com/about/news/2025-data-breach-investigations-report | Release text: third-party involvement "doubled to 30%"; 0.15 is implied by "doubled", not stated | low (share of breaches, not an org probability) |
| cloud-misconfiguration-multi-environment-breach-cost-ibm-2025 | cloud misconfiguration | primary_loss.response | 2,525,000 / 5,050,000 / 10,100,000 USD | any, any | IBM Cost of a Data Breach 2025 (URL above) | Report p.8 Figure 7 and text: multiple environments 5.05M | low (not misconfiguration-specific) |
| cloud-misconfiguration-public-cloud-breach-cost-ibm-2025 | cloud misconfiguration | primary_loss.response | 2,340,000 / 4,680,000 / 9,360,000 USD | any, any | IBM Cost of a Data Breach 2025 (URL above) | Report p.8 Figure 7: public cloud 4.68M (23% of breaches; 2024 5.17M). Read from chart layout, text does not repeat it | low (not misconfiguration-specific; chart read) |
| ddos-annual-prevalence-uk-csbs-2026 | DDoS | frequency.lef | 0.03 / 0.05 / 0.09 per year | any, any | UK CSBS 2025/2026 (URL above) | Section 4.2, Figure 4.4 "Denial of service attacks": 3% / 5% / 9% | medium |
| ddos-dos-vector-breach-cost-ibm-2025 | DDoS | primary_loss.response | 2,205,000 / 4,410,000 / 8,820,000 USD | any, any | IBM Cost of a Data Breach 2025 (URL above) | Report p.9 Figure 9: denial-of-service vector 4.41M | low (DDoS rarely causes a data breach; upper bound) |
| insider-data-theft-malicious-insider-breach-cost-ibm-2025 | insider data theft | primary_loss.response | 2,460,000 / 4,920,000 / 9,840,000 USD | any, any | IBM Cost of a Data Breach 2025 (URL above) | Report p.4 key findings and p.9 Figure 9: malicious insider 4.92M (highest vector) | medium (range widened) |
| insider-data-theft-staff-unauthorised-access-uk-csbs-2026 | insider data theft | frequency.lef | 0.01 / 0.03 / 0.06 per year | any, any | UK CSBS 2025/2026 (URL above) | Section 4.2, Figure 4.4 "Unauthorised access by staff, even if accidental": 1% / 3% / 6% | low (includes accidental access) |
| lost-or-stolen-device-theft-vector-breach-cost-ibm-2025 | lost or stolen device | primary_loss.response | 2,035,000 / 4,070,000 / 8,140,000 USD | any, any | IBM Cost of a Data Breach 2025 (URL above) | Report p.9 Figure 9: "Physical theft or security issue" 4.07M | low (vector is wider than devices) |
| lost-or-stolen-device-device-theft-annual-kensington-2025 | lost or stolen device | frequency.lef | 0.38 / 0.51 / 0.71 per year | any, any | Kensington and Vanson Bourne white paper; kensington.com/siteassets/solution-pages/security/2025/secure-your-device-protect-your-data_white_paper_en_us_final_1743091813.pdf | PDF p.3-4: 76% hit by device theft in the last 2 years; 1,000 IT decision makers, US and EMEA. Annualisation (0.38, 0.51, 0.71) is mine | low (vendor-sponsored, annualised by me) |

## Not verified or not used

- Verizon 2025 DBIR full report (10 MB limit on my fetch tool): only the press-release figures were read. BEC median (about 50,000) and misconfiguration shares were seen only in secondary articles and are not shipped.
- Ponemon/DTEX 2025 (USD 17.4M annual insider cost) was verified on the DTEX page but is an annual total per organisation, not a per-event loss, so it is not shipped.
- HHS OCR breach portal, Thales cloud study and NETSCOUT: counts only or figures not readable on a page I could fetch.
- IBM "ransomware 5.08M", "63% refused to pay" were seen in the report but not used.
