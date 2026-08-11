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
const stepUp = useStepUpAuth()

type LogRow = {
  id: string
  direction: 'verify' | 'event'
  status: 'ok' | 'rejected' | 'error'
  detail: string
  phone_number_id: string | null
  entity_id: string | null
  entity_name: string | null
  organization_name: string | null
  ip_address: string | null
  created_at: string
}

const STATUS_COLORS: Record<string, string> = { ok: 'success', rejected: 'error', error: 'warning' }

const rows = ref<LogRow[]>([])
const loadError = ref('')
const statusFilter = ref<string | null>(null)
const directionFilter = ref<string | null>(null)
const offset = ref(0)
const hasMore = ref(false)
const PAGE_SIZE = 50

async function load(reset = true) {
  loadError.value = ''
  if (reset)
    offset.value = 0
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const query: Record<string, any> = { limit: PAGE_SIZE, offset: offset.value }
    if (statusFilter.value)
      query.status = statusFilter.value
    if (directionFilter.value)
      query.direction = directionFilter.value
    const page = await stepUp.withStepUp(() => $api<LogRow[]>('/v1/admin/waba-webhook-log', { query }))
    rows.value = reset ? page : [...rows.value, ...page]
    hasMore.value = page.length === PAGE_SIZE
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load the WhatsApp webhook log.')
  }
}

async function onLoadMore() {
  offset.value += PAGE_SIZE
  await load(false)
}

watch([statusFilter, directionFilter], () => load())

onMounted(() => load())
</script>

<template>
  <h1 class="text-h4 mb-1">
    WhatsApp Webhook Log
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every call Meta has made to Textzi's WhatsApp webhook -- the one-time verify handshake and
    every event delivery, including rejections that never showed up anywhere else. Use this to
    confirm Meta is actually reaching the platform during Embedded Signup / App Review setup.
  </p>

  <VAlert v-if="isAdmin === false" type="warning" variant="tonal">
    This page is restricted to Super Admin and Operator Admin roles.
  </VAlert>

  <template v-else-if="isAdmin">
    <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
      {{ loadError }}
    </VAlert>

    <VRow class="mb-4">
      <VCol cols="12" sm="4">
        <AppSelect
          v-model="directionFilter"
          :items="[
            { title: 'All calls', value: null },
            { title: 'Verify handshake (GET)', value: 'verify' },
            { title: 'Event delivery (POST)', value: 'event' },
          ]"
          placeholder="Direction"
        />
      </VCol>
      <VCol cols="12" sm="4">
        <AppSelect
          v-model="statusFilter"
          :items="[
            { title: 'All statuses', value: null },
            { title: 'OK', value: 'ok' },
            { title: 'Rejected', value: 'rejected' },
            { title: 'Error', value: 'error' },
          ]"
          placeholder="Status"
        />
      </VCol>
    </VRow>

    <VCard>
      <VTable>
        <thead>
          <tr>
            <th>Customer</th>
            <th>Direction</th>
            <th>Status</th>
            <th>Detail</th>
            <th>Phone number ID</th>
            <th>IP Address</th>
            <th>Date</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td>
              <div class="font-weight-medium">
                {{ row.organization_name ?? '—' }}
              </div>
              <div class="text-body-2 text-medium-emphasis">
                {{ row.entity_name ?? '—' }}
              </div>
            </td>
            <td class="text-capitalize">
              {{ row.direction }}
            </td>
            <td>
              <VChip size="small" :color="STATUS_COLORS[row.status]" class="text-capitalize">
                {{ row.status }}
              </VChip>
            </td>
            <td class="text-body-2" style="max-inline-size: 380px;">
              {{ row.detail }}
            </td>
            <td>{{ row.phone_number_id ?? '—' }}</td>
            <td>{{ row.ip_address ?? '—' }}</td>
            <td>{{ new Date(row.created_at).toLocaleString('en-IN') }}</td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="7" class="text-center text-medium-emphasis">
              No webhook calls logged yet -- nothing from Meta has reached this platform.
            </td>
          </tr>
        </tbody>
      </VTable>
      <div v-if="hasMore" class="text-center pa-4">
        <VBtn size="small" variant="text" @click="onLoadMore">
          Load more
        </VBtn>
      </div>
    </VCard>
  </template>

  <StepUpDialog
    v-model="stepUp.dialogOpen.value"
    :code="stepUp.code.value"
    :error="stepUp.error.value"
    :submitting="stepUp.submitting.value"
    @update:code="v => stepUp.code.value = v"
    @submit="stepUp.submit"
    @cancel="stepUp.cancel"
  />
</template>
