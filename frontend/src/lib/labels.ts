import type { HsStatus, Identity, Label, Relationship, Stage } from './types'

export const LABEL_META: Record<Label, { text: string; tone: 'green' | 'amber' | 'blue' | 'slate' | 'red'; help: string }> = {
  verified: { text: 'Sourced fact', tone: 'green', help: 'Stated by a cited external source (UN Comtrade, an official company page, an article).' },
  client_provided: { text: 'Client-provided', tone: 'blue', help: "From the client's own information (profile, catalogue, HS list). Not independently verified." },
  estimate: { text: 'Estimate', tone: 'amber', help: 'A modelled figure that the evidence marks as an estimate.' },
  inference: { text: 'Hypothesis', tone: 'slate', help: 'Reasoning or a recommendation based on the cited evidence. Adds no new numbers.' },
  unavailable: { text: 'Unknown', tone: 'slate', help: 'The data needed is not in any connected source.' },
  unverified: { text: 'Unverified', tone: 'red', help: 'Failed automatic checks (a number did not match its evidence). Excluded from exports.' },
}

export const STAGES: { key: Stage; label: string }[] = [
  { key: 'identified', label: 'Identified' },
  { key: 'researched', label: 'Researched' },
  { key: 'contacted', label: 'Contacted' },
  { key: 'negotiating', label: 'Negotiating' },
  { key: 'won', label: 'Won' },
  { key: 'lost', label: 'Lost' },
]
export const RELATIONSHIP_LABEL: Record<Relationship, string> = {
  buyer: 'Potential buyer',
  retailer: 'Retailer account',
  competitor: 'Competitor',
  supplier: 'Supplier',
}

export const HS_STATUS: Record<HsStatus, { text: string; tone: 'green' | 'amber' | 'red' | 'slate'; help: string }> = {
  confirmed: { text: 'Confirmed', tone: 'green', help: 'A reviewer confirmed this HS6 code for trade analysis.' },
  candidate: { text: 'Needs review', tone: 'amber', help: 'Needs verification by the client or a customs broker.' },
  discrepancy: { text: 'Discrepancy', tone: 'red', help: "The client's declared code points to a different product family. Confirm with the customs broker." },
  insufficient_info: { text: 'Insufficient info', tone: 'red', help: 'The product description is not enough to classify it. See the open question.' },
  unmapped: { text: 'Unmapped', tone: 'slate', help: 'No HS6 code is assigned yet.' },
}

export const IDENTITY: Record<Identity, { text: string; tone: 'green' | 'amber' | 'slate' }> = {
  confirmed: { text: 'Identity confirmed', tone: 'green' },
  needs_confirmation: { text: 'Identity needs confirmation', tone: 'amber' },
  unverified: { text: 'Identity unverified', tone: 'slate' },
}
export const PL_META = {
  yes: { tone: 'green', text: 'Private label: evidence' },
  possible: { tone: 'amber', text: 'Private label: possible' },
  unknown: { tone: 'slate', text: 'Private label: unknown' },
} as const

export const ALERT_LABEL: Record<string, { text: string; tone: 'teal' | 'amber' | 'red' | 'blue' | 'green' }> = {
  new_importer: { text: 'New importer', tone: 'teal' },
  new_origin: { text: 'New supplier origin', tone: 'amber' },
  volume_spike: { text: 'Volume up', tone: 'green' },
  volume_drop: { text: 'Volume down', tone: 'red' },
  competitor_new_buyer: { text: 'Competitor win', tone: 'blue' },
}
