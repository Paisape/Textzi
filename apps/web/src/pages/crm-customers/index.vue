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
}
type AssignableUser = { id: string, full_name: string, email: string }
type CustomField = { id: string, name: string, field_type: 'text' | 'number' | 'date' | 'dropdown', options: string[], required: boolean }

const customers = ref<Customer[]>([])
const users = ref<AssignableUser[]>([])
const customFields = ref<CustomField[]>([])
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)

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
    <VBtn color="primary" prepend-icon="tabler-plus" @click="openNewDialog">
      New customer
    </VBtn>
  </div>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    Upgrade to the CRM plan to use leads, tickets, and customers.
  </VAlert>
  <VAlert v-else-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>

  <VCard v-if="!crmInactive">
    <VTable>
      <thead>
        <tr>
          <th>Contact</th>
          <th>Source</th>
          <th>Owner</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="customer in customers" :key="customer.id" class="cursor-pointer"
          @click="$router.push(`/crm-customers/${customer.id}`)"
        >
          <td>
            {{ customer.contact.name || customer.contact.phone || customer.contact.email || 'Unknown' }}
          </td>
          <td>{{ sourceLabel(customer) }}</td>
          <td>{{ ownerName(customer) }}</td>
          <td>{{ new Date(customer.created_at).toLocaleDateString() }}</td>
        </tr>
      </tbody>
    </VTable>
    <p v-if="!loading && !customers.length" class="text-medium-emphasis text-center pa-6">
      No customers yet.
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
</template>
