const ADMIN_ROLES = new Set(['super_admin', 'operator_admin'])

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

  return { profile, loaded, isAdmin, capabilities, can, load, clear }
})
