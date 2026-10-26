# Client requirements vs. current build (26 Oct 2026)

Legend: **Done** = built and tested · **Partial** = works but missing parts the client asked for ·
**Missing** = not built · **Blocked** = needs data or a subscription we do not have.

## A. Product & HS-code intelligence

| Requirement | Status | Notes |
|---|---|---|
| Catalogue import (Excel/CSV), names, descriptions, HS codes, categories | **Done** | Durra catalogue loaded: 127 SKUs, 26 collections, 37 HS codes, pack size, packaging, catalogue page images. |
| HS codes for each product | **Partial** | The PDF has no HS codes. Codes were assigned from product descriptions and marked **Suggested**. The client or a customs broker must confirm them (one click per product). |
| Importing and exporting countries per HS code, values, quantities, by year | **Done** | UN Comtrade, 6 years, all reporters. Loading for all 37 codes is in progress; it pauses automatically when the free API quota runs out. |
| Country share with a defined denominator | **Done** | Shares are labelled "of reported imports/exports". |
| Trends, growth, leading partners, growing markets | **Done** | CAGR on complete years only; partial years are flagged. |
| Source, reporting period, retrieval date on every figure | **Done** | |
| Focus on the client's 85+ existing export markets | **Missing** | Needs the client's country list. Plan: "our markets" setting, used to filter, highlight and compare in rankings. |

## B. Supplier & competitor intelligence

| Requirement | Status | Notes |
|---|---|---|
| Supplier-country comparison and market concentration | **Done** | Per-market supplier shares and an openness (HHI) score. |
| Companies in the same category with evidence | **Partial** | AI web research exists for "competitors" (manufacturers/exporters). |
| Three distinct groups: supplier landscape / competitors / potential buyers | **Missing** | Companies currently carry roles only. Plan: an explicit relationship type, separate tabs, and research for each. |
| Competitors' product ranges, markets, export evidence | **Missing** | Plan: structured research fields with sources. |

## C. Buyer discovery & lead generation

| Requirement | Status | Notes |
|---|---|---|
| Find importers, distributors, wholesalers, retailers, brand owners | **Done** | AI research requires a source page for every company; analyst verifies or rejects. |
| Profile fields: product fit, buying signals, private-label fit, contact info, opportunity score, confidence | **Missing** | Plan: extend the research schema; a transparent prospect score computed in Python; public business contacts only. |
| Purchase estimates only with sufficient evidence | **Blocked** | Needs shipment records (ImportGenius/Panjiva/Volza) or client sales history. Shown as "Unknown" until then. |
| Explain why each prospect is relevant | **Partial** | One-line summary today. Plan: evidence-linked "why this prospect" statements. |

## D. Customer business intelligence

| Requirement | Status | Notes |
|---|---|---|
| Per-company brief (products, markets, suppliers, trend, PL fit, negotiation approach) | **Missing** | Plan: AI company brief with Verified / Estimated / Inferred / Unknown labels and citations. |
| Order frequency, monthly volume, spend | **Blocked** | Same as C: no legitimate source in the demo. |

## E. Logistics & shipping

| Requirement | Status | Notes |
|---|---|---|
| Origin/destination, mode, transit time, cost, carrier, assumptions, date | **Partial** | Client-entered quotes with source and validity date; freight API marked "Not connected". |
| Route comparison | **Missing** | Plan: compare quotes per destination (cost per kg/container, days). |
| Live freight pricing | **Blocked** | Needs a Freightos / Searates subscription. |

## F. Global market report

| Requirement | Status | Notes |
|---|---|---|
| Top importers/exporters, values over time, shares, growth, sourcing countries | **Done** | |
| Relevant public market developments and news | **Missing** | Plan: AI web research for recent market news per HS code, with sources and dates. |
| Tariffs / market access | **Missing** | Plan: World Bank WITS tariff lookup (free) as a supplementary adapter. |

## G. AI business analyst

| Requirement | Status | Notes |
|---|---|---|
| Natural-language questions answered from platform data with sources, periods, confidence | **Done (not live-tested)** | Grounding validator withholds unsupported numbers. Needs an API key to test live. |
| Knows the client's own products | **Missing** | Plan: add the catalogue (products, pack sizes, collections) to the evidence pack. |
| Prospect research and negotiation briefs on request | **Missing** | Plan: company-level context and a negotiation-brief action. |

## H. Recommended extras

| Feature | Status |
|---|---|
| Opportunity dashboard (markets) | **Done** |
| Saved prospects / lists | **Done** (basic) |
| CRM pipeline stages + notes | **Missing** |
| Outreach email drafts | **Missing** |
| Exports CSV/Excel/PDF | **Partial** (reports and catalogue; prospect-list export missing) |
| Data-source admin, refresh history | **Done** |
| User roles | **Done**; audit trail **Missing** |

## AI cost control and guardrails (requested 26 Oct)

| Item | Status |
|---|---|
| Cheapest capable model (`claude-haiku-5-5`) for all tasks | **Done**: one setting; per-task override planned only where Haiku proves insufficient |
| Web-search cap per research run, 7-day result cache | **Done** |
| Token/cost logging per call, monthly budget cap, admin cost view | **Missing**: planned |
| Prompt caching of the fixed instructions | **Missing**: planned |
| Grounding: cite evidence, numbers must match evidence, failed statements withheld | **Done** |
| Companies kept only if tied to a retrieved source; page re-checked | **Done** |
| Web content treated as data, never instructions (prompt-injection guard) | **Partial**: add explicit rule and output checks |
| No personal data beyond public business contacts | **Missing**: rule plus field restrictions planned |

"Training" note: the AI is **not fine-tuned**. It is grounded on the platform's data at question time
(retrieval), which keeps answers current and auditable and costs nothing extra. Fine-tuning would not
make it more accurate on facts and is not offered for these models.
