<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
    requiresAdmin: true,
  },
})

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.loaded ? authStore.isAdmin : null)

type AuditLogRow = {
  id: string
  event_type: string
  description: string
  actor_email: string
  ip_address: string | null
  organization_name: string | null
  created_at: string
}

const EVENT_COLORS: Record<string, string> = {
  login_success: 'success',
  login_failed: 'warning',
  login_locked: 'error',
  role_changed: 'error',
  status_changed: 'error',
  password_reset_by_admin: 'warning',
  rate_card_deleted: 'error',
}

const rows = ref<AuditLogRow[]>([])
const loadError = ref('')
const actorEmail = ref('')
let searchTimer: ReturnType<typeof setTimeout> | undefined

async function load() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    rows.value = await $api<AuditLogRow[]>('/v1/admin/audit-log', { query: actorEmail.value ? { actor_email: actorEmail.value } : {} })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load the audit log.')
  }
}

watch(actorEmail, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(load, 300)
})

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Audit Log
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every login, lockout, role change, and admin-panel mutation across the whole platform — not just one customer's own activity.
  </p>

  <VAlert
    v-if="isAdmin === false"
    type="warning"
    variant="tonal"
  >
    This page is restricted to Super Admin and Operator Admin roles.
  </VAlert>

  <VAlert
    v-else-if="loadError"
    type="error"
    variant="tonal"
  >
    {{ loadError }}
  </VAlert>

  <template v-else-if="isAdmin">
    <AppTextField
      v-model="actorEmail"
      placeholder="Filter by actor email"
      prepend-inner-icon="tabler-search"
      class="mb-4"
      style="max-inline-size: 420px;"
      clearable
    />

    <VCard>
      <VTable>
        <thead>
          <tr>
            <th>Event</th>
            <th>Description</th>
            <th>Actor</th>
            <th>Organization</th>
            <th>IP Address</th>
            <th>Date</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.id"
          >
            <td>
              <VChip
                size="small"
                :color="EVENT_COLORS[row.event_type] || 'default'"
                class="text-capitalize"
              >
                {{ row.event_type.replaceAll('_', ' ') }}
              </VChip>
            </td>
            <td>{{ row.description }}</td>
            <td>{{ row.actor_email }}</td>
            <td>{{ row.organization_name ?? '—' }}</td>
            <td>{{ row.ip_address ?? '—' }}</td>
            <td>{{ new Date(row.created_at).toLocaleString('en-IN') }}</td>
          </tr>
          <tr v-if="!rows.length">
            <td
              colspan="6"
              class="text-center text-medium-emphasis"
            >
              No activity recorded yet.
            </td>
          </tr>
        </tbody>
      </VTable>
    </VCard>
  </template>
</template>
