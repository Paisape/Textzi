<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type ApiLogRow = {
  id: string
  endpoint: string
  method: string | null
  status_code: number
  latency_ms: number
  error: string | null
  created_at: string
}

const rows = ref<ApiLogRow[]>([])
const loadError = ref('')

function statusColor(status: number): string {
  if (status < 300)
    return 'success'
  if (status === 401 || status === 403)
    return 'error'
  if (status === 409)
    return 'warning'
  return 'error'
}

async function load() {
  loadError.value = ''
  try {
    rows.value = await $api<ApiLogRow[]>('/v1/reports/api-log')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load the API log.')
  }
}

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    API Log
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every call your integration made to the Send SMS API, success and failures both — most recent first.
  </p>

  <VAlert
    v-if="loadError"
    type="error"
    variant="tonal"
    class="mb-4"
  >
    {{ loadError }}
  </VAlert>

  <VCard>
    <VTable>
      <thead>
        <tr>
          <th>Endpoint</th>
          <th>Method</th>
          <th>Status</th>
          <th>Latency</th>
          <th>Error</th>
          <th>Date</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="row.id"
        >
          <td>{{ row.endpoint }}</td>
          <td>{{ row.method ?? '—' }}</td>
          <td>
            <VChip
              size="small"
              :color="statusColor(row.status_code)"
            >
              {{ row.status_code }}
            </VChip>
          </td>
          <td>{{ row.latency_ms }} ms</td>
          <td>{{ row.error ?? '—' }}</td>
          <td>{{ new Date(row.created_at).toLocaleString('en-IN') }}</td>
        </tr>
        <tr v-if="!rows.length">
          <td
            colspan="6"
            class="text-center text-medium-emphasis"
          >
            No API calls yet.
          </td>
        </tr>
      </tbody>
    </VTable>
  </VCard>
</template>
