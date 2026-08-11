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
const activeTab = ref('inbound')

const STATUS_COLORS: Record<string, string> = { ok: 'success', rejected: 'error', error: 'warning' }
const PAGE_SIZE = 50

// --- Inbound tab (WabaWebhookLog -- calls FROM Meta) ---
type WebhookLogRow = {
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

const rows = ref<WebhookLogRow[]>([])
const loadError = ref('')
const statusFilter = ref<string | null>(null)
const directionFilter = ref<string | null>(null)
const offset = ref(0)
const hasMore = ref(false)

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
    const page = await stepUp.withStepUp(() => $api<WebhookLogRow[]>('/v1/admin/waba-webhook-log', { query }))
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

// --- Outbound tab (WabaApiCallLog -- calls TO Meta) ---
type ApiCallLogRow = {
  id: string
  action: 'send_text' | 'send_media' | 'send_template' | 'register'
  status: 'ok' | 'error'
  detail: string
  to_wa_id: string | null
  entity_id: string | null
  entity_name: string | null
  organization_name: string | null
  created_at: string
}

const outRows = ref<ApiCallLogRow[]>([])
const outLoadError = ref('')
const outStatusFilter = ref<string | null>(null)
const outActionFilter = ref<string | null>(null)
const outOffset = ref(0)
const outHasMore = ref(false)
const outLoaded = ref(false)

async function loadOut(reset = true) {
  outLoadError.value = ''
  if (reset)
    outOffset.value = 0
  try {
    const query: Record<string, any> = { limit: PAGE_SIZE, offset: outOffset.value }
    if (outStatusFilter.value)
      query.status = outStatusFilter.value
    if (outActionFilter.value)
      query.action = outActionFilter.value
    const page = await stepUp.withStepUp(() => $api<ApiCallLogRow[]>('/v1/admin/waba-api-call-log', { query }))
    outRows.value = reset ? page : [...outRows.value, ...page]
    outHasMore.value = page.length === PAGE_SIZE
    outLoaded.value = true
  }
  catch (error: any) {
    outLoadError.value = extractErrorMessage(error, 'Could not load the WhatsApp API call log.')
  }
}

async function onLoadMoreOut() {
  outOffset.value += PAGE_SIZE
  await loadOut(false)
}

watch([outStatusFilter, outActionFilter], () => loadOut())
watch(activeTab, tab => {
  if (tab === 'outbound' && !outLoaded.value)
    loadOut()
})

onMounted(() => load())
</script>

<template>
  <h1 class="text-h4 mb-1">
    WhatsApp API Log
  </h1>
  <p class="text-medium-emphasis mb-6">
    Inbound calls from Meta (the webhook) and outbound calls Textzi makes to Meta (sends, phone
    registration) -- including rejections and real Meta error text that never showed up anywhere
    else. Use this to confirm Meta is actually reaching the platform, and why a send failed.
  </p>

  <VAlert v-if="isAdmin === false" type="warning" variant="tonal">
    This page is restricted to Super Admin and Operator Admin roles.
  </VAlert>

  <template v-else-if="isAdmin">
    <VTabs v-model="activeTab" class="mb-6">
      <VTab value="inbound">
        Inbound (from Meta)
      </VTab>
      <VTab value="outbound">
        Outbound (to Meta)
      </VTab>
    </VTabs>

    <VWindow v-model="activeTab">
      <VWindowItem value="inbound">
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
      </VWindowItem>

      <VWindowItem value="outbound">
        <VAlert v-if="outLoadError" type="error" variant="tonal" class="mb-4">
          {{ outLoadError }}
        </VAlert>

        <VRow class="mb-4">
          <VCol cols="12" sm="4">
            <AppSelect
              v-model="outActionFilter"
              :items="[
                { title: 'All actions', value: null },
                { title: 'Send text', value: 'send_text' },
                { title: 'Send media', value: 'send_media' },
                { title: 'Send template', value: 'send_template' },
                { title: 'Register phone', value: 'register' },
              ]"
              placeholder="Action"
            />
          </VCol>
          <VCol cols="12" sm="4">
            <AppSelect
              v-model="outStatusFilter"
              :items="[
                { title: 'All statuses', value: null },
                { title: 'OK', value: 'ok' },
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
                <th>Action</th>
                <th>Status</th>
                <th>Detail</th>
                <th>To</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in outRows" :key="row.id">
                <td>
                  <div class="font-weight-medium">
                    {{ row.organization_name ?? '—' }}
                  </div>
                  <div class="text-body-2 text-medium-emphasis">
                    {{ row.entity_name ?? '—' }}
                  </div>
                </td>
                <td class="text-capitalize">
                  {{ row.action.replaceAll('_', ' ') }}
                </td>
                <td>
                  <VChip size="small" :color="STATUS_COLORS[row.status]" class="text-capitalize">
                    {{ row.status }}
                  </VChip>
                </td>
                <td class="text-body-2" style="max-inline-size: 380px;">
                  {{ row.detail }}
                </td>
                <td>{{ row.to_wa_id ?? '—' }}</td>
                <td>{{ new Date(row.created_at).toLocaleString('en-IN') }}</td>
              </tr>
              <tr v-if="!outRows.length">
                <td colspan="6" class="text-center text-medium-emphasis">
                  No outbound WhatsApp API calls logged yet.
                </td>
              </tr>
            </tbody>
          </VTable>
          <div v-if="outHasMore" class="text-center pa-4">
            <VBtn size="small" variant="text" @click="onLoadMoreOut">
              Load more
            </VBtn>
          </div>
        </VCard>
      </VWindowItem>
    </VWindow>
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
