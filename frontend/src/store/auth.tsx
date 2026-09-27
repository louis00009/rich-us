import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, clearToken, getToken, getUser, setToken, setUnauthorizedHandler } from '../lib/api'

interface AuthState {
  token: string
  username: string
  initialized: boolean | null
  ready: boolean
  login: (u: string, p: string) => Promise<void>
  setup: (u: string, p: string) => Promise<void>
  logout: () => void
  refreshStatus: () => Promise<void>
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTok] = useState(getToken())
  const [username, setUsername] = useState(getUser())
  const [initialized, setInitialized] = useState<boolean | null>(null)
  const [ready, setReady] = useState(false)

  const refreshStatus = useCallback(async () => {
    try {
      const r = await api.get<{ initialized: boolean }>('/auth/status')
      setInitialized(r.initialized)
    } catch {
      setInitialized(null)
    } finally {
      setReady(true)
    }
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setTok('')
      setUsername('')
    })
    refreshStatus()
  }, [refreshStatus])

  const login = useCallback(async (u: string, p: string) => {
    const r = await api.post<{ access_token: string; username: string }>('/auth/login', {
      username: u,
      password: p,
    })
    setToken(r.access_token, r.username)
    setTok(r.access_token)
    setUsername(r.username)
  }, [])

  const setup = useCallback(async (u: string, p: string) => {
    const r = await api.post<{ access_token: string; username: string }>('/auth/setup', {
      username: u,
      password: p,
    })
    setToken(r.access_token, r.username)
    setTok(r.access_token)
    setUsername(r.username)
    setInitialized(true)
  }, [])

  const logout = useCallback(() => {
    api.post('/auth/logout').catch(() => {})
    clearToken()
    setTok('')
    setUsername('')
  }, [])

  const value = useMemo<AuthState>(
    () => ({ token, username, initialized, ready, login, setup, logout, refreshStatus }),
    [token, username, initialized, ready, login, setup, logout, refreshStatus],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return v
}
