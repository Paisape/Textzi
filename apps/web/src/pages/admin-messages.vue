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

const activeTab = ref('customer')

type MessageRow = {
  id: string
  organization_name: string | null
  entity_name: string
  recipient: string
  rendered_body: string
  status: string
  route: string | null
  credits_charged: number
  delivery_status_code: number | null
  delivery_status_description: string | null
  delivery_status_text: string | null
  delivery_error: string | null
  created_at: string
}

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

const STATUS_COLORS: Record<string, string> = {
  submitted: 'info',
  delivered: 'success',
  delivery_failed: 'error',
  failed: 'error',
}

const ADMIN_MESSAGE_PAGE_SIZE = 50

const rows = ref<MessageRow[]>([])
const loadError = ref('')
const entityIdFilter = ref('')
const statusFilter = ref<string | null>(null)
const messagesOffset = ref(0)
const hasMoreMessages = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | undefined

async function loadMessages(reset = true) {
  loadError.value = ''
  if (reset)
    messagesOffset.value = 0
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const query: Record<string, string | number> = { limit: ADMIN_MESSAGE_PAGE_SIZE, offset: messagesOffset.value }
    if (entityIdFilter.value.trim())
      query.entity_id = entityIdFilter.value.trim()
    if (statusFilter.value)
      query.status_filter = statusFilter.value
    const page = await stepUp.withStepUp(() => $api<MessageRow[]>('/v1/admin/messages', { query }))
    rows.value = reset ? page : [...rows.value, ...page]
    hasMoreMessages.value = page.length === ADMIN_MESSAGE_PAGE_SIZE
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load the customer message log.')
  }
}

async function onLoadMoreMessages() {
  messagesOffset.value += ADMIN_MESSAGE_PAGE_SIZE
  await loadMessages(false)
}

watch([entityIdFilter, statusFilter], () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => loadMessages(true), 300)
})

const platformRows = ref<PlatformMessageRow[]>([])
const platformLoadError = ref('')
const platformLoaded = ref(false)
const platformOffset = ref(0)
const hasMorePlatformMessages = ref(false)

async function loadPlatformMessages(reset = true) {
  platformLoadError.value = ''
  if (reset)
    platformOffset.value = 0
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const page = await stepUp.withStepUp(() => $api<PlatformMessageRow[]>('/v1/admin/platform-messages', { query: { limit: ADMIN_MESSAGE_PAGE_SIZE, offset: platformOffset.value } }))
    platformRows.value = reset ? page : [...platformRows.value, ...page]
    hasMorePlatformMessages.value = page.length === ADMIN_MESSAGE_PAGE_SIZE
    platformLoaded.value = true
  }
  catch (error: any) {
    platformLoadError.value = extractErrorMessage(error, 'Could not load the platform message log.')
  }
}

async function onLoadMorePlatformMessages() {
  platformOffset.value += ADMIN_MESSAGE_PAGE_SIZE
  await loadPlatformMessages(false)
}

watch(activeTab, tab => {
  if (tab === 'platform' && !platformLoaded.value)
    loadPlatformMessages()
})

const telemetryDialog = ref(false)
const telemetryLoading = ref(false)
const telemetryError = ref('')
const telemetry = ref<MessageTelemetry | null>(null)
const platformTelemetry = ref<PlatformMessageTelemetry | null>(null)

function formatJson(value: Record<string, any> | null): string {
  return value ? JSON.stringify(value, null, 2) : '(none)'
}

async function viewMessageTelemetry(id: string) {
  telemetryDialog.value = true
  telemetryLoading.value = true
  telemetryError.value = ''
  telemetry.value = null
  platformTelemetry.value = null
  try {
    telemetry.value = await stepUp.withStepUp(() => $api<MessageTelemetry>(`/v1/admin/messages/${id}/telemetry`))
  }
  catch (error: any) {
    telemetryError.value = extractErrorMessage(error, 'Could not load message telemetry.')
  }
  finally {
    telemetryLoading.value = false
  }
}

async function viewPlatformMessageTelemetry(id: string) {
  telemetryDialog.value = true
  telemetryLoading.value = true
  telemetryError.value = ''
  telemetry.value = null
  platformTelemetry.value = null
  try {
    platformTelemetry.value = await stepUp.withStepUp(() => $api<PlatformMessageTelemetry>(`/v1/admin/platform-messages/${id}/telemetry`))
  }
  catch (error: any) {
    telemetryError.value = extractErrorMessage(error, 'Could not load message telemetry.')
  }
  finally {
    telemetryLoading.value = false
  }
}

onMounted(loadMessages)
</script>

<template>
  <h1 class="text-h4 mb-1">
    SMS Log & Report
  </h1>
  <p class="text-medium-emphasis mb-6">
    Cross-organization view of every message sent through the platform — customer sends and the
    platform's own (login OTPs) are kept separate below. Recipient and body follow each message's
    own masking, exactly as it would appear in that customer's own Logs tab.
  </p>

  <VAlert
    v-if="isAdmin === false"
    type="warning"
    variant="tonal"
  >
    This page is restricted to Super Admin and Operator Admin roles.
  </VAlert>

  <template v-else-if="isAdmin">
    <VTabs v-model="activeTab" class="mb-6">
      <VTab value="customer">
        Customer Messages
      </VTab>
      <VTab value="platform">
        Platform Messages
      </VTab>
    </VTabs>

    <VWindow v-model="activeTab">
      <VWindowItem value="customer">
        <VAlert
          v-if="loadError"
          type="error"
          variant="tonal"
          class="mb-4"
        >
          {{ loadError }}
        </VAlert>

        <VRow class="mb-4">
          <VCol cols="12" sm="5">
            <AppTextField
              v-model="entityIdFilter"
              placeholder="Filter by entity ID"
              prepend-inner-icon="tabler-search"
              clearable
            />
          </VCol>
          <VCol cols="12" sm="3">
            <AppSelect
              v-model="statusFilter"
              :items="[
                { title: 'All statuses', value: null },
                { title: 'Submitted', value: 'submitted' },
                { title: 'Delivered', value: 'delivered' },
                { title: 'Delivery failed', value: 'delivery_failed' },
                { title: 'Failed', value: 'failed' },
              ]"
              placeholder="Status"
            />
          </VCol>
        </VRow>

        <VCard>
          <VTable>
            <thead>
              <tr>
                <th>Organization</th>
                <th>Entity</th>
                <th>Recipient</th>
                <th>Body</th>
                <th>Status</th>
                <th>Route</th>
                <th>Credits</th>
                <th>DR Code</th>
                <th>Date</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.id">
                <td>{{ row.organization_name ?? '—' }}</td>
                <td>{{ row.entity_name }}</td>
                <td>{{ row.recipient }}</td>
                <td class="text-truncate" style="max-inline-size: 260px;">
                  {{ row.rendered_body }}
                </td>
                <td>
                  <VChip size="small" :color="STATUS_COLORS[row.status] || 'default'" class="text-capitalize">
                    {{ row.status.replaceAll('_', ' ') }}
                  </VChip>
                  <div v-if="row.delivery_status_text" class="text-caption text-medium-emphasis mt-1">
                    TTBS: {{ row.delivery_status_text }}
                  </div>
                </td>
                <td>{{ row.route ?? '—' }}</td>
                <td>{{ row.credits_charged }}</td>
                <td>
                  <span v-if="row.delivery_status_code !== null">
                    {{ row.delivery_status_code }}<span v-if="row.delivery_status_description" class="text-medium-emphasis"> — {{ row.delivery_status_description }}</span>
                  </span>
                  <span v-else class="text-medium-emphasis">—</span>
                  <VTooltip v-if="row.delivery_error" location="top">
                    <template #activator="{ props: tooltipProps }">
                      <VIcon
                        v-bind="tooltipProps"
                        icon="tabler-alert-circle"
                        size="16"
                        color="error"
                        class="ms-1"
                      />
                    </template>
                    {{ row.delivery_error }}
                  </VTooltip>
                </td>
                <td>{{ new Date(row.created_at).toLocaleString('en-IN') }}</td>
                <td>
                  <VBtn size="small" variant="text" @click="viewMessageTelemetry(row.id)">
                    View
                  </VBtn>
                </td>
              </tr>
              <tr v-if="!rows.length">
                <td colspan="10" class="text-center text-medium-emphasis">
                  No messages found.
                </td>
              </tr>
            </tbody>
          </VTable>
          <div v-if="hasMoreMessages" class="text-center pa-4">
            <VBtn size="small" variant="text" @click="onLoadMoreMessages">
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
          The platform's own sends — currently login-verification OTPs. The code itself is
          redacted before it ever reaches this screen.
        </p>

        <VCard>
          <VTable>
            <thead>
              <tr>
                <th>Purpose</th>
                <th>Recipient</th>
                <th>Body</th>
                <th>Status</th>
                <th>Route</th>
                <th>Date</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in platformRows" :key="row.id">
                <td class="text-capitalize">
                  {{ row.purpose.replaceAll('_', ' ') }}
                </td>
                <td>{{ row.recipient }}</td>
                <td>{{ row.rendered_body }}</td>
                <td>
                  <VChip size="small" :color="STATUS_COLORS[row.status] || 'default'" class="text-capitalize">
                    {{ row.status.replaceAll('_', ' ') }}
                  </VChip>
                  <div v-if="row.delivery_status_text" class="text-caption text-medium-emphasis mt-1">
                    TTBS: {{ row.delivery_status_text }}{{ row.delivery_status_code !== null ? ` (${row.delivery_status_code}${row.delivery_status_description ? ' — ' + row.delivery_status_description : ''})` : '' }}
                  </div>
                </td>
                <td>{{ row.route ?? '—' }}</td>
                <td>{{ new Date(row.created_at).toLocaleString('en-IN') }}</td>
                <td>
                  <VBtn size="small" variant="text" @click="viewPlatformMessageTelemetry(row.id)">
                    View
                  </VBtn>
                </td>
              </tr>
              <tr v-if="!platformRows.length">
                <td colspan="7" class="text-center text-medium-emphasis">
                  No platform messages sent yet.
                </td>
              </tr>
            </tbody>
          </VTable>
          <div v-if="hasMorePlatformMessages" class="text-center pa-4">
            <VBtn size="small" variant="text" @click="onLoadMorePlatformMessages">
              Load more
            </VBtn>
          </div>
        </VCard>
      </VWindowItem>
    </VWindow>
  </template>

  <VDialog v-model="telemetryDialog" max-width="900">
    <VCard>
      <VCardTitle class="d-flex align-center justify-space-between">
        <span>Message Telemetry</span>
        <VBtn icon="tabler-x" variant="text" size="small" @click="telemetryDialog = false" />
      </VCardTitle>
      <VCardText style="max-block-size: 75vh; overflow-y: auto;">
        <VProgressLinear v-if="telemetryLoading" indeterminate class="mb-4" />

        <VAlert v-if="telemetryError" type="error" variant="tonal" density="compact" class="mb-4">
          {{ telemetryError }}
        </VAlert>

        <template v-if="telemetry">
          <div class="text-caption text-medium-emphasis mb-1">
            To {{ telemetry.recipient }} · {{ new Date(telemetry.created_at).toLocaleString('en-IN') }} ·
            <VChip size="x-small" :color="STATUS_COLORS[telemetry.status] || 'default'" class="text-capitalize">
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

          <template v-for="(attempt, i) in telemetry.attempts" :key="attempt.id">
            <VDivider class="my-4" />
            <div class="d-flex align-center gap-2 mb-1">
              <h6 class="text-subtitle-1 font-weight-bold">
                Route attempt {{ i + 1 }} — {{ attempt.route }}
              </h6>
              <VChip size="x-small" :color="STATUS_COLORS[attempt.status] || 'default'" class="text-capitalize">
                {{ attempt.status.replaceAll('_', ' ') }}
              </VChip>
            </div>
            <p v-if="attempt.error" class="text-caption text-error mb-2">
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
            <pre v-if="attempt.webhook_payload" class="telemetry-block">{{ formatJson(attempt.webhook_payload) }}</pre>
            <p v-else class="text-body-2 text-medium-emphasis">
              Not received yet{{ attempt.delivery_status_code !== null ? '' : ' (or this route never requests delivery reports)' }}.
            </p>
            <p v-if="attempt.delivery_status_code !== null" class="text-caption text-medium-emphasis mt-1">
              DeliveryStatusCode: {{ attempt.delivery_status_code }}<span v-if="attempt.delivery_status_description"> — {{ attempt.delivery_status_description }}</span>
              <span v-if="attempt.delivered_at">· {{ new Date(attempt.delivered_at).toLocaleString('en-IN') }}</span>
            </p>
            <p v-if="attempt.delivery_status_text" class="text-caption text-medium-emphasis">
              TTBS's own DeliveryStatus: <strong>{{ attempt.delivery_status_text }}</strong>
            </p>

            <div class="text-caption text-medium-emphasis mt-3 mb-1 d-flex align-center gap-2">
              6. Relayed to customer's webhook
              <VChip
                v-if="attempt.customer_webhook_status"
                size="x-small"
                :color="attempt.customer_webhook_status === 'success' ? 'success' : attempt.customer_webhook_status === 'failed' ? 'error' : 'default'"
                class="text-capitalize"
              >
                {{ attempt.customer_webhook_status.replaceAll('_', ' ') }}
              </VChip>
            </div>
            <p v-if="attempt.customer_webhook_status === 'not_configured'" class="text-body-2 text-medium-emphasis">
              This customer hasn't configured a DR webhook URL — nothing was sent.
            </p>
            <template v-else-if="attempt.customer_webhook_url">
              <p class="text-caption text-medium-emphasis mb-1">
                Sent to {{ attempt.customer_webhook_url }}<span v-if="attempt.customer_webhook_sent_at"> · {{ new Date(attempt.customer_webhook_sent_at).toLocaleString('en-IN') }}</span>
              </p>
              <p v-if="attempt.customer_webhook_error" class="text-caption text-error mb-1">
                {{ attempt.customer_webhook_error }}
              </p>
              <pre v-if="attempt.customer_webhook_payload" class="telemetry-block">{{ formatJson(attempt.customer_webhook_payload) }}</pre>
            </template>
            <p v-else class="text-body-2 text-medium-emphasis">
              Not sent yet — waiting on a delivery report from TTBS.
            </p>
          </template>

          <p v-if="!telemetry.attempts.length" class="text-body-2 text-medium-emphasis mt-4">
            Not dispatched to a provider yet.
          </p>
        </template>

        <template v-else-if="platformTelemetry">
          <div class="text-caption text-medium-emphasis mb-1">
            To {{ platformTelemetry.recipient }} · {{ new Date(platformTelemetry.created_at).toLocaleString('en-IN') }} ·
            <VChip size="x-small" :color="STATUS_COLORS[platformTelemetry.status] || 'default'" class="text-capitalize">
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
            Delivery report webhook
          </h6>
          <pre v-if="platformTelemetry.webhook_payload" class="telemetry-block">{{ formatJson(platformTelemetry.webhook_payload) }}</pre>
          <p v-else class="text-body-2 text-medium-emphasis">
            Not received yet (or route {{ platformTelemetry.route ?? '(simulated)' }} never requests delivery reports).
          </p>
          <p v-if="platformTelemetry.delivery_status_code !== null" class="text-caption text-medium-emphasis mt-1">
            DeliveryStatusCode: {{ platformTelemetry.delivery_status_code }}<span v-if="platformTelemetry.delivery_status_description"> — {{ platformTelemetry.delivery_status_description }}</span>
            <span v-if="platformTelemetry.delivered_at">· {{ new Date(platformTelemetry.delivered_at).toLocaleString('en-IN') }}</span>
          </p>
          <p v-if="platformTelemetry.delivery_status_text" class="text-caption text-medium-emphasis">
            TTBS's own DeliveryStatus: <strong>{{ platformTelemetry.delivery_status_text }}</strong>
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

<style scoped>
.telemetry-block {
  background: rgba(var(--v-theme-on-surface), 0.05);
  border-radius: 6px;
  padding: 12px;
  font-family: monospace;
  font-size: 0.8125rem;
  white-space: pre-wrap;
  word-break: break-word;
  max-block-size: 240px;
  overflow-y: auto;
}
</style>
