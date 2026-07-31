<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type PurchaseRow = {
  id: string
  invoice_number: string | null
  base_amount: number
  gst_amount: number
  total_amount: number
  credits_purchased: number | null
  price_per_sms: number | null
  created_at: string
}

const rows = ref<PurchaseRow[]>([])
const loadError = ref('')

async function load() {
  loadError.value = ''
  try {
    rows.value = await $api<PurchaseRow[]>('/v1/reports/purchase-ledger')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load the purchase ledger.')
  }
}

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Purchase Ledger
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every successful wallet recharge — rupees paid, credits received, and the rate applied.
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
          <th>Amount paid</th>
          <th>GST</th>
          <th>Total charged</th>
          <th>Credits received</th>
          <th>Rate</th>
          <th>Date</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="row.id"
        >
          <td class="font-weight-medium">
            {{ row.invoice_number ?? '—' }}
          </td>
          <td>₹{{ row.base_amount.toLocaleString('en-IN', { minimumFractionDigits: 2 }) }}</td>
          <td>₹{{ row.gst_amount.toLocaleString('en-IN', { minimumFractionDigits: 2 }) }}</td>
          <td class="font-weight-medium">
            ₹{{ row.total_amount.toLocaleString('en-IN', { minimumFractionDigits: 2 }) }}
          </td>
          <td>{{ row.credits_purchased !== null ? `${row.credits_purchased.toLocaleString('en-IN')} SMS` : '—' }}</td>
          <td>{{ row.price_per_sms !== null ? `₹${row.price_per_sms}/SMS` : '—' }}</td>
          <td>{{ new Date(row.created_at).toLocaleString('en-IN') }}</td>
        </tr>
        <tr v-if="!rows.length">
          <td
            colspan="7"
            class="text-center text-medium-emphasis"
          >
            No purchases yet.
          </td>
        </tr>
      </tbody>
    </VTable>
  </VCard>
</template>
