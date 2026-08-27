<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

import { addRecentlyViewed } from '@/composables/useRecentlyViewed'
import { useAuthStore } from '@/stores/auth'

const route = useRoute('crm-deals-id')
const router = useRouter()
const authStore = useAuthStore()

type CrmContact = { id: string, name: string | null, phone: string | null, email: string | null, title: string | null, company_id: string | null }
type Deal = {
  id: string
  name: string | null
  contact: CrmContact
  pipeline_id: string | null
  stage: string
  source: string
  converted_from_conversation_id: string | null
  converted_from_lead_id: string | null
  owner_user_id: string | null
  notes: string | null
  value: number | null
  probability: number | null
  expected_close_date: string | null
  status: 'open' | 'won' | 'lost'
  lost_reason: string | null
  next_step: string | null
  next_step_due_at: string | null
  custom_fields: Record<string, any>
  stage_approvals: Record<string, { user_id: string, approved_at: string }[]>
  created_at: string
}
type Company = { id: string, name: string, industry: string | null, open_deal_value: number, won_deal_value: number, open_deal_count: number }
type Task = { id: string, title: string, type: string, due_at: string | null, done: boolean, priority: string }
type Quote = { id: string, quote_number: string | null, status: string, total: number, approval_status: string, created_at: string }
type ActivityMessage = { id: string, channel: string, direction: 'inbound' | 'outbound', message_type: string, body: string | null, created_at: string }
type DealDetail = { deal: Deal, company: Company | null, tasks: Task[], quotes: Quote[], waba_contact_id: string | null, recent_messages: ActivityMessage[] }
type AssignableUser = { id: string, full_name: string }
type PipelineStage = { name: string, probability: number, forecast_category: string, required_approval_user_ids?: string[] }
type Pipeline = { id: string, name: string, stages: PipelineStage[] }
type DocumentTemplate = { id: string, name: string, applies_to: string }
type StageEvent = { stage: string, entered_at: string, exited_at: string | null, minutes: number | null, changed_by_user_id: string | null, changed_by_name: string | null }

const detail = ref<DealDetail | null>(null)
const users = ref<AssignableUser[]>([])
const pipelines = ref<Pipeline[]>([])
const documentTemplates = ref<DocumentTemplate[]>([])
const stageHistory = ref<StageEvent[]>([])
const loading = ref(false)
const loadError = ref('')

function dealTitle() {
  const d = detail.value?.deal
  return d?.name || d?.contact.name || d?.contact.phone || d?.contact.email || 'Unknown'
}

function formatActivityTime(iso: string) {
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function durationLabel(minutes: number | null) {
  if (minutes === null)
    return '—'
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)
  if (days)
    return `${days}d ${hours % 24}h`
  if (hours)
    return `${hours}h ${minutes % 60}m`
  return `${minutes}m`
}

function inr(value: number | null) {
  if (value === null)
    return '—'
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value)
}

async function loadStageHistory() {
  const result = await $api<{ events: StageEvent[] }>(`/v1/crm/deals/${route.params.id}/stage-history`)
  stageHistory.value = result.events
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [detailResult, userResult, pipelineResult, documentResult] = await Promise.all([
      $api<DealDetail>(`/v1/crm/deals/${route.params.id}`),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
      $api<Pipeline[]>('/v1/crm/pipelines'),
      $api<DocumentTemplate[]>('/v1/crm/document-templates'),
    ])
    detail.value = detailResult
    users.value = userResult
    pipelines.value = pipelineResult
    documentTemplates.value = documentResult
    await loadStageHistory()
    addRecentlyViewed({
      type: 'deal', id: detailResult.deal.id,
      label: detailResult.deal.name || detailResult.deal.contact.name || detailResult.deal.contact.phone || detailResult.deal.contact.email || 'Unknown',
      sublabel: detailResult.deal.value ? inr(detailResult.deal.value) : null,
    })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load this deal.')
  }
  finally {
    loading.value = false
  }
}

function initial() {
  const c = detail.value?.deal.contact
  return (c?.name || c?.phone || c?.email || '?').slice(0, 1).toUpperCase()
}

async function updateOwner(ownerUserId: string | null) {
  if (!detail.value)
    return
  try {
    const updated = await $api<Deal>(`/v1/crm/deals/${detail.value.deal.id}/owner`, { method: 'PATCH', body: { owner_user_id: ownerUserId } })
    detail.value.deal.owner_user_id = updated.owner_user_id
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not reassign this deal.')
  }
}

async function updateStage(stage: string) {
  if (!detail.value || stage === detail.value.deal.stage)
    return
  try {
    const updated = await $api<Deal>(`/v1/crm/deals/${detail.value.deal.id}/stage`, { method: 'PATCH', body: { stage } })
    detail.value.deal.stage = updated.stage
    await loadStageHistory()
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this deal\'s stage.')
  }
}

// --- Change pipeline --------------------------------------------------------------------------

const pipelineDialog = ref(false)
const pipelineForm = reactive({ pipeline_id: null as string | null, stage: null as string | null })
const pipelineSaving = ref(false)

function openPipelineDialog() {
  if (!detail.value)
    return
  pipelineForm.pipeline_id = detail.value.deal.pipeline_id
  pipelineForm.stage = detail.value.deal.stage
  pipelineDialog.value = true
}

const pipelineFormStages = computed(() => pipelines.value.find(p => p.id === pipelineForm.pipeline_id)?.stages || [])

async function savePipeline() {
  if (!detail.value || !pipelineForm.pipeline_id)
    return
  pipelineSaving.value = true
  try {
    const updated = await $api<Deal>(`/v1/crm/deals/${detail.value.deal.id}/pipeline`, {
      method: 'PATCH',
      query: { pipeline_id: pipelineForm.pipeline_id, stage: pipelineForm.stage },
    })
    Object.assign(detail.value.deal, updated)
    await loadStageHistory()
    pipelineDialog.value = false
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not change this deal\'s pipeline.')
  }
  finally {
    pipelineSaving.value = false
  }
}

// --- Stage approval gate (Pipeline stage's required_approval_user_ids) -----------------------

const currentStageApprovers = computed(() => {
  const pipeline = pipelines.value.find(p => p.id === detail.value?.deal.pipeline_id)
  const stage = pipeline?.stages.find(s => s.name === detail.value?.deal.stage)
  return stage?.required_approval_user_ids || []
})

const missingApprovers = computed(() => {
  if (!detail.value)
    return []
  const approved = new Set((detail.value.deal.stage_approvals[detail.value.deal.stage] || []).map(a => a.user_id))
  return currentStageApprovers.value.filter(id => !approved.has(id))
})

const iCanApprove = computed(() => !!authStore.profile && missingApprovers.value.includes(authStore.profile.id))

const approving = ref(false)

async function approveStage() {
  if (!detail.value)
    return
  approving.value = true
  try {
    const updated = await $api<Deal>(`/v1/crm/deals/${detail.value.deal.id}/stage-approvals/approve`, { method: 'POST' })
    detail.value.deal.stage_approvals = updated.stage_approvals
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not record your approval.')
  }
  finally {
    approving.value = false
  }
}

async function updateNotes(notes: string) {
  if (!detail.value)
    return
  try {
    await $api(`/v1/crm/deals/${detail.value.deal.id}/notes`, { method: 'PATCH', body: { notes } })
    detail.value.deal.notes = notes
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not save notes.')
  }
}

// --- Edit financial fields ---------------------------------------------------------------------

const dealDialog = ref(false)
const dealForm = reactive({
  name: '', value: null as number | null, probability: null as number | null, expected_close_date: '',
  next_step: '', next_step_due_at: '',
})
const dealSaving = ref(false)

function openDealDialog() {
  if (!detail.value)
    return
  dealForm.name = detail.value.deal.name || ''
  dealForm.value = detail.value.deal.value
  dealForm.probability = detail.value.deal.probability
  dealForm.expected_close_date = detail.value.deal.expected_close_date ? detail.value.deal.expected_close_date.slice(0, 10) : ''
  dealForm.next_step = detail.value.deal.next_step || ''
  dealForm.next_step_due_at = detail.value.deal.next_step_due_at ? detail.value.deal.next_step_due_at.slice(0, 10) : ''
  dealDialog.value = true
}

async function saveDeal() {
  if (!detail.value)
    return
  dealSaving.value = true
  try {
    const updated = await $api<Deal>(`/v1/crm/deals/${detail.value.deal.id}`, {
      method: 'PATCH',
      body: {
        name: dealForm.name.trim() || null,
        value: dealForm.value,
        probability: dealForm.probability,
        expected_close_date: dealForm.expected_close_date || null,
        next_step: dealForm.next_step.trim() || null,
        next_step_due_at: dealForm.next_step_due_at || null,
      },
    })
    Object.assign(detail.value.deal, updated)
    dealDialog.value = false
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this deal.')
  }
  finally {
    dealSaving.value = false
  }
}

// --- Won / Lost / Convert -----------------------------------------------------------------------

const lostDialog = ref(false)
const lostReason = ref('')
const converting = ref(false)
const markingWon = ref(false)
const confirmingLost = ref(false)

async function markWon() {
  if (!detail.value)
    return
  markingWon.value = true
  try {
    const updated = await $api<Deal>(`/v1/crm/deals/${detail.value.deal.id}/status`, { method: 'PATCH', body: { status: 'won' } })
    Object.assign(detail.value.deal, updated)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not mark this deal as won.')
  }
  finally {
    markingWon.value = false
  }
}

async function confirmLost() {
  if (!detail.value)
    return
  confirmingLost.value = true
  try {
    const updated = await $api<Deal>(`/v1/crm/deals/${detail.value.deal.id}/status`, { method: 'PATCH', body: { status: 'lost', lost_reason: lostReason.value } })
    Object.assign(detail.value.deal, updated)
    lostDialog.value = false
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not mark this deal as lost.')
  }
  finally {
    confirmingLost.value = false
  }
}

async function convertToCustomer() {
  if (!detail.value)
    return
  converting.value = true
  try {
    const customer = await $api<{ id: string }>(`/v1/crm/deals/${detail.value.deal.id}/convert-to-customer`, { method: 'POST' })
    router.push({ name: 'crm-customers', query: { highlight: customer.id } })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not convert this deal to a customer.')
  }
  finally {
    converting.value = false
  }
}

// --- Delete ----------------------------------------------------------------------------------

const deleting = ref(false)

async function deleteDeal() {
  if (!detail.value)
    return
  deleting.value = true
  try {
    await $api(`/v1/crm/deals/${detail.value.deal.id}`, { method: 'DELETE' })
    router.push({ name: 'crm-deals' })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this deal.')
  }
  finally {
    deleting.value = false
  }
}

const generatingDocument = ref(false)

async function generateDocument(templateId: string) {
  if (!detail.value || !templateId)
    return
  generatingDocument.value = true
  try {
    const template = documentTemplates.value.find(t => t.id === templateId)
    const blob = await $api<Blob, 'blob'>(`/v1/crm/document-templates/${templateId}/generate`, {
      method: 'POST', body: { deal_id: detail.value.deal.id }, responseType: 'blob',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${template?.name || 'document'}.pdf`
    link.click()
    URL.revokeObjectURL(url)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not generate this document.')
  }
  finally {
    generatingDocument.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="d-flex align-center gap-3 mb-4">
    <VBtn icon="tabler-arrow-left" variant="text" :to="{ name: 'crm-deals' }" />
    <h1 class="text-h5 mb-0">
      Deal
    </h1>
  </div>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <VProgressLinear v-if="loading" indeterminate class="mb-4" />

  <VRow v-if="detail">
    <VCol cols="12" md="8">
      <VCard class="mb-4">
        <VCardText class="d-flex align-center gap-4">
          <VAvatar color="primary" variant="tonal" size="56">
            <span class="text-h6">{{ initial() }}</span>
          </VAvatar>
          <div class="flex-grow-1">
            <p class="text-h6 mb-0">
              {{ dealTitle() }}
            </p>
            <p v-if="detail.deal.name" class="text-body-2 text-medium-emphasis mb-0">
              {{ detail.deal.contact.name || detail.deal.contact.phone || detail.deal.contact.email }}
            </p>
            <p class="text-body-2 text-medium-emphasis mb-0">
              {{ inr(detail.deal.value) }} <span v-if="detail.deal.probability !== null">· {{ detail.deal.probability }}%</span>
            </p>
          </div>
          <VChip :color="detail.deal.status === 'won' ? 'success' : detail.deal.status === 'lost' ? 'error' : undefined" size="small">
            {{ detail.deal.status }}
          </VChip>
        </VCardText>
        <VDivider />
        <VCardText class="d-flex flex-wrap gap-3">
          <RouterLink v-if="detail.company" :to="`/crm-companies/${detail.company.id}`" class="d-flex align-center gap-2 text-body-2">
            <VIcon icon="tabler-building" size="16" />
            {{ detail.company.name }}
          </RouterLink>
          <RouterLink :to="`/crm-contacts/${detail.deal.contact.id}`" class="d-flex align-center gap-2 text-body-2">
            <VIcon icon="tabler-user" size="16" />
            View contact
          </RouterLink>
          <RouterLink v-if="detail.waba_contact_id" :to="`/waba-customers/${detail.waba_contact_id}`" class="d-flex align-center gap-2 text-body-2">
            <VIcon icon="tabler-brand-whatsapp" size="16" />
            View WhatsApp conversation
          </RouterLink>
          <span class="d-flex align-center gap-2 text-body-2 text-medium-emphasis">
            <VIcon icon="tabler-calendar" size="16" />
            {{ detail.deal.expected_close_date ? `Closes ${new Date(detail.deal.expected_close_date).toLocaleDateString()}` : 'No close date set' }}
          </span>
        </VCardText>
        <VDivider />
        <VAlert v-if="detail.deal.status === 'open' && missingApprovers.length" type="warning" variant="tonal" class="ma-4 mb-0">
          <div class="d-flex align-center justify-space-between flex-wrap gap-2">
            <span>Needs approval from {{ missingApprovers.length }} {{ missingApprovers.length === 1 ? 'person' : 'people' }} before this deal can leave "{{ detail.deal.stage }}"</span>
            <VBtn v-if="iCanApprove" size="small" color="warning" :loading="approving" @click="approveStage">
              Approve
            </VBtn>
          </div>
        </VAlert>
        <VCardText v-if="detail.deal.status === 'open'">
          <div class="d-flex align-center" style="overflow-x: auto;">
            <template v-for="(stage, i) in (pipelines.find(p => p.id === detail?.deal.pipeline_id)?.stages || [])" :key="stage.name">
              <div class="d-flex flex-column align-center" style="min-inline-size: 90px; cursor: pointer;" @click="updateStage(stage.name)">
                <VAvatar
                  size="28" :color="stage.name === detail.deal.stage ? 'primary' : undefined"
                  :variant="stage.name === detail.deal.stage ? 'flat' : 'tonal'"
                >
                  <VIcon v-if="stage.name === detail.deal.stage" icon="tabler-check" size="16" />
                </VAvatar>
                <span class="text-caption text-center mt-1" :class="stage.name === detail.deal.stage ? 'font-weight-bold' : 'text-medium-emphasis'">
                  {{ formatLabel(stage.name) }}
                </span>
              </div>
              <VDivider v-if="i < (pipelines.find(p => p.id === detail?.deal.pipeline_id)?.stages || []).length - 1" style="min-inline-size: 24px;" />
            </template>
          </div>
        </VCardText>
        <VCardText v-if="detail.deal.next_step" class="pt-0">
          <VDivider class="mb-4" />
          <p class="text-caption text-medium-emphasis mb-1">
            Next step
          </p>
          <p class="mb-0">
            {{ detail.deal.next_step }}
            <span v-if="detail.deal.next_step_due_at" class="text-medium-emphasis">
              · due {{ new Date(detail.deal.next_step_due_at).toLocaleDateString() }}
            </span>
          </p>
        </VCardText>
      </VCard>

      <VCard class="mb-4" title="Activity">
        <VList v-if="detail.recent_messages.length" density="compact">
          <VListItem v-for="m in detail.recent_messages" :key="m.id">
            <template #prepend>
              <VIcon :icon="m.channel === 'email' ? 'tabler-mail' : 'tabler-brand-whatsapp'" size="16" :color="m.channel === 'email' ? undefined : 'success'" />
            </template>
            <VListItemTitle class="text-wrap">
              {{ m.body || `[${m.message_type}]` }}
            </VListItemTitle>
            <VListItemSubtitle>
              {{ m.direction === 'outbound' ? 'Sent' : 'Received' }} · {{ formatActivityTime(m.created_at) }}
            </VListItemSubtitle>
          </VListItem>
        </VList>
        <p v-else class="text-medium-emphasis text-center pa-6">
          No WhatsApp or email activity yet.
        </p>
      </VCard>

      <VCard class="mb-4" title="Notes">
        <VCardText>
          <VTextarea
            :model-value="detail.deal.notes || ''" rows="3" density="compact" placeholder="Add notes about this deal..."
            @blur="(e: FocusEvent) => updateNotes((e.target as HTMLTextAreaElement).value)"
          />
        </VCardText>
      </VCard>

      <VCard class="mb-4" title="Quotes">
        <VList v-if="detail.quotes.length" density="compact">
          <VListItem v-for="quote in detail.quotes" :key="quote.id" :to="{ name: 'crm-quotes', query: { highlight: quote.id } }">
            <VListItemTitle>{{ quote.quote_number || 'Draft quote' }} · {{ inr(quote.total) }}</VListItemTitle>
            <VListItemSubtitle>{{ quote.status }} · {{ quote.approval_status.replace('_', ' ') }}</VListItemSubtitle>
          </VListItem>
        </VList>
        <p v-else class="text-medium-emphasis text-center pa-6">
          No quotes yet.
        </p>
        <VCardActions>
          <VBtn variant="text" size="small" :to="{ name: 'crm-quotes', query: { deal_id: detail.deal.id } }">
            New quote
          </VBtn>
        </VCardActions>
      </VCard>

      <VCard title="Tasks">
        <VList v-if="detail.tasks.length" density="compact">
          <VListItem v-for="task in detail.tasks" :key="task.id">
            <VListItemTitle :class="task.done ? 'text-decoration-line-through text-medium-emphasis' : ''">
              {{ task.title }}
            </VListItemTitle>
            <VListItemSubtitle>
              {{ task.type }} · {{ task.due_at ? new Date(task.due_at).toLocaleDateString() : 'no due date' }}
            </VListItemSubtitle>
          </VListItem>
        </VList>
        <p v-else class="text-medium-emphasis text-center pa-6">
          No tasks yet.
        </p>
      </VCard>

      <VCard class="mt-4" title="Time in stage">
        <VList v-if="stageHistory.length" density="compact">
          <VListItem v-for="(event, i) in stageHistory" :key="i">
            <VListItemTitle>
              {{ formatLabel(event.stage) }}
            </VListItemTitle>
            <VListItemSubtitle>
              {{ new Date(event.entered_at).toLocaleDateString() }}
              <span v-if="event.changed_by_name"> · by {{ event.changed_by_name }}</span>
              <span v-if="!event.exited_at" class="text-primary"> · currently here</span>
            </VListItemSubtitle>
            <template #append>
              <span class="text-caption text-medium-emphasis">{{ durationLabel(event.minutes) }}</span>
            </template>
          </VListItem>
        </VList>
        <p v-else class="text-medium-emphasis text-center pa-6">
          No stage history yet.
        </p>
      </VCard>
    </VCol>

    <VCol cols="12" md="4">
      <VCard class="mb-4" title="Details">
        <VCardText class="d-flex flex-column gap-4">
          <div>
            <p class="text-caption text-medium-emphasis mb-1">
              Owner
            </p>
            <VSelect
              :model-value="detail.deal.owner_user_id"
              :items="users.map(u => ({ title: u.full_name, value: u.id }))"
              placeholder="Unassigned" density="compact" hide-details clearable
              @update:model-value="updateOwner"
            />
          </div>
          <div>
            <p class="text-caption text-medium-emphasis mb-1">
              Source
            </p>
            <p class="mb-0">
              {{ formatLabel(detail.deal.source) }}
            </p>
          </div>
          <div v-if="detail.deal.lost_reason">
            <p class="text-caption text-medium-emphasis mb-1">
              Lost reason
            </p>
            <p class="mb-0">
              {{ detail.deal.lost_reason }}
            </p>
          </div>
          <div>
            <p class="text-caption text-medium-emphasis mb-1">
              Created
            </p>
            <p class="mb-0">
              {{ new Date(detail.deal.created_at).toLocaleDateString() }}
            </p>
          </div>
        </VCardText>
      </VCard>

      <VCard title="Actions">
        <VCardText class="d-flex flex-column gap-3">
          <VBtn variant="tonal" block @click="openDealDialog">
            Edit deal
          </VBtn>
          <VBtn variant="tonal" block @click="openPipelineDialog">
            Change pipeline
          </VBtn>
          <VSelect
            v-if="documentTemplates.length"
            placeholder="Generate document" density="compact" hide-details :loading="generatingDocument"
            :items="documentTemplates.map(t => ({ title: t.name, value: t.id }))"
            @update:model-value="(v: string) => generateDocument(v)"
          />
          <template v-if="detail.deal.status === 'open'">
            <VBtn color="success" variant="tonal" block :loading="markingWon" :disabled="markingWon" @click="markWon">
              Mark won
            </VBtn>
            <VBtn color="error" variant="tonal" block :disabled="markingWon" @click="lostDialog = true">
              Mark lost
            </VBtn>
            <VBtn color="primary" block :loading="converting" :disabled="converting" @click="convertToCustomer">
              Convert to customer
            </VBtn>
          </template>
          <VBtn color="error" variant="text" block :loading="deleting" :disabled="deleting" @click="deleteDeal">
            Delete deal
          </VBtn>
        </VCardText>
      </VCard>
    </VCol>
  </VRow>

  <VDialog v-model="dealDialog" max-width="420" persistent>
    <VCard title="Edit deal">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="dealDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VTextField v-model="dealForm.name" label="Deal name" density="compact" />
        <VTextField v-model.number="dealForm.value" label="Deal value (INR)" type="number" min="0" density="compact" />
        <VTextField v-model.number="dealForm.probability" label="Probability (%)" type="number" min="0" max="100" density="compact" />
        <VTextField v-model="dealForm.expected_close_date" label="Expected close date" type="date" density="compact" />
        <VTextField v-model="dealForm.next_step" label="Next step" density="compact" />
        <VTextField v-model="dealForm.next_step_due_at" label="Next step due" type="date" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="dealDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="dealSaving" @click="saveDeal">
          Save
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="pipelineDialog" max-width="420" persistent>
    <VCard title="Change pipeline">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="pipelineDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VSelect
          v-model="pipelineForm.pipeline_id" label="Pipeline" density="compact"
          :items="pipelines.map(p => ({ title: p.name, value: p.id }))"
          @update:model-value="pipelineForm.stage = null"
        />
        <VSelect
          v-model="pipelineForm.stage" label="Starting stage" density="compact"
          :items="pipelineFormStages.map(s => ({ title: formatLabel(s.name), value: s.name }))"
        />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="pipelineDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="pipelineSaving" @click="savePipeline">
          Save
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="lostDialog" max-width="420" persistent>
    <VCard title="Mark as lost">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="lostDialog = false" />
      </template>
      <VCardText>
        <VTextField v-model="lostReason" label="Reason (optional)" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" :disabled="confirmingLost" @click="lostDialog = false">
          Cancel
        </VBtn>
        <VBtn color="error" :loading="confirmingLost" :disabled="confirmingLost" @click="confirmLost">
          Mark lost
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
