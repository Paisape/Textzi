<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
    staffArea: 'finance',
  },
})

const authStore = useAuthStore()
const hasAccess = computed(() => authStore.loaded ? (authStore.isAdmin || authStore.staffArea === 'finance') : null)

type CustomerRow = { organization_id: string, organization_name: string, primary_contact_name: string | null, primary_contact_email: string | null }
type EntityRow = { id: string, organization_id: string, name: string, status: string }

const customers = ref<CustomerRow[]>([])
const customerSearch = ref('')
const customerSearchLoading = ref(false)
let customerSearchTimer: ReturnType<typeof setTimeout> | undefined

const entities = ref<EntityRow[]>([])
const selectedOrgId = ref<string | null>(null)
const selectedEntityId = ref<string | null>(null)
const amount = ref<number | null>(null)
const generateInvoice = ref(true)
const notes = ref('')

const submitting = ref(false)
const error = ref('')
const result = ref<{ credits_added: number, available_balance: number, invoice: { status: string, invoice_number: string | null, id: string } | null } | null>(null)

function customerLabel(customer: CustomerRow): string {
  const who = customer.primary_contact_name || customer.primary_contact_email || 'Unknown contact'
  return `${who} — ${customer.organization_name}`
}

async function searchCustomers(query: string) {
  customerSearchLoading.value = true
  try {
    customers.value = await $api<CustomerRow[]>('/v1/admin/customers', { query: query ? { search: query } : {} })
  }
  catch (err: any) {
    error.value = extractErrorMessage(err, 'Could not search customers.')
  }
  finally {
    customerSearchLoading.value = false
  }
}

watch(customerSearch, query => {
  clearTimeout(customerSearchTimer)
  customerSearchTimer = setTimeout(() => searchCustomers(query), 300)
})

watch(selectedOrgId, async orgId => {
  selectedEntityId.value = null
  entities.value = []
  if (!orgId)
    return
  try {
    entities.value = await $api<EntityRow[]>('/v1/admin/entities', { query: { organization_id: orgId } })
    if (entities.value.length === 1)
      selectedEntityId.value = entities.value[0].id
  }
  catch (err: any) {
    error.value = extractErrorMessage(err, 'Could not load entities for this organization.')
  }
})

async function loadOrgs() {
  error.value = ''
  await authStore.load()
  if (!(authStore.isAdmin || authStore.staffArea === 'finance'))
    return
  await searchCustomers('')
}

async function onSubmit() {
  error.value = ''
  result.value = null
  if (!selectedEntityId.value || !amount.value) {
    error.value = 'Select an entity and enter an amount.'
    return
  }
  submitting.value = true
  try {
    result.value = await $api(`/v1/admin/wallet-credits`, {
      method: 'POST',
      body: { entity_id: selectedEntityId.value, amount: amount.value, generate_invoice: generateInvoice.value, notes: notes.value || null },
    })
    amount.value = null
    notes.value = ''
  }
  catch (err: any) {
    error.value = extractErrorMessage(err, 'Could not credit this wallet.')
  }
  finally {
    submitting.value = false
  }
}

onMounted(loadOrgs)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Wallet Credits
  </h1>
  <p class="text-medium-emphasis mb-6">
    Manually add SMS credits to a customer's wallet. Every credit creates an invoice for
    accounting/GST traceability — issue it now, or save it as a draft to issue later from
    Invoices.
  </p>

  <VAlert
    v-if="hasAccess === false"
    type="warning"
    variant="tonal"
  >
    This page is restricted to Super Admin, Operator Admin, and Finance Team roles.
  </VAlert>

  <VCard
    v-else-if="hasAccess"
    max-width="640"
  >
    <VCardText>
      <VAlert
        v-if="error"
        type="error"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        {{ error }}
      </VAlert>
      <VAlert
        v-if="result"
        type="success"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        Credited {{ result.credits_added }} SMS credits. New balance: {{ result.available_balance }}.
        <span v-if="result.invoice">
          Invoice {{ result.invoice.status === 'issued' ? result.invoice.invoice_number : '(saved as draft — issue later from Invoices)' }}.
        </span>
      </VAlert>

      <VForm @submit.prevent="onSubmit">
        <VAutocomplete
          v-model="selectedOrgId"
          v-model:search="customerSearch"
          :items="customers"
          :item-title="customerLabel"
          item-value="organization_id"
          label="Customer"
          placeholder="Search by name, email, or organization"
          :loading="customerSearchLoading"
          no-filter
          class="mb-4"
        />
        <VSelect
          v-model="selectedEntityId"
          :items="entities"
          item-title="name"
          item-value="id"
          label="Entity"
          :disabled="!entities.length"
          class="mb-4"
        />
        <AppTextField
          v-model.number="amount"
          type="number"
          label="Amount to credit (₹)"
          placeholder="500"
          class="mb-4"
        />
        <AppTextField
          v-model="notes"
          label="Notes (optional)"
          placeholder="Reason for this credit"
          class="mb-4"
        />
        <VSwitch
          v-model="generateInvoice"
          label="Issue invoice immediately"
          color="success"
          class="mb-4"
        />
        <VBtn
          type="submit"
          :loading="submitting"
        >
          Credit Wallet
        </VBtn>
      </VForm>
    </VCardText>
  </VCard>
</template>
