<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

import { addRecentlyViewed } from '@/composables/useRecentlyViewed'

const route = useRoute('crm-companies-id')
const router = useRouter()

type Company = {
  id: string, name: string, gstin: string | null, industry: string | null, website: string | null, notes: string | null,
  owner_user_id: string | null, account_type: string | null, parent_company_id: string | null, phone: string | null,
  address: string | null, employee_count: number | null, annual_revenue: number | null,
  contact_count: number, open_deal_value: number, won_deal_value: number, open_deal_count: number, created_at: string,
}
type CrmContact = { id: string, name: string | null, phone: string | null, email: string | null, title: string | null }
type CompanySummary = { id: string, name: string }
type AssignableUser = { id: string, full_name: string }
type CompanyDetail = { company: Company, contacts: CrmContact[], parent_company: CompanySummary | null, child_companies: CompanySummary[] }

const ACCOUNT_TYPES = ['customer', 'partner', 'prospect', 'vendor']
const ACCOUNT_TYPE_COLORS: Record<string, string | undefined> = { customer: 'success', partner: 'info', prospect: 'warning', vendor: undefined }

const detail = ref<CompanyDetail | null>(null)
const allCompanies = ref<CompanySummary[]>([])
const assignableUsers = ref<AssignableUser[]>([])
const loading = ref(false)
const loadError = ref('')

function inr(value: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value)
}

function initial(contact: CrmContact) {
  return (contact.name || contact.phone || contact.email || '?').slice(0, 1).toUpperCase()
}

function ownerName(ownerUserId: string | null) {
  return assignableUsers.value.find(u => u.id === ownerUserId)?.full_name || '—'
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [detailResult, companiesResult, userResult] = await Promise.all([
      $api<CompanyDetail>(`/v1/crm/companies/${route.params.id}`),
      $api<Company[]>('/v1/crm/companies'),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
    ])
    detail.value = detailResult
    allCompanies.value = companiesResult.map(c => ({ id: c.id, name: c.name }))
    assignableUsers.value = userResult
    addRecentlyViewed({ type: 'company', id: detailResult.company.id, label: detailResult.company.name, sublabel: detailResult.company.industry })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load this company.')
  }
  finally {
    loading.value = false
  }
}

// --- Edit ------------------------------------------------------------------------------------

const editDialog = ref(false)
const form = reactive({
  name: '', gstin: '', industry: '', website: '', notes: '', owner_user_id: null as string | null,
  account_type: null as string | null, parent_company_id: null as string | null, phone: '', address: '',
  employee_count: null as number | null, annual_revenue: null as number | null,
})
const saving = ref(false)

function openEdit() {
  if (!detail.value)
    return
  const c = detail.value.company
  form.name = c.name
  form.gstin = c.gstin || ''
  form.industry = c.industry || ''
  form.website = c.website || ''
  form.notes = c.notes || ''
  form.owner_user_id = c.owner_user_id
  form.account_type = c.account_type
  form.parent_company_id = c.parent_company_id
  form.phone = c.phone || ''
  form.address = c.address || ''
  form.employee_count = c.employee_count
  form.annual_revenue = c.annual_revenue
  editDialog.value = true
}

async function save() {
  if (!detail.value || !form.name.trim())
    return
  saving.value = true
  try {
    const updated = await $api<Company>(`/v1/crm/companies/${detail.value.company.id}`, {
      method: 'PUT',
      body: {
        name: form.name.trim(), gstin: form.gstin.trim() || null, industry: form.industry.trim() || null,
        website: form.website.trim() || null, notes: form.notes.trim() || null, owner_user_id: form.owner_user_id,
        account_type: form.account_type, parent_company_id: form.parent_company_id, phone: form.phone.trim() || null,
        address: form.address.trim() || null, employee_count: form.employee_count, annual_revenue: form.annual_revenue,
      },
    })
    detail.value.company = updated
    editDialog.value = false
    await load()
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not save this company.')
  }
  finally {
    saving.value = false
  }
}

const deleting = ref(false)

async function remove() {
  if (!detail.value)
    return
  deleting.value = true
  try {
    await $api(`/v1/crm/companies/${detail.value.company.id}`, { method: 'DELETE' })
    router.push({ name: 'crm-companies' })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this company.')
  }
  finally {
    deleting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="d-flex align-center gap-3 mb-4">
    <VBtn icon="tabler-arrow-left" variant="text" :to="{ name: 'crm-companies' }" />
    <h1 class="text-h5 mb-0">
      Company
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
            <span class="text-h6">{{ detail.company.name.slice(0, 1).toUpperCase() }}</span>
          </VAvatar>
          <div class="flex-grow-1">
            <div class="d-flex align-center gap-2">
              <p class="text-h6 mb-0">
                {{ detail.company.name }}
              </p>
              <VChip v-if="detail.company.account_type" size="small" :color="ACCOUNT_TYPE_COLORS[detail.company.account_type]" class="text-capitalize">
                {{ detail.company.account_type }}
              </VChip>
            </div>
            <p v-if="detail.company.industry" class="text-body-2 text-medium-emphasis mb-0">
              {{ detail.company.industry }}
            </p>
            <p v-if="detail.company.gstin" class="text-body-2 text-medium-emphasis mb-0">
              GSTIN {{ detail.company.gstin }}
            </p>
          </div>
          <VBtn variant="tonal" size="small" @click="openEdit">
            Edit
          </VBtn>
        </VCardText>
        <VDivider />
        <VCardText class="d-flex flex-wrap gap-3">
          <RouterLink v-if="detail.parent_company" :to="`/crm-companies/${detail.parent_company.id}`" class="d-flex align-center gap-2 text-body-2">
            <VIcon icon="tabler-corner-left-up" size="16" />
            Part of {{ detail.parent_company.name }}
          </RouterLink>
          <span v-if="detail.company.phone" class="d-flex align-center gap-2 text-body-2 text-medium-emphasis">
            <VIcon icon="tabler-phone" size="16" />
            {{ detail.company.phone }}
          </span>
          <span v-if="detail.company.employee_count" class="d-flex align-center gap-2 text-body-2 text-medium-emphasis">
            <VIcon icon="tabler-users" size="16" />
            {{ detail.company.employee_count }} employees
          </span>
        </VCardText>
        <VDivider v-if="detail.company.notes || detail.company.address" />
        <VCardText v-if="detail.company.address" class="text-body-2 text-medium-emphasis">
          {{ detail.company.address }}
        </VCardText>
        <VCardText v-if="detail.company.notes">
          {{ detail.company.notes }}
        </VCardText>
      </VCard>

      <VCard v-if="detail.child_companies.length" class="mb-4" title="Branches">
        <VList density="compact">
          <VListItem v-for="child in detail.child_companies" :key="child.id" :to="`/crm-companies/${child.id}`">
            <VListItemTitle>{{ child.name }}</VListItemTitle>
          </VListItem>
        </VList>
      </VCard>

      <VCard title="Contacts">
        <VList v-if="detail.contacts.length" density="compact">
          <VListItem v-for="contact in detail.contacts" :key="contact.id" :to="`/crm-contacts/${contact.id}`">
            <template #prepend>
              <VAvatar color="primary" variant="tonal" size="32">
                <span class="text-caption">{{ initial(contact) }}</span>
              </VAvatar>
            </template>
            <VListItemTitle>{{ contact.name || contact.phone || contact.email || 'Unknown' }}</VListItemTitle>
            <VListItemSubtitle v-if="contact.title">
              {{ contact.title }}
            </VListItemSubtitle>
          </VListItem>
        </VList>
        <p v-else class="text-medium-emphasis text-center pa-6">
          No contacts linked to this company yet.
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
            <p class="mb-0">
              {{ ownerName(detail.company.owner_user_id) }}
            </p>
          </div>
          <div v-if="detail.company.annual_revenue">
            <p class="text-caption text-medium-emphasis mb-1">
              Annual revenue
            </p>
            <p class="mb-0">
              {{ inr(detail.company.annual_revenue) }}
            </p>
          </div>
          <div>
            <p class="text-caption text-medium-emphasis mb-1">
              Open deals
            </p>
            <p class="mb-0">
              {{ detail.company.open_deal_count }} · {{ inr(detail.company.open_deal_value) }}
            </p>
          </div>
          <div>
            <p class="text-caption text-medium-emphasis mb-1">
              Won value
            </p>
            <p class="mb-0">
              {{ inr(detail.company.won_deal_value) }}
            </p>
          </div>
          <div>
            <p class="text-caption text-medium-emphasis mb-1">
              Created
            </p>
            <p class="mb-0">
              {{ new Date(detail.company.created_at).toLocaleDateString() }}
            </p>
          </div>
        </VCardText>
      </VCard>

      <VCard title="Actions">
        <VCardText>
          <VBtn color="error" variant="tonal" block :loading="deleting" @click="remove">
            Delete company
          </VBtn>
        </VCardText>
      </VCard>
    </VCol>
  </VRow>

  <VDialog v-model="editDialog" max-width="560" persistent>
    <VCard title="Edit company">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="editDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VTextField v-model="form.name" label="Company name" density="compact" />
        <VSelect v-model="form.account_type" label="Account type" density="compact" clearable :items="ACCOUNT_TYPES" class="text-capitalize" />
        <VSelect
          v-model="form.owner_user_id" label="Owner" density="compact" clearable
          :items="assignableUsers.map(u => ({ title: u.full_name, value: u.id }))"
        />
        <VSelect
          v-model="form.parent_company_id" label="Parent company" density="compact" clearable
          :items="allCompanies.filter(c => c.id !== detail?.company.id).map(c => ({ title: c.name, value: c.id }))"
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
        <VBtn variant="text" @click="editDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="saving" :disabled="!form.name.trim()" @click="save">
          Save
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
