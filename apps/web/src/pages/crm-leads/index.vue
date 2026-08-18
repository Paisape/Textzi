<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

type CrmContact = { id: string, name: string | null, phone: string | null, email: string | null, title: string | null, company_id: string | null }
type Lead = {
  id: string
  contact: CrmContact
  company_name: string | null
  source: string
  status: 'new' | 'contacted' | 'qualified' | 'unqualified' | 'converted'
  owner_user_id: string | null
  notes: string | null
  custom_fields: Record<string, any>
  score: number
  converted_at: string | null
  converted_deal_id: string | null
  created_at: string
}
type AssignableUser = { id: string, full_name: string, email: string }
type PipelineStage = { name: string, probability: number, forecast_category: string }
type Pipeline = { id: string, name: string, stages: PipelineStage[] }
type CustomField = { id: string, name: string, field_type: 'text' | 'number' | 'date' | 'dropdown', options: string[], required: boolean }
type SavedView = { id: string, applies_to: string, name: string, filters: Record<string, any> }

const leads = ref<Lead[]>([])
const users = ref<AssignableUser[]>([])
const pipelines = ref<Pipeline[]>([])
const customFields = ref<CustomField[]>([])
const savedViews = ref<SavedView[]>([])
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)
const showConverted = ref(false)

const visibleLeads = computed(() => leads.value.filter(l => showConverted.value || l.status !== 'converted'))

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    const [leadResult, userResult, pipelineResult, fieldResult, viewResult] = await Promise.all([
      $api<Lead[]>('/v1/crm/leads'),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
      $api<Pipeline[]>('/v1/crm/pipelines'),
      $api<CustomField[]>('/v1/crm/custom-fields?applies_to=lead'),
      $api<SavedView[]>('/v1/crm/saved-views?applies_to=lead'),
    ])
    leads.value = leadResult
    users.value = userResult
    pipelines.value = pipelineResult
    customFields.value = fieldResult
    savedViews.value = viewResult
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

function initial(lead: Lead) {
  return (lead.contact.name || lead.contact.phone || lead.contact.email || '?').slice(0, 1).toUpperCase()
}

async function updateStatus(lead: Lead, status: string) {
  try {
    const updated = await $api<Lead>(`/v1/crm/leads/${lead.id}`, { method: 'PATCH', body: { status } })
    Object.assign(lead, updated)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this lead\'s status.')
  }
}

async function updateOwner(lead: Lead, ownerUserId: string | null) {
  try {
    const updated = await $api<Lead>(`/v1/crm/leads/${lead.id}`, { method: 'PATCH', body: { owner_user_id: ownerUserId } })
    Object.assign(lead, updated)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not reassign this lead.')
  }
}

// --- Convert to deal -----------------------------------------------------------------------

const router = useRouter()
const convertDialog = ref(false)
const convertingLead = ref<Lead | null>(null)
const convertForm = reactive({ deal_name: '', pipeline_id: null as string | null, stage: 'inquiry', value: null as number | null, probability: null as number | null, expected_close_date: '' })
const converting = ref(false)

function openConvertDialog(lead: Lead) {
  convertingLead.value = lead
  const defaultPipeline = pipelines.value[0] || null
  convertForm.deal_name = ''
  convertForm.pipeline_id = defaultPipeline?.id || null
  convertForm.stage = defaultPipeline?.stages[0]?.name || 'inquiry'
  convertForm.value = null
  convertForm.probability = defaultPipeline?.stages[0]?.probability ?? null
  convertForm.expected_close_date = ''
  convertDialog.value = true
}

async function confirmConvert() {
  if (!convertingLead.value)
    return
  converting.value = true
  try {
    const deal = await $api<{ id: string }>(`/v1/crm/leads/${convertingLead.value.id}/convert`, {
      method: 'POST',
      body: {
        deal_name: convertForm.deal_name.trim() || null,
        pipeline_id: convertForm.pipeline_id,
        stage: convertForm.stage,
        value: convertForm.value,
        probability: convertForm.probability,
        expected_close_date: convertForm.expected_close_date || null,
      },
    })
    convertDialog.value = false
    await loadAll()
    router.push(`/crm-deals/${deal.id}`)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not convert this lead to a deal.')
  }
  finally {
    converting.value = false
  }
}

// --- New lead --------------------------------------------------------------------------------

const LEAD_SOURCES = ['manual', 'whatsapp_conversation', 'web_form', 'csv_import']

const newDialog = ref(false)
const newForm = reactive({ name: '', phone: '', email: '', title: '', company_name: '', source: 'manual', owner_user_id: null as string | null, notes: '', custom_fields: {} as Record<string, any> })
const newSaving = ref(false)
const newError = ref('')

function openNewDialog() {
  newForm.name = ''
  newForm.phone = ''
  newForm.email = ''
  newForm.title = ''
  newForm.company_name = ''
  newForm.source = 'manual'
  newForm.owner_user_id = null
  newForm.notes = ''
  newForm.custom_fields = {}
  newError.value = ''
  newDialog.value = true
}

async function createLead() {
  if (!newForm.name.trim())
    return
  newSaving.value = true
  newError.value = ''
  try {
    const created = await $api<Lead>('/v1/crm/leads', {
      method: 'POST',
      body: {
        name: newForm.name.trim(),
        phone: newForm.phone.trim() || null,
        email: newForm.email.trim() || null,
        title: newForm.title.trim() || null,
        company_name: newForm.company_name.trim() || null,
        source: newForm.source,
        owner_user_id: newForm.owner_user_id,
        notes: newForm.notes.trim() || null,
        custom_fields: newForm.custom_fields,
      },
    })
    leads.value.unshift(created)
    newDialog.value = false
  }
  catch (error: any) {
    newError.value = extractErrorMessage(error, 'Could not create this lead.')
  }
  finally {
    newSaving.value = false
  }
}

// --- CSV import ------------------------------------------------------------------------------

const importDialog = ref(false)
const importFile = ref<File | null>(null)
const importing = ref(false)
const importResult = ref<{ created: number, skipped: number, errors: string[] } | null>(null)
const importError = ref('')

function openImportDialog() {
  importFile.value = null
  importResult.value = null
  importError.value = ''
  importDialog.value = true
}

async function runImport() {
  if (!importFile.value)
    return
  importing.value = true
  importError.value = ''
  try {
    const formData = new FormData()
    formData.append('file', importFile.value)
    importResult.value = await $api('/v1/crm/leads/import', { method: 'POST', body: formData })
    await loadAll()
  }
  catch (error: any) {
    importError.value = extractErrorMessage(error, 'Could not import this file.')
  }
  finally {
    importing.value = false
  }
}

// --- Bulk actions ----------------------------------------------------------------------------

const selected = ref<string[]>([])
const bulkOwnerUserId = ref<string | null>(null)
const bulkBusy = ref(false)

function clearSelection() {
  selected.value = []
}

async function bulkReassign() {
  bulkBusy.value = true
  try {
    const updated = await $api<Lead[]>('/v1/crm/leads/bulk-owner', { method: 'POST', body: { lead_ids: selected.value, owner_user_id: bulkOwnerUserId.value } })
    for (const lead of updated) {
      const existing = leads.value.find(l => l.id === lead.id)
      if (existing)
        Object.assign(existing, lead)
    }
    clearSelection()
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not reassign the selected leads.')
  }
  finally {
    bulkBusy.value = false
  }
}

async function bulkDelete() {
  bulkBusy.value = true
  try {
    await $api('/v1/crm/leads/bulk-delete', { method: 'POST', body: { lead_ids: selected.value } })
    leads.value = leads.value.filter(l => !selected.value.includes(l.id))
    clearSelection()
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete the selected leads.')
  }
  finally {
    bulkBusy.value = false
  }
}

function exportCsv() {
  const rows = [['Name', 'Phone', 'Email', 'Company', 'Source', 'Status', 'Score', 'Created']]
  for (const lead of visibleLeads.value)
    rows.push([lead.contact.name || '', lead.contact.phone || '', lead.contact.email || '', lead.company_name || '', lead.source, lead.status, String(lead.score), lead.created_at])
  const csv = rows.map(row => row.map(cell => `"${cell.replace(/"/g, '""')}"`).join(',')).join('\n')
  const link = document.createElement('a')
  link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
  link.download = 'leads.csv'
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
    const created = await $api<SavedView>('/v1/crm/saved-views', { method: 'POST', body: { applies_to: 'lead', name: saveViewName.value.trim(), filters: { showConverted: showConverted.value } } })
    savedViews.value.push(created)
    saveViewDialog.value = false
    saveViewName.value = ''
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not save this view.')
  }
}

function applyView(view: SavedView) {
  showConverted.value = Boolean(view.filters.showConverted)
}

async function deleteView(view: SavedView) {
  try {
    await $api(`/v1/crm/saved-views/${view.id}`, { method: 'DELETE' })
    savedViews.value = savedViews.value.filter(v => v.id !== view.id)
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
        Leads
      </h1>
      <p class="text-medium-emphasis">
        Unqualified, top-of-funnel contacts -- convert to a deal once qualified.
      </p>
    </div>
    <div class="d-flex align-center gap-3">
      <VBtn variant="tonal" prepend-icon="tabler-upload" @click="openImportDialog">
        Import CSV
      </VBtn>
      <VBtn color="primary" prepend-icon="tabler-plus" @click="openNewDialog">
        New lead
      </VBtn>
      <VBtn variant="tonal" prepend-icon="tabler-briefcase" :to="{ name: 'crm-deals' }">
        Deals
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
        <VMenu v-if="savedViews.length">
          <template #activator="{ props: menuProps }">
            <VBtn variant="tonal" size="small" prepend-icon="tabler-bookmark" v-bind="menuProps">
              Views
            </VBtn>
          </template>
          <VList density="compact">
            <VListItem v-for="view in savedViews" :key="view.id" @click="applyView(view)">
              <VListItemTitle>{{ view.name }}</VListItemTitle>
              <template #append>
                <VBtn icon="tabler-x" variant="text" size="x-small" @click.stop="deleteView(view)" />
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
      <VCheckbox v-model="showConverted" label="Show converted" density="compact" hide-details />
    </div>

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
                :model-value="selected.length > 0 && selected.length === visibleLeads.length"
                :indeterminate="selected.length > 0 && selected.length < visibleLeads.length"
                density="compact" hide-details
                @update:model-value="(v: boolean | null) => selected = v ? visibleLeads.map(l => l.id) : []"
              />
            </th>
            <th>Contact</th>
            <th>Company</th>
            <th>Source</th>
            <th>Status</th>
            <th>Score</th>
            <th>Owner</th>
            <th>Created</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="lead in visibleLeads" :key="lead.id">
            <td>
              <VCheckbox v-model="selected" :value="lead.id" density="compact" hide-details />
            </td>
            <td>
              <div class="d-flex align-center gap-3">
                <VAvatar color="primary" variant="tonal" size="32">
                  <span class="text-caption">{{ initial(lead) }}</span>
                </VAvatar>
                <RouterLink :to="`/crm-leads/${lead.id}`" class="font-weight-medium">
                  {{ lead.contact.name || lead.contact.phone || lead.contact.email || 'Unknown' }}
                </RouterLink>
              </div>
            </td>
            <td>{{ lead.company_name || '—' }}</td>
            <td>
              {{ formatLabel(lead.source) }}
            </td>
            <td>
              <VSelect
                v-if="lead.status !== 'converted'"
                :model-value="lead.status"
                :items="['new', 'contacted', 'qualified', 'unqualified']"
                density="compact" hide-details variant="plain" style="max-width: 140px;"
                @update:model-value="(status: string) => updateStatus(lead, status)"
              />
              <VChip v-else size="small" color="primary">
                converted
              </VChip>
            </td>
            <td>{{ lead.score }}</td>
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
              <VBtn v-if="lead.status !== 'converted'" size="small" variant="tonal" color="primary" @click="openConvertDialog(lead)">
                Convert to deal
              </VBtn>
              <VBtn v-else size="small" variant="text" :to="`/crm-deals/${lead.converted_deal_id}`">
                View deal
              </VBtn>
            </td>
          </tr>
        </tbody>
      </VTable>
      <p v-if="!loading && !visibleLeads.length" class="text-medium-emphasis text-center pa-6">
        No leads yet. Convert a WhatsApp conversation to a lead from the inbox.
      </p>
    </VCard>
  </template>

  <VDialog v-model="convertDialog" max-width="420" persistent>
    <VCard title="Convert to deal">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="convertDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VTextField v-model="convertForm.deal_name" label="Deal name (optional -- defaults to contact name)" density="compact" />
        <VSelect
          v-model="convertForm.pipeline_id"
          :items="pipelines.map(p => ({ title: p.name, value: p.id }))"
          label="Pipeline" density="compact"
        />
        <VSelect
          v-model="convertForm.stage"
          :items="(pipelines.find(p => p.id === convertForm.pipeline_id)?.stages || []).map(s => ({ title: formatLabel(s.name), value: s.name }))"
          label="Stage" density="compact"
        />
        <VTextField v-model.number="convertForm.value" label="Deal value (INR)" type="number" min="0" density="compact" />
        <VTextField v-model.number="convertForm.probability" label="Probability (%)" type="number" min="0" max="100" density="compact" />
        <VTextField v-model="convertForm.expected_close_date" label="Expected close date" type="date" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="convertDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="converting" @click="confirmConvert">
          Convert
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="newDialog" max-width="420" persistent>
    <VCard title="New lead">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="newDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="newError" type="error" variant="tonal" density="compact">
          {{ newError }}
        </VAlert>
        <VTextField v-model="newForm.name" label="Name" density="compact" autofocus />
        <VTextField v-model="newForm.title" label="Title / designation" density="compact" />
        <VTextField v-model="newForm.phone" label="Phone / WhatsApp number" density="compact" />
        <VTextField v-model="newForm.email" label="Email" density="compact" />
        <VTextField v-model="newForm.company_name" label="Company" density="compact" />
        <VSelect
          v-model="newForm.source" label="Lead source" density="compact"
          :items="LEAD_SOURCES.map(s => ({ title: s.replace('_', ' '), value: s }))"
        />
        <VSelect
          v-model="newForm.owner_user_id" label="Lead owner" density="compact" clearable
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
        <VTextarea v-model="newForm.notes" label="Notes" rows="2" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="newDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="newSaving" :disabled="!newForm.name.trim()" @click="createLead">
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

  <VDialog v-model="importDialog" max-width="480" persistent>
    <VCard title="Import leads from CSV">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="importDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <p class="text-body-2 text-medium-emphasis mb-0">
          CSV columns: <code>name, phone, email, title, company</code> (only name is required).
          A row whose contact already has an open lead or deal is skipped.
        </p>
        <VAlert v-if="importError" type="error" variant="tonal" density="compact">
          {{ importError }}
        </VAlert>
        <VAlert v-if="importResult" type="success" variant="tonal" density="compact">
          {{ importResult.created }} created, {{ importResult.skipped }} skipped.
          <div v-if="importResult.errors.length" class="mt-1">
            <div v-for="(err, i) in importResult.errors" :key="i" class="text-caption">
              {{ err }}
            </div>
          </div>
        </VAlert>
        <VFileInput v-model="importFile" label="CSV file" density="compact" accept=".csv" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="importDialog = false">
          Close
        </VBtn>
        <VBtn color="primary" :loading="importing" :disabled="!importFile" @click="runImport">
          Import
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
