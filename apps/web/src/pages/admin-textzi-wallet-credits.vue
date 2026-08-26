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
type BalanceResult = { entity_id: string, balance: number }

const customers = ref<CustomerRow[]>([])
const customerSearch = ref('')
const customerSearchLoading = ref(false)
let customerSearchTimer: ReturnType<typeof setTimeout> | undefined

const entities = ref<EntityRow[]>([])
const selectedOrgId = ref<string | null>(null)
const selectedEntityId = ref<string | null>(null)

const direction = ref<'credit' | 'debit'>('credit')
const amount = ref<number | null>(null)
const notes = ref('')

const currentBalance = ref<number | null>(null)
const balanceLoading = ref(false)

const submitting = ref(false)
const error = ref('')
const result = ref<{ amount: number, balance: number } | null>(null)

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

async function loadBalance(entityId: string) {
  balanceLoading.value = true
  currentBalance.value = null
  try {
    const balanceResult = await $api<BalanceResult>(`/v1/admin/textzi-wallet/entities/${entityId}/balance`)
    currentBalance.value = balanceResult.balance
  }
  catch (err: any) {
    error.value = extractErrorMessage(err, 'Could not load this entity\'s Textzi Wallet balance.')
  }
  finally {
    balanceLoading.value = false
  }
}

watch(selectedEntityId, entityId => {
  if (entityId)
    loadBalance(entityId)
  else
    currentBalance.value = null
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
    const response = await $api<{ entity_id: string, amount: number, balance: number }>(`/v1/admin/textzi-wallet/${direction.value}`, {
      method: 'POST',
      body: { entity_id: selectedEntityId.value, amount: amount.value, notes: notes.value || null },
    })
    result.value = { amount: response.amount, balance: response.balance }
    currentBalance.value = response.balance
    amount.value = null
    notes.value = ''
  }
  catch (err: any) {
    error.value = extractErrorMessage(err, direction.value === 'credit' ? 'Could not credit this wallet.' : 'Could not debit this wallet.')
  }
  finally {
    submitting.value = false
  }
}

onMounted(loadOrgs)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Textzi Wallet Credits &amp; Debits
  </h1>
  <p class="text-medium-emphasis mb-6">
    Manually adjust a customer's Textzi Wallet (the rupee-balance wallet funded by Smart Collect
    or a verified bank transfer) — no invoice is generated for either direction.
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
        {{ direction === 'credit' ? 'Credited' : 'Debited' }} ₹{{ result.amount.toLocaleString('en-IN') }}. New balance: ₹{{ result.balance.toLocaleString('en-IN') }}.
      </VAlert>

      <VForm @submit.prevent="onSubmit">
        <VBtnToggle
          v-model="direction"
          mandatory
          color="primary"
          density="comfortable"
          class="mb-4"
        >
          <VBtn value="credit">
            Credit
          </VBtn>
          <VBtn value="debit">
            Debit
          </VBtn>
        </VBtnToggle>

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

        <VCard
          v-if="selectedEntityId"
          variant="tonal"
          color="secondary"
          class="mb-4 pa-3"
        >
          <div v-if="balanceLoading" class="text-body-2 text-medium-emphasis">
            Loading current balance…
          </div>
          <div v-else-if="currentBalance !== null" class="text-body-2">
            Current balance: <span class="font-weight-medium">₹{{ currentBalance.toLocaleString('en-IN') }}</span>
          </div>
        </VCard>

        <AppTextField
          v-model.number="amount"
          type="number"
          :label="direction === 'credit' ? 'Amount to credit (₹)' : 'Amount to debit (₹)'"
          placeholder="500"
          class="mb-4"
        />
        <AppTextField
          v-model="notes"
          label="Notes (optional)"
          :placeholder="direction === 'credit' ? 'Reason for this credit' : 'Reason for this debit'"
          class="mb-4"
        />

        <p class="text-body-2 text-medium-emphasis mb-4">
          {{ direction === 'credit' ? 'No invoice is created — this is a direct wallet credit, logged to the audit trail.' : 'No invoice is created — this is a direct correction, logged to the audit trail.' }}
        </p>

        <VBtn
          type="submit"
          :color="direction === 'debit' ? 'error' : undefined"
          :loading="submitting"
        >
          {{ direction === 'credit' ? 'Credit Wallet' : 'Debit Wallet' }}
        </VBtn>
      </VForm>
    </VCardText>
  </VCard>
</template>
