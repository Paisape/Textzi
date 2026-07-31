<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type RateCardSlab = { id: string, min_amount: number, max_amount: number | null, price_per_sms: number }
type RateCardSummary = { name: string, min_recharge_amount: number, slabs: RateCardSlab[] }

const rateCard = ref<RateCardSummary | null>(null)
const loadError = ref('')

async function load() {
  loadError.value = ''
  try {
    rateCard.value = await $api<RateCardSummary>('/v1/wallet/rate-card')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load your pricing plan.')
  }
}

function slabLabel(slab: RateCardSlab): string {
  const range = slab.max_amount ? `₹${slab.min_amount.toLocaleString('en-IN')}–₹${slab.max_amount.toLocaleString('en-IN')}` : `₹${slab.min_amount.toLocaleString('en-IN')}+`
  return `${range} recharged`
}

onMounted(load)
</script>

<template>
  <div class="d-flex align-center gap-2 text-body-2 text-medium-emphasis mb-1">
    <RouterLink to="/channels">
      Channels
    </RouterLink>
    <span>/</span>
    <span>SMS Pricing</span>
  </div>
  <h1 class="text-h4 mb-6">
    SMS Pricing
  </h1>

  <VAlert
    v-if="loadError"
    type="error"
    variant="tonal"
  >
    {{ loadError }}
  </VAlert>

  <VCard
    v-else-if="rateCard"
    max-width="480"
  >
    <VCardText>
      <div class="d-flex align-center justify-space-between mb-4">
        <span class="text-h6">{{ rateCard.name }}</span>
        <VChip
          color="primary"
          size="small"
        >
          Your plan
        </VChip>
      </div>
      <p class="text-body-2 text-medium-emphasis mb-4">
        Minimum top-up: ₹{{ rateCard.min_recharge_amount.toLocaleString('en-IN') }}. GST (18%) applies on top of every recharge.
      </p>
      <VTable>
        <thead>
          <tr>
            <th>Recharge amount</th>
            <th>Price per SMS</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="slab in rateCard.slabs"
            :key="slab.id"
          >
            <td>{{ slabLabel(slab) }}</td>
            <td>₹{{ slab.price_per_sms.toFixed(2) }}</td>
          </tr>
        </tbody>
      </VTable>
    </VCardText>
    <VCardText>
      <RouterLink to="/wallet" class="font-weight-medium">
        Go to Wallet & Billing to add credits
      </RouterLink>
    </VCardText>
  </VCard>
</template>
