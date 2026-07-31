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

type OrgBreakdown = {
  organization_id: string
  organization_name: string
  entity_count: number
  messages_sent: number
  wallet_balance: number
  last_activity: string | null
}

type UsageSummary = {
  total_organizations: number
  total_entities: number
  total_messages_sent: number
  total_wallet_credits_issued: number
  total_revenue: number
  breakdown: OrgBreakdown[]
}

const summary = ref<UsageSummary | null>(null)
const loadError = ref('')

async function loadSummary() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    summary.value = await $api<UsageSummary>('/v1/admin/usage/summary')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load platform usage.')
  }
}

function onExportCsv() {
  if (!summary.value)
    return
  downloadCsv(
    'usage-by-organization.csv',
    [
      { key: 'organization_name', label: 'Organization' },
      { key: 'entity_count', label: 'Entities' },
      { key: 'messages_sent', label: 'Messages Sent' },
      { key: 'wallet_balance', label: 'Wallet Balance' },
      { key: 'last_activity', label: 'Last Activity' },
    ],
    summary.value.breakdown,
  )
}

onMounted(loadSummary)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Platform Usage
  </h1>
  <p class="text-medium-emphasis mb-6">
    Aggregate activity across every customer on Textzi.
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

  <template v-else-if="isAdmin && summary">
    <VRow class="mb-2">
      <VCol cols="12" sm="6" md="3">
        <VCard>
          <VCardText>
            <div class="text-body-2 text-medium-emphasis mb-1">
              Organizations
            </div>
            <div class="text-h5">
              {{ summary.total_organizations }}
            </div>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" sm="6" md="3">
        <VCard>
          <VCardText>
            <div class="text-body-2 text-medium-emphasis mb-1">
              Entities
            </div>
            <div class="text-h5">
              {{ summary.total_entities }}
            </div>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" sm="6" md="3">
        <VCard>
          <VCardText>
            <div class="text-body-2 text-medium-emphasis mb-1">
              Messages Sent
            </div>
            <div class="text-h5">
              {{ summary.total_messages_sent.toLocaleString('en-IN') }}
            </div>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" sm="6" md="3">
        <VCard>
          <VCardText>
            <div class="text-body-2 text-medium-emphasis mb-1">
              Total Revenue (issued invoices)
            </div>
            <div class="text-h5">
              ₹{{ summary.total_revenue.toLocaleString('en-IN') }}
            </div>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>

    <VCard>
      <VCardText class="d-flex align-center justify-space-between">
        <h6 class="text-h6">
          By Organization
        </h6>
        <VBtn
          variant="tonal"
          prepend-icon="tabler-file-export"
          size="small"
          @click="onExportCsv"
        >
          Export CSV
        </VBtn>
      </VCardText>
      <VTable>
        <thead>
          <tr>
            <th>Organization</th>
            <th>Entities</th>
            <th>Messages Sent</th>
            <th>Wallet Balance</th>
            <th>Last Activity</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="org in summary.breakdown"
            :key="org.organization_id"
          >
            <td>
              <RouterLink :to="`/customers/${org.organization_id}`">
                {{ org.organization_name }}
              </RouterLink>
            </td>
            <td>{{ org.entity_count }}</td>
            <td>{{ org.messages_sent.toLocaleString('en-IN') }}</td>
            <td>{{ org.wallet_balance.toLocaleString('en-IN') }}</td>
            <td>{{ org.last_activity ? new Date(org.last_activity).toLocaleString('en-IN') : '—' }}</td>
          </tr>
        </tbody>
      </VTable>
    </VCard>
  </template>
</template>
