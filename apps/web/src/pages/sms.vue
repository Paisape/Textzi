<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'sms',
  },
})

const SMS_SEGMENT_LENGTH = 160

type TemplateSummary = {
  id: string
  alias: string
  dlt_template_id: string
  body: string
  category: string
}

type MessageRow = {
  id: string
  recipient: string
  rendered_body: string
  status: string
  route: string | null
  credits_charged: number
  created_at: string
}

type OptOutEntry = {
  id: string
  mobile: string
  reason: string | null
  created_at: string
}

const activeTab = ref('compose')

const templates = ref<TemplateSummary[]>([])
const messages = ref<MessageRow[]>([])
const loadError = ref('')
const needsOnboarding = ref(false)
const loading = ref(true)

const selectedTemplateId = ref<string | null>(null)
const mobile = ref('')
const variableValues = ref<Record<string, string>>({})
const sendError = ref('')
const sendResult = ref<{ status: string, route: string, balance: number, creditsCharged: number } | null>(null)
const sending = ref(false)

const selectedTemplate = computed(() => templates.value.find(t => t.id === selectedTemplateId.value) ?? null)

type VariableSlot = { key: string, label: string }

// DLT-approved templates almost always use {#...#}-style placeholders (the TRAI/DLT platform's
// own convention -- see services.render_template), not Textzi's own {{var}}. Those are purely
// positional server-side (matched by occurrence order, not by name), so each occurrence gets its
// own input even if the text inside the braces repeats -- unlike {{var}}, which is deduplicated
// by name. A template uses one convention or the other, never both, so checking for {{var}} first
// and falling back to {#...#} covers every real template correctly.
const variableSlots = computed<VariableSlot[]>(() => {
  if (!selectedTemplate.value)
    return []
  const body = selectedTemplate.value.body
  const namedMatches = [...body.matchAll(/\{\{\s*(\w+)\s*\}\}/g)]
  if (namedMatches.length) {
    const seen = new Set<string>()
    const slots: VariableSlot[] = []
    for (const m of namedMatches) {
      if (!seen.has(m[1])) {
        seen.add(m[1])
        slots.push({ key: m[1], label: m[1] })
      }
    }
    return slots
  }
  const dltMatches = [...body.matchAll(/\{#([^{}]*)#\}/g)]
  return dltMatches.map((m, index) => ({ key: `dlt_${index}`, label: m[1] || `Variable ${index + 1}` }))
})

function initVariableValues() {
  const values: Record<string, string> = {}
  for (const slot of variableSlots.value)
    values[slot.key] = ''
  variableValues.value = values
}

const previewBody = computed(() => {
  if (!selectedTemplate.value)
    return ''
  const body = selectedTemplate.value.body
  if (variableSlots.value.length && body.includes('{{'))
    return body.replace(/\{\{\s*(\w+)\s*\}\}/g, (_match, name) => variableValues.value[name] || `{{${name}}}`)
  let index = 0
  return body.replace(/\{#[^{}]*#\}/g, () => {
    const slot = variableSlots.value[index]
    index += 1
    if (!slot)
      return '{#...#}'
    return variableValues.value[slot.key] || `{#${slot.label}#}`
  })
})

const estimatedCredits = computed(() => {
  const len = previewBody.value.length
  return len ? Math.max(1, Math.ceil(len / SMS_SEGMENT_LENGTH)) : 1
})

watch(selectedTemplateId, () => {
  initVariableValues()
})

async function loadTemplates() {
  templates.value = await $api<TemplateSummary[]>('/v1/sms/templates')
}

const MESSAGE_PAGE_SIZE = 20
const messagesOffset = ref(0)
const hasMoreMessages = ref(false)

async function loadMessages(reset = true) {
  if (reset)
    messagesOffset.value = 0
  const page = await $api<MessageRow[]>('/v1/sms/messages', { query: { limit: MESSAGE_PAGE_SIZE, offset: messagesOffset.value } })
  messages.value = reset ? page : [...messages.value, ...page]
  hasMoreMessages.value = page.length === MESSAGE_PAGE_SIZE
}

async function onLoadMoreMessages() {
  messagesOffset.value += MESSAGE_PAGE_SIZE
  await loadMessages(false)
}

function isoDate(date: Date) {
  return date.toISOString().slice(0, 10)
}

const reportDateFrom = ref(isoDate(new Date(Date.now() - 29 * 24 * 60 * 60 * 1000)))
const reportDateTo = ref(isoDate(new Date()))
const downloadingReport = ref(false)
const reportError = ref('')

async function onDownloadReport() {
  reportError.value = ''
  if (!reportDateFrom.value || !reportDateTo.value) {
    reportError.value = 'Select both a from and to date.'
    return
  }
  downloadingReport.value = true
  try {
    const blob = await $api<Blob, 'blob'>('/v1/reports/messages/export', {
      query: { date_from: reportDateFrom.value, date_to: reportDateTo.value },
      responseType: 'blob',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `Textzi-Messages-${reportDateFrom.value}-to-${reportDateTo.value}.xlsx`
    link.click()
    URL.revokeObjectURL(url)
  }
  catch (error: any) {
    reportError.value = extractErrorMessage(error, 'Could not download this report.')
  }
  finally {
    downloadingReport.value = false
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  needsOnboarding.value = false
  try {
    await Promise.all([loadTemplates(), loadMessages(true)])
  }
  catch (error: any) {
    const detail = typeof error?.data?.detail === 'string' ? error.data.detail : ''
    if (detail.includes('onboarding'))
      needsOnboarding.value = true
    else
      loadError.value = extractErrorMessage(error, 'Could not load your templates and messages.')
  }
  finally {
    loading.value = false
  }
}

async function onSend() {
  sendError.value = ''
  sendResult.value = null
  if (!selectedTemplate.value) {
    sendError.value = 'Select a template first.'
    return
  }
  if (!mobile.value.trim()) {
    sendError.value = 'Enter a recipient mobile number.'
    return
  }
  const missing = variableSlots.value.filter(slot => !variableValues.value[slot.key]?.trim())
  if (missing.length) {
    sendError.value = `Fill in: ${missing.map(slot => slot.label).join(', ')}`
    return
  }
  sending.value = true
  try {
    const result = await $api<{ status: string, message_id: string, route: string, balance: number, credits_charged: number }>('/v1/sms/compose', {
      method: 'POST',
      body: {
        template: selectedTemplate.value.alias,
        mobile: mobile.value.trim(),
        variables: variableValues.value,
      },
    })
    sendResult.value = { status: result.status, route: result.route, balance: result.balance, creditsCharged: result.credits_charged }
    mobile.value = ''
    initVariableValues()
    await loadMessages(true)
  }
  catch (error: any) {
    sendError.value = extractErrorMessage(error, 'Could not send this message.')
  }
  finally {
    sending.value = false
  }
}

function statusColor(status: string): string {
  if (status === 'submitted' || status === 'delivered')
    return 'success'
  if (status === 'failed' || status === 'delivery_failed')
    return 'error'
  return 'warning'
}

const optOuts = ref<OptOutEntry[]>([])
const optOutLoadError = ref('')
const optOutLoaded = ref(false)
const newOptOutMobile = ref('')
const newOptOutReason = ref('')
const optOutSaving = ref(false)
const optOutError = ref('')
const removingOptOutId = ref<string | null>(null)

async function loadOptOuts() {
  optOutLoadError.value = ''
  try {
    optOuts.value = await $api<OptOutEntry[]>('/v1/sms/opt-outs')
    optOutLoaded.value = true
  }
  catch (error: any) {
    optOutLoadError.value = extractErrorMessage(error, 'Could not load the opt-out list.')
  }
}

async function onAddOptOut() {
  optOutError.value = ''
  if (!newOptOutMobile.value.trim()) {
    optOutError.value = 'Enter a mobile number.'
    return
  }
  optOutSaving.value = true
  try {
    await $api('/v1/sms/opt-outs', {
      method: 'POST',
      body: { mobile: newOptOutMobile.value.trim(), reason: newOptOutReason.value.trim() || null },
    })
    newOptOutMobile.value = ''
    newOptOutReason.value = ''
    await loadOptOuts()
  }
  catch (error: any) {
    optOutError.value = extractErrorMessage(error, 'Could not add this number to the opt-out list.')
  }
  finally {
    optOutSaving.value = false
  }
}

async function onRemoveOptOut(id: string) {
  removingOptOutId.value = id
  try {
    await $api(`/v1/sms/opt-outs/${id}`, { method: 'DELETE' })
    await loadOptOuts()
  }
  catch (error: any) {
    optOutError.value = extractErrorMessage(error, 'Could not remove this entry.')
  }
  finally {
    removingOptOutId.value = null
  }
}

watch(activeTab, tab => {
  if (tab === 'opt-outs' && !optOutLoaded.value)
    loadOptOuts()
})

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Send SMS
  </h1>
  <p class="text-medium-emphasis mb-6">
    Compose a message from one of your DLT-approved templates and track delivery.
  </p>

  <VAlert
    v-if="needsOnboarding"
    type="warning"
    variant="tonal"
    class="mb-6"
  >
    Finish setting up your organisation before you can send messages.
    <RouterLink
      to="/onboarding"
      class="font-weight-medium"
    >
      Complete onboarding
    </RouterLink>
  </VAlert>

  <VAlert
    v-else-if="loadError"
    type="error"
    variant="tonal"
    class="mb-6"
  >
    {{ loadError }}
  </VAlert>

  <template v-else-if="!loading">
    <VAlert
      v-if="!templates.length"
      type="info"
      variant="tonal"
      class="mb-6"
    >
      No DLT-approved templates are available on your account yet. Ask an administrator to register one under DLT Hierarchy.
    </VAlert>

    <template v-else>
      <VTabs v-model="activeTab" class="mb-6">
        <VTab value="compose">
          Compose & Log
        </VTab>
        <VTab value="opt-outs">
          Opt-Out List
        </VTab>
      </VTabs>

      <VWindow v-model="activeTab">
        <VWindowItem value="compose">
          <VRow>
            <VCol cols="12" md="6">
              <VCard class="mb-6">
                <VCardText>
                  <h6 class="text-h6 mb-4">
                    Compose
                  </h6>
                  <VAlert
                    v-if="sendError"
                    type="error"
                    variant="tonal"
                    density="compact"
                    class="mb-4"
                  >
                    {{ sendError }}
                  </VAlert>
                  <VAlert
                    v-if="sendResult"
                    :type="sendResult.status === 'failed' ? 'error' : 'success'"
                    variant="tonal"
                    density="compact"
                    class="mb-4"
                  >
                    Message {{ sendResult.status }} via route "{{ sendResult.route }}" — charged {{ sendResult.creditsCharged }} credit{{ sendResult.creditsCharged === 1 ? '' : 's' }}. SMS credits remaining: {{ sendResult.balance.toLocaleString('en-IN', { maximumFractionDigits: 2 }) }}
                  </VAlert>
                  <VForm @submit.prevent="onSend">
                    <VSelect
                      v-model="selectedTemplateId"
                      :items="templates"
                      item-title="alias"
                      item-value="id"
                      label="Template"
                      class="mb-4"
                    />
                    <AppTextField
                      v-model="mobile"
                      label="Recipient mobile"
                      placeholder="9198765xxxxx"
                      class="mb-4"
                    />
                    <template v-if="selectedTemplate">
                      <p class="text-body-2 text-medium-emphasis mb-1">
                        Approved wording: <em>{{ selectedTemplate.body }}</em>
                      </p>
                      <p class="text-body-2 text-medium-emphasis mb-2">
                        Cost: 1 credit per 160 characters — this message is currently estimated at
                        <strong>{{ estimatedCredits }} credit{{ estimatedCredits === 1 ? '' : 's' }}</strong> ({{ previewBody.length }} chars)
                      </p>
                      <AppTextField
                        v-for="slot in variableSlots"
                        :key="slot.key"
                        v-model="variableValues[slot.key]"
                        :label="slot.label"
                        class="mb-4"
                      />
                      <p
                        v-if="variableSlots.length"
                        class="text-body-2 mb-4"
                      >
                        Preview: {{ previewBody }}
                      </p>
                    </template>
                    <VBtn
                      type="submit"
                      :loading="sending"
                      :disabled="!selectedTemplateId"
                      prepend-icon="tabler-send"
                    >
                      Send message
                    </VBtn>
                  </VForm>
                </VCardText>
              </VCard>
            </VCol>

            <VCol cols="12" md="6">
              <VCard>
                <VCardText>
                  <div class="d-flex flex-wrap align-center justify-space-between gap-4 mb-4">
                    <h6 class="text-h6">
                      Recent messages
                    </h6>
                    <div class="d-flex flex-wrap align-center gap-2">
                      <VTextField
                        v-model="reportDateFrom"
                        type="date"
                        label="From"
                        density="compact"
                        style="max-width: 150px;"
                        hide-details
                      />
                      <VTextField
                        v-model="reportDateTo"
                        type="date"
                        label="To"
                        density="compact"
                        style="max-width: 150px;"
                        hide-details
                      />
                      <VBtn
                        size="small"
                        prepend-icon="tabler-download"
                        :loading="downloadingReport"
                        @click="onDownloadReport"
                      >
                        Download report
                      </VBtn>
                    </div>
                  </div>
                  <VAlert
                    v-if="reportError"
                    type="error"
                    variant="tonal"
                    density="compact"
                    class="mb-4"
                  >
                    {{ reportError }}
                  </VAlert>
                  <VTable>
                    <thead>
                      <tr>
                        <th>Recipient</th>
                        <th>Status</th>
                        <th>Route</th>
                        <th>Credits</th>
                        <th>Sent</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="message in messages"
                        :key="message.id"
                      >
                        <td>{{ message.recipient }}</td>
                        <td>
                          <VChip
                            :color="statusColor(message.status)"
                            size="small"
                            class="text-capitalize"
                          >
                            {{ message.status }}
                          </VChip>
                        </td>
                        <td>{{ message.route ?? '—' }}</td>
                        <td>{{ message.credits_charged }}</td>
                        <td>{{ new Date(message.created_at).toLocaleString('en-IN') }}</td>
                      </tr>
                      <tr v-if="!messages.length">
                        <td
                          colspan="5"
                          class="text-center text-medium-emphasis"
                        >
                          No messages sent yet.
                        </td>
                      </tr>
                    </tbody>
                  </VTable>
                  <div v-if="hasMoreMessages" class="text-center mt-4">
                    <VBtn size="small" variant="text" @click="onLoadMoreMessages">
                      Load more
                    </VBtn>
                  </div>
                </VCardText>
              </VCard>
            </VCol>
          </VRow>
        </VWindowItem>

        <VWindowItem value="opt-outs">
          <VCard max-width="640">
            <VCardText>
              <p class="text-body-2 text-medium-emphasis mb-4">
                Numbers on this list are never billed or dispatched to. This is your own
                self-service suppression list — not a connection to India's NCPR/DND registry,
                which is enforced separately at the network/provider level.
              </p>

              <VAlert v-if="optOutLoadError" type="error" variant="tonal" density="compact" class="mb-4">
                {{ optOutLoadError }}
              </VAlert>
              <VAlert v-if="optOutError" type="error" variant="tonal" density="compact" class="mb-4">
                {{ optOutError }}
              </VAlert>

              <VForm class="mb-6" @submit.prevent="onAddOptOut">
                <VRow>
                  <VCol cols="12" sm="5">
                    <AppTextField
                      v-model="newOptOutMobile"
                      label="Mobile number"
                      placeholder="9198765xxxxx"
                    />
                  </VCol>
                  <VCol cols="12" sm="5">
                    <AppTextField
                      v-model="newOptOutReason"
                      label="Reason (optional)"
                      placeholder="Replied STOP"
                    />
                  </VCol>
                  <VCol cols="12" sm="2" class="d-flex align-end">
                    <VBtn type="submit" :loading="optOutSaving">
                      Add
                    </VBtn>
                  </VCol>
                </VRow>
              </VForm>

              <VTable density="compact">
                <thead>
                  <tr>
                    <th>Mobile</th>
                    <th>Reason</th>
                    <th>Added</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="entry in optOuts" :key="entry.id">
                    <td>{{ entry.mobile }}</td>
                    <td>{{ entry.reason ?? '—' }}</td>
                    <td>{{ new Date(entry.created_at).toLocaleString('en-IN') }}</td>
                    <td>
                      <VBtn
                        size="small"
                        variant="text"
                        color="error"
                        :loading="removingOptOutId === entry.id"
                        @click="onRemoveOptOut(entry.id)"
                      >
                        Remove
                      </VBtn>
                    </td>
                  </tr>
                  <tr v-if="!optOuts.length">
                    <td colspan="4" class="text-center text-medium-emphasis">
                      No numbers on your opt-out list.
                    </td>
                  </tr>
                </tbody>
              </VTable>
            </VCardText>
          </VCard>
        </VWindowItem>
      </VWindow>
    </template>
  </template>
</template>
