<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type Contact = { id: string, wa_id: string | null, email: string | null, name: string | null }
type Customer = {
  id: string
  contact: Contact
  lead_id: string | null
  converted_from_conversation_id: string | null
  owner_user_id: string | null
  notes: string | null
  created_at: string
}
type AssignableUser = { id: string, full_name: string, email: string }

const customers = ref<Customer[]>([])
const users = ref<AssignableUser[]>([])
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    const [customerResult, userResult] = await Promise.all([
      $api<Customer[]>('/v1/crm/customers'),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
    ])
    customers.value = customerResult
    users.value = userResult
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
  if (customer.lead_id)
    return 'Converted from lead'
  if (customer.converted_from_conversation_id)
    return 'Direct from WhatsApp'
  return 'Manual'
}

onMounted(loadAll)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Customers
  </h1>
  <p class="text-medium-emphasis mb-6">
    Converted, active accounts — either promoted from a lead once its pipeline closes, or
    converted directly from a WhatsApp conversation for an existing customer with no sales
    process to track.
  </p>

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
        <tr v-for="customer in customers" :key="customer.id">
          <td>
            {{ customer.contact.name || customer.contact.wa_id || customer.contact.email || 'Unknown' }}
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
</template>
