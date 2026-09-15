<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    layoutWrapperClasses: 'layout-content-width-fluid',
    channel: 'crm',
  },
})

import { addRecentlyViewed } from '@/composables/useRecentlyViewed'

const route = useRoute('crm-customers-id')
const router = useRouter()

type CrmContact = { id: string, name: string | null, phone: string | null, email: string | null, title: string | null, company_id: string | null }
type Task = { id: string, title: string, type: string, due_at: string | null, done: boolean, priority: string }
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
type CustomerDetail = Customer & { tasks: Task[] }
type Deal = { id: string, name: string | null, stage: string, status: 'open' | 'won' | 'lost', value: number | null, probability: number | null, expected_close_date: string | null, created_at: string }
type LineItem = { description: string, hsn_code: string, quantity: number, unit_price: number }
type Quote = { id: string, quote_number: string | null, status: 'draft' | 'sent' | 'accepted' | 'rejected', total: number, created_at: string, sent_at: string | null, line_items: LineItem[] }
type SalesInvoice = { id: string, invoice_number: string | null, status: 'issued' | 'partially_paid' | 'paid' | 'cancelled', total: number, amount_paid: number, balance_due: number, created_at: string, line_items: LineItem[] }
type Attachment = { id: string, filename: string, uploaded_by_user_id: string | null, created_at: string }
type ActivityMessage = { id: string, channel: string, direction: 'inbound' | 'outbound', message_type: string, body: string | null, created_at: string }
type LogEntry = { kind: string, label: string, at: string }
type StatusCountAmount = { count: number, amount: number }
type CustomerSummary = {
  customer: CustomerDetail
  deals: Deal[]
  quotes: Quote[]
  invoices: SalesInvoice[]
  attachments: Attachment[]
  tickets: ActivityMessage[]
  emails: ActivityMessage[]
  log: LogEntry[]
  total_deal_value: number
  total_invoiced: number
  total_paid: number
  open_deal_count: number
  invoices_by_status: Record<string, StatusCountAmount>
  quotes_by_status: Record<string, StatusCountAmount>
}
type AssignableUser = { id: string, full_name: string }
type CustomField = { id: string, name: string, field_type: 'text' | 'number' | 'date' | 'dropdown', options: string[], required: boolean }

const summary = ref<CustomerSummary | null>(null)
const users = ref<AssignableUser[]>([])
const customFields = ref<CustomField[]>([])
const loading = ref(false)
const loadError = ref('')
const activeTab = ref('summary')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [summaryResult, userResult, fieldResult] = await Promise.all([
      $api<CustomerSummary>(`/v1/crm/customers/${route.params.id}/summary`),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
      $api<CustomField[]>('/v1/crm/custom-fields?applies_to=customer'),
    ])
    summary.value = summaryResult
    users.value = userResult
    customFields.value = fieldResult
    addRecentlyViewed({
      type: 'customer', id: summaryResult.customer.id,
      label: summaryResult.customer.contact.name || summaryResult.customer.contact.phone || summaryResult.customer.contact.email || 'Unknown',
      sublabel: 'Customer',
    })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load this customer.')
  }
  finally {
    loading.value = false
  }
}

function initial() {
  const c = summary.value?.customer.contact
  return (c?.name || c?.phone || c?.email || '?').slice(0, 1).toUpperCase()
}

function ownerName(ownerUserId: string | null) {
  return users.value.find(u => u.id === ownerUserId)?.full_name || 'Unassigned'
}

function inr(value: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(value)
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

async function updateNotes(notes: string) {
  if (!summary.value)
    return
  try {
    const updated = await $api<Customer>(`/v1/crm/customers/${summary.value.customer.id}`, { method: 'PATCH', body: { notes } })
    summary.value.customer = { ...summary.value.customer, ...updated }
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not save notes.')
  }
}

async function updateOwner(ownerUserId: string | null) {
  if (!summary.value)
    return
  try {
    const updated = await $api<Customer>(`/v1/crm/customers/${summary.value.customer.id}`, { method: 'PATCH', body: { owner_user_id: ownerUserId } })
    summary.value.customer = { ...summary.value.customer, ...updated }
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not reassign this customer.')
  }
}

async function updateCustomField(name: string, value: any) {
  if (!summary.value)
    return
  const custom_fields = { ...summary.value.customer.custom_fields, [name]: value }
  try {
    const updated = await $api<Customer>(`/v1/crm/customers/${summary.value.customer.id}`, { method: 'PATCH', body: { custom_fields } })
    summary.value.customer = { ...summary.value.customer, ...updated }
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not save this field.')
  }
}

const deleting = ref(false)

async function deleteCustomer() {
  if (!summary.value)
    return
  deleting.value = true
  try {
    await $api(`/v1/crm/customers/${summary.value.customer.id}`, { method: 'DELETE' })
    router.push({ name: 'crm-customers' })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this customer.')
  }
  finally {
    deleting.value = false
  }
}

// --- Files (multiple) -----------------------------------------------------------------------

const uploading = ref(false)
const fileInput = ref<HTMLInputElement>()

async function onFilesSelected(event: Event) {
  const files = Array.from((event.target as HTMLInputElement).files || [])
  ;(event.target as HTMLInputElement).value = ''
  if (!files.length || !summary.value)
    return
  uploading.value = true
  try {
    for (const file of files) {
      const formData = new FormData()
      formData.append('file', file)
      const attachment = await $api<Attachment>(`/v1/crm/contacts/${summary.value.customer.contact.id}/attachments`, { method: 'POST', body: formData })
      summary.value.attachments.unshift(attachment)
    }
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not upload one or more files.')
  }
  finally {
    uploading.value = false
  }
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
    loadError.value = extractErrorMessage(error, 'Could not download this file.')
  }
}

async function downloadQuotePdf(quote: Quote) {
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
    loadError.value = extractErrorMessage(error, 'Could not download this quote.')
  }
}

async function downloadInvoicePdf(invoice: SalesInvoice) {
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
    loadError.value = extractErrorMessage(error, 'Could not download this invoice.')
  }
}

const QUOTE_STATUS_COLOR: Record<string, string> = { draft: undefined as any, sent: 'primary', accepted: 'success', rejected: 'error' }
const INVOICE_STATUS_COLOR: Record<string, string> = { issued: 'primary', partially_paid: 'warning', paid: 'success', cancelled: 'error' }
const DEAL_STATUS_COLOR: Record<string, string> = { open: 'primary', won: 'success', lost: 'error' }

// WHMCS's own Summary ordering (Paid, Draft, Unpaid/Due, ...) -- fixed row order so the card reads
// the same every time regardless of which statuses this customer happens to have.
const INVOICE_STATUS_ORDER = ['paid', 'partially_paid', 'issued', 'cancelled']
const INVOICE_STATUS_LABEL: Record<string, string> = { paid: 'Paid', partially_paid: 'Partially paid', issued: 'Unpaid / Due', cancelled: 'Cancelled' }
const QUOTE_STATUS_ORDER = ['accepted', 'sent', 'draft', 'rejected']
const QUOTE_STATUS_LABEL: Record<string, string> = { accepted: 'Accepted', sent: 'Sent (awaiting reply)', draft: 'Draft', rejected: 'Rejected' }

function statusRow(byStatus: Record<string, { count: number, amount: number }>, key: string) {
  return byStatus[key] || { count: 0, amount: 0 }
}

// "Products/Services" (WHMCS's own term for what a customer is actually subscribed to/has
// bought) -- this CRM has no separate subscription/product-catalog-per-customer concept, so this
// is derived from what's actually been sold: line items on issued invoices (the real sale) plus
// accepted quotes not yet converted to an invoice, deduplicated by description with quantities
// summed. Draft/sent/rejected quotes and cancelled invoices are deliberately excluded -- those
// were never actually sold.
const subscribedServices = computed(() => {
  if (!summary.value)
    return []
  const rows = new Map<string, { description: string, quantity: number, total: number }>()
  const relevantLineSources = [
    ...summary.value.invoices.filter(i => i.status !== 'cancelled').map(i => i.line_items),
    ...summary.value.quotes.filter(q => q.status === 'accepted').map(q => q.line_items),
  ]
  for (const items of relevantLineSources) {
    for (const item of items) {
      const existing = rows.get(item.description)
      const lineTotal = item.quantity * item.unit_price
      if (existing) {
        existing.quantity += item.quantity
        existing.total += lineTotal
      }
      else {
        rows.set(item.description, { description: item.description, quantity: item.quantity, total: lineTotal })
      }
    }
  }
  return [...rows.values()]
})

// Always available, even when this customer has no email on file yet -- deep-links into CRM
// Email's own compose dialog (pre-filled with whatever name/email we do have) instead of a dead
// mailto: link that only ever worked for a customer who already had an email saved.
function sendEmail() {
  if (!summary.value)
    return
  const query: Record<string, string> = { compose: '1' }
  if (summary.value.customer.contact.name)
    query.to_name = summary.value.customer.contact.name
  if (summary.value.customer.contact.email)
    query.to_email = summary.value.customer.contact.email
  router.push({ name: 'crm-email', query })
}

onMounted(load)
</script>

<template>
  <div class="d-flex align-center gap-3 mb-4">
    <VBtn icon="tabler-arrow-left" variant="text" :to="{ name: 'crm-customers' }" />
    <h1 class="text-h5 mb-0">
      Customer
    </h1>
  </div>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <VProgressLinear v-if="loading" indeterminate class="mb-4" />

  <template v-if="summary">
    <VCard class="mb-4">
      <VCardText class="d-flex align-center flex-wrap gap-4">
        <VAvatar color="primary" variant="tonal" size="56">
          <span class="text-h6">{{ initial() }}</span>
        </VAvatar>
        <div class="flex-grow-1">
          <p class="text-h6 mb-0">
            {{ summary.customer.contact.name || summary.customer.contact.phone || summary.customer.contact.email || 'Unknown' }}
          </p>
          <p v-if="summary.customer.contact.title" class="text-body-2 text-medium-emphasis mb-0">
            {{ summary.customer.contact.title }}
          </p>
          <p class="text-body-2 text-medium-emphasis mb-0">
            {{ summary.customer.contact.phone || summary.customer.contact.email || '—' }} · Owner: {{ ownerName(summary.customer.owner_user_id) }}
          </p>
        </div>
        <div class="d-flex flex-wrap ga-6">
          <div class="text-center">
            <p class="text-caption text-medium-emphasis mb-0">
              Deal value
            </p>
            <p class="text-h6 mb-0">
              {{ inr(summary.total_deal_value) }}
            </p>
          </div>
          <div class="text-center">
            <p class="text-caption text-medium-emphasis mb-0">
              Invoiced
            </p>
            <p class="text-h6 mb-0">
              {{ inr(summary.total_invoiced) }}
            </p>
          </div>
          <div class="text-center">
            <p class="text-caption text-medium-emphasis mb-0">
              Paid
            </p>
            <p class="text-h6 mb-0">
              {{ inr(summary.total_paid) }}
            </p>
          </div>
          <div class="text-center">
            <p class="text-caption text-medium-emphasis mb-0">
              Open deals
            </p>
            <p class="text-h6 mb-0">
              {{ summary.open_deal_count }}
            </p>
          </div>
        </div>
      </VCardText>
      <VDivider />
      <VCardText class="d-flex flex-wrap gap-3">
        <RouterLink :to="`/crm-contacts/${summary.customer.contact.id}`" class="d-flex align-center gap-2 text-body-2">
          <VIcon icon="tabler-user" size="16" />
          View contact
        </RouterLink>
        <RouterLink v-if="summary.customer.deal_id" :to="`/crm-deals/${summary.customer.deal_id}`" class="d-flex align-center gap-2 text-body-2">
          <VIcon icon="tabler-briefcase" size="16" />
          View originating deal
        </RouterLink>
        <a href="#" class="d-flex align-center gap-2 text-body-2" @click.prevent="sendEmail">
          <VIcon icon="tabler-mail" size="16" />
          Send email
        </a>
      </VCardText>
    </VCard>

    <VTabs v-model="activeTab" class="mb-4">
      <VTab value="summary">
        Summary
      </VTab>
      <VTab value="deals">
        Deals ({{ summary.deals.length }})
      </VTab>
      <VTab value="quotes">
        Quotes ({{ summary.quotes.length }})
      </VTab>
      <VTab value="invoices">
        Invoices ({{ summary.invoices.length }})
      </VTab>
      <VTab value="tickets">
        Tickets ({{ summary.tickets.length }})
      </VTab>
      <VTab value="emails">
        Emails ({{ summary.emails.length }})
      </VTab>
      <VTab value="notes">
        Notes
      </VTab>
      <VTab value="files">
        Files ({{ summary.attachments.length }})
      </VTab>
      <VTab value="log">
        Log
      </VTab>
    </VTabs>

    <VWindow v-model="activeTab">
      <VWindowItem value="summary">
        <VRow class="mb-2">
          <VCol cols="12" md="4">
            <VCard title="Invoices / Billing">
              <VCardText>
                <div v-for="key in INVOICE_STATUS_ORDER" :key="key" class="d-flex justify-space-between text-body-2 mb-2">
                  <span>{{ INVOICE_STATUS_LABEL[key] }}</span>
                  <span>{{ statusRow(summary.invoices_by_status, key).count }} ({{ inr(statusRow(summary.invoices_by_status, key).amount) }})</span>
                </div>
                <VDivider class="my-2" />
                <div class="d-flex justify-space-between text-body-2 font-weight-medium mb-1">
                  <span>Total invoiced</span>
                  <span>{{ inr(summary.total_invoiced) }}</span>
                </div>
                <div class="d-flex justify-space-between text-body-2 font-weight-medium">
                  <span>Total paid</span>
                  <span>{{ inr(summary.total_paid) }}</span>
                </div>
              </VCardText>
            </VCard>
          </VCol>

          <VCol cols="12" md="4">
            <VCard title="Deals / Quotes">
              <VCardText>
                <div class="d-flex justify-space-between text-body-2 mb-2">
                  <span>Open deals</span>
                  <span>{{ summary.open_deal_count }}</span>
                </div>
                <div class="d-flex justify-space-between text-body-2 mb-2">
                  <span>Total deal value</span>
                  <span>{{ inr(summary.total_deal_value) }}</span>
                </div>
                <VDivider class="my-2" />
                <div v-for="key in QUOTE_STATUS_ORDER" :key="key" class="d-flex justify-space-between text-body-2 mb-2">
                  <span>{{ QUOTE_STATUS_LABEL[key] }}</span>
                  <span>{{ statusRow(summary.quotes_by_status, key).count }} ({{ inr(statusRow(summary.quotes_by_status, key).amount) }})</span>
                </div>
              </VCardText>
            </VCard>
          </VCol>

          <VCol cols="12" md="4">
            <VCard title="Quick actions">
              <VList density="compact">
                <VListItem prepend-icon="tabler-briefcase" @click="router.push(`/crm-deals?new=1&contact_id=${summary.customer.contact.id}`)">
                  New deal
                </VListItem>
                <VListItem prepend-icon="tabler-file-invoice" @click="router.push('/crm-quotes')">
                  New quote / invoice
                </VListItem>
                <VListItem prepend-icon="tabler-checklist" @click="router.push('/crm-tasks')">
                  New task
                </VListItem>
                <VListItem prepend-icon="tabler-mail" @click="sendEmail">
                  Send email
                </VListItem>
              </VList>
            </VCard>
          </VCol>
        </VRow>

        <VRow class="mb-2">
          <VCol cols="12">
            <VCard title="Products / Services">
              <VTable density="compact">
                <thead>
                  <tr>
                    <th>Description</th>
                    <th class="text-end">
                      Quantity
                    </th>
                    <th class="text-end">
                      Total
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in subscribedServices" :key="row.description">
                    <td>{{ row.description }}</td>
                    <td class="text-end">
                      {{ row.quantity }}
                    </td>
                    <td class="text-end">
                      {{ inr(row.total) }}
                    </td>
                  </tr>
                </tbody>
              </VTable>
              <p v-if="!subscribedServices.length" class="text-medium-emphasis text-center pa-6 mb-0">
                Nothing sold to this customer yet -- shows up here once a quote is accepted or an invoice is issued.
              </p>
            </VCard>
          </VCol>
        </VRow>

        <VRow>
          <VCol cols="12" md="8">
            <VCard v-if="customFields.length" class="mb-4" title="Custom fields">
              <VCardText class="d-flex flex-column gap-4">
                <template v-for="field in customFields" :key="field.id">
                  <VSelect
                    v-if="field.field_type === 'dropdown'"
                    :model-value="summary.customer.custom_fields[field.name]" :label="field.name" :items="field.options" density="compact" hide-details clearable
                    @update:model-value="(v: string) => updateCustomField(field.name, v)"
                  />
                  <VTextField
                    v-else
                    :model-value="summary.customer.custom_fields[field.name]" :label="field.name"
                    :type="field.field_type === 'number' ? 'number' : field.field_type === 'date' ? 'date' : 'text'" density="compact" hide-details
                    @blur="(e: FocusEvent) => updateCustomField(field.name, (e.target as HTMLInputElement).value)"
                  />
                </template>
              </VCardText>
            </VCard>

            <VCard title="Tasks">
              <VList v-if="summary.customer.tasks.length" density="compact">
                <VListItem v-for="task in summary.customer.tasks" :key="task.id">
                  <VListItemTitle :class="task.done ? 'text-decoration-line-through text-medium-emphasis' : ''">
                    {{ task.title }}
                  </VListItemTitle>
                  <VListItemSubtitle>
                    {{ task.type }} · {{ task.due_at ? formatDate(task.due_at) : 'no due date' }}
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
                  <VSelect
                    :model-value="summary.customer.owner_user_id"
                    :items="users.map(u => ({ title: u.full_name, value: u.id }))"
                    placeholder="Unassigned" density="compact" hide-details clearable
                    @update:model-value="updateOwner"
                  />
                </div>
                <div>
                  <p class="text-caption text-medium-emphasis mb-1">
                    Created
                  </p>
                  <p class="mb-0">
                    {{ formatDate(summary.customer.created_at) }}
                  </p>
                </div>
              </VCardText>
            </VCard>

            <VCard title="Actions">
              <VCardText>
                <VBtn color="error" variant="tonal" block :loading="deleting" @click="deleteCustomer">
                  Delete customer
                </VBtn>
              </VCardText>
            </VCard>
          </VCol>
        </VRow>
      </VWindowItem>

      <VWindowItem value="deals">
        <VCard>
          <VTable>
            <thead>
              <tr>
                <th>Deal</th>
                <th>Stage</th>
                <th>Status</th>
                <th>Value</th>
                <th>Expected close</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="deal in summary.deals" :key="deal.id" style="cursor: pointer;" @click="router.push(`/crm-deals/${deal.id}`)">
                <td>{{ deal.name || '(unnamed)' }}</td>
                <td>{{ deal.stage }}</td>
                <td>
                  <VChip size="small" :color="DEAL_STATUS_COLOR[deal.status]" variant="tonal">
                    {{ deal.status }}
                  </VChip>
                </td>
                <td>{{ deal.value != null ? inr(deal.value) : '—' }}</td>
                <td>{{ deal.expected_close_date ? formatDate(deal.expected_close_date) : '—' }}</td>
                <td>{{ formatDate(deal.created_at) }}</td>
              </tr>
            </tbody>
          </VTable>
          <p v-if="!summary.deals.length" class="text-medium-emphasis text-center pa-6 mb-0">
            No deals yet.
          </p>
        </VCard>
      </VWindowItem>

      <VWindowItem value="quotes">
        <VCard>
          <VTable>
            <thead>
              <tr>
                <th>Quote</th>
                <th>Status</th>
                <th>Total</th>
                <th>Sent</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <tr v-for="quote in summary.quotes" :key="quote.id">
                <td>{{ quote.quote_number || '(draft)' }}</td>
                <td>
                  <VChip size="small" :color="QUOTE_STATUS_COLOR[quote.status]" variant="tonal">
                    {{ quote.status }}
                  </VChip>
                </td>
                <td>{{ inr(quote.total) }}</td>
                <td>{{ quote.sent_at ? formatDate(quote.sent_at) : '—' }}</td>
                <td class="text-end">
                  <VBtn icon="tabler-download" size="small" variant="text" title="Download PDF" @click="downloadQuotePdf(quote)" />
                </td>
              </tr>
            </tbody>
          </VTable>
          <p v-if="!summary.quotes.length" class="text-medium-emphasis text-center pa-6 mb-0">
            No quotes yet.
          </p>
        </VCard>
      </VWindowItem>

      <VWindowItem value="invoices">
        <VCard>
          <VTable>
            <thead>
              <tr>
                <th>Invoice</th>
                <th>Status</th>
                <th>Total</th>
                <th>Paid</th>
                <th>Balance due</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <tr v-for="invoice in summary.invoices" :key="invoice.id">
                <td>{{ invoice.invoice_number || '(unissued)' }}</td>
                <td>
                  <VChip size="small" :color="INVOICE_STATUS_COLOR[invoice.status]" variant="tonal">
                    {{ invoice.status.replace('_', ' ') }}
                  </VChip>
                </td>
                <td>{{ inr(invoice.total) }}</td>
                <td>{{ inr(invoice.amount_paid) }}</td>
                <td>{{ inr(invoice.balance_due) }}</td>
                <td class="text-end">
                  <VBtn icon="tabler-download" size="small" variant="text" title="Download PDF" @click="downloadInvoicePdf(invoice)" />
                </td>
              </tr>
            </tbody>
          </VTable>
          <p v-if="!summary.invoices.length" class="text-medium-emphasis text-center pa-6 mb-0">
            No invoices yet.
          </p>
        </VCard>
      </VWindowItem>

      <VWindowItem value="tickets">
        <VCard>
          <VList v-if="summary.tickets.length" density="compact">
            <VListItem v-for="m in summary.tickets" :key="m.id">
              <template #prepend>
                <VIcon :icon="m.direction === 'outbound' ? 'tabler-arrow-up-right' : 'tabler-arrow-down-left'" :color="m.direction === 'outbound' ? 'primary' : 'success'" size="16" />
              </template>
              <VListItemTitle>{{ m.body || `[${m.message_type}]` }}</VListItemTitle>
              <VListItemSubtitle>{{ m.channel }} · {{ formatDateTime(m.created_at) }}</VListItemSubtitle>
            </VListItem>
          </VList>
          <p v-else class="text-medium-emphasis text-center pa-6 mb-0">
            No WhatsApp/ticket activity yet.
          </p>
        </VCard>
      </VWindowItem>

      <VWindowItem value="emails">
        <VCard>
          <VList v-if="summary.emails.length" density="compact">
            <VListItem v-for="m in summary.emails" :key="m.id">
              <template #prepend>
                <VIcon :icon="m.direction === 'outbound' ? 'tabler-arrow-up-right' : 'tabler-arrow-down-left'" :color="m.direction === 'outbound' ? 'primary' : 'success'" size="16" />
              </template>
              <VListItemTitle>{{ m.body || '(no content)' }}</VListItemTitle>
              <VListItemSubtitle>{{ formatDateTime(m.created_at) }}</VListItemSubtitle>
            </VListItem>
          </VList>
          <p v-else class="text-medium-emphasis text-center pa-6 mb-0">
            No email activity yet.
          </p>
        </VCard>
      </VWindowItem>

      <VWindowItem value="notes">
        <VCard>
          <VCardText>
            <VTextarea
              :model-value="summary.customer.notes || ''" rows="6" density="compact" placeholder="Add notes about this customer..."
              @blur="(e: FocusEvent) => updateNotes((e.target as HTMLTextAreaElement).value)"
            />
          </VCardText>
        </VCard>
      </VWindowItem>

      <VWindowItem value="files">
        <VCard>
          <VCardText class="d-flex justify-space-between align-center">
            <span class="text-body-2 text-medium-emphasis">Upload one or more files -- visible to your whole team.</span>
            <VBtn size="small" prepend-icon="tabler-upload" :loading="uploading" @click="fileInput?.click()">
              Upload files
            </VBtn>
            <input ref="fileInput" type="file" multiple class="d-none" @change="onFilesSelected">
          </VCardText>
          <VDivider />
          <VList v-if="summary.attachments.length" density="compact">
            <VListItem v-for="attachment in summary.attachments" :key="attachment.id" @click="downloadAttachment(attachment)">
              <template #prepend>
                <VIcon icon="tabler-paperclip" size="18" />
              </template>
              <VListItemTitle>{{ attachment.filename }}</VListItemTitle>
              <VListItemSubtitle>{{ formatDateTime(attachment.created_at) }}</VListItemSubtitle>
            </VListItem>
          </VList>
          <p v-else class="text-medium-emphasis text-center pa-6 mb-0">
            No files yet.
          </p>
        </VCard>
      </VWindowItem>

      <VWindowItem value="log">
        <VCard>
          <VTimeline v-if="summary.log.length" density="compact" side="end" class="pa-4">
            <VTimelineItem v-for="(entry, i) in summary.log" :key="i" size="x-small" dot-color="primary">
              <p class="mb-0">
                {{ entry.label }}
              </p>
              <p class="text-caption text-medium-emphasis mb-0">
                {{ formatDateTime(entry.at) }}
              </p>
            </VTimelineItem>
          </VTimeline>
          <p v-else class="text-medium-emphasis text-center pa-6 mb-0">
            No activity yet.
          </p>
        </VCard>
      </VWindowItem>
    </VWindow>
  </template>
</template>
