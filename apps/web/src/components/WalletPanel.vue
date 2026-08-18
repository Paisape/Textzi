<script setup lang="ts">
const props = defineProps<{
  title: string
  balanceEndpoint: string
  rechargeEndpoint: string
  creditsBased?: boolean
  channelActive?: boolean | null
}>()

const showAddCreditsDialog = ref(false)

type WalletTransaction = {
  id: string
  type: string
  amount: number
  balance_after: number
  reference: string | null
  created_at: string
}

type WalletData = {
  entity_id: string
  prepaid_balance: number
  credit_limit: number
  credit_used: number
  available_balance: number
  transactions: WalletTransaction[]
  dev_recharge_available: boolean
}

const wallet = ref<WalletData | null>(null)
const needsOnboarding = ref(false)
const loadError = ref('')
const rechargeAmount = ref<number | null>(1000)
const rechargeError = ref('')
const rechargeNote = ref('')
const submitting = ref(false)
const loading = ref(true)

async function loadWallet() {
  loading.value = true
  loadError.value = ''
  needsOnboarding.value = false
  try {
    wallet.value = await $api<WalletData>(props.balanceEndpoint)
  }
  catch (error: any) {
    const detail = typeof error?.data?.detail === 'string' ? error.data.detail : ''
    if (detail.includes('onboarding'))
      needsOnboarding.value = true
    else
      loadError.value = extractErrorMessage(error, 'Could not load this wallet. Please try again.')
  }
  finally {
    loading.value = false
  }
}

async function onSimulatedRecharge() {
  rechargeError.value = ''
  rechargeNote.value = ''
  if (!rechargeAmount.value || rechargeAmount.value <= 0) {
    rechargeError.value = 'Enter an amount greater than zero.'
    return
  }
  submitting.value = true
  try {
    const result = await $api<{ dev_note: string | null }>(props.rechargeEndpoint, {
      method: 'POST',
      body: { amount: rechargeAmount.value },
    })
    rechargeNote.value = result.dev_note ?? ''
    await loadWallet()
  }
  catch (error: any) {
    rechargeError.value = extractErrorMessage(error, 'Could not add funds. Please try again.')
  }
  finally {
    submitting.value = false
  }
}

function formatAmount(value: number): string {
  if (props.creditsBased)
    return `${value.toLocaleString('en-IN', { maximumFractionDigits: 2 })} SMS`
  return `₹${value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

onMounted(loadWallet)

defineExpose({ loadWallet })
</script>

<template>
  <h6 class="text-h6 mb-4">
    {{ title }}
  </h6>

  <VAlert
    v-if="needsOnboarding"
    type="warning"
    variant="tonal"
    class="mb-6"
  >
    Finish setting up your organisation before you can use this wallet.
    <RouterLink
      to="/onboarding"
      class="font-weight-medium"
    >
      Complete onboarding
    </RouterLink>
  </VAlert>

  <VAlert
    v-else-if="loadError"
    type="error"
    variant="tonal"
    class="mb-6"
  >
    {{ loadError }}
  </VAlert>

  <template v-else-if="wallet">
    <VRow class="mb-2">
      <VCol
        cols="12"
        sm="6"
        md="3"
      >
        <VCard>
          <VCardText>
            <p class="text-body-2 text-medium-emphasis mb-1">
              Available balance
            </p>
            <h4 class="text-h4 font-weight-bold">
              {{ formatAmount(wallet.available_balance) }}
            </h4>
          </VCardText>
        </VCard>
      </VCol>
      <VCol
        cols="12"
        sm="6"
        md="3"
      >
        <VCard>
          <VCardText>
            <p class="text-body-2 text-medium-emphasis mb-1">
              Prepaid balance
            </p>
            <h4 class="text-h4 font-weight-bold">
              {{ formatAmount(wallet.prepaid_balance) }}
            </h4>
          </VCardText>
        </VCard>
      </VCol>
      <VCol
        cols="12"
        sm="6"
        md="3"
      >
        <VCard>
          <VCardText>
            <p class="text-body-2 text-medium-emphasis mb-1">
              Credit limit
            </p>
            <h4 class="text-h4 font-weight-bold">
              {{ formatAmount(wallet.credit_limit) }}
            </h4>
          </VCardText>
        </VCard>
      </VCol>
      <VCol
        cols="12"
        sm="6"
        md="3"
      >
        <VCard>
          <VCardText>
            <p class="text-body-2 text-medium-emphasis mb-1">
              Credit used
            </p>
            <h4 class="text-h4 font-weight-bold">
              {{ formatAmount(wallet.credit_used) }}
            </h4>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>

    <VCard class="mb-6">
      <VCardText>
        <h6 class="text-h6 mb-4">
          Add funds
        </h6>
        <VAlert
          v-if="rechargeNote"
          type="info"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ rechargeNote }}
        </VAlert>
        <VAlert
          v-if="rechargeError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ rechargeError }}
        </VAlert>

        <VAlert
          v-if="creditsBased && channelActive === false"
          type="warning"
          variant="tonal"
        >
          Activate the SMS channel before adding credits.
          <RouterLink
            to="/channels-sms"
            class="font-weight-medium"
          >
            Activate now
          </RouterLink>
        </VAlert>

        <VBtn
          v-else-if="creditsBased"
          prepend-icon="tabler-credit-card"
          @click="showAddCreditsDialog = true"
        >
          Add Credits
        </VBtn>

        <VForm
          v-else-if="wallet?.dev_recharge_available"
          @submit.prevent="onSimulatedRecharge"
        >
          <VRow align="center">
            <VCol
              cols="12"
              sm="4"
            >
              <AppTextField
                v-model.number="rechargeAmount"
                type="number"
                label="Amount (₹)"
                placeholder="1000"
              />
            </VCol>
            <VCol
              cols="12"
              sm="4"
            >
              <VBtn
                type="submit"
                :loading="submitting"
                prepend-icon="tabler-credit-card"
              >
                Simulate recharge (dev)
              </VBtn>
            </VCol>
          </VRow>
        </VForm>
        <VAlert
          v-else
          type="info"
          variant="tonal"
        >
          Wallet top-up isn't self-service yet for this channel — contact support to add funds.
        </VAlert>
      </VCardText>
    </VCard>

    <AddCreditsDialog
      v-if="creditsBased"
      v-model:is-dialog-visible="showAddCreditsDialog"
      :current-balance="wallet.available_balance"
      @recharged="loadWallet"
    />

    <VCard>
      <VCardText>
        <h6 class="text-h6 mb-4">
          Transaction history
        </h6>
        <VTable>
          <thead>
            <tr>
              <th>Type</th>
              <th>Amount</th>
              <th>Balance after</th>
              <th>Reference</th>
              <th>Date</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="tx in wallet.transactions"
              :key="tx.id"
            >
              <td class="text-capitalize">
                {{ tx.type }}
              </td>
              <td :class="tx.amount < 0 ? 'text-error' : 'text-success'">
                {{ tx.amount < 0 ? '-' : '+' }}{{ formatAmount(Math.abs(tx.amount)) }}
              </td>
              <td>{{ formatAmount(tx.balance_after) }}</td>
              <td>{{ tx.reference ?? '—' }}</td>
              <td>{{ new Date(tx.created_at).toLocaleString('en-IN') }}</td>
            </tr>
            <tr v-if="!wallet.transactions.length">
              <td
                colspan="5"
                class="text-center text-medium-emphasis"
              >
                No transactions yet.
              </td>
            </tr>
          </tbody>
        </VTable>
      </VCardText>
    </VCard>
  </template>
</template>
