# Client requirements vs. current build (updated 26 Oct 2026, after live AI tests)

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
| Focus on the client's 85+ existing export markets | **Done** (needs data) | Administration → "Countries we already export to"; ranking shows "Existing market" and filters new vs existing. Client list still to be entered. |

## B. Supplier & competitor intelligence

| Requirement | Status | Notes |
|---|---|---|
| Supplier-country comparison and market concentration | **Done** | Per-market supplier shares and an openness (HHI) score. |
| Companies in the same category with evidence | **Done** | AI research for competitors and for the supplier landscape, each with sources. |
| Three distinct groups: supplier landscape / competitors / potential buyers | **Done** | Separate tabs, separate research, reclassification; only buyers are scored as prospects. |
| Competitors' product ranges, markets, export evidence | **Done** | Product range, markets served, sourced signals per company. |

## C. Buyer discovery & lead generation

| Requirement | Status | Notes |
|---|---|---|
| Find importers, distributors, wholesalers, retailers, brand owners | **Done** | AI research requires a source page for every company; analyst verifies or rejects. |
| Profile fields: product fit, buying signals, private-label fit, contact info, opportunity score, confidence | **Done** | Transparent 0-100 fit score with breakdown; generic business contacts on the company's own domain only. Live-tested. |
| Purchase estimates only with sufficient evidence | **Blocked** | Needs shipment records (ImportGenius/Panjiva/Volza) or client sales history. Shown as "Unknown" until then. |
| Explain why each prospect is relevant | **Done** | "Fit with our products" per company plus the AI company brief. |

## D. Customer business intelligence

| Requirement | Status | Notes |
|---|---|---|
| Per-company brief (products, markets, suppliers, trend, PL fit, negotiation approach) | **Done** | Live-tested ($0.004 per brief) including a draft first-contact email. |
| Order frequency, monthly volume, spend | **Blocked** | Same as C: no legitimate source in the demo. |

## E. Logistics & shipping

| Requirement | Status | Notes |
|---|---|---|
| Origin/destination, mode, transit time, cost, carrier, assumptions, date | **Partial** | Client-entered quotes with source and validity date; freight API marked "Not connected". |
| Route comparison | **Done** | Per destination with cheapest/fastest; carrier, Incoterm, assumptions recorded. |
| Live freight pricing | **Blocked** | Needs a Freightos / Searates subscription. |

## F. Global market report

| Requirement | Status | Notes |
|---|---|---|
| Top importers/exporters, values over time, shares, growth, sourcing countries | **Done** | |
| Relevant public market developments and news | **Done** | Sourced items only; cached 7 days. |
| Tariffs / market access | **Missing** | Next candidate: World Bank WITS tariff adapter. News research already surfaces tariff changes with sources. |

## G. AI business analyst

| Requirement | Status | Notes |
|---|---|---|
| Natural-language questions answered from platform data with sources, periods, confidence | **Done** | Live-tested ($0.002 per answer). |
| Knows the client's own products | **Done** | Company profile (editable) and catalogue products are part of every evidence pack. |
| Prospect research and negotiation briefs on request | **Done** | |

## H. Recommended extras

| Feature | Status |
|---|---|
| Opportunity dashboard (markets) | **Done** |
| Saved prospects / lists | **Done** (basic) |
| CRM pipeline stages + notes | **Done** |
| Outreach email drafts | **Done** (draft only, never sent) |
| Exports CSV/Excel/PDF | **Done** (reports, catalogue, companies, prospect lists) |
| Data-source admin, refresh history | **Done** |
| User roles and audit trail | **Done** |

## AI cost control and guardrails (requested 26 Oct)

| Item | Status |
|---|---|
| Cheapest capable model (`claude-haiku-5-5`) for all tasks | **Done**: one setting; per-task override planned only where Haiku proves insufficient |
| Web-search cap per research run, 7-day result cache | **Done** |
| Token/cost logging per call, monthly budget cap, admin cost view | **Done** |
| Prompt caching of instructions + evidence | **Done** (verified live) |
| Grounding: cite evidence, numbers must match evidence, failed statements withheld | **Done** |
| Companies kept only if tied to a retrieved source; page re-checked | **Done** |
| Web content treated as data, never instructions (prompt-injection guard) | **Done**: rule in every prompt + URL/number validation |
| No personal data beyond public business contacts | **Done**: prompt rule + contact filter (generic mailboxes on own domain) |

"Training" note: the AI is **not fine-tuned**. It is grounded on the platform's data at question time
(retrieval), which keeps answers current and auditable and costs nothing extra. Fine-tuning would not
make it more accurate on facts and is not offered for these models.
