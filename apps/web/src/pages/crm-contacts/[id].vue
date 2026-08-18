<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

import { addRecentlyViewed } from '@/composables/useRecentlyViewed'

const route = useRoute('crm-contacts-id')
const router = useRouter()

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
type AssignableUser = { id: string, full_name: string }
type Company = { id: string, name: string, industry: string | null, open_deal_value: number, won_deal_value: number, open_deal_count: number }
type Lead = { id: string, status: string, company_name: string | null, score: number, created_at: string }
type Deal = { id: string, stage: string, status: string, value: number | null, created_at: string }
type Customer = { id: string, created_at: string }
type Task = { id: string, title: string, type: string, due_at: string | null, done: boolean }
type Attachment = { id: string, filename: string, created_at: string }
type ContactSummary = { id: string, name: string | null, phone: string | null, email: string | null }
type ContactDetail = {
  contact: CrmContact
  company: Company | null
  leads: Lead[]
  deals: Deal[]
  customers: Customer[]
  tasks: Task[]
  attachments: Attachment[]
  waba_contact_id: string | null
  reports_to: ContactSummary | null
  direct_reports: ContactSummary[]
}
type Companies = { id: string, name: string }[]

function contactSummaryLabel(c: ContactSummary) {
  return c.name || c.phone || c.email || 'Unknown'
}

const detail = ref<ContactDetail | null>(null)
const companies = ref<Companies>([])
const assignableUsers = ref<AssignableUser[]>([])
const loading = ref(false)
const loadError = ref('')

function ownerName(ownerUserId: string | null) {
  return assignableUsers.value.find(u => u.id === ownerUserId)?.full_name || '—'
}

function inr(value: number | null) {
  if (value === null)
    return '—'
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value)
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [detailResult, companyResult, userResult] = await Promise.all([
      $api<ContactDetail>(`/v1/crm/contacts/${route.params.id}/detail`),
      $api<Companies>('/v1/crm/companies'),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
    ])
    detail.value = detailResult
    companies.value = companyResult
    assignableUsers.value = userResult
    addRecentlyViewed({
      type: 'contact', id: detailResult.contact.id,
      label: detailResult.contact.name || detailResult.contact.phone || detailResult.contact.email || 'Unknown',
      sublabel: detailResult.contact.title,
    })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load this contact.')
  }
  finally {
    loading.value = false
  }
}

function initial() {
  const c = detail.value?.contact
  return (c?.name || c?.phone || c?.email || '?').slice(0, 1).toUpperCase()
}

// --- Edit ------------------------------------------------------------------------------------

const editDialog = ref(false)
const editForm = reactive({ name: '', phone: '', email: '', title: '', company_id: null as string | null, owner_user_id: null as string | null, address: '', reports_to_id: null as string | null })
const editSaving = ref(false)

const reportsToSearch = ref('')
const reportsToOptions = ref<ContactSummary[]>([])
const reportsToSearchLoading = ref(false)
let reportsToSearchTimer: ReturnType<typeof setTimeout> | undefined

async function searchReportsTo(query: string) {
  reportsToSearchLoading.value = true
  try {
    const results = await $api<ContactSummary[]>('/v1/crm/contacts', { params: { search: query } })
    reportsToOptions.value = results.filter(c => c.id !== detail.value?.contact.id)
  }
  catch {
    // best-effort search -- an empty result list is an acceptable failure mode here
  }
  finally {
    reportsToSearchLoading.value = false
  }
}

watch(reportsToSearch, (query) => {
  clearTimeout(reportsToSearchTimer)
  reportsToSearchTimer = setTimeout(() => searchReportsTo(query || ''), 300)
})

function openEditDialog() {
  if (!detail.value)
    return
  editForm.name = detail.value.contact.name || ''
  editForm.phone = detail.value.contact.phone || ''
  editForm.email = detail.value.contact.email || ''
  editForm.title = detail.value.contact.title || ''
  editForm.company_id = detail.value.contact.company_id
  editForm.owner_user_id = detail.value.contact.owner_user_id
  editForm.address = detail.value.contact.address || ''
  editForm.reports_to_id = detail.value.contact.reports_to_id
  reportsToSearch.value = ''
  reportsToOptions.value = detail.value.reports_to ? [detail.value.reports_to] : []
  editDialog.value = true
}

async function downloadAttachment(attachment: Attachment) {
  try {
    const blob = await $api<Blob, 'blob'>(`/v1/crm/attachments/${attachment.id}/download`, { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = attachment.filename
    link.click()
    URL.revokeObjectURL(url)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not download this attachment.')
  }
}

async function saveEdit() {
  if (!detail.value)
    return
  editSaving.value = true
  try {
    const previousCompanyId = detail.value.contact.company_id
    const previousReportsToId = detail.value.contact.reports_to_id
    const updated = await $api<CrmContact>(`/v1/crm/contacts/${detail.value.contact.id}`, {
      method: 'PATCH',
      body: {
        name: editForm.name.trim(), phone: editForm.phone.trim() || null, email: editForm.email.trim() || null,
        title: editForm.title.trim() || null, company_id: editForm.company_id, owner_user_id: editForm.owner_user_id,
        address: editForm.address.trim() || null, reports_to_id: editForm.reports_to_id,
      },
    })
    detail.value.contact = updated
    if (updated.company_id !== previousCompanyId || updated.reports_to_id !== previousReportsToId)
      await load()
    editDialog.value = false
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not save this contact.')
  }
  finally {
    editSaving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="d-flex align-center gap-3 mb-4">
    <VBtn icon="tabler-arrow-left" variant="text" :to="{ name: 'crm-contacts' }" />
    <h1 class="text-h5 mb-0">
      Contact
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
              {{ detail.contact.name || detail.contact.phone || detail.contact.email || 'Unknown' }}
            </p>
            <p v-if="detail.contact.title" class="text-body-2 text-medium-emphasis mb-0">
              {{ detail.contact.title }}
            </p>
            <p class="text-body-2 text-medium-emphasis mb-0">
              {{ detail.contact.phone || '—' }} <span v-if="detail.contact.email">· {{ detail.contact.email }}</span>
            </p>
          </div>
          <VBtn variant="tonal" size="small" @click="openEditDialog">
            Edit
          </VBtn>
        </VCardText>
        <VDivider />
        <VCardText class="d-flex flex-wrap gap-3">
          <RouterLink v-if="detail.company" :to="`/crm-companies/${detail.company.id}`" class="d-flex align-center gap-2 text-body-2">
            <VIcon icon="tabler-building" size="16" />
            {{ detail.company.name }}
          </RouterLink>
          <RouterLink v-if="detail.waba_contact_id" :to="`/waba-customers/${detail.waba_contact_id}`" class="d-flex align-center gap-2 text-body-2">
            <VIcon icon="tabler-brand-whatsapp" size="16" />
            View WhatsApp conversation
          </RouterLink>
          <RouterLink v-if="detail.reports_to" :to="`/crm-contacts/${detail.reports_to.id}`" class="d-flex align-center gap-2 text-body-2">
            <VIcon icon="tabler-corner-left-up" size="16" />
            Reports to {{ contactSummaryLabel(detail.reports_to) }}
          </RouterLink>
          <span class="d-flex align-center gap-2 text-body-2 text-medium-emphasis">
            <VIcon icon="tabler-tag" size="16" />
            {{ formatLabel(detail.contact.source) }}
          </span>
        </VCardText>
      </VCard>

      <VCard v-if="detail.direct_reports.length" class="mb-4" title="Direct reports">
        <VList density="compact">
          <VListItem v-for="report in detail.direct_reports" :key="report.id" :to="`/crm-contacts/${report.id}`">
            <VListItemTitle>{{ contactSummaryLabel(report) }}</VListItemTitle>
          </VListItem>
        </VList>
      </VCard>

      <VCard class="mb-4" title="Funnel history">
        <VList v-if="detail.leads.length || detail.deals.length || detail.customers.length" density="compact">
          <VListItem v-for="lead in detail.leads" :key="`lead-${lead.id}`" :to="`/crm-leads/${lead.id}`">
            <template #prepend>
              <VIcon icon="tabler-target-arrow" size="16" />
            </template>
            <VListItemTitle>Lead · {{ lead.company_name || 'No company' }}</VListItemTitle>
            <VListItemSubtitle>{{ lead.status }} · score {{ lead.score }}</VListItemSubtitle>
          </VListItem>
          <VListItem v-for="deal in detail.deals" :key="`deal-${deal.id}`" :to="`/crm-deals/${deal.id}`">
            <template #prepend>
              <VIcon icon="tabler-briefcase" size="16" />
            </template>
            <VListItemTitle>Deal · {{ inr(deal.value) }}</VListItemTitle>
            <VListItemSubtitle>{{ deal.stage }} · {{ deal.status }}</VListItemSubtitle>
          </VListItem>
          <VListItem v-for="customer in detail.customers" :key="`customer-${customer.id}`">
            <template #prepend>
              <VIcon icon="tabler-user-check" size="16" />
            </template>
            <VListItemTitle>Customer since {{ new Date(customer.created_at).toLocaleDateString() }}</VListItemTitle>
          </VListItem>
        </VList>
        <p v-else class="text-medium-emphasis text-center pa-6">
          No leads, deals, or customer record yet.
        </p>
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
    </VCol>

    <VCol cols="12" md="4">
      <VCard class="mb-4" title="Details">
        <VCardText class="d-flex flex-column gap-4">
          <div>
            <p class="text-caption text-medium-emphasis mb-1">
              Owner
            </p>
            <p class="mb-0">
              {{ ownerName(detail.contact.owner_user_id) }}
            </p>
          </div>
          <div v-if="detail.contact.address">
            <p class="text-caption text-medium-emphasis mb-1">
              Address
            </p>
            <p class="mb-0">
              {{ detail.contact.address }}
            </p>
          </div>
          <div>
            <p class="text-caption text-medium-emphasis mb-1">
              Created
            </p>
            <p class="mb-0">
              {{ new Date(detail.contact.created_at).toLocaleDateString() }}
            </p>
          </div>
        </VCardText>
      </VCard>

      <VCard title="Attachments">
        <VList v-if="detail.attachments.length" density="compact">
          <VListItem v-for="attachment in detail.attachments" :key="attachment.id" @click="downloadAttachment(attachment)">
            <template #prepend>
              <VIcon icon="tabler-paperclip" size="16" />
            </template>
            <VListItemTitle>{{ attachment.filename }}</VListItemTitle>
          </VListItem>
        </VList>
        <p v-else class="text-medium-emphasis text-center pa-6">
          No attachments yet.
        </p>
      </VCard>
    </VCol>
  </VRow>

  <VDialog v-model="editDialog" max-width="420" persistent>
    <VCard title="Edit contact">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="editDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VTextField v-model="editForm.name" label="Name" density="compact" autofocus />
        <VTextField v-model="editForm.title" label="Title / designation" density="compact" />
        <VTextField v-model="editForm.phone" label="Phone / WhatsApp number" density="compact" />
        <VTextField v-model="editForm.email" label="Email" density="compact" />
        <VSelect
          v-model="editForm.company_id" label="Company" density="compact" clearable
          :items="companies.map(c => ({ title: c.name, value: c.id }))"
        />
        <VSelect
          v-model="editForm.owner_user_id" label="Owner" density="compact" clearable
          :items="assignableUsers.map(u => ({ title: u.full_name, value: u.id }))"
        />
        <VTextarea v-model="editForm.address" label="Address" rows="2" density="compact" />
        <VAutocomplete
          v-model="editForm.reports_to_id"
          v-model:search="reportsToSearch"
          :items="reportsToOptions"
          :item-title="(c: ContactSummary) => contactSummaryLabel(c)"
          item-value="id"
          label="Reports to (optional)"
          placeholder="Search by name, phone, or email"
          :loading="reportsToSearchLoading"
          clearable
          no-filter
        />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="editDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="editSaving" @click="saveEdit">
          Save
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
