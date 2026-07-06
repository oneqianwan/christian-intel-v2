import { createContext } from 'react'
import type {
  AuthStatus,
  AuthUser,
  ChangePasswordRequest,
  ChangePasswordResponse,
  LoginRequest,
  LogoutAllResponse,
} from '../types/auth'

export interface AuthContextValue {
  user: AuthUser | null
  status: AuthStatus
  error: Error | null
  login: (request: LoginRequest) => Promise<AuthUser>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
  changePassword: (request: ChangePasswordRequest) => Promise<ChangePasswordResponse>
  logoutAll: () => Promise<LogoutAllResponse>
  clearError: () => void
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)
