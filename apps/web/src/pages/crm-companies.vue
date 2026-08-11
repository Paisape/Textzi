<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type Company = { id: string, name: string, gstin: string | null, industry: string | null, website: string | null, notes: string | null, contact_count: number }
type Contact = { id: string, wa_id: string | null, email: string | null, name: string | null }

const companies = ref<Company[]>([])
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    companies.value = await $api<Company[]>('/v1/crm/companies')
  }
  catch (error: any) {
    if (error?.response?.status === 422)
      crmInactive.value = true
    else
      loadError.value = extractErrorMessage(error, 'Could not load companies.')
  }
  finally {
    loading.value = false
  }
}

// --- Create/edit dialog ----------------------------------------------------------------------

const dialog = ref(false)
const editingId = ref<string | null>(null)
const form = reactive({ name: '', gstin: '', industry: '', website: '', notes: '' })
const saving = ref(false)
const saveError = ref('')

function openCreate() {
  editingId.value = null
  form.name = ''
  form.gstin = ''
  form.industry = ''
  form.website = ''
  form.notes = ''
  saveError.value = ''
  dialog.value = true
}

function openEdit(company: Company) {
  editingId.value = company.id
  form.name = company.name
  form.gstin = company.gstin || ''
  form.industry = company.industry || ''
  form.website = company.website || ''
  form.notes = company.notes || ''
  saveError.value = ''
  dialog.value = true
}

async function save() {
  if (!form.name.trim())
    return
  saving.value = true
  saveError.value = ''
  const body = {
    name: form.name.trim(),
    gstin: form.gstin.trim() || null,
    industry: form.industry.trim() || null,
    website: form.website.trim() || null,
    notes: form.notes.trim() || null,
  }
  try {
    if (editingId.value) {
      const updated = await $api<Company>(`/v1/crm/companies/${editingId.value}`, { method: 'PUT', body })
      const idx = companies.value.findIndex(c => c.id === editingId.value)
      if (idx !== -1)
        companies.value[idx] = updated
    }
    else {
      companies.value.push(await $api<Company>('/v1/crm/companies', { method: 'POST', body }))
    }
    dialog.value = false
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save this company.')
  }
  finally {
    saving.value = false
  }
}

async function remove(company: Company) {
  try {
    await $api(`/v1/crm/companies/${company.id}`, { method: 'DELETE' })
    companies.value = companies.value.filter(c => c.id !== company.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this company.')
  }
}

// --- Contacts dialog -------------------------------------------------------------------------

const contactsDialog = ref(false)
const contactsCompany = ref<Company | null>(null)
const contacts = ref<Contact[]>([])
const contactsLoading = ref(false)

async function openContacts(company: Company) {
  contactsCompany.value = company
  contactsDialog.value = true
  contactsLoading.value = true
  try {
    contacts.value = await $api<Contact[]>(`/v1/crm/companies/${company.id}/contacts`)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load this company\'s contacts.')
  }
  finally {
    contactsLoading.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-1">
    <div>
      <h1 class="text-h4 mb-1">
        Companies
      </h1>
      <p class="text-medium-emphasis">
        Businesses your contacts belong to — group multiple contacts under one account.
      </p>
    </div>
    <VBtn color="primary" prepend-icon="tabler-plus" @click="openCreate">
      New company
    </VBtn>
  </div>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    Upgrade to the CRM plan to use leads, tickets, and customers.
  </VAlert>
  <VAlert v-else-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <VCard v-if="!crmInactive">
    <VTable>
      <thead>
        <tr>
          <th>Name</th>
          <th>GSTIN</th>
          <th>Industry</th>
          <th>Contacts</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr v-for="company in companies" :key="company.id">
          <td>{{ company.name }}</td>
          <td>{{ company.gstin || '—' }}</td>
          <td>{{ company.industry || '—' }}</td>
          <td>
            <VBtn size="small" variant="text" @click="openContacts(company)">
              {{ company.contact_count }} contact{{ company.contact_count === 1 ? '' : 's' }}
            </VBtn>
          </td>
          <td class="text-end">
            <VBtn icon="tabler-pencil" size="small" variant="text" @click="openEdit(company)" />
            <VBtn icon="tabler-trash" size="small" variant="text" @click="remove(company)" />
          </td>
        </tr>
      </tbody>
    </VTable>
    <p v-if="!loading && !companies.length" class="text-medium-emphasis text-center pa-6">
      No companies yet.
    </p>
  </VCard>

  <VDialog v-model="dialog" max-width="480">
    <VCard :title="editingId ? 'Edit company' : 'New company'">
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="saveError" type="error" variant="tonal" density="compact">
          {{ saveError }}
        </VAlert>
        <VTextField v-model="form.name" label="Company name" density="compact" />
        <VTextField v-model="form.gstin" label="GSTIN (optional)" density="compact" />
        <VTextField v-model="form.industry" label="Industry" density="compact" />
        <VTextField v-model="form.website" label="Website" density="compact" />
        <VTextarea v-model="form.notes" label="Notes" rows="3" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="dialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="saving" :disabled="!form.name.trim()" @click="save">
          Save
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="contactsDialog" max-width="420">
    <VCard :title="`${contactsCompany?.name} — contacts`">
      <VCardText>
        <VProgressLinear v-if="contactsLoading" indeterminate class="mb-3" />
        <VList v-if="contacts.length" density="compact">
          <VListItem v-for="contact in contacts" :key="contact.id" :to="`/waba-customers/${contact.id}`">
            <VListItemTitle>{{ contact.name || contact.wa_id || contact.email || 'Unknown' }}</VListItemTitle>
          </VListItem>
        </VList>
        <p v-else-if="!contactsLoading" class="text-medium-emphasis mb-0">
          No contacts linked to this company yet.
        </p>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="contactsDialog = false">
          Close
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
