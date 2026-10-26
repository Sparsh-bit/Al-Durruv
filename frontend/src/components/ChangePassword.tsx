import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { post } from '../lib/api'
import { Button, Field, Input, Modal } from './ui'

export default function ChangePassword({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const change = useMutation({
    mutationFn: () => post('/api/auth/change-password', { current_password: current, new_password: next }),
    onSuccess: () => {
      toast.success('Password changed')
      setCurrent('')
      setNext('')
      setConfirm('')
      onOpenChange(false)
    },
  })
  const mismatch = confirm.length > 0 && confirm !== next
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!mismatch) change.mutate()
  }
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Change password" description="Use at least 8 characters; longer passphrases are stronger.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Current password">
          <Input type="password" required autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </Field>
        <Field label="New password">
          <Input type="password" required minLength={8} maxLength={128} autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        </Field>
        <Field label="Confirm new password" error={mismatch ? 'Passwords do not match.' : undefined}>
          <Input type="password" required autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" loading={change.isPending} disabled={mismatch}>Change password</Button>
        </div>
      </form>
    </Modal>
  )
}
