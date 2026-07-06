export type UserRole = 'super_admin' | 'admin' | 'analyst' | 'viewer'

export type UserStatus = 'active' | 'disabled' | 'pending'

export type AuthStatus = 'disabled' | 'loading' | 'authenticated' | 'unauthenticated' | 'error'

export interface AuthUser {
  public_id: string
  email: string
  display_name: string
  role: UserRole
  status: UserStatus
}

export interface LoginRequest {
  email: string
  password: string
}

export interface LoginResponse {
  user: AuthUser
}

export interface LogoutResponse {
  success: boolean
}

export interface ChangePasswordRequest {
  current_password: string
  new_password: string
  confirm_password: string
}

export interface ChangePasswordResponse {
  success: boolean
  reauthentication_required: boolean
}

export interface LogoutAllResponse {
  success: boolean
  revoked_count: number
}

export interface AuthApiErrorPayload {
  status: number
  errorCode: string
  message: string
  retryAfterSeconds?: number
  isNetworkError?: boolean
}
