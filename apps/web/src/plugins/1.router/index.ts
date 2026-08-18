import { setupLayouts } from 'virtual:meta-layouts'
import type { App } from 'vue'

import type { RouteRecordRaw } from 'vue-router/auto'

import { createRouter, createWebHistory } from 'vue-router/auto'
import { useAuthStore } from '@/stores/auth'
import { $api } from '@/utils/api'

const VISITOR_SESSION_STORAGE_KEY = 'textzi_visitor_session_id'

// Where a channel_scope-restricted teammate lands -- sms has no separate workspace shell (it's
// already a single page) so its own path is its home; waba/crm redirect through the thin landing
// pages at src/pages/waba.vue and src/pages/crm.vue. Plain paths (not { name: ... } objects),
// matching every other redirect in this guard -- the generated typed-router guard signature
// only accepts route names it can resolve to one exact params/query shape, which a bare
// `{ name }` object without a matching `params` structurally fails to satisfy.
const CHANNEL_HOME_PATH = { sms: '/sms', waba: '/waba', crm: '/crm' } as const

// Passive visitor analytics only -- path, referrer, viewport, coarse device/location (see
// Privacy Policy Section 1/7). session_id lives in localStorage (first-party to this frontend's
// own origin), not a cookie, since the API sits on a different subdomain (api.textzi.in) and
// this app's CORS policy runs with allow_credentials=False, which a cross-origin cookie
// wouldn't reliably round-trip through anyway. Never blocks/delays navigation -- fire-and-forget,
// swallow any failure.
function trackPageView(path: string, internalReferrer?: string) {
  const sessionId = localStorage.getItem(VISITOR_SESSION_STORAGE_KEY) || undefined
  $api<{ session_id: string }>('/v1/public/track', {
    method: 'POST',
    body: {
      session_id: sessionId,
      path,
      referrer: internalReferrer || document.referrer || undefined,
      viewport_width: window.innerWidth,
      viewport_height: window.innerHeight,
    },
  })
    .then(result => localStorage.setItem(VISITOR_SESSION_STORAGE_KEY, result.session_id))
    .catch(() => {})
}

function recursiveLayouts(route: RouteRecordRaw): RouteRecordRaw {
  if (route.children) {
    for (let i = 0; i < route.children.length; i++)
      route.children[i] = recursiveLayouts(route.children[i])

    return route
  }

  return setupLayouts([route])[0]
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  scrollBehavior(to) {
    if (to.hash)
      return { el: to.hash, behavior: 'smooth', top: 60 }

    return { top: 0 }
  },
  extendRoutes: pages => [
    ...[...pages].map(route => recursiveLayouts(route)),
  ],
})

router.beforeEach(async to => {
  const isLoggedIn = !!useCookie('accessToken').value

  if (to.meta.unauthenticatedOnly && isLoggedIn)
    return '/dashboard'

  if (!to.meta.public && !isLoggedIn)
    return { path: '/login', query: { redirect: to.fullPath } }

  // Every logged-in user must finish organisation onboarding before reaching any other page --
  // not just a soft banner on individual pages. Scoped to enterprise_customer specifically (not
  // "any role with no organization_id") because platform-staff roles never have an organization
  // at all by design -- checking organization_id alone would wrongly send an admin-invited staff
  // member (who has no org and never will) into the customer onboarding wizard.
  if (isLoggedIn && !to.meta.public && to.name !== 'onboarding' && to.name !== 'complete-profile') {
    const authStore = useAuthStore()
    await authStore.load()
    if (!authStore.profile) {
      // The stored token was rejected (expired, revoked, or the session was signed out
      // elsewhere) -- authStore.load() swallows the actual error itself (see stores/auth.ts),
      // so this is the only place a dead session gets detected on a plain navigation, as
      // opposed to an API call from an already-rendered page (handled in utils/api.ts).
      // Previously nothing caught this: the page below would just render against a null
      // profile, and whatever it happened to show (often a raw "not authenticated" banner)
      // was the only signal the user ever got.
      useCookie('accessToken').value = null
      return { path: '/login', query: { sessionExpired: '1', redirect: to.fullPath } }
    }
    if (authStore.profile?.role === 'enterprise_customer' && !authStore.profile.organization_id)
      return '/onboarding'

    // Mandatory post-onboarding gate: every organization starts with profile_completed_at NULL
    // (including ones that onboarded long before this field existed), so this applies retroactively
    // to existing customers too, not just brand new ones -- they'll hit this once on their next
    // navigation until they submit the form.
    if (authStore.profile?.organization_id && authStore.profile.profile_completed === false)
      return '/complete-profile'

    // Structural backstop for admin-only pages -- every admin page already checks
    // authStore.isAdmin itself before rendering/fetching, but that's per-page discipline with
    // no enforcement if a future page forgets it. This makes the router the source of truth:
    // any route tagged requiresAdmin is unreachable by a non-admin regardless.
    if (to.meta.requiresAdmin && !authStore.isAdmin)
      return '/dashboard'

    // Scoped staff areas (finance_team/sales_team/support_team) -- a route tagged staffArea is
    // reachable by full admins (who can reach everything) or by a staff account whose own area
    // matches, and by nobody else. Same backstop role as requiresAdmin above, just narrower.
    if (to.meta.staffArea && !authStore.isAdmin && authStore.staffArea !== to.meta.staffArea)
      return '/dashboard'

    // A page-scoped teammate's "home" is the first page they're actually allowed into, not the
    // channel's generic landing route (/crm, /waba) -- that landing page itself immediately
    // redirects to a fixed page (crm-leads, inbox) which may not be in their allowed list, so
    // sending them there first would just bounce straight back here again (an infinite loop,
    // caught live while testing this). router.resolve(...).path rather than a bare { name }
    // object -- see CHANNEL_HOME_PATH's own comment on why the typed guard signature rejects that.
    const channelHome = () => (authStore.pageScope?.length ? router.resolve({ name: authStore.pageScope[0] as any }).path : CHANNEL_HOME_PATH[authStore.channelScope!])

    // A tenant teammate whose channel_scope locks them to one channel (set at invite time --
    // see team.py) never reaches the general dashboard, another channel's workspace, or any
    // channel-less page (wallet, team, invoices, ...) -- every navigation outside their one
    // channel bounces straight back into it, including a direct URL hit on /dashboard itself.
    if (authStore.channelScope && to.meta.channel !== authStore.channelScope)
      return channelHome()

    // Finer than channel_scope -- an owner can narrow a teammate to just a few pages within
    // their one channel (team.vue, set at invite time). Enforced here as a UX/nav boundary; the
    // real security boundary is channel_scope itself, hard-enforced backend-side
    // (permissions.require_channel_scope) since a restricted teammate could otherwise still hit
    // an out-of-scope endpoint directly.
    if (authStore.channelScope && authStore.pageScope && to.name && !authStore.pageScope.includes(to.name as string))
      return channelHome()
  }
})

router.afterEach((to, from) => {
  trackPageView(to.fullPath, from.name ? from.fullPath : undefined)
})

export { router }

export default function (app: App) {
  app.use(router)
}
