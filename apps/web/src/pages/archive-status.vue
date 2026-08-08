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

type RunRow = {
  id: string
  job: string
  status: string
  records_processed: number
  error: string | null
  started_at: string
  finished_at: string
}

type ManifestRow = {
  id: string
  tier: string
  period: string
  record_count: number
  size_bytes: number
  created_at: string
}

const STATUS_COLORS: Record<string, string> = {
  success: 'success',
  failed: 'error',
  partial: 'warning',
}

const runs = ref<RunRow[]>([])
const manifest = ref<ManifestRow[]>([])
const loadError = ref('')
const loading = ref(false)
const running = ref(false)
const runError = ref('')
const runSuccess = ref('')

function formatBytes(bytes: number): string {
  if (bytes < 1024)
    return `${bytes} B`
  if (bytes < 1024 * 1024)
    return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

async function load() {
  loadError.value = ''
  loading.value = true
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const [runsResult, manifestResult] = await Promise.all([
      $api<RunRow[]>('/v1/admin/archive/runs'),
      $api<ManifestRow[]>('/v1/admin/archive/manifest'),
    ])
    runs.value = runsResult
    manifest.value = manifestResult
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load archive status.')
  }
  finally {
    loading.value = false
  }
}

async function onRunNow() {
  runError.value = ''
  runSuccess.value = ''
  running.value = true
  try {
    const result = await $api<{ local: any, r2: any }>('/v1/admin/archive/run-now', { method: 'POST' })
    runSuccess.value = `Local: ${JSON.stringify(result.local)} — R2: ${JSON.stringify(result.r2)}`
    await load()
  }
  catch (error: any) {
    runError.value = extractErrorMessage(error, 'Could not run the archive job.')
  }
  finally {
    running.value = false
  }
}

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Archive Status
  </h1>
  <p class="text-medium-emphasis mb-6">
    The daily job that moves message telemetry from Postgres to local gzip (8-30 days old), then
    to R2 as Parquet (31+ days old) — see
    <RouterLink to="/platform-r2-settings">
      R2 Setting
    </RouterLink>
    for the storage credentials. Runs automatically once a day; use Run Now to trigger it on
    demand.
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
    <VAlert v-if="runError" type="error" variant="tonal" density="compact" class="mb-4" closable @click:close="runError = ''">
      {{ runError }}
    </VAlert>
    <VAlert v-if="runSuccess" type="success" variant="tonal" density="compact" class="mb-4" closable @click:close="runSuccess = ''">
      {{ runSuccess }}
    </VAlert>

    <VBtn
      class="mb-6"
      :loading="running"
      @click="onRunNow"
    >
      Run Now
    </VBtn>

    <h2 class="text-h6 mb-2">
      Recent runs
    </h2>
    <VCard class="mb-6">
      <VTable>
        <thead>
          <tr>
            <th>Started</th>
            <th>Job</th>
            <th>Status</th>
            <th>Records</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in runs"
            :key="row.id"
          >
            <td>{{ new Date(row.started_at).toLocaleString('en-IN') }}</td>
            <td class="text-uppercase">
              {{ row.job }}
            </td>
            <td>
              <VChip
                size="small"
                :color="STATUS_COLORS[row.status] || 'default'"
                class="text-capitalize"
              >
                {{ row.status }}
              </VChip>
            </td>
            <td>{{ row.records_processed }}</td>
            <td class="text-truncate" style="max-inline-size: 320px;">
              {{ row.error ?? '—' }}
            </td>
          </tr>
          <tr v-if="!loading && !runs.length">
            <td
              colspan="5"
              class="text-center text-medium-emphasis"
            >
              No archive runs recorded yet.
            </td>
          </tr>
        </tbody>
      </VTable>
    </VCard>

    <h2 class="text-h6 mb-2">
      Manifest
    </h2>
    <VCard>
      <VTable>
        <thead>
          <tr>
            <th>Period</th>
            <th>Tier</th>
            <th>Records</th>
            <th>Size</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in manifest"
            :key="row.id"
          >
            <td>{{ row.period }}</td>
            <td class="text-uppercase">
              {{ row.tier }}
            </td>
            <td>{{ row.record_count.toLocaleString('en-IN') }}</td>
            <td>{{ formatBytes(row.size_bytes) }}</td>
            <td>{{ new Date(row.created_at).toLocaleString('en-IN') }}</td>
          </tr>
          <tr v-if="!loading && !manifest.length">
            <td
              colspan="5"
              class="text-center text-medium-emphasis"
            >
              Nothing archived yet.
            </td>
          </tr>
        </tbody>
      </VTable>
    </VCard>
  </template>
</template>
