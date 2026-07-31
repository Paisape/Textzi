<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type InvoiceRow = {
  id: string
  invoice_number: string | null
  type: string
  status: string
  base_amount: number
  gst_amount: number
  total_amount: number
  created_at: string
  issued_at: string | null
}

const TYPE_LABELS: Record<string, string> = {
  wallet_recharge: 'SMS Wallet Recharge',
  dlt_fee: 'DLT Registration Fee',
  channel_subscription: 'Channel Subscription Fee',
  admin_credit: 'Manual SMS Credit',
}

const invoices = ref<InvoiceRow[]>([])
const loadError = ref('')
const downloadingId = ref<string | null>(null)
const viewingId = ref<string | null>(null)
const viewDialog = ref(false)
const viewUrl = ref('')
const viewTitle = ref('')

async function loadInvoices() {
  loadError.value = ''
  try {
    invoices.value = await $api<InvoiceRow[]>('/v1/invoices')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load invoices.')
  }
}

async function onView(invoice: InvoiceRow) {
  viewingId.value = invoice.id
  try {
    // Previewed in an <iframe> within this page rather than a new tab -- Chrome blocks
    // navigating a separately-opened tab to a blob: URL created by a different browsing context
    // (hardening against blob-URL phishing), which made a reliable "open in new tab" impossible
    // without re-fetching the PDF from a fresh top-level navigation (which can't carry the
    // Authorization header this endpoint requires). An iframe has no such restriction since the
    // blob never leaves the browsing context that created it.
    const blob = await $api<Blob, 'blob'>(`/v1/invoices/${invoice.id}/pdf`, { responseType: 'blob' })
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

function closeView() {
  viewDialog.value = false
  if (viewUrl.value) {
    URL.revokeObjectURL(viewUrl.value)
    viewUrl.value = ''
  }
}

async function onDownload(invoice: InvoiceRow) {
  downloadingId.value = invoice.id
  try {
    const blob = await $api<Blob, 'blob'>(`/v1/invoices/${invoice.id}/pdf`, { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${invoice.invoice_number}.pdf`
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

onMounted(loadInvoices)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Invoices
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every recharge, fee, and credit to your account produces an invoice here.
  </p>

  <VAlert
    v-if="loadError"
    type="error"
    variant="tonal"
    class="mb-4"
  >
    {{ loadError }}
  </VAlert>

  <VCard>
    <VTable>
      <thead>
        <tr>
          <th>Invoice #</th>
          <th>Description</th>
          <th>Amount</th>
          <th>GST</th>
          <th>Total</th>
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
            {{ invoice.invoice_number }}
          </td>
          <td>{{ TYPE_LABELS[invoice.type] || invoice.type }}</td>
          <td>₹{{ invoice.base_amount.toLocaleString('en-IN') }}</td>
          <td>₹{{ invoice.gst_amount.toLocaleString('en-IN') }}</td>
          <td class="font-weight-medium">
            ₹{{ invoice.total_amount.toLocaleString('en-IN') }}
          </td>
          <td>{{ invoice.issued_at ? new Date(invoice.issued_at).toLocaleDateString('en-IN') : '—' }}</td>
          <td>
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
          </td>
        </tr>
        <tr v-if="!invoices.length">
          <td
            colspan="7"
            class="text-center text-medium-emphasis"
          >
            No invoices yet.
          </td>
        </tr>
      </tbody>
    </VTable>
  </VCard>

  <VDialog
    v-model="viewDialog"
    max-width="900"
    @update:model-value="value => { if (!value) closeView() }"
  >
    <VCard>
      <VCardTitle class="d-flex align-center justify-space-between">
        <span>{{ viewTitle }}</span>
        <VBtn
          icon="tabler-x"
          variant="text"
          size="small"
          @click="closeView"
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
