export function isAuthUiEnabled() {
  return import.meta.env.VITE_AUTH_V1_ENABLED === 'true'
}

export function isAuthRequired() {
  return import.meta.env.VITE_AUTH_REQUIRED === 'true'
}
