<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
  },
})

const authStore = useAuthStore()
const canView = computed(() => authStore.loaded ? authStore.can('activity:view') : null)

type ActivityRow = {
  id: string
  event_type: string
  description: string
  actor_email: string
  ip_address: string | null
  created_at: string
}

const EVENT_COLORS: Record<string, string> = {
  login_success: 'success',
  login_failed: 'warning',
  login_locked: 'error',
  role_changed: 'error',
  '2fa_disabled': 'warning',
}

const rows = ref<ActivityRow[]>([])
const loadError = ref('')

async function load() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.can('activity:view'))
      return
    rows.value = await $api<ActivityRow[]>('/v1/reports/activity-log')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load the activity log.')
  }
}

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Activity Log
  </h1>
  <p class="text-medium-emphasis mb-6">
    Logins, lockouts, 2FA changes, and team activity across your organization.
  </p>

  <VAlert
    v-if="canView === false"
    type="warning"
    variant="tonal"
  >
    This report is only visible to the account owner.
  </VAlert>

  <VAlert
    v-else-if="loadError"
    type="error"
    variant="tonal"
    class="mb-4"
  >
    {{ loadError }}
  </VAlert>

  <VCard v-else-if="canView">
    <VTable>
      <thead>
        <tr>
          <th>Event</th>
          <th>Description</th>
          <th>User</th>
          <th>IP address</th>
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
          <td>{{ row.ip_address ?? '—' }}</td>
          <td>{{ new Date(row.created_at).toLocaleString('en-IN') }}</td>
        </tr>
        <tr v-if="!rows.length">
          <td
            colspan="5"
            class="text-center text-medium-emphasis"
          >
            No activity recorded yet.
          </td>
        </tr>
      </tbody>
    </VTable>
  </VCard>
</template>
