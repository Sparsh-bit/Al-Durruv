import type { AskResponse } from './types'

export type Msg = { role: 'user'; text: string } | { role: 'assistant'; answer: AskResponse } | { role: 'error'; text: string }

export function toHistory(msgs: Msg[]): { role: 'user' | 'assistant'; content: string }[] {
  return msgs.flatMap((m): { role: 'user' | 'assistant'; content: string }[] =>
    m.role === 'user'
      ? [{ role: 'user' as const, content: m.text }]
      : m.role === 'assistant'
        ? [{ role: 'assistant' as const, content: m.answer.statements.map((s) => s.text).join(' ') }]
        : [],
  )
}
