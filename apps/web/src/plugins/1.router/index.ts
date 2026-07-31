import { setupLayouts } from 'virtual:meta-layouts'
import type { App } from 'vue'

import type { RouteRecordRaw } from 'vue-router/auto'

import { createRouter, createWebHistory } from 'vue-router/auto'
import { useAuthStore } from '@/stores/auth'

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
  if (isLoggedIn && !to.meta.public && to.name !== 'onboarding') {
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

    // Structural backstop for admin-only pages -- every admin page already checks
    // authStore.isAdmin itself before rendering/fetching, but that's per-page discipline with
    // no enforcement if a future page forgets it. This makes the router the source of truth:
    // any route tagged requiresAdmin is unreachable by a non-admin regardless.
    if (to.meta.requiresAdmin && !authStore.isAdmin)
      return '/dashboard'
  }
})

export { router }

export default function (app: App) {
  app.use(router)
}
