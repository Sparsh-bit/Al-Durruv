export type Role = 'admin' | 'analyst' | 'viewer'
export type User = { id: number; email: string; full_name: string; role: Role; is_active: boolean }

export type Product = {
  id: number
  sku: string
  name: string
  brand: string
  description: string
  category: string
  pack_size: string
  net_quantity: number | null
  net_unit: '' | 'g' | 'kg' | 'ml' | 'L'
  packaging: string
  catalogue_page: string
  catalogue_pages: number[]
  notes: string
  hs_code: string
  hs_status: 'suggested' | 'confirmed'
  hs_note: string
  hs_description: string
  has_trade_data: boolean
}

export type DataStatus = {
  hs_codes: number
  loaded: number
  failed: string[]
  active: { hs_code: string; status: 'queued' | 'running'; message: string }[]
}

export type Source = { id: number; url: string; retrieved_at: string; period?: string; adapter?: string; title?: string }

export type Run = {
  id: number
  adapter: string
  scope: string
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  rows: number
  message: string
  error: string
  started_at: string
  finished_at: string | null
}

export type CountryRow = {
  m49: number
  iso3: string
  name: string
  value_usd: number
  net_weight_kg: number | null
  share: number | null
  unit_value: number | null
  year: number
  source: Source
}

export type Overview =
  | { hs_code: string; has_data: false; refresh: Run | null }
  | {
      hs_code: string
      has_data: true
      hs_description: string
      reference_year: number
      reporters: number
      world_imports_usd: number
      trend: { year: number; value_usd: number; reporters: number; complete: boolean }[]
      world_cagr: number | null
      world_cagr_period: string | null
      top_importers: CountryRow[]
      top_importer_trends: { m49: number; name: string; series: { year: number; value_usd: number }[] }[]
      exporters_year: number | null
      world_exports_usd: number | null
      top_exporters: CountryRow[]
      note: string
      refresh: Run | null
    }

export type Component = {
  label: string
  value: number | null
  unit: string
  normalized: number | null
  weight: number
  period: string
  status: 'ok' | 'unavailable'
}

export type Weights = { market_size: number; growth: number; openness: number; price_level: number; data_quality: number }

export type RankedMarket = {
  rank: number
  m49: number
  iso3: string
  name: string
  score: number
  latest_year: number
  latest_value_usd: number
  components: Record<keyof Weights, Component>
  source: Source
  existing_market?: boolean
}

export type CountryDetail = {
  m49: number
  iso3: string
  name: string
  hs_code: string
  series: { year: number; value_usd: number; net_weight_kg: number | null; unit_value: number | null; source: Source }[]
  latest_year: number
  latest_value_usd: number
  suppliers: { m49: number; name: string; iso3: string; value_usd: number; share: number | null; unit_value: number | null; source: Source }[]
  supplier_data_available: boolean
  home_country: string | null
  home_share: number | null
}

export type Relationship = 'buyer' | 'competitor' | 'supplier'
export type Stage = 'identified' | 'researched' | 'contacted' | 'negotiating' | 'won' | 'lost'
export type ScoreComponent = { label: string; normalized: number | null; weight: number; status: 'ok' | 'unavailable' }

export type Company = {
  id: number
  name: string
  country_iso3: string
  country_name: string
  website: string
  relationship_type: Relationship
  roles: string[]
  summary: string
  product_range: string
  product_fit: string
  private_label: 'yes' | 'possible' | 'unknown'
  private_label_evidence: string
  buying_signals: { text: string; url: string; title: string }[]
  markets_served: string[]
  contact: { email?: string; phone?: string; address?: string; contact_url?: string }
  name_on_source: boolean | null
  prospect_score: number | null
  score_components: Record<string, ScoreComponent>
  pipeline_stage: Stage
  notes: string
  hs_codes: string[]
  review_status: 'candidate' | 'verified' | 'rejected'
  has_brief: boolean
  brief_generated_at: string | null
  evidence: { id: number; claim: string; excerpt: string; source: Source }[]
}

export type CompanyBrief = {
  company: string
  generated_at: string
  model: string
  cost_usd: number
  sections: { title: string; statements: Statement[] }[]
  outreach_email: { subject: string; body: string; warnings: string[] }
  evidence: Evidence[]
}

export type NewsItem = { title: string; summary: string; date: string; topic: string; url: string; source_title: string }

export type CompanyProfile = {
  name: string
  brand: string
  country_iso3: string
  founded: string
  description: string
  label_languages: string[]
  certifications: string[]
}
export type AppSettings = { company_profile: CompanyProfile; export_markets: string[]; ai_monthly_budget_usd: number }

export type Label = 'verified' | 'estimate' | 'inference' | 'unavailable' | 'unverified'
export type Statement = { text: string; label: Label; evidence_ids: string[]; issues: string[] }
export type Evidence = { id: string; kind: string; text: string; values: number[]; source: Source | null }

export type AskResponse = {
  statements: Statement[]
  follow_up_questions: string[]
  evidence: Evidence[]
  usage: { model: string; input_tokens: number; output_tokens: number; cost_usd?: number }
}

export type ReportSummary = {
  id: number
  title: string
  hs_code: string
  product_id: number | null
  model: string
  created_at: string
  validation: { statements: number; exported: number; withheld: number }
}

export type ReportContent = {
  title: string
  product: string
  hs_code: string
  hs_description: string
  generated_at: string
  model: string
  sections: { title: string; statements: Statement[] }[]
  evidence: Evidence[]
  ranking: { rank: number; name: string; iso3: string; score: number; latest_value_usd: number; latest_year: number }[]
  companies: Company[]
  validation: { statements: number; exported: number; withheld: number }
}

export type Provider = { key: string; name: string; status: string; detail: string }
export type Quote = {
  id: number
  origin: string
  destination: string
  destination_iso3: string
  mode: string
  container: string
  carrier: string
  incoterm: string
  assumptions: string
  cost_usd: number | null
  transit_days: number | null
  provenance: string
  source_note: string
  valid_until: string | null
  created_at: string
}
