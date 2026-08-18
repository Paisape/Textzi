<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

type CrmContact = {
  id: string
  name: string | null
  phone: string | null
  email: string | null
  title: string | null
  company_id: string | null
  owner_user_id: string | null
  address: string | null
  reports_to_id: string | null
  source: string
  custom_fields: Record<string, any>
  consent_given_at: string | null
  consent_source: string | null
  created_at: string
}
type Company = { id: string, name: string }
type CustomField = { id: string, name: string, field_type: 'text' | 'number' | 'date' | 'dropdown', options: string[], required: boolean }
type SavedView = { id: string, applies_to: string, name: string, filters: Record<string, any> }
type AssignableUser = { id: string, full_name: string }
type DuplicateGroup = { match_on: string, contacts: CrmContact[] }

const contacts = ref<CrmContact[]>([])
const companies = ref<Company[]>([])
const customFields = ref<CustomField[]>([])
const savedViews = ref<SavedView[]>([])
const assignableUsers = ref<AssignableUser[]>([])
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)
const search = ref('')

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    const [contactResult, companyResult, fieldResult, viewResult, userResult] = await Promise.all([
      $api<CrmContact[]>('/v1/crm/contacts', { params: search.value ? { search: search.value } : {} }),
      $api<Company[]>('/v1/crm/companies'),
      $api<CustomField[]>('/v1/crm/custom-fields?applies_to=crm_contact'),
      $api<SavedView[]>('/v1/crm/saved-views?applies_to=crm_contact'),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
    ])
    contacts.value = contactResult
    companies.value = companyResult
    customFields.value = fieldResult
    savedViews.value = viewResult
    assignableUsers.value = userResult
  }
  catch (error: any) {
    if (error?.response?.status === 422)
      crmInactive.value = true
    else
      loadError.value = extractErrorMessage(error, 'Could not load contacts.')
  }
  finally {
    loading.value = false
  }
}

function companyName(companyId: string | null) {
  return companies.value.find(c => c.id === companyId)?.name || '—'
}

function ownerName(ownerUserId: string | null) {
  return assignableUsers.value.find(u => u.id === ownerUserId)?.full_name || '—'
}

function initial(contact: CrmContact) {
  return (contact.name || contact.phone || contact.email || '?').slice(0, 1).toUpperCase()
}

let searchTimer: ReturnType<typeof setTimeout> | undefined
watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(loadAll, 300)
})

// --- New contact ---------------------------------------------------------------------------

const newDialog = ref(false)
const newForm = reactive({ name: '', phone: '', email: '', title: '', company_id: null as string | null, owner_user_id: null as string | null, address: '', custom_fields: {} as Record<string, any> })
const newSaving = ref(false)
const newError = ref('')

function openNewDialog() {
  newForm.name = ''
  newForm.phone = ''
  newForm.email = ''
  newForm.title = ''
  newForm.company_id = null
  newForm.owner_user_id = null
  newForm.address = ''
  newForm.custom_fields = {}
  newError.value = ''
  newDialog.value = true
}

async function createContact() {
  if (!newForm.name.trim())
    return
  newSaving.value = true
  newError.value = ''
  try {
    const created = await $api<CrmContact>('/v1/crm/contacts', {
      method: 'POST',
      body: {
        name: newForm.name.trim(),
        phone: newForm.phone.trim() || null,
        email: newForm.email.trim() || null,
        title: newForm.title.trim() || null,
        company_id: newForm.company_id,
        owner_user_id: newForm.owner_user_id,
        address: newForm.address.trim() || null,
        custom_fields: newForm.custom_fields,
      },
    })
    contacts.value.unshift(created)
    newDialog.value = false
  }
  catch (error: any) {
    newError.value = extractErrorMessage(error, 'Could not create this contact.')
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
    importResult.value = await $api('/v1/crm/contacts/import', { method: 'POST', body: formData })
    await loadAll()
  }
  catch (error: any) {
    importError.value = extractErrorMessage(error, 'Could not import this file.')
  }
  finally {
    importing.value = false
  }
}

// --- Duplicate detection & merge --------------------------------------------------------------

const duplicatesDialog = ref(false)
const duplicateGroups = ref<DuplicateGroup[]>([])
const duplicatesLoading = ref(false)
const mergePrimary = ref<Record<number, string>>({})
const merging = ref<string | null>(null)

async function openDuplicatesDialog() {
  duplicatesDialog.value = true
  duplicatesLoading.value = true
  try {
    duplicateGroups.value = await $api<DuplicateGroup[]>('/v1/crm/contacts/duplicates')
    mergePrimary.value = {}
    duplicateGroups.value.forEach((group, i) => { mergePrimary.value[i] = group.contacts[0].id })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load duplicate contacts.')
  }
  finally {
    duplicatesLoading.value = false
  }
}

async function mergeGroup(index: number) {
  const group = duplicateGroups.value[index]
  const primaryId = mergePrimary.value[index]
  const duplicateIds = group.contacts.map(c => c.id).filter(id => id !== primaryId)
  merging.value = primaryId
  try {
    await $api('/v1/crm/contacts/merge', { method: 'POST', body: { primary_id: primaryId, duplicate_ids: duplicateIds } })
    duplicateGroups.value.splice(index, 1)
    await loadAll()
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not merge this group.')
  }
  finally {
    merging.value = null
  }
}

// --- Saved views & export -----------------------------------------------------------------------

const saveViewDialog = ref(false)
const saveViewName = ref('')

async function saveCurrentView() {
  if (!saveViewName.value.trim())
    return
  try {
    const created = await $api<SavedView>('/v1/crm/saved-views', { method: 'POST', body: { applies_to: 'crm_contact', name: saveViewName.value.trim(), filters: { search: search.value } } })
    savedViews.value.push(created)
    saveViewDialog.value = false
    saveViewName.value = ''
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not save this view.')
  }
}

function applyView(view: SavedView) {
  search.value = view.filters.search || ''
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

function exportCsv() {
  const rows = [['Name', 'Title', 'Phone', 'Email', 'Company', 'Source', 'Created']]
  for (const contact of contacts.value)
    rows.push([contact.name || '', contact.title || '', contact.phone || '', contact.email || '', companyName(contact.company_id), contact.source, contact.created_at])
  const csv = rows.map(row => row.map(cell => `"${cell.replace(/"/g, '""')}"`).join(',')).join('\n')
  const link = document.createElement('a')
  link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
  link.download = 'contacts.csv'
  link.click()
  URL.revokeObjectURL(link.href)
}

onMounted(loadAll)
</script>

<template>
  <div class="d-flex align-center justify-space-between flex-wrap gap-4 mb-1">
    <div>
      <h1 class="text-h4 mb-1">
        Contacts
      </h1>
      <p class="text-medium-emphasis">
        CRM's own people records — created directly, or linked from a WhatsApp conversation once
        converted.
      </p>
    </div>
    <div class="d-flex align-center gap-3">
      <VBtn variant="tonal" prepend-icon="tabler-git-merge" @click="openDuplicatesDialog">
        Find duplicates
      </VBtn>
      <VBtn variant="tonal" prepend-icon="tabler-upload" @click="openImportDialog">
        Import CSV
      </VBtn>
      <VBtn color="primary" prepend-icon="tabler-plus" @click="openNewDialog">
        New contact
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
    <div class="d-flex align-center flex-wrap gap-3 mb-4">
      <VTextField
        v-model="search" placeholder="Search by name, phone, or email" density="compact"
        prepend-inner-icon="tabler-search" style="max-width: 320px;" clearable hide-details
      />
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

    <VCard>
      <VTable>
        <thead>
          <tr>
            <th>Name</th>
            <th>Title</th>
            <th>Phone</th>
            <th>Email</th>
            <th>Company</th>
            <th>Owner</th>
            <th>Source</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="contact in contacts" :key="contact.id">
            <td>
              <div class="d-flex align-center gap-3">
                <VAvatar color="primary" variant="tonal" size="32">
                  <span class="text-caption">{{ initial(contact) }}</span>
                </VAvatar>
                <RouterLink :to="`/crm-contacts/${contact.id}`" class="font-weight-medium">
                  {{ contact.name || 'Unknown' }}
                </RouterLink>
              </div>
            </td>
            <td>{{ contact.title || '—' }}</td>
            <td>{{ contact.phone || '—' }}</td>
            <td>{{ contact.email || '—' }}</td>
            <td>{{ companyName(contact.company_id) }}</td>
            <td>{{ ownerName(contact.owner_user_id) }}</td>
            <td>
              {{ formatLabel(contact.source) }}
            </td>
            <td>{{ new Date(contact.created_at).toLocaleDateString() }}</td>
          </tr>
        </tbody>
      </VTable>
      <p v-if="!loading && !contacts.length" class="text-medium-emphasis text-center pa-6">
        No contacts yet.
      </p>
    </VCard>
  </template>

  <VDialog v-model="newDialog" max-width="420" persistent>
    <VCard title="New contact">
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
        <VSelect
          v-model="newForm.company_id" label="Company" density="compact" clearable
          :items="companies.map(c => ({ title: c.name, value: c.id }))"
        />
        <VSelect
          v-model="newForm.owner_user_id" label="Owner" density="compact" clearable
          :items="assignableUsers.map(u => ({ title: u.full_name, value: u.id }))"
        />
        <VTextarea v-model="newForm.address" label="Address" rows="2" density="compact" />
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
        <VBtn color="primary" :loading="newSaving" :disabled="!newForm.name.trim()" @click="createContact">
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
    <VCard title="Import contacts from CSV">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="importDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <p class="text-body-2 text-medium-emphasis mb-0">
          CSV columns: <code>name, phone, email, title, company</code> (only name is required).
          Rows matching an existing contact's phone or email are skipped, not overwritten.
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

  <VDialog v-model="duplicatesDialog" max-width="640" persistent>
    <VCard title="Duplicate contacts">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="duplicatesDialog = false" />
      </template>
      <VCardText>
        <VProgressLinear v-if="duplicatesLoading" indeterminate class="mb-3" />
        <p v-if="!duplicatesLoading && !duplicateGroups.length" class="text-medium-emphasis mb-0">
          No duplicate contacts found -- matched by shared phone number or email address.
        </p>
        <VCard v-for="(group, i) in duplicateGroups" :key="i" variant="outlined" class="mb-3">
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-2">
              Matched on {{ group.match_on }}
            </p>
            <VRadioGroup v-model="mergePrimary[i]" density="compact" hide-details>
              <VRadio v-for="c in group.contacts" :key="c.id" :value="c.id">
                <template #label>
                  <span>{{ c.name || 'Unknown' }} — {{ c.phone || c.email }} <span class="text-caption text-medium-emphasis">(keep this one)</span></span>
                </template>
              </VRadio>
            </VRadioGroup>
            <div class="d-flex justify-end mt-2">
              <VBtn size="small" color="primary" :loading="merging === mergePrimary[i]" @click="mergeGroup(i)">
                Merge into selected
              </VBtn>
            </div>
          </VCardText>
        </VCard>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="duplicatesDialog = false">
          Close
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
