import type { Label } from './types'

export const LABEL_META: Record<Label, { text: string; tone: 'green' | 'amber' | 'blue' | 'slate' | 'red'; help: string }> = {
  verified: { text: 'Verified', tone: 'green', help: 'Directly stated by the cited data source.' },
  estimate: { text: 'Estimate', tone: 'amber', help: 'A labelled estimate or client-provided figure.' },
  inference: { text: 'Inference', tone: 'blue', help: 'Analyst reasoning based on the cited evidence; no new numbers.' },
  unavailable: { text: 'Unavailable', tone: 'slate', help: 'The data needed is not available from connected sources.' },
  unverified: { text: 'Unverified', tone: 'red', help: 'Failed automatic checks (a number did not match its evidence). Excluded from exports.' },
}
