<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

type CrmContact = { id: string, name: string | null, phone: string | null, email: string | null, title: string | null, company_id: string | null }
type Customer = {
  id: string
  contact: CrmContact
  deal_id: string | null
  converted_from_conversation_id: string | null
  owner_user_id: string | null
  notes: string | null
  custom_fields: Record<string, any>
  created_at: string
  open_ticket_count: number
  open_deal_id: string | null
  last_activity_at: string | null
}
type AssignableUser = { id: string, full_name: string, email: string }
type CustomField = { id: string, name: string, field_type: 'text' | 'number' | 'date' | 'dropdown', options: string[], required: boolean }

const customers = ref<Customer[]>([])
const users = ref<AssignableUser[]>([])
const customFields = ref<CustomField[]>([])
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)
const search = ref('')

const filteredCustomers = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q)
    return customers.value
  return customers.value.filter((customer) => {
    const { name, phone, email } = customer.contact
    return [name, phone, email].some(v => v?.toLowerCase().includes(q))
  })
})

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    const [customerResult, userResult, fieldResult] = await Promise.all([
      $api<Customer[]>('/v1/crm/customers'),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
      $api<CustomField[]>('/v1/crm/custom-fields?applies_to=customer'),
    ])
    customers.value = customerResult
    users.value = userResult
    customFields.value = fieldResult
  }
  catch (error: any) {
    if (error?.response?.status === 422) {
      crmInactive.value = true
    }
    else {
      loadError.value = extractErrorMessage(error, 'Could not load customers.')
    }
  }
  finally {
    loading.value = false
  }
}

function ownerName(customer: Customer) {
  return users.value.find(u => u.id === customer.owner_user_id)?.full_name || 'Unassigned'
}

function sourceLabel(customer: Customer) {
  if (customer.deal_id)
    return 'Converted from deal'
  if (customer.converted_from_conversation_id)
    return 'Direct from WhatsApp'
  return 'Manual'
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—'
}

const exportingCsv = ref(false)

function exportCsv() {
  exportingCsv.value = true
  try {
    const rows = [['Name', 'Mobile', 'Email', 'Source', 'Owner', 'Open tickets', 'Last activity', 'Created']]
    for (const customer of filteredCustomers.value) {
      rows.push([
        customer.contact.name || '', customer.contact.phone || '', customer.contact.email || '',
        sourceLabel(customer), ownerName(customer), String(customer.open_ticket_count),
        customer.last_activity_at || '', customer.created_at,
      ])
    }
    const csv = rows.map(row => row.map(cell => `"${cell.replace(/"/g, '""')}"`).join(',')).join('\n')
    const link = document.createElement('a')
    link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    link.download = 'customers.csv'
    link.click()
    URL.revokeObjectURL(link.href)
  }
  finally {
    exportingCsv.value = false
  }
}

// --- New customer ------------------------------------------------------------------------------

const newDialog = ref(false)
const newForm = reactive({ name: '', phone: '', email: '', title: '', owner_user_id: null as string | null, notes: '', custom_fields: {} as Record<string, any> })
const newSaving = ref(false)
const newError = ref('')

function openNewDialog() {
  newForm.name = ''
  newForm.phone = ''
  newForm.email = ''
  newForm.title = ''
  newForm.owner_user_id = null
  newForm.notes = ''
  newForm.custom_fields = {}
  newError.value = ''
  newDialog.value = true
}

async function createCustomer() {
  if (!newForm.name.trim())
    return
  newSaving.value = true
  newError.value = ''
  try {
    const created = await $api<Customer>('/v1/crm/customers', {
      method: 'POST',
      body: {
        name: newForm.name.trim(),
        phone: newForm.phone.trim() || null,
        email: newForm.email.trim() || null,
        title: newForm.title.trim() || null,
        owner_user_id: newForm.owner_user_id,
        notes: newForm.notes.trim() || null,
        custom_fields: newForm.custom_fields,
      },
    })
    customers.value.unshift(created)
    newDialog.value = false
  }
  catch (error: any) {
    newError.value = extractErrorMessage(error, 'Could not create this customer.')
  }
  finally {
    newSaving.value = false
  }
}

// --- CSV import ------------------------------------------------------------------------------

const importDialog = ref(false)
const importFile = ref<File[]>([])
const importing = ref(false)
const importError = ref('')
const importResult = ref<{ created: number, skipped: number, errors: string[] } | null>(null)

async function onImportFile() {
  const file = importFile.value[0]
  if (!file)
    return
  importing.value = true
  importError.value = ''
  importResult.value = null
  try {
    const formData = new FormData()
    formData.append('file', file)
    importResult.value = await $api('/v1/crm/customers/import', { method: 'POST', body: formData })
    await loadAll()
  }
  catch (error: any) {
    importError.value = extractErrorMessage(error, 'Could not import this file.')
  }
  finally {
    importing.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="d-flex align-center justify-space-between flex-wrap gap-4 mb-1">
    <div>
      <h1 class="text-h4 mb-1">
        Customers
      </h1>
      <p class="text-medium-emphasis">
        Converted, active accounts — promoted from a deal, converted directly from a WhatsApp
        conversation, or added manually for a customer with no sales process to track.
      </p>
    </div>
    <div class="d-flex align-center gap-3">
      <VBtn variant="tonal" prepend-icon="tabler-upload" @click="importDialog = true">
        Import CSV
      </VBtn>
      <VBtn variant="tonal" prepend-icon="tabler-download" :loading="exportingCsv" :disabled="exportingCsv" @click="exportCsv">
        Export CSV
      </VBtn>
      <VBtn color="primary" prepend-icon="tabler-plus" @click="openNewDialog">
        New customer
      </VBtn>
    </div>
  </div>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    Upgrade to the CRM plan to use leads, tickets, and customers.
    <RouterLink to="/channels-crm?tab=billing" class="font-weight-medium">
      View plans
    </RouterLink>
  </VAlert>
  <VAlert v-else-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>

  <VCard v-if="!crmInactive">
    <VCardText>
      <VTextField
        v-model="search" placeholder="Search by name, phone, or email" density="compact"
        prepend-inner-icon="tabler-search" style="max-width: 320px;" clearable hide-details
      />
    </VCardText>
    <VTable>
      <thead>
        <tr>
          <th>Name</th>
          <th>Mobile no</th>
          <th>Email</th>
          <th>Source</th>
          <th>Owner</th>
          <th>Last activity</th>
          <th>Status</th>
          <th>Created</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="customer in filteredCustomers" :key="customer.id" class="cursor-pointer"
          @click="$router.push(`/crm-customers/${customer.id}`)"
        >
          <td>
            {{ customer.contact.name || customer.contact.phone || customer.contact.email || 'Unknown' }}
          </td>
          <td>{{ customer.contact.phone || '—' }}</td>
          <td>{{ customer.contact.email || '—' }}</td>
          <td>{{ sourceLabel(customer) }}</td>
          <td>{{ ownerName(customer) }}</td>
          <td>{{ formatDate(customer.last_activity_at) }}</td>
          <td>
            <VChip v-if="customer.open_deal_id" size="small" color="warning" variant="tonal">
              Open deal
            </VChip>
            <VChip v-if="customer.open_ticket_count" size="small" color="error" variant="tonal" class="ml-1">
              {{ customer.open_ticket_count }} open ticket{{ customer.open_ticket_count === 1 ? '' : 's' }}
            </VChip>
            <span v-if="!customer.open_deal_id && !customer.open_ticket_count" class="text-medium-emphasis">—</span>
          </td>
          <td>{{ new Date(customer.created_at).toLocaleDateString() }}</td>
          <td>
            <RouterLink :to="`/crm-customers/${customer.id}`" class="font-weight-medium" @click.stop>
              View
            </RouterLink>
          </td>
        </tr>
      </tbody>
    </VTable>
    <p v-if="!loading && !customers.length" class="text-medium-emphasis text-center pa-6">
      No customers yet.
    </p>
    <p v-else-if="!loading && !filteredCustomers.length" class="text-medium-emphasis text-center pa-6">
      No customers match "{{ search }}".
    </p>
  </VCard>

  <VDialog v-model="newDialog" max-width="420" persistent>
    <VCard title="New customer">
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
          v-model="newForm.owner_user_id" label="Owner" density="compact" clearable
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
        <VBtn color="primary" :loading="newSaving" :disabled="!newForm.name.trim()" @click="createCustomer">
          Create
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="importDialog" max-width="480">
    <VCard>
      <VCardTitle>Import customers</VCardTitle>
      <VCardText>
        <p class="text-body-2 text-medium-emphasis mb-3">
          A CSV with a <code>name</code> column (required) and optional <code>phone</code>/
          <code>email</code>/<code>title</code> columns. A row matching an existing customer's
          phone or email is skipped, not duplicated.
        </p>
        <VAlert v-if="importError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ importError }}
        </VAlert>
        <VAlert v-if="importResult" type="success" variant="tonal" density="compact" class="mb-3">
          {{ importResult.created }} created, {{ importResult.skipped }} skipped.
        </VAlert>
        <VFileInput v-model="importFile" accept=".csv" label="CSV file" :loading="importing" @update:model-value="onImportFile" />
      </VCardText>
      <VCardText class="d-flex justify-end pt-0">
        <VBtn variant="text" @click="importDialog = false">
          Close
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>
</template>
