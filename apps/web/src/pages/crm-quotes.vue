<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type Contact = { id: string, wa_id: string | null, email: string | null, name: string | null }
type Lead = { id: string, contact: Contact, stage: string, status: string }
type LineItem = { description: string, hsn_code: string, quantity: number, unit_price: number }
type Quote = {
  id: string
  lead_id: string
  quote_number: string | null
  line_items: LineItem[]
  status: 'draft' | 'sent' | 'accepted' | 'rejected'
  subtotal: number
  cgst: number
  sgst: number
  igst: number
  total: number
  has_pdf: boolean
  approval_status: 'not_required' | 'pending' | 'approved' | 'rejected'
  converted_invoice_id: string | null
  created_at: string
  sent_at: string | null
}

const quotes = ref<Quote[]>([])
const leads = ref<Lead[]>([])
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)
const actionError = ref('')
const busy = ref<string | null>(null)

function leadContactLabel(leadId: string) {
  const lead = leads.value.find(l => l.id === leadId)
  return lead ? (lead.contact.name || lead.contact.wa_id || lead.contact.email || 'Unknown') : '…'
}

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    const [quoteResult, leadResult] = await Promise.all([
      $api<Quote[]>('/v1/crm/quotes'),
      $api<Lead[]>('/v1/crm/leads'),
    ])
    quotes.value = quoteResult
    leads.value = leadResult
  }
  catch (error: any) {
    if (error?.response?.status === 422)
      crmInactive.value = true
    else
      loadError.value = extractErrorMessage(error, 'Could not load quotes.')
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
const form = reactive({ lead_id: '', line_items: [{ description: '', hsn_code: '', quantity: 1, unit_price: 0 }] as LineItem[] })
const saving = ref(false)
const saveError = ref('')

function openCreate() {
  form.lead_id = ''
  form.line_items = [{ description: '', hsn_code: '', quantity: 1, unit_price: 0 }]
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

const draftTotal = computed(() => form.line_items.reduce((sum, item) => sum + (item.quantity || 0) * (item.unit_price || 0), 0))

async function save() {
  if (!form.lead_id || !form.line_items.length)
    return
  saving.value = true
  saveError.value = ''
  try {
    const created = await $api<Quote>('/v1/crm/quotes', { method: 'POST', body: { lead_id: form.lead_id, line_items: form.line_items } })
    quotes.value.unshift(created)
    dialog.value = false
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not create this quote.')
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

async function convertToInvoice(quote: Quote) {
  busy.value = quote.id
  actionError.value = ''
  try {
    const updated = await $api<Quote>(`/v1/crm/quotes/${quote.id}/convert-to-invoice`, { method: 'POST' })
    Object.assign(quote, updated)
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not convert this quote to an invoice.')
  }
  finally {
    busy.value = null
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-1">
    <div>
      <h1 class="text-h4 mb-1">
        Quotes
      </h1>
      <p class="text-medium-emphasis">
        GST-compliant proforma quotes tied to a lead — send via WhatsApp, then convert to an invoice once accepted.
      </p>
    </div>
    <VBtn color="primary" prepend-icon="tabler-plus" @click="openCreate">
      New quote
    </VBtn>
  </div>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    Upgrade to the CRM plan to use leads, tickets, and customers.
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
          <th>Lead</th>
          <th>Total</th>
          <th>Status</th>
          <th>Approval</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr v-for="quote in quotes" :key="quote.id">
          <td>{{ quote.quote_number || 'Draft' }}</td>
          <td>{{ leadContactLabel(quote.lead_id) }}</td>
          <td>{{ inr(quote.total) }}</td>
          <td>
            <VChip size="small" :color="statusColor[quote.status]">
              {{ quote.status }}
            </VChip>
          </td>
          <td>
            <VChip v-if="quote.approval_status !== 'not_required'" size="small" :color="quote.approval_status === 'pending' ? 'warning' : quote.approval_status === 'approved' ? 'success' : 'error'" variant="tonal">
              {{ quote.approval_status }}
            </VChip>
            <span v-else class="text-medium-emphasis">—</span>
          </td>
          <td>
            <div class="d-flex ga-1 flex-wrap justify-end">
              <VBtn size="small" variant="text" :loading="busy === quote.id" @click="downloadPdf(quote)">
                PDF
              </VBtn>
              <VBtn v-if="quote.approval_status === 'pending'" size="small" variant="text" color="success" :loading="busy === quote.id" @click="approveQuote(quote)">
                Approve
              </VBtn>
              <VBtn
                v-if="quote.status === 'draft' && quote.approval_status !== 'pending'"
                size="small" variant="text" :loading="busy === quote.id" @click="sendWhatsapp(quote)"
              >
                Send WhatsApp
              </VBtn>
              <VBtn v-if="quote.status !== 'accepted' && quote.status !== 'rejected'" size="small" variant="text" color="success" :loading="busy === quote.id" @click="setStatus(quote, 'accepted')">
                Accept
              </VBtn>
              <VBtn v-if="quote.status !== 'accepted' && quote.status !== 'rejected'" size="small" variant="text" color="error" :loading="busy === quote.id" @click="setStatus(quote, 'rejected')">
                Reject
              </VBtn>
              <VBtn v-if="quote.status === 'accepted' && !quote.converted_invoice_id" size="small" variant="tonal" color="primary" :loading="busy === quote.id" @click="convertToInvoice(quote)">
                Convert to invoice
              </VBtn>
              <VChip v-if="quote.converted_invoice_id" size="small" variant="tonal">
                Invoiced
              </VChip>
              <VBtn v-if="quote.status === 'draft'" icon="tabler-trash" size="small" variant="text" :loading="busy === quote.id" @click="removeQuote(quote)" />
            </div>
          </td>
        </tr>
      </tbody>
    </VTable>
    <p v-if="!loading && !quotes.length" class="text-medium-emphasis text-center pa-6">
      No quotes yet.
    </p>
  </VCard>

  <VDialog v-model="dialog" max-width="640">
    <VCard title="New quote">
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="saveError" type="error" variant="tonal" density="compact">
          {{ saveError }}
        </VAlert>
        <VSelect
          v-model="form.lead_id"
          :items="leads.filter(l => l.status === 'open').map(l => ({ title: l.contact.name || l.contact.wa_id || l.contact.email || 'Unknown', value: l.id }))"
          label="Lead" density="compact"
        />

        <div>
          <div class="d-flex align-center justify-space-between mb-2">
            <span class="text-subtitle-2">Line items</span>
            <VBtn size="small" variant="text" prepend-icon="tabler-plus" @click="addLine">
              Add line
            </VBtn>
          </div>
          <div v-for="(item, index) in form.line_items" :key="index" class="d-flex ga-2 mb-2 align-center">
            <VTextField v-model="item.description" placeholder="Description" density="compact" hide-details style="flex: 2;" />
            <VTextField v-model="item.hsn_code" placeholder="HSN" density="compact" hide-details style="max-width: 90px;" />
            <VTextField v-model.number="item.quantity" type="number" placeholder="Qty" density="compact" hide-details style="max-width: 80px;" />
            <VTextField v-model.number="item.unit_price" type="number" placeholder="Unit price" density="compact" hide-details style="max-width: 110px;" />
            <VBtn icon="tabler-x" size="small" variant="text" :disabled="form.line_items.length === 1" @click="removeLine(index)" />
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
        <VBtn color="primary" :loading="saving" :disabled="!form.lead_id" @click="save">
          Create
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
