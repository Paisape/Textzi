import { ofetch } from 'ofetch'
import { router } from '@/plugins/1.router'
import { useAuthStore } from '@/stores/auth'

// Owned by the router guard instead (plugins/1.router/index.ts) -- it already awaits these on
// every navigation and redirects if the session turns out to be dead, so handling them here too
// would race that guard's own in-flight `router.push`.
const SESSION_CHECK_ENDPOINTS = ['/v1/auth/me', '/v1/auth/permissions']

let handlingSessionExpiry = false

export const $api = ofetch.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  async onRequest({ options }) {
    const accessToken = useCookie('accessToken').value
    if (accessToken)
      options.headers.append('Authorization', `Bearer ${accessToken}`)
  },
  async onResponseError({ request, response, options }) {
    // A 401 on a request that carried our own session token means the token itself is dead
    // (expired from inactivity, revoked, or signed out elsewhere) -- require_user (auth.py) is
    // the only thing that ever returns 401 in that situation. Login/2FA/OTP-verification
    // requests never attach this header (there's no session yet), so a wrong password or a bad
    // authenticator code can never be mistaken for a session expiry here -- those keep showing
    // their own page-level error exactly as before. Previously nothing did this: whichever page
    // was open when the token died just showed its own generic error banner for the raw 401,
    // instead of the user actually being logged out.
    const hadSessionToken = (options.headers as Headers | undefined)?.has?.('Authorization')
    const url = typeof request === 'string' ? request : request.url
    const isSessionCheckEndpoint = SESSION_CHECK_ENDPOINTS.some(path => url.includes(path))
    if (response?.status === 401 && hadSessionToken && !isSessionCheckEndpoint && !handlingSessionExpiry) {
      handlingSessionExpiry = true
      useCookie('accessToken').value = null
      useAuthStore().clear()
      if (router.currentRoute.value.name !== 'login')
        router.push({ path: '/login', query: { sessionExpired: '1', redirect: router.currentRoute.value.fullPath } })
      // Reset once this navigation has had time to land, so a later, genuinely new session
      // expiring after a fresh login can trigger this again.
      setTimeout(() => { handlingSessionExpiry = false }, 1000)
    }
  },
})
