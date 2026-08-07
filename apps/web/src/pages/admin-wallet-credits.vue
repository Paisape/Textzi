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
type WalletSummary = { entity_id: string, prepaid_balance: number, credit_limit: number, credit_used: number, available_balance: number }
type AdjustmentQuote = { credits: number, price_per_sms: number }

const customers = ref<CustomerRow[]>([])
const customerSearch = ref('')
const customerSearchLoading = ref(false)
let customerSearchTimer: ReturnType<typeof setTimeout> | undefined

const entities = ref<EntityRow[]>([])
const selectedOrgId = ref<string | null>(null)
const selectedEntityId = ref<string | null>(null)

const direction = ref<'credit' | 'debit'>('credit')
const amount = ref<number | null>(null)
const generateInvoice = ref(false)
const paid = ref(true)
const notes = ref('')

const walletSummary = ref<WalletSummary | null>(null)
const walletSummaryLoading = ref(false)

const quote = ref<AdjustmentQuote | null>(null)
const quoteLoading = ref(false)
const quoteError = ref('')
let quoteTimer: ReturnType<typeof setTimeout> | undefined

const projectedBalance = computed(() => {
  if (!walletSummary.value || !quote.value)
    return null
  const delta = direction.value === 'credit' ? quote.value.credits : -quote.value.credits
  return walletSummary.value.available_balance + delta
})

const submitting = ref(false)
const error = ref('')
const creditResult = ref<{ credits_added: number, available_balance: number, invoice: { status: string, invoice_number: string | null, id: string } | null } | null>(null)
const debitResult = ref<{ credits_debited: number, available_balance: number } | null>(null)

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

async function loadWalletSummary(entityId: string) {
  walletSummaryLoading.value = true
  walletSummary.value = null
  try {
    walletSummary.value = await $api<WalletSummary>(`/v1/admin/entities/${entityId}/wallet-summary`)
  }
  catch (err: any) {
    error.value = extractErrorMessage(err, 'Could not load this entity\'s wallet balance.')
  }
  finally {
    walletSummaryLoading.value = false
  }
}

watch(selectedEntityId, entityId => {
  quote.value = null
  if (entityId)
    loadWalletSummary(entityId)
  else
    walletSummary.value = null
})

async function loadQuote() {
  if (!selectedEntityId.value || !amount.value || amount.value <= 0) {
    quote.value = null
    return
  }
  quoteError.value = ''
  quoteLoading.value = true
  try {
    quote.value = await $api<AdjustmentQuote>('/v1/admin/wallet-credits/quote', {
      query: { entity_id: selectedEntityId.value, amount: amount.value },
    })
  }
  catch (err: any) {
    quote.value = null
    quoteError.value = extractErrorMessage(err, 'Could not calculate credits for this amount.')
  }
  finally {
    quoteLoading.value = false
  }
}

watch([amount, selectedEntityId], () => {
  clearTimeout(quoteTimer)
  quoteTimer = setTimeout(loadQuote, 300)
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
  creditResult.value = null
  debitResult.value = null
  if (!selectedEntityId.value || !amount.value) {
    error.value = 'Select an entity and enter an amount.'
    return
  }
  submitting.value = true
  try {
    if (direction.value === 'credit') {
      creditResult.value = await $api(`/v1/admin/wallet-credits`, {
        method: 'POST',
        body: { entity_id: selectedEntityId.value, amount: amount.value, generate_invoice: generateInvoice.value, paid: paid.value, notes: notes.value || null },
      })
    }
    else {
      debitResult.value = await $api(`/v1/admin/wallet-debits`, {
        method: 'POST',
        body: { entity_id: selectedEntityId.value, amount: amount.value, notes: notes.value || null },
      })
    }
    amount.value = null
    notes.value = ''
    quote.value = null
    if (selectedEntityId.value)
      await loadWalletSummary(selectedEntityId.value)
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
    Wallet Credits &amp; Debits
  </h1>
  <p class="text-medium-emphasis mb-6">
    Manually adjust a customer's SMS wallet. A credit creates an invoice for accounting/GST
    traceability — issue it now, or save it as a draft to approve or reject later from Invoices. A
    debit is a direct correction with no invoice or Zoho involvement.
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
        v-if="creditResult"
        type="success"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        Credited {{ creditResult.credits_added }} SMS credits. New balance: {{ creditResult.available_balance }}.
        <span v-if="creditResult.invoice">
          Invoice {{ creditResult.invoice.status === 'issued' ? creditResult.invoice.invoice_number : '(saved as draft — approve or reject later from Invoices)' }}.
        </span>
      </VAlert>
      <VAlert
        v-if="debitResult"
        type="success"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        Debited {{ debitResult.credits_debited }} SMS credits. New balance: {{ debitResult.available_balance }}.
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
          <div v-if="walletSummaryLoading" class="text-body-2 text-medium-emphasis">
            Loading current balance…
          </div>
          <div v-else-if="walletSummary" class="text-body-2">
            <div>
              Current balance: <span class="font-weight-medium">{{ walletSummary.available_balance.toLocaleString('en-IN') }} credits</span>
              <span class="text-medium-emphasis"> ({{ walletSummary.prepaid_balance.toLocaleString('en-IN') }} prepaid + {{ Math.max(0, walletSummary.credit_limit - walletSummary.credit_used).toLocaleString('en-IN') }} credit headroom)</span>
            </div>
            <div v-if="quote">
              This {{ direction }} of ₹{{ amount }} ≈ <span class="font-weight-medium">{{ quote.credits.toLocaleString('en-IN') }} credits</span>
              at ₹{{ quote.price_per_sms }}/SMS.
              <span v-if="projectedBalance !== null">
                New balance would be <span class="font-weight-medium">{{ projectedBalance.toLocaleString('en-IN') }} credits</span>.
              </span>
            </div>
            <div v-else-if="quoteLoading" class="text-medium-emphasis">
              Calculating…
            </div>
            <div v-else-if="quoteError" class="text-error">
              {{ quoteError }}
            </div>
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

        <template v-if="direction === 'credit'">
          <VSwitch
            v-model="generateInvoice"
            label="Issue invoice immediately"
            color="success"
            class="mb-2"
          />
          <p class="text-body-2 text-medium-emphasis mb-4">
            Leave this off to have the invoice start as a draft you approve or reject later from
            <RouterLink to="/admin-invoices">Invoices</RouterLink>.
          </p>
          <VBtnToggle
            v-model="paid"
            mandatory
            color="primary"
            density="comfortable"
            class="mb-4"
          >
            <VBtn :value="true">
              Paid
            </VBtn>
            <VBtn :value="false">
              Unpaid
            </VBtn>
          </VBtnToggle>
          <p class="text-caption text-medium-emphasis mb-4" style="margin-block-start: -12px;">
            Paid reconciles this invoice against a Customer Payment in Zoho Books (e.g. money
            already collected outside Razorpay). Unpaid issues the invoice but leaves it
            outstanding in Zoho Books — use this for a free/promotional credit with no real payment.
          </p>
        </template>
        <p v-else class="text-body-2 text-medium-emphasis mb-4">
          No invoice is created for a debit — it's a direct correction, logged to the audit trail.
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
