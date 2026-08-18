<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

type Company = {
  id: string, name: string, gstin: string | null, industry: string | null, website: string | null, notes: string | null,
  owner_user_id: string | null, account_type: string | null, parent_company_id: string | null, phone: string | null,
  address: string | null, employee_count: number | null, annual_revenue: number | null,
  contact_count: number, open_deal_value: number, won_deal_value: number, open_deal_count: number,
}
type AssignableUser = { id: string, full_name: string }

const ACCOUNT_TYPES = ['customer', 'partner', 'prospect', 'vendor']
const ACCOUNT_TYPE_COLORS: Record<string, string | undefined> = { customer: 'success', partner: 'info', prospect: 'warning', vendor: undefined }

const companies = ref<Company[]>([])
const assignableUsers = ref<AssignableUser[]>([])
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)

function inr(value: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value)
}

function initial(company: Company) {
  return company.name.slice(0, 1).toUpperCase()
}

function ownerName(ownerUserId: string | null) {
  return assignableUsers.value.find(u => u.id === ownerUserId)?.full_name || '—'
}

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    const [companyResult, userResult] = await Promise.all([
      $api<Company[]>('/v1/crm/companies'),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
    ])
    companies.value = companyResult
    assignableUsers.value = userResult
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
const form = reactive({
  name: '', gstin: '', industry: '', website: '', notes: '', owner_user_id: null as string | null,
  account_type: null as string | null, parent_company_id: null as string | null, phone: '', address: '',
  employee_count: null as number | null, annual_revenue: null as number | null,
})
const saving = ref(false)
const saveError = ref('')

function openCreate() {
  editingId.value = null
  form.name = ''
  form.gstin = ''
  form.industry = ''
  form.website = ''
  form.notes = ''
  form.owner_user_id = null
  form.account_type = null
  form.parent_company_id = null
  form.phone = ''
  form.address = ''
  form.employee_count = null
  form.annual_revenue = null
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
  form.owner_user_id = company.owner_user_id
  form.account_type = company.account_type
  form.parent_company_id = company.parent_company_id
  form.phone = company.phone || ''
  form.address = company.address || ''
  form.employee_count = company.employee_count
  form.annual_revenue = company.annual_revenue
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
    owner_user_id: form.owner_user_id,
    account_type: form.account_type,
    parent_company_id: form.parent_company_id,
    phone: form.phone.trim() || null,
    address: form.address.trim() || null,
    employee_count: form.employee_count,
    annual_revenue: form.annual_revenue,
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
          <th>Type</th>
          <th>Industry</th>
          <th>Owner</th>
          <th>Contacts</th>
          <th>Open deals</th>
          <th>Won value</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr v-for="company in companies" :key="company.id">
          <td>
            <div class="d-flex align-center gap-3">
              <VAvatar color="primary" variant="tonal" size="32">
                <span class="text-caption">{{ initial(company) }}</span>
              </VAvatar>
              <RouterLink :to="`/crm-companies/${company.id}`" class="font-weight-medium">
                {{ company.name }}
              </RouterLink>
            </div>
          </td>
          <td>
            <VChip v-if="company.account_type" size="small" :color="ACCOUNT_TYPE_COLORS[company.account_type]" class="text-capitalize">
              {{ company.account_type }}
            </VChip>
            <span v-else class="text-medium-emphasis">—</span>
          </td>
          <td>{{ company.industry || '—' }}</td>
          <td>{{ ownerName(company.owner_user_id) }}</td>
          <td>
            <RouterLink :to="`/crm-companies/${company.id}`" class="text-body-2">
              {{ company.contact_count }} contact{{ company.contact_count === 1 ? '' : 's' }}
            </RouterLink>
          </td>
          <td>{{ company.open_deal_count }} · {{ inr(company.open_deal_value) }}</td>
          <td>{{ inr(company.won_deal_value) }}</td>
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

  <VDialog v-model="dialog" max-width="560" persistent>
    <VCard :title="editingId ? 'Edit company' : 'New company'">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="dialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="saveError" type="error" variant="tonal" density="compact">
          {{ saveError }}
        </VAlert>
        <VTextField v-model="form.name" label="Company name" density="compact" />
        <VSelect v-model="form.account_type" label="Account type" density="compact" clearable :items="ACCOUNT_TYPES" class="text-capitalize" />
        <VSelect
          v-model="form.owner_user_id" label="Owner" density="compact" clearable
          :items="assignableUsers.map(u => ({ title: u.full_name, value: u.id }))"
        />
        <VSelect
          v-model="form.parent_company_id" label="Parent company" density="compact" clearable
          :items="companies.filter(c => c.id !== editingId).map(c => ({ title: c.name, value: c.id }))"
        />
        <VTextField v-model="form.gstin" label="GSTIN (optional)" density="compact" />
        <VTextField v-model="form.industry" label="Industry" density="compact" />
        <VTextField v-model="form.phone" label="Phone" density="compact" />
        <VTextField v-model="form.website" label="Website" density="compact" />
        <VTextField v-model.number="form.employee_count" label="Employees" type="number" min="0" density="compact" />
        <VTextField v-model.number="form.annual_revenue" label="Annual revenue (INR)" type="number" min="0" density="compact" />
        <VTextarea v-model="form.address" label="Address" rows="2" density="compact" />
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
</template>
