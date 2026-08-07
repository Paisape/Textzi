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

type InvoiceAdminRow = {
  id: string
  invoice_number: string | null
  type: string
  status: string
  base_amount: number
  gst_amount: number
  total_amount: number
  created_at: string
  issued_at: string | null
  entity_name: string
  organization_name: string
  organization_zoho_linked: boolean
  zoho_sync_status: string
  zoho_invoice_id: string | null
  zoho_payment_id: string | null
  zoho_mark_paid: boolean
  zoho_sync_error: string | null
}

function zohoStatus(invoice: InvoiceAdminRow): { label: string, color: string, hint: string } {
  if (invoice.status !== 'issued')
    return { label: '—', color: 'default', hint: '' }
  if (!invoice.organization_zoho_linked)
    return { label: 'Not linked', color: 'default', hint: 'This customer has not been linked to Zoho Books yet.' }
  if (invoice.zoho_sync_status === 'synced')
    return { label: 'Synced', color: 'success', hint: invoice.zoho_invoice_id ? `Zoho invoice ${invoice.zoho_invoice_id}` : '' }
  if (invoice.zoho_sync_status === 'failed') {
    return invoice.zoho_invoice_id
      ? { label: 'Invoice created, payment pending', color: 'warning', hint: invoice.zoho_sync_error || '' }
      : { label: 'Failed', color: 'error', hint: invoice.zoho_sync_error || '' }
  }
  return { label: 'Pending', color: 'warning', hint: 'Linked, but not yet pushed to Zoho Books.' }
}

const TYPE_LABELS: Record<string, string> = {
  wallet_recharge: 'SMS Wallet Recharge',
  dlt_fee: 'DLT Registration Fee',
  channel_subscription: 'Channel Subscription Fee',
  admin_credit: 'Manual SMS Credit',
}

const invoices = ref<InvoiceAdminRow[]>([])
const loadError = ref('')
const downloadingId = ref<string | null>(null)
const issuingId = ref<string | null>(null)
const viewingId = ref<string | null>(null)
const viewDialog = ref(false)
const viewUrl = ref('')
const viewTitle = ref('')

async function loadInvoices() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!(authStore.isAdmin || authStore.staffArea === 'finance'))
      return
    invoices.value = await $api<InvoiceAdminRow[]>('/v1/admin/invoices')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load invoices.')
  }
}

async function onView(invoice: InvoiceAdminRow) {
  viewingId.value = invoice.id
  try {
    // Previewed in an <iframe> rather than a new tab -- Chrome blocks navigating a separately-
    // opened tab to a blob: URL created by a different browsing context, so a new-tab approach
    // can't reliably work here; an iframe has no such restriction.
    const blob = await $api<Blob, 'blob'>(`/v1/admin/invoices/${invoice.id}/pdf`, { responseType: 'blob' })
    if (viewUrl.value)
      URL.revokeObjectURL(viewUrl.value)
    viewUrl.value = URL.createObjectURL(blob)
    viewTitle.value = invoice.invoice_number ?? 'Invoice'
    viewDialog.value = true
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not open this invoice.')
  }
  finally {
    viewingId.value = null
  }
}

function closeViewDialog() {
  viewDialog.value = false
  if (viewUrl.value) {
    URL.revokeObjectURL(viewUrl.value)
    viewUrl.value = ''
  }
}

async function onDownload(invoice: InvoiceAdminRow) {
  downloadingId.value = invoice.id
  try {
    const blob = await $api<Blob, 'blob'>(`/v1/admin/invoices/${invoice.id}/pdf`, { responseType: 'blob' })
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
  finally {
    downloadingId.value = null
  }
}

async function onIssue(invoice: InvoiceAdminRow) {
  issuingId.value = invoice.id
  try {
    const updated = await $api<InvoiceAdminRow>(`/v1/admin/invoices/${invoice.id}/issue`, { method: 'POST' })
    Object.assign(invoice, updated)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not issue this invoice.')
  }
  finally {
    issuingId.value = null
  }
}

const rejectingId = ref<string | null>(null)

async function onReject(invoice: InvoiceAdminRow) {
  rejectingId.value = invoice.id
  try {
    const updated = await $api<InvoiceAdminRow>(`/v1/admin/invoices/${invoice.id}/reject`, { method: 'POST' })
    Object.assign(invoice, updated)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not reject this invoice.')
  }
  finally {
    rejectingId.value = null
  }
}

const draftCount = computed(() => invoices.value.filter(i => i.status === 'draft').length)
const bulkIssuing = ref(false)

async function onBulkIssue() {
  bulkIssuing.value = true
  try {
    await $api('/v1/admin/invoices/issue-all-drafts', { method: 'POST' })
    await loadInvoices()
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not issue draft invoices.')
  }
  finally {
    bulkIssuing.value = false
  }
}

function onExportCsv() {
  downloadCsv(
    'invoices.csv',
    [
      { key: 'invoice_number', label: 'Invoice #' },
      { key: 'organization_name', label: 'Customer' },
      { key: 'entity_name', label: 'Entity' },
      { key: 'type', label: 'Type' },
      { key: 'base_amount', label: 'Base Amount' },
      { key: 'gst_amount', label: 'GST' },
      { key: 'total_amount', label: 'Total' },
      { key: 'status', label: 'Status' },
      { key: 'issued_at', label: 'Issued' },
    ],
    invoices.value,
  )
}

onMounted(loadInvoices)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Invoices
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every recharge, fee, and admin credit across every customer, in one place. Every manual admin
    credit always starts as a draft — Issue (approve) it here once you've reviewed it, or Reject
    it if it was a test or a mistake; a rejected invoice never reaches Zoho Books and never gets
    an invoice number. The Zoho column shows whether an issued invoice has actually synced (and,
    if applicable, whether its payment was recorded there) — see
    <RouterLink to="/zoho-sync-log">Zoho Sync Log</RouterLink> for the full call history and to
    retry a failed one.
  </p>

  <VAlert
    v-if="hasAccess === false"
    type="warning"
    variant="tonal"
  >
    This page is restricted to Super Admin, Operator Admin, and Finance Team roles.
  </VAlert>

  <VAlert
    v-else-if="loadError"
    type="error"
    variant="tonal"
  >
    {{ loadError }}
  </VAlert>

  <template v-else-if="hasAccess">
    <div class="d-flex align-center justify-end gap-2 mb-4">
      <VBtn
        v-if="draftCount > 0"
        variant="tonal"
        color="warning"
        :loading="bulkIssuing"
        @click="onBulkIssue"
      >
        Issue All Drafts ({{ draftCount }})
      </VBtn>
      <VBtn
        variant="tonal"
        prepend-icon="tabler-file-export"
        @click="onExportCsv"
      >
        Export CSV
      </VBtn>
    </div>

    <VCard>
    <VTable>
      <thead>
        <tr>
          <th>Invoice #</th>
          <th>Customer</th>
          <th>Description</th>
          <th>Total</th>
          <th>Status</th>
          <th>Zoho</th>
          <th>Issued</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="invoice in invoices"
          :key="invoice.id"
        >
          <td class="font-weight-medium">
            {{ invoice.invoice_number || '—' }}
          </td>
          <td>
            <div>{{ invoice.organization_name }}</div>
            <div class="text-body-2 text-medium-emphasis">
              {{ invoice.entity_name }}
            </div>
          </td>
          <td>{{ TYPE_LABELS[invoice.type] || invoice.type }}</td>
          <td class="font-weight-medium">
            ₹{{ invoice.total_amount.toLocaleString('en-IN') }}
          </td>
          <td>
            <VChip
              :color="invoice.status === 'issued' ? 'success' : invoice.status === 'draft' ? 'warning' : 'error'"
              size="small"
              class="text-capitalize"
            >
              {{ invoice.status }}
            </VChip>
          </td>
          <td>
            <VTooltip v-if="zohoStatus(invoice).hint" location="top">
              <template #activator="{ props }">
                <VChip v-bind="props" :color="zohoStatus(invoice).color" size="small">
                  {{ zohoStatus(invoice).label }}
                </VChip>
              </template>
              {{ zohoStatus(invoice).hint }}
            </VTooltip>
            <VChip v-else :color="zohoStatus(invoice).color" size="small">
              {{ zohoStatus(invoice).label }}
            </VChip>
          </td>
          <td>{{ invoice.issued_at ? new Date(invoice.issued_at).toLocaleDateString('en-IN') : '—' }}</td>
          <td class="d-flex gap-2">
            <template v-if="invoice.status === 'draft'">
              <VBtn
                size="small"
                :loading="issuingId === invoice.id"
                @click="onIssue(invoice)"
              >
                Issue
              </VBtn>
              <VBtn
                size="small"
                variant="text"
                color="error"
                :loading="rejectingId === invoice.id"
                @click="onReject(invoice)"
              >
                Reject
              </VBtn>
            </template>
            <template v-if="invoice.status === 'issued'">
              <VBtn
                size="small"
                variant="text"
                :loading="viewingId === invoice.id"
                @click="onView(invoice)"
              >
                View
              </VBtn>
              <VBtn
                size="small"
                variant="text"
                :loading="downloadingId === invoice.id"
                @click="onDownload(invoice)"
              >
                Download
              </VBtn>
            </template>
          </td>
        </tr>
        <tr v-if="!invoices.length">
          <td
            colspan="8"
            class="text-center text-medium-emphasis"
          >
            No invoices yet.
          </td>
        </tr>
      </tbody>
    </VTable>
    </VCard>
  </template>

  <VDialog
    v-model="viewDialog"
    max-width="900"
    @update:model-value="value => { if (!value) closeViewDialog() }"
  >
    <VCard>
      <VCardTitle class="d-flex align-center justify-space-between">
        <span>{{ viewTitle }}</span>
        <VBtn
          icon="tabler-x"
          variant="text"
          size="small"
          @click="closeViewDialog"
        />
      </VCardTitle>
      <VCardText style="block-size: 80vh;">
        <iframe
          v-if="viewUrl"
          :src="viewUrl"
          style="inline-size: 100%; block-size: 100%; border: none;"
        />
      </VCardText>
    </VCard>
  </VDialog>
</template>
