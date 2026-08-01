const ADMIN_ROLES = new Set(['super_admin', 'operator_admin'])

// Platform-staff roles with access to one scoped slice of the admin panel instead of all of it
// (finance_team -> Billing/Invoices/Wallet Top-up Report/Usage, sales_team -> Customers/Rate
// Cards, support_team -> Contact Us Submissions/Users [view-only]/Audit Log) -- mirrors the
// backend's admin.STAFF_AREA_ROLES, which is the actual enforcement point; this only decides
// what nav/routes to show, never grants access on its own.
const STAFF_AREA_BY_ROLE: Record<string, 'finance' | 'sales' | 'support'> = {
  finance_team: 'finance',
  sales_team: 'sales',
  support_team: 'support',
}

export type AuthProfile = {
  id: string
  email: string
  full_name: string
  role: string
  organization_id: string | null
}

export const useAuthStore = defineStore('auth', () => {
  const profile = ref<AuthProfile | null>(null)
  const loaded = ref(false)
  const capabilities = ref<Set<string>>(new Set())

  const isAdmin = computed(() => !!profile.value && ADMIN_ROLES.has(profile.value.role))
  const staffArea = computed(() => profile.value ? STAFF_AREA_BY_ROLE[profile.value.role] ?? null : null)

  function can(capability: string): boolean {
    return capabilities.value.has('*') || capabilities.value.has(capability)
  }

  async function load(force = false) {
    if (loaded.value && !force)
      return
    try {
      profile.value = await $api<AuthProfile>('/v1/auth/me')
      const perms = await $api<{ capabilities: string[] }>('/v1/auth/permissions')
      capabilities.value = new Set(perms.capabilities)
    }
    catch {
      profile.value = null
      capabilities.value = new Set()
    }
    finally {
      loaded.value = true
    }
  }

  function clear() {
    profile.value = null
    capabilities.value = new Set()
    loaded.value = false
  }

  return { profile, loaded, isAdmin, staffArea, capabilities, can, load, clear }
})
