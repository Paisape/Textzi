<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

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
  created_at: string
}
type AssignableUser = { id: string, full_name: string, email: string }
type PipelineStage = { name: string, probability: number, forecast_category: string }
type Pipeline = { id: string, name: string, stages: PipelineStage[] }
type CustomField = { id: string, name: string, field_type: 'text' | 'number' | 'date' | 'dropdown', options: string[], required: boolean }
type SavedView = { id: string, applies_to: string, name: string, filters: Record<string, any> }

const pipelines = ref<Pipeline[]>([])
const activePipelineId = ref<string | null>(null)
const deals = ref<Deal[]>([])
const users = ref<AssignableUser[]>([])
const customFields = ref<CustomField[]>([])
const savedViews = ref<SavedView[]>([])
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)
const view = ref<'table' | 'board'>('board')
const showClosed = ref(false)

const activePipeline = computed(() => pipelines.value.find(p => p.id === activePipelineId.value) || null)
const stages = computed(() => activePipeline.value?.stages.map(s => s.name) || [])

const visibleDeals = computed(() => deals.value.filter(d => showClosed.value || d.status === 'open'))

function inr(value: number | null) {
  if (value === null)
    return '—'
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value)
}

function initial(deal: Deal) {
  return (deal.contact.name || deal.contact.phone || deal.contact.email || '?').slice(0, 1).toUpperCase()
}

function dealLabel(deal: Deal) {
  return deal.name || deal.contact.name || deal.contact.phone || deal.contact.email || 'Unknown'
}

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    const [dealResult, userResult, pipelineResult, fieldResult, viewResult] = await Promise.all([
      $api<Deal[]>('/v1/crm/deals'),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
      $api<Pipeline[]>('/v1/crm/pipelines'),
      $api<CustomField[]>('/v1/crm/custom-fields?applies_to=deal'),
      $api<SavedView[]>('/v1/crm/saved-views?applies_to=deal'),
    ])
    deals.value = dealResult
    users.value = userResult
    pipelines.value = pipelineResult
    customFields.value = fieldResult
    savedViews.value = viewResult
    if (!activePipelineId.value)
      activePipelineId.value = pipelineResult[0]?.id || null
  }
  catch (error: any) {
    if (error?.response?.status === 422)
      crmInactive.value = true
    else
      loadError.value = extractErrorMessage(error, 'Could not load deals.')
  }
  finally {
    loading.value = false
  }
}

function ownerName(deal: Deal) {
  return users.value.find(u => u.id === deal.owner_user_id)?.full_name || null
}

async function updateStage(deal: Deal, stage: string) {
  try {
    const updated = await $api<Deal>(`/v1/crm/deals/${deal.id}/stage`, { method: 'PATCH', body: { stage } })
    deal.stage = updated.stage
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this deal\'s stage.')
  }
}

async function updateOwner(deal: Deal, ownerUserId: string | null) {
  try {
    const updated = await $api<Deal>(`/v1/crm/deals/${deal.id}/owner`, { method: 'PATCH', body: { owner_user_id: ownerUserId } })
    deal.owner_user_id = updated.owner_user_id
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not reassign this deal.')
  }
}

const converting = ref<string | null>(null)

async function convertToCustomer(deal: Deal) {
  converting.value = deal.id
  try {
    await $api(`/v1/crm/deals/${deal.id}/convert-to-customer`, { method: 'POST' })
    deals.value = deals.value.filter(d => d.id !== deal.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not convert this deal to a customer.')
  }
  finally {
    converting.value = null
  }
}

// --- Deal financial fields dialog ---------------------------------------------------------------

const dealDialog = ref(false)
const editingDeal = ref<Deal | null>(null)
const dealForm = reactive({ value: null as number | null, probability: null as number | null, expected_close_date: '', custom_fields: {} as Record<string, any> })
const dealSaving = ref(false)

function openDealDialog(deal: Deal) {
  editingDeal.value = deal
  dealForm.value = deal.value
  dealForm.probability = deal.probability
  dealForm.expected_close_date = deal.expected_close_date ? deal.expected_close_date.slice(0, 10) : ''
  dealForm.custom_fields = { ...deal.custom_fields }
  dealDialog.value = true
}

async function saveDeal() {
  if (!editingDeal.value)
    return
  dealSaving.value = true
  try {
    const updated = await $api<Deal>(`/v1/crm/deals/${editingDeal.value.id}`, {
      method: 'PATCH',
      body: {
        value: dealForm.value,
        probability: dealForm.probability,
        expected_close_date: dealForm.expected_close_date || null,
        custom_fields: dealForm.custom_fields,
      },
    })
    Object.assign(editingDeal.value, updated)
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
const lostDeal = ref<Deal | null>(null)
const lostReason = ref('')

async function markWon(deal: Deal) {
  try {
    const updated = await $api<Deal>(`/v1/crm/deals/${deal.id}/status`, { method: 'PATCH', body: { status: 'won' } })
    Object.assign(deal, updated)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not mark this deal as won.')
  }
}

function openLostDialog(deal: Deal) {
  lostDeal.value = deal
  lostReason.value = ''
  lostDialog.value = true
}

async function confirmLost() {
  if (!lostDeal.value)
    return
  try {
    const updated = await $api<Deal>(`/v1/crm/deals/${lostDeal.value.id}/status`, { method: 'PATCH', body: { status: 'lost', lost_reason: lostReason.value } })
    Object.assign(lostDeal.value, updated)
    lostDialog.value = false
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not mark this deal as lost.')
  }
}

// --- Kanban board (native HTML5 drag/drop, no library) --------------------------------------

const dragDealId = ref<string | null>(null)

function onDragStart(deal: Deal) {
  dragDealId.value = deal.id
}

function onDrop(stage: string) {
  if (!dragDealId.value)
    return
  const deal = deals.value.find(d => d.id === dragDealId.value)
  if (deal && deal.stage !== stage)
    updateStage(deal, stage)
  dragDealId.value = null
}

function dealsInStage(stage: string) {
  return visibleDeals.value.filter(d => d.stage === stage && (!activePipelineId.value || d.pipeline_id === activePipelineId.value))
}

function stageValue(stage: string) {
  return dealsInStage(stage).reduce((sum, d) => sum + (d.value || 0), 0)
}

// --- New deal --------------------------------------------------------------------------------

const newDialog = ref(false)
const newForm = reactive({ name: '', dealName: '', phone: '', email: '', title: '', pipeline_id: null as string | null, stage: 'inquiry', value: null as number | null, probability: null as number | null, owner_user_id: null as string | null, custom_fields: {} as Record<string, any> })
const newSaving = ref(false)
const newError = ref('')

function openNewDialog() {
  const defaultPipeline = pipelines.value[0] || null
  newForm.name = ''
  newForm.dealName = ''
  newForm.phone = ''
  newForm.email = ''
  newForm.title = ''
  newForm.pipeline_id = defaultPipeline?.id || null
  newForm.stage = defaultPipeline?.stages[0]?.name || 'inquiry'
  newForm.value = null
  newForm.probability = defaultPipeline?.stages[0]?.probability ?? null
  newForm.owner_user_id = null
  newForm.custom_fields = {}
  newError.value = ''
  newDialog.value = true
}

async function createDeal() {
  if (!newForm.name.trim())
    return
  newSaving.value = true
  newError.value = ''
  try {
    const created = await $api<Deal>('/v1/crm/deals', {
      method: 'POST',
      body: {
        name: newForm.name.trim(),
        deal_name: newForm.dealName.trim() || null,
        phone: newForm.phone.trim() || null,
        email: newForm.email.trim() || null,
        title: newForm.title.trim() || null,
        pipeline_id: newForm.pipeline_id,
        stage: newForm.stage,
        value: newForm.value,
        probability: newForm.probability,
        owner_user_id: newForm.owner_user_id,
        custom_fields: newForm.custom_fields,
      },
    })
    deals.value.unshift(created)
    newDialog.value = false
  }
  catch (error: any) {
    newError.value = extractErrorMessage(error, 'Could not create this deal.')
  }
  finally {
    newSaving.value = false
  }
}

// --- Bulk actions (table view only) -----------------------------------------------------------

const selected = ref<string[]>([])
const bulkOwnerUserId = ref<string | null>(null)
const bulkBusy = ref(false)

function clearSelection() {
  selected.value = []
}

async function bulkReassign() {
  bulkBusy.value = true
  try {
    const updated = await $api<Deal[]>('/v1/crm/deals/bulk-owner', { method: 'POST', body: { deal_ids: selected.value, owner_user_id: bulkOwnerUserId.value } })
    for (const deal of updated) {
      const existing = deals.value.find(d => d.id === deal.id)
      if (existing)
        Object.assign(existing, deal)
    }
    clearSelection()
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not reassign the selected deals.')
  }
  finally {
    bulkBusy.value = false
  }
}

async function bulkDelete() {
  bulkBusy.value = true
  try {
    await $api('/v1/crm/deals/bulk-delete', { method: 'POST', body: { deal_ids: selected.value } })
    deals.value = deals.value.filter(d => !selected.value.includes(d.id))
    clearSelection()
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete the selected deals -- deals with quotes must have those deleted first.')
  }
  finally {
    bulkBusy.value = false
  }
}

function exportCsv() {
  const rows = [['Contact', 'Stage', 'Value', 'Probability', 'Status', 'Created']]
  for (const deal of visibleDeals.value)
    rows.push([deal.contact.name || '', deal.stage, String(deal.value ?? ''), String(deal.probability ?? ''), deal.status, deal.created_at])
  const csv = rows.map(row => row.map(cell => `"${cell.replace(/"/g, '""')}"`).join(',')).join('\n')
  const link = document.createElement('a')
  link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
  link.download = 'deals.csv'
  link.click()
  URL.revokeObjectURL(link.href)
}

// --- Saved views -------------------------------------------------------------------------------

const saveViewDialog = ref(false)
const saveViewName = ref('')

async function saveCurrentView() {
  if (!saveViewName.value.trim())
    return
  try {
    const created = await $api<SavedView>('/v1/crm/saved-views', { method: 'POST', body: { applies_to: 'deal', name: saveViewName.value.trim(), filters: { showClosed: showClosed.value } } })
    savedViews.value.push(created)
    saveViewDialog.value = false
    saveViewName.value = ''
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not save this view.')
  }
}

function applyView(savedView: SavedView) {
  showClosed.value = Boolean(savedView.filters.showClosed)
}

async function deleteView(savedView: SavedView) {
  try {
    await $api(`/v1/crm/saved-views/${savedView.id}`, { method: 'DELETE' })
    savedViews.value = savedViews.value.filter(v => v.id !== savedView.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this view.')
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="d-flex align-center justify-space-between flex-wrap gap-4 mb-1">
    <div>
      <h1 class="text-h4 mb-1">
        Deals
      </h1>
      <p class="text-medium-emphasis">
        Qualified opportunities, converted from leads or added directly.
      </p>
    </div>
    <div class="d-flex align-center gap-3">
      <VSelect
        v-if="pipelines.length > 1"
        v-model="activePipelineId"
        :items="pipelines.map(p => ({ title: p.name, value: p.id }))"
        density="compact" hide-details variant="outlined" style="min-width: 180px;"
      />
      <VBtn color="primary" prepend-icon="tabler-plus" @click="openNewDialog">
        New deal
      </VBtn>
      <VBtn variant="tonal" prepend-icon="tabler-target-arrow" :to="{ name: 'crm-leads' }">
        Leads
      </VBtn>
      <VBtn variant="tonal" prepend-icon="tabler-settings" :to="{ name: 'crm-pipelines' }">
        Pipelines
      </VBtn>
      <VBtn variant="tonal" prepend-icon="tabler-chart-bar" :to="{ name: 'crm-reports' }">
        Reports
      </VBtn>
    </div>
  </div>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    Upgrade to the CRM plan to use leads, deals, and customers.
  </VAlert>
  <VAlert v-else-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <template v-if="!crmInactive">
    <div class="d-flex align-center justify-space-between flex-wrap gap-3 mb-4">
      <div class="d-flex align-center gap-3">
        <VBtnToggle v-model="view" density="compact" mandatory color="primary" variant="outlined">
          <VBtn value="board">
            Board
          </VBtn>
          <VBtn value="table">
            Table
          </VBtn>
        </VBtnToggle>
        <VMenu v-if="savedViews.length">
          <template #activator="{ props: menuProps }">
            <VBtn variant="tonal" size="small" prepend-icon="tabler-bookmark" v-bind="menuProps">
              Views
            </VBtn>
          </template>
          <VList density="compact">
            <VListItem v-for="savedView in savedViews" :key="savedView.id" @click="applyView(savedView)">
              <VListItemTitle>{{ savedView.name }}</VListItemTitle>
              <template #append>
                <VBtn icon="tabler-x" variant="text" size="x-small" @click.stop="deleteView(savedView)" />
              </template>
            </VListItem>
          </VList>
        </VMenu>
        <VBtn variant="text" size="small" prepend-icon="tabler-bookmark-plus" @click="saveViewDialog = true">
          Save view
        </VBtn>
        <VBtn variant="text" size="small" prepend-icon="tabler-download" @click="exportCsv">
          Export CSV
        </VBtn>
      </div>
      <VCheckbox v-model="showClosed" label="Show won/lost" density="compact" hide-details />
    </div>

    <!-- Board view -->
    <div v-if="view === 'board'" class="d-flex gap-4 overflow-x-auto pb-2">
      <div
        v-for="stage in stages" :key="stage" class="flex-shrink-0 rounded-lg pa-2"
        style="width: 280px; background: rgba(var(--v-theme-on-surface), 0.03);"
        @dragover.prevent
        @drop="onDrop(stage)"
      >
        <div class="d-flex align-center justify-space-between mb-2 px-1">
          <span class="text-subtitle-2">{{ formatLabel(stage) }}</span>
          <span class="text-caption text-medium-emphasis">{{ inr(stageValue(stage)) }}</span>
        </div>
        <div class="d-flex flex-column gap-2" style="min-height: 80px;">
          <VCard
            v-for="deal in dealsInStage(stage)" :key="deal.id" variant="flat" draggable="true"
            :class="{ 'opacity-50': deal.status !== 'open' }"
            @dragstart="onDragStart(deal)"
          >
            <VCardText class="pa-3">
              <div class="d-flex align-center gap-2 mb-1">
                <VAvatar color="primary" variant="tonal" size="24">
                  <span class="text-caption">{{ initial(deal) }}</span>
                </VAvatar>
                <RouterLink :to="`/crm-deals/${deal.id}`" class="font-weight-medium flex-grow-1 text-truncate">
                  {{ dealLabel(deal) }}
                </RouterLink>
                <VChip v-if="deal.status !== 'open'" size="x-small" :color="deal.status === 'won' ? 'success' : 'error'">
                  {{ deal.status }}
                </VChip>
              </div>
              <div class="text-caption text-medium-emphasis mb-1">
                {{ inr(deal.value) }} <span v-if="deal.probability !== null">· {{ deal.probability }}%</span>
              </div>
              <div class="text-caption text-medium-emphasis mb-2">
                {{ ownerName(deal) || 'Unassigned' }}
              </div>
              <div class="d-flex gap-1">
                <VBtn size="x-small" variant="text" @click="openDealDialog(deal)">
                  Edit deal
                </VBtn>
                <VBtn v-if="deal.status === 'open'" size="x-small" variant="text" color="success" @click="markWon(deal)">
                  Won
                </VBtn>
                <VBtn v-if="deal.status === 'open'" size="x-small" variant="text" color="error" @click="openLostDialog(deal)">
                  Lost
                </VBtn>
              </div>
            </VCardText>
          </VCard>
          <p v-if="!dealsInStage(stage).length" class="text-caption text-medium-emphasis text-center pa-2 mb-0">
            No deals
          </p>
        </div>
      </div>
    </div>

    <!-- Table view -->
    <template v-else>
      <VCard v-if="selected.length" color="primary" variant="tonal" class="mb-4">
        <VCardText class="d-flex align-center flex-wrap gap-3">
          <span class="font-weight-medium">{{ selected.length }} selected</span>
          <VSelect
            v-model="bulkOwnerUserId" placeholder="Reassign owner to..." density="compact" hide-details clearable
            :items="users.map(u => ({ title: u.full_name, value: u.id }))" style="max-width: 220px;"
          />
          <VBtn size="small" variant="tonal" :loading="bulkBusy" :disabled="!bulkOwnerUserId" @click="bulkReassign">
            Reassign
          </VBtn>
          <VBtn size="small" variant="tonal" color="error" :loading="bulkBusy" @click="bulkDelete">
            Delete
          </VBtn>
          <VSpacer />
          <VBtn size="small" variant="text" @click="clearSelection">
            Clear
          </VBtn>
        </VCardText>
      </VCard>

      <VCard>
        <VTable>
          <thead>
            <tr>
              <th style="width: 40px;">
                <VCheckbox
                  :model-value="selected.length > 0 && selected.length === visibleDeals.length"
                  :indeterminate="selected.length > 0 && selected.length < visibleDeals.length"
                  density="compact" hide-details
                  @update:model-value="(v: boolean | null) => selected = v ? visibleDeals.map(d => d.id) : []"
                />
              </th>
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
            <tr v-for="deal in visibleDeals" :key="deal.id">
              <td>
                <VCheckbox v-model="selected" :value="deal.id" density="compact" hide-details />
              </td>
              <td>
                <div class="d-flex align-center gap-3">
                  <VAvatar color="primary" variant="tonal" size="32">
                    <span class="text-caption">{{ initial(deal) }}</span>
                  </VAvatar>
                  <RouterLink :to="`/crm-deals/${deal.id}`" class="font-weight-medium">
                    {{ dealLabel(deal) }}
                  </RouterLink>
                </div>
              </td>
              <td>
                <VSelect
                  :model-value="deal.stage"
                  :items="(pipelines.find(p => p.id === deal.pipeline_id)?.stages || activePipeline?.stages || []).map(s => ({ title: formatLabel(s.name), value: s.name }))"
                  density="compact" hide-details variant="plain" style="max-width: 160px;"
                  @update:model-value="(stage: string) => updateStage(deal, stage)"
                />
              </td>
              <td>{{ inr(deal.value) }}</td>
              <td>{{ deal.probability !== null ? `${deal.probability}%` : '—' }}</td>
              <td>{{ deal.expected_close_date ? new Date(deal.expected_close_date).toLocaleDateString() : '—' }}</td>
              <td>
                <VChip size="small" :color="deal.status === 'won' ? 'success' : deal.status === 'lost' ? 'error' : undefined">
                  {{ deal.status }}
                </VChip>
              </td>
              <td>
                <VSelect
                  :model-value="deal.owner_user_id"
                  :items="users.map(u => ({ title: u.full_name, value: u.id }))"
                  placeholder="Unassigned" density="compact" hide-details variant="plain" clearable
                  style="max-width: 180px;"
                  @update:model-value="(ownerUserId: string | null) => updateOwner(deal, ownerUserId)"
                />
              </td>
              <td>{{ new Date(deal.created_at).toLocaleDateString() }}</td>
              <td>
                <div class="d-flex gap-1">
                  <VBtn size="small" variant="text" @click="openDealDialog(deal)">
                    Deal
                  </VBtn>
                  <VBtn v-if="deal.status === 'open'" size="small" variant="tonal" :loading="converting === deal.id" @click="convertToCustomer(deal)">
                    Convert
                  </VBtn>
                </div>
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!loading && !visibleDeals.length" class="text-medium-emphasis text-center pa-6">
          No deals yet. Convert a lead, or start one directly from the inbox.
        </p>
      </VCard>
    </template>
  </template>

  <VDialog v-model="dealDialog" max-width="420" persistent>
    <VCard title="Edit deal">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="dealDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VTextField v-model.number="dealForm.value" label="Deal value (INR)" type="number" min="0" density="compact" />
        <VTextField v-model.number="dealForm.probability" label="Probability (%)" type="number" min="0" max="100" density="compact" />
        <VTextField v-model="dealForm.expected_close_date" label="Expected close date" type="date" density="compact" />
        <template v-for="field in customFields" :key="field.id">
          <VSelect
            v-if="field.field_type === 'dropdown'"
            :model-value="dealForm.custom_fields[field.name]" :label="field.name" :items="field.options" density="compact" clearable
            @update:model-value="(v: string) => dealForm.custom_fields[field.name] = v"
          />
          <VTextField
            v-else
            :model-value="dealForm.custom_fields[field.name]" :label="field.name"
            :type="field.field_type === 'number' ? 'number' : field.field_type === 'date' ? 'date' : 'text'" density="compact"
            @update:model-value="(v: string) => dealForm.custom_fields[field.name] = v"
          />
        </template>
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
        <VBtn variant="text" @click="lostDialog = false">
          Cancel
        </VBtn>
        <VBtn color="error" @click="confirmLost">
          Mark lost
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="newDialog" max-width="420" persistent>
    <VCard title="New deal">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="newDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="newError" type="error" variant="tonal" density="compact">
          {{ newError }}
        </VAlert>
        <VTextField v-model="newForm.name" label="Contact name" density="compact" autofocus />
        <VTextField v-model="newForm.dealName" label="Deal name (optional -- defaults to contact name)" density="compact" />
        <VTextField v-model="newForm.title" label="Title / designation" density="compact" />
        <VTextField v-model="newForm.phone" label="Phone / WhatsApp number" density="compact" />
        <VTextField v-model="newForm.email" label="Email" density="compact" />
        <VSelect
          v-model="newForm.pipeline_id"
          :items="pipelines.map(p => ({ title: p.name, value: p.id }))"
          label="Pipeline" density="compact"
        />
        <VSelect
          v-model="newForm.stage"
          :items="(pipelines.find(p => p.id === newForm.pipeline_id)?.stages || []).map(s => ({ title: formatLabel(s.name), value: s.name }))"
          label="Stage" density="compact"
        />
        <VTextField v-model.number="newForm.value" label="Deal value (INR)" type="number" min="0" density="compact" />
        <VTextField v-model.number="newForm.probability" label="Probability (%)" type="number" min="0" max="100" density="compact" />
        <VSelect
          v-model="newForm.owner_user_id" label="Deal owner" density="compact" clearable
          :items="users.map(u => ({ title: u.full_name, value: u.id }))"
        />
        <template v-for="field in customFields" :key="field.id">
          <VSelect
            v-if="field.field_type === 'dropdown'"
            :model-value="newForm.custom_fields[field.name]" :label="field.name" :items="field.options" density="compact" clearable
            @update:model-value="(v: string) => newForm.custom_fields[field.name] = v"
          />
          <VTextField
            v-else
            :model-value="newForm.custom_fields[field.name]" :label="field.name"
            :type="field.field_type === 'number' ? 'number' : field.field_type === 'date' ? 'date' : 'text'" density="compact"
            @update:model-value="(v: string) => newForm.custom_fields[field.name] = v"
          />
        </template>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="newDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="newSaving" :disabled="!newForm.name.trim()" @click="createDeal">
          Create
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="saveViewDialog" max-width="360" persistent>
    <VCard title="Save current view">
      <VCardText>
        <VTextField v-model="saveViewName" label="View name" density="compact" autofocus @keyup.enter="saveCurrentView" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="saveViewDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :disabled="!saveViewName.trim()" @click="saveCurrentView">
          Save
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
