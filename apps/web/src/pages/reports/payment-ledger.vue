<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type PaymentRow = {
  id: string
  provider: string
  provider_order_id: string
  purpose: string
  amount: number
  status: string
  created_at: string
}

const STATUS_COLORS: Record<string, string> = {
  created: 'warning',
  paid: 'success',
  failed: 'error',
}

const rows = ref<PaymentRow[]>([])
const loadError = ref('')

async function load() {
  loadError.value = ''
  try {
    rows.value = await $api<PaymentRow[]>('/v1/reports/payment-ledger')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load the payment ledger.')
  }
}

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Payment Ledger
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every payment-gateway order raised on your account, whatever its outcome — created, paid, or failed.
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
          <th>Provider</th>
          <th>Order ID</th>
          <th>Purpose</th>
          <th>Amount</th>
          <th>Status</th>
          <th>Date</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="row.id"
        >
          <td class="text-capitalize">
            {{ row.provider }}
          </td>
          <td>{{ row.provider_order_id }}</td>
          <td class="text-capitalize">
            {{ row.purpose.replaceAll('_', ' ') }}
          </td>
          <td>₹{{ row.amount.toLocaleString('en-IN', { minimumFractionDigits: 2 }) }}</td>
          <td>
            <VChip
              size="small"
              :color="STATUS_COLORS[row.status] || 'default'"
              class="text-capitalize"
            >
              {{ row.status }}
            </VChip>
          </td>
          <td>{{ new Date(row.created_at).toLocaleString('en-IN') }}</td>
        </tr>
        <tr v-if="!rows.length">
          <td
            colspan="6"
            class="text-center text-medium-emphasis"
          >
            No payment orders yet.
          </td>
        </tr>
      </tbody>
    </VTable>
  </VCard>
</template>
