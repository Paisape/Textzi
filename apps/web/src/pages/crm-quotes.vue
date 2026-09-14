<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

type CrmContact = { id: string, name: string | null, phone: string | null, email: string | null }
type Deal = { id: string, contact: CrmContact, stage: string, status: string }
type LineItem = { description: string, hsn_code: string, quantity: number, unit_price: number, product_id?: string | null, tax_rate?: number | null, discount_percent?: number }
type Quote = {
  id: string
  deal_id: string
  quote_number: string | null
  line_items: LineItem[]
  status: 'draft' | 'sent' | 'accepted' | 'rejected'
  subtotal: number
  discount_total: number
  cgst: number
  sgst: number
  igst: number
  total: number
  has_pdf: boolean
  approval_status: 'not_required' | 'pending' | 'approved' | 'rejected'
  approvals: { user_id: string, approved_at: string }[]
  approvers_required: string[]
  converted_invoice_id: string | null
  created_at: string
  sent_at: string | null
  signed_by_name: string | null
  signed_at: string | null
}
type SalesInvoice = {
  id: string
  deal_id: string
  quote_id: string | null
  invoice_number: string | null
  status: 'issued' | 'partially_paid' | 'paid' | 'cancelled'
  total: number
  amount_paid: number
  balance_due: number
  has_pdf: boolean
  created_at: string
  sent_at: string | null
  paid_at: string | null
}

const route = useRoute()
const authStore = useAuthStore()
type Product = { id: string, name: string, sku: string | null, hsn_code: string, unit_price: number, tax_rate: number | null, category: string | null, is_bundle: boolean, active: boolean }

const quotes = ref<Quote[]>([])
const salesInvoices = ref<SalesInvoice[]>([])
const deals = ref<Deal[]>([])
const products = ref<Product[]>([])
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)
const crmInactiveMessage = ref('')
const actionError = ref('')
const busy = ref<string | null>(null)
const pendingMyApprovalOnly = ref(false)

function approvalProgress(quote: Quote) {
  if (!quote.approvers_required.length)
    return null
  return `${quote.approvals.length}/${quote.approvers_required.length} approved`
}

function iHaveApproved(quote: Quote) {
  return quote.approvals.some(a => a.user_id === authStore.profile?.id)
}

function iCanApprove(quote: Quote) {
  if (quote.approval_status !== 'pending')
    return false
  if (!quote.approvers_required.length)
    return true
  return quote.approvers_required.includes(authStore.profile?.id || '') && !iHaveApproved(quote)
}

const visibleQuotes = computed(() => pendingMyApprovalOnly.value ? quotes.value.filter(iCanApprove) : quotes.value)

function dealContactLabel(dealId: string) {
  const deal = deals.value.find(d => d.id === dealId)
  return deal ? (deal.contact.name || deal.contact.phone || deal.contact.email || 'Unknown') : '…'
}

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    const [quoteResult, invoiceResult, dealResult, productResult] = await Promise.all([
      $api<Quote[]>('/v1/crm/quotes'),
      $api<SalesInvoice[]>('/v1/crm/quotes/invoices'),
      $api<Deal[]>('/v1/crm/deals'),
      $api<Product[]>('/v1/crm/quotes/products'),
    ])
    quotes.value = quoteResult
    salesInvoices.value = invoiceResult
    deals.value = dealResult
    products.value = productResult.filter(p => p.active)
  }
  catch (error: any) {
    if (error?.response?.status === 422) {
      crmInactive.value = true
      // The backend's own detail text already distinguishes "CRM plan not active" from "this plan
      // doesn't include this feature" (require_plan_feature vs. the whole-channel gate) -- show it
      // verbatim instead of a hardcoded message written before per-feature gating existed.
      crmInactiveMessage.value = extractErrorMessage(error, 'Upgrade your CRM plan to use this feature.')
    }
    else {
      loadError.value = extractErrorMessage(error, 'Could not load quotes.')
    }
  }
  finally {
    loading.value = false
  }
}

function inr(value: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(value)
}

const statusColor: Record<string, string> = { draft: undefined as any, sent: 'info', accepted: 'success', rejected: 'error' }

// --- Create dialog -------------------------------------------------------------------------

const dialog = ref(false)
const form = reactive({ deal_id: '', line_items: [{ description: '', hsn_code: '', quantity: 1, unit_price: 0 }] as LineItem[] })
const saving = ref(false)
const saveError = ref('')
const editingQuoteId = ref<string | null>(null)

function openCreate() {
  editingQuoteId.value = null
  form.deal_id = typeof route.query.deal_id === 'string' ? route.query.deal_id : ''
  form.line_items = [{ description: '', hsn_code: '', quantity: 1, unit_price: 0 }]
  saveError.value = ''
  dialog.value = true
}

function openEdit(quote: Quote) {
  editingQuoteId.value = quote.id
  form.deal_id = quote.deal_id
  form.line_items = quote.line_items.map(item => ({ ...item }))
  saveError.value = ''
  dialog.value = true
}

function addLine() {
  form.line_items.push({ description: '', hsn_code: '', quantity: 1, unit_price: 0 })
}

function removeLine(index: number) {
  if (form.line_items.length > 1)
    form.line_items.splice(index, 1)
}

function pickProduct(item: LineItem, productId: string | null) {
  item.product_id = productId
  const product = products.value.find(p => p.id === productId)
  if (product) {
    item.description = product.name
    item.hsn_code = product.hsn_code
    // A bundle's own price/tax are meaningless (0/null on the Product row) -- the backend expands
    // this single line into one real, individually-priced line per component on save, so the
    // draft-total preview below is deliberately not accurate for a bundle line until then.
    item.unit_price = product.is_bundle ? 0 : product.unit_price
    item.tax_rate = product.is_bundle ? null : product.tax_rate
  }
}

function isBundleLine(item: LineItem) {
  return !!item.product_id && products.value.find(p => p.id === item.product_id)?.is_bundle
}

const draftTotal = computed(() => form.line_items.reduce((sum, item) => sum + (item.quantity || 0) * (item.unit_price || 0), 0))

async function save() {
  if (!form.deal_id || !form.line_items.length)
    return
  saving.value = true
  saveError.value = ''
  try {
    if (editingQuoteId.value) {
      const updated = await $api<Quote>(`/v1/crm/quotes/${editingQuoteId.value}`, { method: 'PATCH', body: { line_items: form.line_items } })
      const index = quotes.value.findIndex(q => q.id === editingQuoteId.value)
      if (index !== -1)
        quotes.value[index] = updated
    }
    else {
      const created = await $api<Quote>('/v1/crm/quotes', { method: 'POST', body: { deal_id: form.deal_id, line_items: form.line_items } })
      quotes.value.unshift(created)
    }
    dialog.value = false
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save this quote.')
  }
  finally {
    saving.value = false
  }
}

// --- Actions ---------------------------------------------------------------------------------

async function removeQuote(quote: Quote) {
  busy.value = quote.id
  try {
    await $api(`/v1/crm/quotes/${quote.id}`, { method: 'DELETE' })
    quotes.value = quotes.value.filter(q => q.id !== quote.id)
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not delete this quote.')
  }
  finally {
    busy.value = null
  }
}

async function approveQuote(quote: Quote) {
  busy.value = quote.id
  try {
    const updated = await $api<Quote>(`/v1/crm/quotes/${quote.id}/approve`, { method: 'POST' })
    Object.assign(quote, updated)
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not approve this quote.')
  }
  finally {
    busy.value = null
  }
}

async function downloadPdf(quote: Quote) {
  busy.value = quote.id
  actionError.value = ''
  try {
    const blob = await $api<Blob, 'blob'>(`/v1/crm/quotes/${quote.id}/pdf`, { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${quote.quote_number || quote.id}.pdf`
    link.click()
    URL.revokeObjectURL(url)
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not download this quote.')
  }
  finally {
    busy.value = null
  }
}

async function sendWhatsapp(quote: Quote) {
  busy.value = quote.id
  actionError.value = ''
  try {
    const updated = await $api<Quote>(`/v1/crm/quotes/${quote.id}/send-whatsapp`, { method: 'POST' })
    Object.assign(quote, updated)
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not send this quote via WhatsApp.')
  }
  finally {
    busy.value = null
  }
}

async function setStatus(quote: Quote, status: 'accepted' | 'rejected') {
  busy.value = quote.id
  try {
    const updated = await $api<Quote>(`/v1/crm/quotes/${quote.id}/status/${status}`, { method: 'POST' })
    Object.assign(quote, updated)
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not update this quote\'s status.')
  }
  finally {
    busy.value = null
  }
}

function invoiceForQuote(quote: Quote) {
  return salesInvoices.value.find(i => i.id === quote.converted_invoice_id)
}

async function convertToInvoice(quote: Quote) {
  busy.value = quote.id
  actionError.value = ''
  try {
    const invoice = await $api<SalesInvoice>(`/v1/crm/quotes/${quote.id}/convert-to-invoice`, { method: 'POST' })
    salesInvoices.value.unshift(invoice)
    quote.converted_invoice_id = invoice.id
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not issue a tax invoice for this quote.')
  }
  finally {
    busy.value = null
  }
}

async function downloadInvoicePdf(invoice: SalesInvoice) {
  busy.value = invoice.id
  actionError.value = ''
  try {
    const blob = await $api<Blob, 'blob'>(`/v1/crm/quotes/invoices/${invoice.id}/pdf`, { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${invoice.invoice_number || invoice.id}.pdf`
    link.click()
    URL.revokeObjectURL(url)
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not download this invoice.')
  }
  finally {
    busy.value = null
  }
}

async function sendInvoiceWhatsapp(invoice: SalesInvoice) {
  busy.value = invoice.id
  actionError.value = ''
  try {
    const updated = await $api<SalesInvoice>(`/v1/crm/quotes/invoices/${invoice.id}/send-whatsapp`, { method: 'POST' })
    Object.assign(invoice, updated)
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not send this invoice via WhatsApp.')
  }
  finally {
    busy.value = null
  }
}

const recordPaymentDialog = ref(false)
const recordPaymentInvoice = ref<SalesInvoice | null>(null)
const recordPaymentAmount = ref<number | null>(null)
const recordPaymentError = ref('')

function openRecordPayment(invoice: SalesInvoice) {
  recordPaymentInvoice.value = invoice
  recordPaymentAmount.value = invoice.balance_due
  recordPaymentError.value = ''
  recordPaymentDialog.value = true
}

async function confirmRecordPayment() {
  if (!recordPaymentInvoice.value || !recordPaymentAmount.value)
    return
  busy.value = recordPaymentInvoice.value.id
  recordPaymentError.value = ''
  try {
    const updated = await $api<SalesInvoice>(`/v1/crm/quotes/invoices/${recordPaymentInvoice.value.id}/record-payment`, { method: 'POST', body: { amount: recordPaymentAmount.value } })
    Object.assign(recordPaymentInvoice.value, updated)
    recordPaymentDialog.value = false
  }
  catch (error: any) {
    recordPaymentError.value = extractErrorMessage(error, 'Could not record this payment.')
  }
  finally {
    busy.value = null
  }
}

const cancelInvoiceDialog = ref(false)
const cancelInvoiceTarget = ref<SalesInvoice | null>(null)
const cancelInvoiceReason = ref('')
const cancelInvoiceError = ref('')

function openCancelInvoice(invoice: SalesInvoice) {
  cancelInvoiceTarget.value = invoice
  cancelInvoiceReason.value = ''
  cancelInvoiceError.value = ''
  cancelInvoiceDialog.value = true
}

async function confirmCancelInvoice() {
  if (!cancelInvoiceTarget.value || cancelInvoiceReason.value.trim().length < 3)
    return
  busy.value = cancelInvoiceTarget.value.id
  cancelInvoiceError.value = ''
  try {
    const updated = await $api<SalesInvoice>(`/v1/crm/quotes/invoices/${cancelInvoiceTarget.value.id}/cancel`, { method: 'POST', body: { reason: cancelInvoiceReason.value.trim() } })
    Object.assign(cancelInvoiceTarget.value, updated)
    cancelInvoiceDialog.value = false
  }
  catch (error: any) {
    cancelInvoiceError.value = extractErrorMessage(error, 'Could not cancel this invoice.')
  }
  finally {
    busy.value = null
  }
}

onMounted(async () => {
  await loadAll()
  if (typeof route.query.deal_id === 'string')
    openCreate()
})
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-1">
    <div>
      <h1 class="text-h4 mb-1">
        Quotes
      </h1>
      <p class="text-medium-emphasis">
        GST-compliant proforma quotes tied to a deal — send via WhatsApp, then convert to an invoice once accepted.
      </p>
    </div>
    <div class="d-flex align-center gap-4">
      <VCheckbox v-model="pendingMyApprovalOnly" label="Pending my approval" density="compact" hide-details />
      <VBtn color="primary" prepend-icon="tabler-plus" @click="openCreate">
        New quote
      </VBtn>
    </div>
  </div>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    {{ crmInactiveMessage }}
    <RouterLink to="/channels-crm?tab=billing" class="font-weight-medium">
      View plans
    </RouterLink>
  </VAlert>
  <VAlert v-else-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>
  <VAlert v-if="actionError" type="error" variant="tonal" class="mb-4" closable @click:close="actionError = ''">
    {{ actionError }}
  </VAlert>

  <VCard v-if="!crmInactive">
    <VTable>
      <thead>
        <tr>
          <th>Quote #</th>
          <th>Deal</th>
          <th>Total</th>
          <th>Status</th>
          <th>Approval</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr v-for="quote in visibleQuotes" :key="quote.id">
          <td>
            <span v-if="quote.quote_number">{{ quote.quote_number }}</span>
            <span v-else class="text-medium-emphasis font-italic">Not yet numbered</span>
          </td>
          <td>{{ dealContactLabel(quote.deal_id) }}</td>
          <td>
            {{ inr(quote.total) }}
            <p v-if="quote.discount_total" class="text-caption text-medium-emphasis mb-0">
              {{ inr(quote.discount_total) }} discount applied
            </p>
          </td>
          <td>
            <VChip size="small" :color="statusColor[quote.status]">
              {{ quote.status }}
            </VChip>
            <p v-if="quote.signed_by_name" class="text-caption text-medium-emphasis mb-0 mt-1">
              Signed by {{ quote.signed_by_name }}
            </p>
          </td>
          <td>
            <div v-if="quote.approval_status !== 'not_required'" class="d-flex align-center ga-1">
              <VChip size="small" :color="quote.approval_status === 'pending' ? 'warning' : quote.approval_status === 'approved' ? 'success' : 'error'" variant="tonal">
                {{ quote.approval_status }}
              </VChip>
              <span v-if="approvalProgress(quote)" class="text-caption text-medium-emphasis">{{ approvalProgress(quote) }}</span>
            </div>
            <span v-else class="text-medium-emphasis">—</span>
          </td>
          <td>
            <div class="d-flex ga-1 flex-wrap justify-end align-center">
              <VBtn icon="tabler-download" size="small" variant="text" :loading="busy === quote.id" title="Download PDF" @click="downloadPdf(quote)" />
              <VBtn v-if="quote.status === 'draft'" icon="tabler-pencil" size="small" variant="text" title="Edit line items" @click="openEdit(quote)" />
              <VBtn v-if="iCanApprove(quote)" icon="tabler-circle-check" size="small" variant="text" color="success" :loading="busy === quote.id" title="Approve" @click="approveQuote(quote)" />
              <VBtn
                v-if="quote.status === 'draft' && quote.approval_status !== 'pending'"
                icon="tabler-brand-whatsapp" size="small" variant="text" color="success" :loading="busy === quote.id" title="Send via WhatsApp" @click="sendWhatsapp(quote)"
              />
              <VBtn v-if="quote.status !== 'accepted' && quote.status !== 'rejected'" icon="tabler-check" size="small" variant="text" color="success" :loading="busy === quote.id" title="Mark accepted" @click="setStatus(quote, 'accepted')" />
              <VBtn v-if="quote.status !== 'accepted' && quote.status !== 'rejected'" icon="tabler-x" size="small" variant="text" color="error" :loading="busy === quote.id" title="Mark rejected" @click="setStatus(quote, 'rejected')" />
              <VBtn v-if="quote.status === 'accepted' && !quote.converted_invoice_id" size="small" variant="tonal" color="primary" :loading="busy === quote.id" @click="convertToInvoice(quote)">
                Issue tax invoice
              </VBtn>
              <template v-if="quote.converted_invoice_id && invoiceForQuote(quote)">
                <VChip size="small" :color="invoiceForQuote(quote)!.status === 'paid' ? 'success' : invoiceForQuote(quote)!.status === 'cancelled' ? 'error' : invoiceForQuote(quote)!.status === 'partially_paid' ? 'warning' : 'default'" variant="tonal">
                  {{ invoiceForQuote(quote)!.invoice_number }} · {{ invoiceForQuote(quote)!.status.replace('_', ' ') }}
                </VChip>
                <VBtn icon="tabler-download" size="small" variant="text" :loading="busy === invoiceForQuote(quote)!.id" title="Download tax invoice" @click="downloadInvoicePdf(invoiceForQuote(quote)!)" />
                <VBtn icon="tabler-brand-whatsapp" size="small" variant="text" color="success" :loading="busy === invoiceForQuote(quote)!.id" title="Send tax invoice via WhatsApp" @click="sendInvoiceWhatsapp(invoiceForQuote(quote)!)" />
                <VBtn v-if="!['paid', 'cancelled'].includes(invoiceForQuote(quote)!.status)" icon="tabler-cash" size="small" variant="text" color="success" :loading="busy === invoiceForQuote(quote)!.id" title="Record payment" @click="openRecordPayment(invoiceForQuote(quote)!)" />
                <VBtn v-if="invoiceForQuote(quote)!.status !== 'cancelled'" icon="tabler-ban" size="small" variant="text" color="error" :loading="busy === invoiceForQuote(quote)!.id" title="Cancel (issues a credit note)" @click="openCancelInvoice(invoiceForQuote(quote)!)" />
              </template>
              <VBtn v-if="quote.status === 'draft'" icon="tabler-trash" size="small" variant="text" :loading="busy === quote.id" title="Delete" @click="removeQuote(quote)" />
            </div>
          </td>
        </tr>
      </tbody>
    </VTable>
    <p v-if="!loading && !visibleQuotes.length" class="text-medium-emphasis text-center pa-6">
      {{ pendingMyApprovalOnly ? 'Nothing waiting on your approval.' : 'No quotes yet.' }}
    </p>
  </VCard>

  <VDialog v-model="dialog" max-width="640" persistent>
    <VCard :title="editingQuoteId ? 'Edit quote' : 'New quote'">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="dialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="saveError" type="error" variant="tonal" density="compact">
          {{ saveError }}
        </VAlert>
        <VSelect
          v-model="form.deal_id" :disabled="!!editingQuoteId"
          :items="deals.filter(d => d.status === 'open').map(d => ({ title: d.contact.name || d.contact.phone || d.contact.email || 'Unknown', value: d.id }))"
          label="Deal" density="compact"
        />

        <div>
          <div class="d-flex align-center justify-space-between mb-2">
            <span class="text-subtitle-2">Line items</span>
            <VBtn size="small" variant="text" prepend-icon="tabler-plus" @click="addLine">
              Add line
            </VBtn>
          </div>
          <div v-for="(item, index) in form.line_items" :key="index" class="mb-2">
            <div class="d-flex ga-2 align-center">
              <VSelect
                v-if="products.length"
                :model-value="item.product_id" placeholder="Pick a product (optional)" density="compact" hide-details clearable
                style="max-width: 160px;" :items="products.map(p => ({ title: p.is_bundle ? `${p.name} (bundle)` : p.name, value: p.id }))"
                @update:model-value="(v: string | null) => pickProduct(item, v)"
              />
              <VTextField v-model="item.description" placeholder="Description" density="compact" hide-details style="flex: 2;" />
              <VTextField v-model="item.hsn_code" placeholder="HSN" density="compact" hide-details style="max-width: 90px;" :disabled="isBundleLine(item)" />
              <VTextField v-model.number="item.quantity" type="number" placeholder="Qty" density="compact" hide-details style="max-width: 80px;" />
              <VTextField v-model.number="item.unit_price" type="number" placeholder="Unit price" density="compact" hide-details style="max-width: 110px;" :disabled="isBundleLine(item)" />
              <VBtn icon="tabler-x" size="small" variant="text" :disabled="form.line_items.length === 1" @click="removeLine(index)" />
            </div>
            <p v-if="isBundleLine(item)" class="text-caption text-medium-emphasis mb-0 mt-1">
              This bundle expands into one priced line per component when you save.
            </p>
          </div>
          <p class="text-caption text-medium-emphasis text-end mb-0">
            Subtotal (before GST): {{ inr(draftTotal) }}
          </p>
        </div>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="dialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="saving" :disabled="!form.deal_id" @click="save">
          {{ editingQuoteId ? 'Save' : 'Create' }}
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="recordPaymentDialog" max-width="360" persistent>
    <VCard title="Record a payment">
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="recordPaymentError" type="error" variant="tonal" density="compact">
          {{ recordPaymentError }}
        </VAlert>
        <p v-if="recordPaymentInvoice" class="text-body-2 text-medium-emphasis mb-0">
          Balance due: {{ inr(recordPaymentInvoice.balance_due) }}
        </p>
        <VTextField v-model.number="recordPaymentAmount" label="Amount received" type="number" min="0.01" density="compact" autofocus />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="recordPaymentDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="!!busy" :disabled="!recordPaymentAmount || recordPaymentAmount <= 0" @click="confirmRecordPayment">
          Record
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="cancelInvoiceDialog" max-width="420" persistent>
    <VCard title="Cancel this tax invoice">
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="cancelInvoiceError" type="error" variant="tonal" density="compact">
          {{ cancelInvoiceError }}
        </VAlert>
        <p class="text-body-2 text-medium-emphasis mb-0">
          A credit note will be issued for the full invoice amount. The original invoice number stays valid and unchanged, as required by GST law.
        </p>
        <VTextField v-model="cancelInvoiceReason" label="Reason" density="compact" autofocus />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="cancelInvoiceDialog = false">
          Keep invoice
        </VBtn>
        <VBtn color="error" :loading="!!busy" :disabled="cancelInvoiceReason.trim().length < 3" @click="confirmCancelInvoice">
          Cancel & issue credit note
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
