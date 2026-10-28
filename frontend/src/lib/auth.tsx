import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, setUnauthorizedHandler, tokenStore } from './api'
import type { Role, User } from './types'

type AuthState = {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
  can: (role: Role) => boolean
}

const RANK: Record<Role, number> = { viewer: 0, analyst: 1, admin: 2 }
const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(() => Boolean(tokenStore.get()))

  const logout = useCallback(() => {
    tokenStore.set(null)
    setUser(null)
    qc.clear()
  }, [qc])

  useEffect(() => {
    setUnauthorizedHandler(logout)
    if (!tokenStore.get()) return
    api<User>('/api/auth/me')
      .then(setUser)
      .catch(() => tokenStore.set(null))
      .finally(() => setLoading(false))
  }, [logout])

  const login = useCallback(async (email: string, password: string) => {
    const res = await api<{ access_token: string; user: User }>('/api/auth/login', {
      method: 'POST',
      body: new URLSearchParams({ username: email, password }),
    })
    tokenStore.set(res.access_token)
    setUser(res.user)
  }, [])

  const refresh = useCallback(async () => {
    setUser(await api<User>('/api/auth/me'))
  }, [])

  const value = useMemo<AuthState>(
    () => ({ user, loading, login, logout, refresh, can: (r) => Boolean(user && RANK[user.role] >= RANK[r]) }),
    [user, loading, login, logout, refresh],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth outside AuthProvider')
  return v
}
