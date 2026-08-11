<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type Contact = { id: string, wa_id: string | null, email: string | null, name: string | null }
type Lead = {
  id: string
  contact: Contact
  pipeline_id: string | null
  stage: string
  source: string
  converted_from_conversation_id: string | null
  owner_user_id: string | null
  notes: string | null
  value: number | null
  probability: number | null
  expected_close_date: string | null
  status: 'open' | 'won' | 'lost'
  lost_reason: string | null
  custom_fields: Record<string, any>
  score: number
  created_at: string
}
type AssignableUser = { id: string, full_name: string, email: string }
type Pipeline = { id: string, name: string, stages: string[] }

const pipelines = ref<Pipeline[]>([])
const activePipelineId = ref<string | null>(null)
const leads = ref<Lead[]>([])
const users = ref<AssignableUser[]>([])
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)
const view = ref<'table' | 'board'>('board')
const showClosed = ref(false)

const activePipeline = computed(() => pipelines.value.find(p => p.id === activePipelineId.value) || null)
const stages = computed(() => activePipeline.value?.stages || [])

const visibleLeads = computed(() => leads.value.filter(l => showClosed.value || l.status === 'open'))

function inr(value: number | null) {
  if (value === null)
    return '—'
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value)
}

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    const [leadResult, userResult, pipelineResult] = await Promise.all([
      $api<Lead[]>('/v1/crm/leads'),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
      $api<Pipeline[]>('/v1/crm/pipelines'),
    ])
    leads.value = leadResult
    users.value = userResult
    pipelines.value = pipelineResult
    if (!activePipelineId.value)
      activePipelineId.value = pipelineResult[0]?.id || null
  }
  catch (error: any) {
    if (error?.response?.status === 422)
      crmInactive.value = true
    else
      loadError.value = extractErrorMessage(error, 'Could not load leads.')
  }
  finally {
    loading.value = false
  }
}

function ownerName(lead: Lead) {
  return users.value.find(u => u.id === lead.owner_user_id)?.full_name || null
}

async function updateStage(lead: Lead, stage: string) {
  try {
    const updated = await $api<Lead>(`/v1/crm/leads/${lead.id}/stage`, { method: 'PATCH', body: { stage } })
    lead.stage = updated.stage
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this lead\'s stage.')
  }
}

async function updateOwner(lead: Lead, ownerUserId: string | null) {
  try {
    const updated = await $api<Lead>(`/v1/crm/leads/${lead.id}/owner`, { method: 'PATCH', body: { owner_user_id: ownerUserId } })
    lead.owner_user_id = updated.owner_user_id
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not reassign this lead.')
  }
}

async function switchPipeline(lead: Lead, pipelineId: string) {
  try {
    const updated = await $api<Lead>(`/v1/crm/leads/${lead.id}/pipeline?pipeline_id=${pipelineId}`, { method: 'PATCH' })
    Object.assign(lead, updated)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not move this lead to another pipeline.')
  }
}

const converting = ref<string | null>(null)

async function convertToCustomer(lead: Lead) {
  converting.value = lead.id
  try {
    await $api(`/v1/crm/leads/${lead.id}/convert-to-customer`, { method: 'POST' })
    leads.value = leads.value.filter(l => l.id !== lead.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not convert this lead to a customer.')
  }
  finally {
    converting.value = null
  }
}

// --- Deal fields dialog ------------------------------------------------------------------------

const dealDialog = ref(false)
const dealLead = ref<Lead | null>(null)
const dealForm = reactive({ value: null as number | null, probability: null as number | null, expected_close_date: '' })
const dealSaving = ref(false)

function openDealDialog(lead: Lead) {
  dealLead.value = lead
  dealForm.value = lead.value
  dealForm.probability = lead.probability
  dealForm.expected_close_date = lead.expected_close_date ? lead.expected_close_date.slice(0, 10) : ''
  dealDialog.value = true
}

async function saveDeal() {
  if (!dealLead.value)
    return
  dealSaving.value = true
  try {
    const updated = await $api<Lead>(`/v1/crm/leads/${dealLead.value.id}/deal`, {
      method: 'PATCH',
      body: {
        value: dealForm.value,
        probability: dealForm.probability,
        expected_close_date: dealForm.expected_close_date || null,
      },
    })
    Object.assign(dealLead.value, updated)
    dealDialog.value = false
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this deal.')
  }
  finally {
    dealSaving.value = false
  }
}

// --- Won / Lost ----------------------------------------------------------------------------

const lostDialog = ref(false)
const lostLead = ref<Lead | null>(null)
const lostReason = ref('')

async function markWon(lead: Lead) {
  try {
    const updated = await $api<Lead>(`/v1/crm/leads/${lead.id}/status`, { method: 'PATCH', body: { status: 'won' } })
    Object.assign(lead, updated)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not mark this lead as won.')
  }
}

function openLostDialog(lead: Lead) {
  lostLead.value = lead
  lostReason.value = ''
  lostDialog.value = true
}

async function confirmLost() {
  if (!lostLead.value)
    return
  try {
    const updated = await $api<Lead>(`/v1/crm/leads/${lostLead.value.id}/status`, { method: 'PATCH', body: { status: 'lost', lost_reason: lostReason.value } })
    Object.assign(lostLead.value, updated)
    lostDialog.value = false
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not mark this lead as lost.')
  }
}

// --- Kanban board (native HTML5 drag/drop, no library) --------------------------------------

const dragLeadId = ref<string | null>(null)

function onDragStart(lead: Lead) {
  dragLeadId.value = lead.id
}

function onDrop(stage: string) {
  if (!dragLeadId.value)
    return
  const lead = leads.value.find(l => l.id === dragLeadId.value)
  if (lead && lead.stage !== stage)
    updateStage(lead, stage)
  dragLeadId.value = null
}

function leadsInStage(stage: string) {
  return visibleLeads.value.filter(l => l.stage === stage && (!activePipelineId.value || l.pipeline_id === activePipelineId.value))
}

function stageValue(stage: string) {
  return leadsInStage(stage).reduce((sum, l) => sum + (l.value || 0), 0)
}

onMounted(loadAll)
</script>

<template>
  <div class="d-flex align-center justify-space-between flex-wrap gap-4 mb-1">
    <div>
      <h1 class="text-h4 mb-1">
        Leads
      </h1>
      <p class="text-medium-emphasis">
        Sales-pipeline records converted from WhatsApp conversations or added directly.
      </p>
    </div>
    <div class="d-flex align-center gap-3">
      <VSelect
        v-if="pipelines.length > 1"
        v-model="activePipelineId"
        :items="pipelines.map(p => ({ title: p.name, value: p.id }))"
        density="compact" hide-details variant="outlined" style="min-width: 180px;"
      />
      <VBtn variant="tonal" prepend-icon="tabler-settings" :to="{ name: 'crm-pipelines' }">
        Pipelines
      </VBtn>
      <VBtn variant="tonal" prepend-icon="tabler-chart-bar" :to="{ name: 'crm-reports' }">
        Reports
      </VBtn>
    </div>
  </div>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    Upgrade to the CRM plan to use leads, tickets, and customers.
  </VAlert>
  <VAlert v-else-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <template v-if="!crmInactive">
    <div class="d-flex align-center justify-space-between mb-4">
      <VBtnToggle v-model="view" density="compact" mandatory color="primary" variant="outlined">
        <VBtn value="board">
          Board
        </VBtn>
        <VBtn value="table">
          Table
        </VBtn>
      </VBtnToggle>
      <VCheckbox v-model="showClosed" label="Show won/lost" density="compact" hide-details />
    </div>

    <!-- Board view -->
    <div v-if="view === 'board'" class="d-flex gap-4 overflow-x-auto pb-2">
      <div
        v-for="stage in stages" :key="stage" class="flex-shrink-0"
        style="width: 280px;"
        @dragover.prevent
        @drop="onDrop(stage)"
      >
        <div class="d-flex align-center justify-space-between mb-2 px-1">
          <span class="text-subtitle-2 text-capitalize">{{ stage }}</span>
          <span class="text-caption text-medium-emphasis">{{ inr(stageValue(stage)) }}</span>
        </div>
        <div class="d-flex flex-column gap-2" style="min-height: 60px;">
          <VCard
            v-for="lead in leadsInStage(stage)" :key="lead.id" variant="outlined" draggable="true"
            :class="{ 'opacity-50': lead.status !== 'open' }"
            @dragstart="onDragStart(lead)"
          >
            <VCardText class="pa-3">
              <div class="d-flex align-center justify-space-between mb-1">
                <span class="font-weight-medium">{{ lead.contact.name || lead.contact.wa_id || lead.contact.email || 'Unknown' }}</span>
                <VChip v-if="lead.status !== 'open'" size="x-small" :color="lead.status === 'won' ? 'success' : 'error'">
                  {{ lead.status }}
                </VChip>
              </div>
              <div class="text-caption text-medium-emphasis mb-1">
                {{ inr(lead.value) }} <span v-if="lead.probability !== null">· {{ lead.probability }}%</span>
              </div>
              <div class="text-caption text-medium-emphasis mb-2">
                {{ ownerName(lead) || 'Unassigned' }}
              </div>
              <div class="d-flex gap-1">
                <VBtn size="x-small" variant="text" @click="openDealDialog(lead)">
                  Edit deal
                </VBtn>
                <VBtn v-if="lead.status === 'open'" size="x-small" variant="text" color="success" @click="markWon(lead)">
                  Won
                </VBtn>
                <VBtn v-if="lead.status === 'open'" size="x-small" variant="text" color="error" @click="openLostDialog(lead)">
                  Lost
                </VBtn>
              </div>
            </VCardText>
          </VCard>
          <p v-if="!leadsInStage(stage).length" class="text-caption text-medium-emphasis text-center pa-2">
            No leads
          </p>
        </div>
      </div>
    </div>

    <!-- Table view -->
    <VCard v-else>
      <VTable>
        <thead>
          <tr>
            <th>Contact</th>
            <th>Stage</th>
            <th>Value</th>
            <th>Probability</th>
            <th>Close date</th>
            <th>Status</th>
            <th>Owner</th>
            <th>Created</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="lead in visibleLeads" :key="lead.id">
            <td>
              {{ lead.contact.name || lead.contact.wa_id || lead.contact.email || 'Unknown' }}
            </td>
            <td>
              <VSelect
                :model-value="lead.stage"
                :items="pipelines.find(p => p.id === lead.pipeline_id)?.stages || stages"
                density="compact" hide-details variant="plain" style="max-width: 160px;"
                @update:model-value="(stage: string) => updateStage(lead, stage)"
              />
            </td>
            <td>{{ inr(lead.value) }}</td>
            <td>{{ lead.probability !== null ? `${lead.probability}%` : '—' }}</td>
            <td>{{ lead.expected_close_date ? new Date(lead.expected_close_date).toLocaleDateString() : '—' }}</td>
            <td>
              <VChip size="small" :color="lead.status === 'won' ? 'success' : lead.status === 'lost' ? 'error' : undefined">
                {{ lead.status }}
              </VChip>
            </td>
            <td>
              <VSelect
                :model-value="lead.owner_user_id"
                :items="users.map(u => ({ title: u.full_name, value: u.id }))"
                placeholder="Unassigned" density="compact" hide-details variant="plain" clearable
                style="max-width: 180px;"
                @update:model-value="(ownerUserId: string | null) => updateOwner(lead, ownerUserId)"
              />
            </td>
            <td>{{ new Date(lead.created_at).toLocaleDateString() }}</td>
            <td>
              <div class="d-flex gap-1">
                <VBtn size="small" variant="text" @click="openDealDialog(lead)">
                  Deal
                </VBtn>
                <VBtn v-if="lead.status === 'open'" size="small" variant="tonal" :loading="converting === lead.id" @click="convertToCustomer(lead)">
                  Convert
                </VBtn>
              </div>
            </td>
          </tr>
        </tbody>
      </VTable>
      <p v-if="!loading && !visibleLeads.length" class="text-medium-emphasis text-center pa-6">
        No leads yet. Convert a WhatsApp conversation to a lead from the inbox.
      </p>
    </VCard>
  </template>

  <VDialog v-model="dealDialog" max-width="420">
    <VCard title="Edit deal">
      <VCardText class="d-flex flex-column gap-4">
        <VTextField v-model.number="dealForm.value" label="Deal value (INR)" type="number" min="0" density="compact" />
        <VTextField v-model.number="dealForm.probability" label="Probability (%)" type="number" min="0" max="100" density="compact" />
        <VTextField v-model="dealForm.expected_close_date" label="Expected close date" type="date" density="compact" />
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

  <VDialog v-model="lostDialog" max-width="420">
    <VCard title="Mark as lost">
      <VCardText>
        <VTextField v-model="lostReason" label="Reason (optional)" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="lostDialog = false">
          Cancel
        </VBtn>
        <VBtn color="error" @click="confirmLost">
          Mark lost
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
