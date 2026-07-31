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

type CallLogRow = {
  id: string
  invoice_id: string | null
  invoice_number: string | null
  method: string
  path: string
  status: string
  status_code: number | null
  error: string | null
  created_at: string
}

const STATUS_COLORS: Record<string, string> = {
  success: 'success',
  error: 'error',
}

const rows = ref<CallLogRow[]>([])
const loadError = ref('')
const statusFilter = ref<string | null>(null)
const loading = ref(false)

const retryingInvoiceId = ref('')
const retryError = ref('')
const retrySuccess = ref('')

async function load() {
  loadError.value = ''
  loading.value = true
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    rows.value = await $api<CallLogRow[]>('/v1/admin/erpnext/call-log', {
      query: statusFilter.value ? { status_filter: statusFilter.value } : {},
    })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load the ERPNext call log.')
  }
  finally {
    loading.value = false
  }
}

async function retry(invoiceId: string) {
  retryError.value = ''
  retrySuccess.value = ''
  retryingInvoiceId.value = invoiceId
  try {
    const result = await $api<{ invoice_id: string, erpnext_sync_status: string, erpnext_invoice_name: string | null, erpnext_sync_error: string | null }>(
      `/v1/admin/invoices/${invoiceId}/retry-erpnext-sync`,
      { method: 'POST' },
    )
    retrySuccess.value = result.erpnext_sync_status === 'synced'
      ? `Synced successfully${result.erpnext_invoice_name ? ` as ${result.erpnext_invoice_name}` : ''}.`
      : `Still failing: ${result.erpnext_sync_error ?? 'unknown error'}`
    await load()
  }
  catch (error: any) {
    retryError.value = extractErrorMessage(error, 'Retry failed.')
  }
  finally {
    retryingInvoiceId.value = ''
  }
}

watch(statusFilter, load)
onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    ERPNext Sync Log
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every request Textzi made to ERPNext when issuing an invoice — Customer/Item lookups, Sales
    Invoice creation, and PDF fetches — success or failure. If an invoice's ERPNext sync failed,
    fix the underlying cause in ERPNext (or in <RouterLink to="/platform-erpnext-settings">ERPNext Integration settings</RouterLink>) then retry it from here.
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
    <VAlert v-if="retryError" type="error" variant="tonal" density="compact" class="mb-4" closable @click:close="retryError = ''">
      {{ retryError }}
    </VAlert>
    <VAlert v-if="retrySuccess" type="success" variant="tonal" density="compact" class="mb-4" closable @click:close="retrySuccess = ''">
      {{ retrySuccess }}
    </VAlert>

    <VBtnToggle
      v-model="statusFilter"
      class="mb-4"
      density="comfortable"
      mandatory
      color="primary"
    >
      <VBtn :value="null">
        All
      </VBtn>
      <VBtn value="success">
        Success
      </VBtn>
      <VBtn value="error">
        Failed
      </VBtn>
    </VBtnToggle>

    <VCard>
      <VTable>
        <thead>
          <tr>
            <th>Time</th>
            <th>Invoice</th>
            <th>Method</th>
            <th>Path</th>
            <th>Status</th>
            <th>Error</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.id"
          >
            <td>{{ new Date(row.created_at).toLocaleString('en-IN') }}</td>
            <td>{{ row.invoice_number ?? '—' }}</td>
            <td>{{ row.method }}</td>
            <td class="text-truncate" style="max-inline-size: 320px;">
              {{ row.path }}
            </td>
            <td>
              <VChip
                size="small"
                :color="STATUS_COLORS[row.status] || 'default'"
              >
                {{ row.status }}{{ row.status_code ? ` (${row.status_code})` : '' }}
              </VChip>
            </td>
            <td class="text-truncate" style="max-inline-size: 320px;">
              {{ row.error ?? '—' }}
            </td>
            <td>
              <VBtn
                v-if="row.status === 'error' && row.invoice_id"
                size="small"
                variant="tonal"
                :loading="retryingInvoiceId === row.invoice_id"
                @click="retry(row.invoice_id)"
              >
                Retry
              </VBtn>
            </td>
          </tr>
          <tr v-if="!loading && !rows.length">
            <td
              colspan="7"
              class="text-center text-medium-emphasis"
            >
              No ERPNext calls recorded yet.
            </td>
          </tr>
        </tbody>
      </VTable>
    </VCard>
  </template>
</template>
