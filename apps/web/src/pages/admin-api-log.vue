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
const activeTab = ref('developer')

const STATUS_COLORS: Record<number, string> = {
  200: 'success', 201: 'success', 202: 'success',
  401: 'error', 403: 'error', 404: 'error', 409: 'warning', 422: 'warning', 429: 'warning', 500: 'error',
}

function statusColor(code: number): string {
  return STATUS_COLORS[code] || (code < 300 ? 'success' : code < 500 ? 'warning' : 'error')
}

function formatJson(value: Record<string, any> | null): string {
  return value ? JSON.stringify(value, null, 2) : '(none)'
}

const MSG_STATUS_COLORS: Record<string, string> = {
  submitted: 'info', delivered: 'success', delivery_failed: 'error', failed: 'error', accepted: 'info',
}

// ---- Developer API tab (ApiLog -- calls to /v1/sms/send and /v1/sms/send-bulk) ----
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

const rows = ref<ApiLogRow[]>([])
const loadError = ref('')
const entityIdFilter = ref('')
const statusFilter = ref<number | null>(null)
const offset = ref(0)
const hasMore = ref(false)
const PAGE_SIZE = 50
let searchTimer: ReturnType<typeof setTimeout> | undefined

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

watch([entityIdFilter, statusFilter], () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => load(), 300)
})

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
  customer_webhook_url: string | null
  customer_webhook_payload: Record<string, any> | null
  customer_webhook_status: string | null
  customer_webhook_error: string | null
  customer_webhook_sent_at: string | null
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

// ---- Platform Sends tab (PlatformMessage -- login/verification OTPs, admin Send Test SMS) ----
type PlatformMessageRow = {
  id: string
  purpose: string
  recipient: string
  rendered_body: string
  status: string
  route: string | null
  delivery_status_code: number | null
  delivery_status_description: string | null
  delivery_status_text: string | null
  created_at: string
}

const platformRows = ref<PlatformMessageRow[]>([])
const platformLoadError = ref('')
const platformOffset = ref(0)
const platformHasMore = ref(false)
const platformLoaded = ref(false)

async function loadPlatform(reset = true) {
  platformLoadError.value = ''
  if (reset)
    platformOffset.value = 0
  try {
    const page = await stepUp.withStepUp(() => $api<PlatformMessageRow[]>('/v1/admin/platform-messages', { query: { limit: PAGE_SIZE, offset: platformOffset.value } }))
    platformRows.value = reset ? page : [...platformRows.value, ...page]
    platformHasMore.value = page.length === PAGE_SIZE
    platformLoaded.value = true
  }
  catch (error: any) {
    platformLoadError.value = extractErrorMessage(error, 'Could not load platform sends.')
  }
}

async function onLoadMorePlatform() {
  platformOffset.value += PAGE_SIZE
  await loadPlatform(false)
}

watch(activeTab, tab => {
  if (tab === 'platform' && !platformLoaded.value)
    loadPlatform()
})

type PlatformMessageTelemetry = {
  message_id: string
  purpose: string
  recipient: string
  rendered_body: string
  status: string
  route: string | null
  request_payload: Record<string, any> | null
  response_body: string | null
  delivery_status_code: number | null
  delivery_status_description: string | null
  delivery_status_text: string | null
  delivered_at: string | null
  webhook_payload: Record<string, any> | null
  created_at: string
}

const platformTelemetryDialog = ref(false)
const platformTelemetryLoading = ref(false)
const platformTelemetryError = ref('')
const platformTelemetry = ref<PlatformMessageTelemetry | null>(null)

async function onViewPlatformTelemetry(row: PlatformMessageRow) {
  platformTelemetryDialog.value = true
  platformTelemetryLoading.value = true
  platformTelemetryError.value = ''
  platformTelemetry.value = null
  try {
    platformTelemetry.value = await stepUp.withStepUp(() => $api<PlatformMessageTelemetry>(`/v1/admin/platform-messages/${row.id}/telemetry`))
  }
  catch (error: any) {
    platformTelemetryError.value = extractErrorMessage(error, 'Could not load telemetry for this send.')
  }
  finally {
    platformTelemetryLoading.value = false
  }
}

onMounted(() => load())
</script>

<template>
  <h1 class="text-h4 mb-1">
    API Log & Report
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every message send Textzi makes -- both the developer-facing REST API customers call, and the platform's own sends (login/verification OTPs, admin test sends) -- with the full request/response/webhook trail for each.
  </p>

  <VAlert
    v-if="isAdmin === false"
    type="warning"
    variant="tonal"
  >
    This page is restricted to Super Admin and Operator Admin roles.
  </VAlert>

  <template v-else-if="isAdmin">
    <VTabs
      v-model="activeTab"
      class="mb-6"
    >
      <VTab value="developer">
        Developer API
      </VTab>
      <VTab value="platform">
        Platform Sends
      </VTab>
    </VTabs>

    <VWindow v-model="activeTab">
      <VWindowItem value="developer">
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
      </VWindowItem>

      <VWindowItem value="platform">
        <VAlert
          v-if="platformLoadError"
          type="error"
          variant="tonal"
          class="mb-4"
        >
          {{ platformLoadError }}
        </VAlert>

        <p class="text-body-2 text-medium-emphasis mb-4">
          The platform's own sends -- login/verification OTPs and admin-triggered test sends. Never routed through the developer API, so it has no IP/User-Agent to show (there's no external caller) -- but the same full route + delivery-report webhook trail is available below.
        </p>

        <VCard>
          <VTable>
            <thead>
              <tr>
                <th>Purpose</th>
                <th>Recipient</th>
                <th>Status</th>
                <th>Route</th>
                <th>TTBS DR</th>
                <th>Date</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in platformRows"
                :key="row.id"
              >
                <td class="text-capitalize">
                  {{ row.purpose.replaceAll('_', ' ') }}
                </td>
                <td>{{ row.recipient }}</td>
                <td>
                  <VChip
                    size="small"
                    :color="MSG_STATUS_COLORS[row.status] || 'default'"
                    class="text-capitalize"
                  >
                    {{ row.status.replaceAll('_', ' ') }}
                  </VChip>
                </td>
                <td>{{ row.route ?? '—' }}</td>
                <td>
                  <span v-if="row.delivery_status_text">
                    {{ row.delivery_status_text }}
                    <span v-if="row.delivery_status_code !== null">({{ row.delivery_status_code }}<span v-if="row.delivery_status_description"> — {{ row.delivery_status_description }}</span>)</span>
                  </span>
                  <span
                    v-else
                    class="text-medium-emphasis"
                  >—</span>
                </td>
                <td>{{ new Date(row.created_at).toLocaleString('en-IN') }}</td>
                <td>
                  <VBtn
                    size="small"
                    variant="text"
                    @click="onViewPlatformTelemetry(row)"
                  >
                    View
                  </VBtn>
                </td>
              </tr>
              <tr v-if="!platformRows.length">
                <td
                  colspan="7"
                  class="text-center text-medium-emphasis"
                >
                  No platform sends yet.
                </td>
              </tr>
            </tbody>
          </VTable>
          <div
            v-if="platformHasMore"
            class="text-center pa-4"
          >
            <VBtn
              size="small"
              variant="text"
              @click="onLoadMorePlatform"
            >
              Load more
            </VBtn>
          </div>
        </VCard>
      </VWindowItem>
    </VWindow>
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
              5. Delivery report webhook (received from TTBS)
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

            <div class="text-caption text-medium-emphasis mt-3 mb-1 d-flex align-center gap-2">
              6. Relayed to customer's webhook (sent by Textzi)
              <VChip
                v-if="attempt.customer_webhook_status"
                size="x-small"
                :color="attempt.customer_webhook_status === 'success' ? 'success' : attempt.customer_webhook_status === 'failed' ? 'error' : 'default'"
                class="text-capitalize"
              >
                {{ attempt.customer_webhook_status.replaceAll('_', ' ') }}
              </VChip>
            </div>
            <p
              v-if="attempt.customer_webhook_status === 'not_configured'"
              class="text-body-2 text-medium-emphasis"
            >
              This customer hasn't configured a DR webhook URL — nothing was sent.
            </p>
            <template v-else-if="attempt.customer_webhook_url">
              <p class="text-caption text-medium-emphasis mb-1">
                Sent to {{ attempt.customer_webhook_url }}<span v-if="attempt.customer_webhook_sent_at"> · {{ new Date(attempt.customer_webhook_sent_at).toLocaleString('en-IN') }}</span>
              </p>
              <p
                v-if="attempt.customer_webhook_error"
                class="text-caption text-error mb-1"
              >
                {{ attempt.customer_webhook_error }}
              </p>
              <pre
                v-if="attempt.customer_webhook_payload"
                class="telemetry-block"
              >{{ formatJson(attempt.customer_webhook_payload) }}</pre>
            </template>
            <p
              v-else
              class="text-body-2 text-medium-emphasis"
            >
              Not sent yet — waiting on a delivery report from TTBS.
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

  <VDialog
    v-model="platformTelemetryDialog"
    max-width="900"
  >
    <VCard>
      <VCardTitle class="d-flex align-center justify-space-between">
        <span>Platform Send Telemetry</span>
        <VBtn
          icon="tabler-x"
          variant="text"
          size="small"
          @click="platformTelemetryDialog = false"
        />
      </VCardTitle>
      <VCardText style="max-block-size: 75vh; overflow-y: auto;">
        <VProgressLinear
          v-if="platformTelemetryLoading"
          indeterminate
          class="mb-4"
        />

        <VAlert
          v-if="platformTelemetryError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ platformTelemetryError }}
        </VAlert>

        <template v-if="platformTelemetry">
          <div class="text-caption text-medium-emphasis mb-1">
            To {{ platformTelemetry.recipient }} · {{ new Date(platformTelemetry.created_at).toLocaleString('en-IN') }} ·
            <VChip
              size="x-small"
              :color="MSG_STATUS_COLORS[platformTelemetry.status] || 'default'"
              class="text-capitalize"
            >
              {{ platformTelemetry.status.replaceAll('_', ' ') }}
            </VChip>
          </div>

          <h6 class="text-subtitle-1 font-weight-bold mt-4 mb-1">
            Our request to the provider
          </h6>
          <pre class="telemetry-block">{{ formatJson(platformTelemetry.request_payload) }}</pre>

          <h6 class="text-subtitle-1 font-weight-bold mt-4 mb-1">
            Provider response
          </h6>
          <pre class="telemetry-block">{{ platformTelemetry.response_body ?? '(none)' }}</pre>

          <h6 class="text-subtitle-1 font-weight-bold mt-4 mb-1">
            Delivery report webhook (received from TTBS)
          </h6>
          <pre
            v-if="platformTelemetry.webhook_payload"
            class="telemetry-block"
          >{{ formatJson(platformTelemetry.webhook_payload) }}</pre>
          <p
            v-else
            class="text-body-2 text-medium-emphasis"
          >
            Not received yet (or route {{ platformTelemetry.route ?? '(simulated)' }} never requests delivery reports).
          </p>
          <p
            v-if="platformTelemetry.delivery_status_code !== null"
            class="text-caption text-medium-emphasis mt-1"
          >
            DeliveryStatusCode: {{ platformTelemetry.delivery_status_code }}<span v-if="platformTelemetry.delivery_status_description"> — {{ platformTelemetry.delivery_status_description }}</span>
            <span v-if="platformTelemetry.delivered_at">· {{ new Date(platformTelemetry.delivered_at).toLocaleString('en-IN') }}</span>
          </p>
          <p
            v-if="platformTelemetry.delivery_status_text"
            class="text-caption text-medium-emphasis"
          >
            TTBS's own DeliveryStatus: <strong>{{ platformTelemetry.delivery_status_text }}</strong>
          </p>

          <p class="text-body-2 text-medium-emphasis mt-4">
            Platform sends are internal (login OTPs, admin test sends) -- there's no customer webhook to relay to.
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
