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

type ApiLogRow = {
  id: string
  entity_id: string | null
  entity_name: string | null
  organization_name: string | null
  message_id: string | null
  endpoint: string
  method: string | null
  status_code: number
  latency_ms: number
  error: string | null
  ip_address: string | null
  country: string | null
  user_agent: string | null
  created_at: string
}

const STATUS_COLORS: Record<number, string> = {
  200: 'success', 201: 'success', 202: 'success',
  401: 'error', 403: 'error', 404: 'error', 409: 'warning', 422: 'warning', 429: 'warning', 500: 'error',
}

function statusColor(code: number): string {
  return STATUS_COLORS[code] || (code < 300 ? 'success' : code < 500 ? 'warning' : 'error')
}

const rows = ref<ApiLogRow[]>([])
const loadError = ref('')
const entityIdFilter = ref('')
const statusFilter = ref<number | null>(null)
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
    if (entityIdFilter.value.trim())
      query.entity_id = entityIdFilter.value.trim()
    if (statusFilter.value)
      query.status_code = statusFilter.value
    const page = await stepUp.withStepUp(() => $api<ApiLogRow[]>('/v1/admin/api-log', { query }))
    rows.value = reset ? page : [...rows.value, ...page]
    hasMore.value = page.length === PAGE_SIZE
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load the API log.')
  }
}

async function onLoadMore() {
  offset.value += PAGE_SIZE
  await load(false)
}

watch([entityIdFilter, statusFilter], () => load())

type DeliveryAttemptTelemetry = {
  id: string
  route: string
  status: string
  provider_message_id: string | null
  error: string | null
  delivery_status_code: number | null
  delivery_status_description: string | null
  delivery_status_text: string | null
  delivered_at: string | null
  request_payload: Record<string, any> | null
  response_body: string | null
  webhook_payload: Record<string, any> | null
  created_at: string
}

type MessageTelemetry = {
  message_id: string
  recipient: string
  rendered_body: string
  status: string
  request_payload: Record<string, any> | null
  response_payload: Record<string, any> | null
  created_at: string
  attempts: DeliveryAttemptTelemetry[]
}

const MSG_STATUS_COLORS: Record<string, string> = {
  submitted: 'info', delivered: 'success', delivery_failed: 'error', failed: 'error', accepted: 'info',
}

function formatJson(value: Record<string, any> | null): string {
  return value ? JSON.stringify(value, null, 2) : '(none)'
}

const telemetryDialog = ref(false)
const telemetryLoading = ref(false)
const telemetryError = ref('')
const telemetry = ref<MessageTelemetry | null>(null)

async function onViewTelemetry(row: ApiLogRow) {
  if (!row.message_id)
    return
  telemetryDialog.value = true
  telemetryLoading.value = true
  telemetryError.value = ''
  telemetry.value = null
  try {
    telemetry.value = await stepUp.withStepUp(() => $api<MessageTelemetry>(`/v1/admin/messages/${row.message_id}/telemetry`))
  }
  catch (error: any) {
    telemetryError.value = extractErrorMessage(error, 'Could not load telemetry for this call.')
  }
  finally {
    telemetryLoading.value = false
  }
}

onMounted(() => load())
</script>

<template>
  <h1 class="text-h4 mb-1">
    API Log & Report
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every raw call to the send-sms API, across every customer -- who called, from where, what happened, and (for single sends) the full route + delivery-report trail that call led to.
  </p>

  <VAlert
    v-if="isAdmin === false"
    type="warning"
    variant="tonal"
  >
    This page is restricted to Super Admin and Operator Admin roles.
  </VAlert>

  <template v-else-if="isAdmin">
    <VAlert
      v-if="loadError"
      type="error"
      variant="tonal"
      class="mb-4"
    >
      {{ loadError }}
    </VAlert>

    <VRow class="mb-4">
      <VCol
        cols="12"
        sm="5"
      >
        <AppTextField
          v-model="entityIdFilter"
          placeholder="Filter by entity ID"
          prepend-inner-icon="tabler-search"
          clearable
        />
      </VCol>
      <VCol
        cols="12"
        sm="3"
      >
        <AppSelect
          v-model="statusFilter"
          :items="[
            { title: 'All statuses', value: null },
            { title: '2xx Success', value: 202 },
            { title: '401 Unauthorized', value: 401 },
            { title: '403 Forbidden', value: 403 },
            { title: '422 Rejected', value: 422 },
            { title: '429 Rate limited', value: 429 },
            { title: '409 Duplicate', value: 409 },
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
            <th>Endpoint</th>
            <th>Method</th>
            <th>Status</th>
            <th>Latency</th>
            <th>IP Address</th>
            <th>Country</th>
            <th>User-Agent</th>
            <th>Date</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.id"
          >
            <td>
              <div class="font-weight-medium">
                {{ row.organization_name ?? '—' }}
              </div>
              <div class="text-body-2 text-medium-emphasis">
                {{ row.entity_name ?? '—' }}
              </div>
            </td>
            <td>{{ row.endpoint }}</td>
            <td>{{ row.method ?? '—' }}</td>
            <td>
              <VChip
                size="small"
                :color="statusColor(row.status_code)"
              >
                {{ row.status_code }}
              </VChip>
              <VTooltip
                v-if="row.error"
                location="top"
              >
                <template #activator="{ props: tooltipProps }">
                  <VIcon
                    v-bind="tooltipProps"
                    icon="tabler-alert-circle"
                    size="16"
                    color="error"
                    class="ms-1"
                  />
                </template>
                {{ row.error }}
              </VTooltip>
            </td>
            <td>{{ row.latency_ms }}ms</td>
            <td>{{ row.ip_address ?? '—' }}</td>
            <td>{{ row.country ?? '—' }}</td>
            <td
              class="text-truncate"
              style="max-inline-size: 220px;"
            >
              {{ row.user_agent ?? '—' }}
            </td>
            <td>{{ new Date(row.created_at).toLocaleString('en-IN') }}</td>
            <td>
              <VBtn
                v-if="row.message_id"
                size="small"
                variant="text"
                @click="onViewTelemetry(row)"
              >
                View
              </VBtn>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td
              colspan="10"
              class="text-center text-medium-emphasis"
            >
              No API calls logged yet.
            </td>
          </tr>
        </tbody>
      </VTable>
      <div
        v-if="hasMore"
        class="text-center pa-4"
      >
        <VBtn
          size="small"
          variant="text"
          @click="onLoadMore"
        >
          Load more
        </VBtn>
      </div>
    </VCard>
  </template>

  <VDialog
    v-model="telemetryDialog"
    max-width="900"
  >
    <VCard>
      <VCardTitle class="d-flex align-center justify-space-between">
        <span>Call Telemetry</span>
        <VBtn
          icon="tabler-x"
          variant="text"
          size="small"
          @click="telemetryDialog = false"
        />
      </VCardTitle>
      <VCardText style="max-block-size: 75vh; overflow-y: auto;">
        <VProgressLinear
          v-if="telemetryLoading"
          indeterminate
          class="mb-4"
        />

        <VAlert
          v-if="telemetryError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ telemetryError }}
        </VAlert>

        <template v-if="telemetry">
          <div class="text-caption text-medium-emphasis mb-1">
            To {{ telemetry.recipient }} · {{ new Date(telemetry.created_at).toLocaleString('en-IN') }} ·
            <VChip
              size="x-small"
              :color="MSG_STATUS_COLORS[telemetry.status] || 'default'"
              class="text-capitalize"
            >
              {{ telemetry.status.replaceAll('_', ' ') }}
            </VChip>
          </div>

          <h6 class="text-subtitle-1 font-weight-bold mt-4 mb-1">
            1. API request from customer
          </h6>
          <pre class="telemetry-block">{{ formatJson(telemetry.request_payload) }}</pre>

          <h6 class="text-subtitle-1 font-weight-bold mt-4 mb-1">
            2. Our response to customer
          </h6>
          <pre class="telemetry-block">{{ formatJson(telemetry.response_payload) }}</pre>

          <template
            v-for="(attempt, i) in telemetry.attempts"
            :key="attempt.id"
          >
            <VDivider class="my-4" />
            <div class="d-flex align-center gap-2 mb-1">
              <h6 class="text-subtitle-1 font-weight-bold">
                Route attempt {{ i + 1 }} — {{ attempt.route }}
              </h6>
              <VChip
                size="x-small"
                :color="MSG_STATUS_COLORS[attempt.status] || 'default'"
                class="text-capitalize"
              >
                {{ attempt.status.replaceAll('_', ' ') }}
              </VChip>
            </div>
            <p
              v-if="attempt.error"
              class="text-caption text-error mb-2"
            >
              {{ attempt.error }}
            </p>

            <div class="text-caption text-medium-emphasis mb-1">
              3. Our request to the provider
            </div>
            <pre class="telemetry-block">{{ formatJson(attempt.request_payload) }}</pre>

            <div class="text-caption text-medium-emphasis mt-3 mb-1">
              4. Provider response
            </div>
            <pre class="telemetry-block">{{ attempt.response_body ?? '(none)' }}</pre>

            <div class="text-caption text-medium-emphasis mt-3 mb-1">
              5. Delivery report webhook
            </div>
            <pre
              v-if="attempt.webhook_payload"
              class="telemetry-block"
            >{{ formatJson(attempt.webhook_payload) }}</pre>
            <p
              v-else
              class="text-body-2 text-medium-emphasis"
            >
              Not received yet{{ attempt.delivery_status_code !== null ? '' : ' (or this route never requests delivery reports)' }}.
            </p>
            <p
              v-if="attempt.delivery_status_code !== null"
              class="text-caption text-medium-emphasis mt-1"
            >
              DeliveryStatusCode: {{ attempt.delivery_status_code }}<span v-if="attempt.delivery_status_description"> — {{ attempt.delivery_status_description }}</span>
              <span v-if="attempt.delivered_at">· {{ new Date(attempt.delivered_at).toLocaleString('en-IN') }}</span>
            </p>
            <p
              v-if="attempt.delivery_status_text"
              class="text-caption text-medium-emphasis"
            >
              TTBS's own DeliveryStatus: <strong>{{ attempt.delivery_status_text }}</strong>
            </p>
          </template>

          <p
            v-if="!telemetry.attempts.length"
            class="text-body-2 text-medium-emphasis mt-4"
          >
            Not dispatched to a provider yet.
          </p>
        </template>
      </VCardText>
    </VCard>
  </VDialog>

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

<style scoped lang="scss">
.telemetry-block {
  background: rgba(var(--v-theme-on-surface), 0.04);
  border-radius: 6px;
  padding: 12px;
  font-size: 0.8rem;
  white-space: pre-wrap;
  word-break: break-word;
  max-block-size: 260px;
  overflow-y: auto;
}
</style>
