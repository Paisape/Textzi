<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type LedgerRow = {
  id: string
  channel: string
  type: string
  amount: number
  balance_before: number
  balance_after: number
  reference: string | null
  created_at: string
}

const channel = ref<'all' | 'sms' | 'waba'>('all')
const rows = ref<LedgerRow[]>([])
const loadError = ref('')
const loading = ref(true)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    rows.value = await $api<LedgerRow[]>('/v1/reports/wallet-ledger', {
      query: channel.value === 'all' ? {} : { channel: channel.value },
    })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load the wallet ledger.')
  }
  finally {
    loading.value = false
  }
}

watch(channel, load)
onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Wallet Ledger
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every credit and debit to your SMS and WhatsApp wallets, most recent first.
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
    <VCardText class="d-flex align-center gap-4">
      <VBtnToggle
        v-model="channel"
        density="comfortable"
        mandatory
        divided
      >
        <VBtn value="all">
          All
        </VBtn>
        <VBtn value="sms">
          SMS
        </VBtn>
        <VBtn value="waba">
          WhatsApp
        </VBtn>
      </VBtnToggle>
    </VCardText>

    <VTable>
      <thead>
        <tr>
          <th>Channel</th>
          <th>Type</th>
          <th>Previous balance</th>
          <th>Amount</th>
          <th>Balance after</th>
          <th>Reference</th>
          <th>Date</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="row.id"
        >
          <td class="text-uppercase">
            {{ row.channel }}
          </td>
          <td class="text-capitalize">
            {{ row.type.replaceAll('_', ' ') }}
          </td>
          <td>{{ row.balance_before.toLocaleString('en-IN', { maximumFractionDigits: 2 }) }}</td>
          <td :class="row.amount < 0 ? 'text-error' : 'text-success'">
            {{ row.amount < 0 ? '-' : '+' }}{{ Math.abs(row.amount).toLocaleString('en-IN', { maximumFractionDigits: 2 }) }}
          </td>
          <td>{{ row.balance_after.toLocaleString('en-IN', { maximumFractionDigits: 2 }) }}</td>
          <td>{{ row.reference ?? '—' }}</td>
          <td>{{ new Date(row.created_at).toLocaleString('en-IN') }}</td>
        </tr>
        <tr v-if="!loading && !rows.length">
          <td
            colspan="7"
            class="text-center text-medium-emphasis"
          >
            No wallet transactions yet.
          </td>
        </tr>
      </tbody>
    </VTable>
  </VCard>
</template>
