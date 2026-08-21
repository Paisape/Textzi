<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

const activeTab = ref('textzi')
const channelActive = ref<boolean | null>(null)

async function loadChannelStatus() {
  try {
    const status = await $api<{ channel_active: boolean }>('/v1/channels/sms/status')
    channelActive.value = status.channel_active
  }
  catch {
    channelActive.value = null
  }
}

// --- Textzi Wallet (Smart Collect bank-transfer balance) -----------------------------------

type TextziWallet = { entity_id: string, balance: number }
type VirtualAccount = { account_number: string | null, ifsc: string | null, status: string }
type TextziTransaction = { id: string, type: string, amount: number, balance_after: number, reference: string | null, created_at: string }
type PaymentMethod = { payment_method: string, enabled: boolean, flat_fee_paise: number }

const textziWallet = ref<TextziWallet | null>(null)
const virtualAccount = ref<VirtualAccount | null>(null)
const textziTransactions = ref<TextziTransaction[]>([])
const textziLoading = ref(false)
const textziError = ref('')
const generatingAccount = ref(false)
const smartCollectFeePaise = ref<number | null>(null)

const smartCollectFeeLabel = computed(() => smartCollectFeePaise.value === null ? null : inr(smartCollectFeePaise.value / 100))

async function loadTextziWallet() {
  textziLoading.value = true
  textziError.value = ''
  try {
    const [walletResult, txnResult, methodsResult] = await Promise.all([
      $api<TextziWallet>('/v1/wallet/textzi'),
      $api<TextziTransaction[]>('/v1/wallet/textzi/transactions'),
      $api<PaymentMethod[]>('/v1/wallet/payment-methods').catch(() => [] as PaymentMethod[]),
    ])
    textziWallet.value = walletResult
    textziTransactions.value = txnResult
    smartCollectFeePaise.value = methodsResult.find(m => m.payment_method === 'razorpay_smart_collect')?.flat_fee_paise ?? null
  }
  catch (error: any) {
    textziError.value = extractErrorMessage(error, 'Could not load your Textzi Wallet.')
  }
  finally {
    textziLoading.value = false
  }
}

async function generateAccount() {
  generatingAccount.value = true
  textziError.value = ''
  try {
    virtualAccount.value = await $api<VirtualAccount>('/v1/wallet/textzi/account', { method: 'POST' })
  }
  catch (error: any) {
    textziError.value = extractErrorMessage(error, 'Could not get your bank transfer details.')
  }
  finally {
    generatingAccount.value = false
  }
}

const removingAccount = ref(false)
const removeConfirmOpen = ref(false)

async function removeAccount() {
  removingAccount.value = true
  textziError.value = ''
  try {
    await $api('/v1/wallet/textzi/account/close', { method: 'POST' })
    virtualAccount.value = null
    removeConfirmOpen.value = false
  }
  catch (error: any) {
    textziError.value = extractErrorMessage(error, 'Could not remove this bank transfer account.')
  }
  finally {
    removingAccount.value = false
  }
}

const copied = ref<string | null>(null)
async function copyValue(value: string, field: string) {
  await navigator.clipboard.writeText(value)
  copied.value = field
  setTimeout(() => { copied.value = null }, 2000)
}

function inr(value: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(value)
}

watch(activeTab, tab => {
  if (tab === 'textzi' && !textziWallet.value)
    loadTextziWallet()
})

onMounted(() => {
  loadChannelStatus()
  if (activeTab.value === 'textzi')
    loadTextziWallet()
})
</script>

<template>
  <h1 class="text-h4 mb-1">
    Wallet & Billing
  </h1>
  <p class="text-medium-emphasis mb-6">
    Track your balance, add funds, and review every credit and debit on your account — SMS and WhatsApp are billed from separate wallets.
  </p>

  <VTabs v-model="activeTab" class="mb-6">
    <VTab value="textzi">
      Textzi Wallet
    </VTab>
    <VTab value="sms">
      SMS Wallet
    </VTab>
    <VTab value="waba">
      WhatsApp Wallet
    </VTab>
  </VTabs>

  <VWindow v-model="activeTab">
    <VWindowItem value="sms">
      <WalletPanel
        title="SMS Wallet"
        balance-endpoint="/v1/wallet"
        recharge-endpoint="/v1/wallet/recharge"
        :credits-based="true"
        :channel-active="channelActive"
      />
    </VWindowItem>
    <VWindowItem value="waba">
      <WalletPanel
        title="WhatsApp Wallet"
        balance-endpoint="/v1/wallet/waba"
        recharge-endpoint="/v1/wallet/waba/recharge"
      />
    </VWindowItem>
    <VWindowItem value="textzi">
      <VAlert v-if="textziError" type="error" variant="tonal" class="mb-4" closable @click:close="textziError = ''">
        {{ textziError }}
      </VAlert>

      <VRow>
        <VCol cols="12" md="5">
          <VCard>
            <VCardText>
              <p class="text-caption text-medium-emphasis mb-1">
                Balance
              </p>
              <p class="text-h4 mb-4">
                {{ textziWallet ? inr(textziWallet.balance) : '—' }}
              </p>
              <p class="text-body-2 text-medium-emphasis mb-4">
                Funded by bank transfer (IMPS, NEFT, or RTGS only) via Razorpay Smart Collect. Spendable on SMS credit top-up, WhatsApp subscription, or CRM subscription — each spend requires a one-time code sent to your mobile or email.
              </p>

              <template v-if="!virtualAccount">
                <VBtn :loading="generatingAccount" @click="generateAccount">
                  Get bank transfer details
                </VBtn>
              </template>
              <template v-else>
                <VDivider class="mb-4" />
                <div class="d-flex flex-column ga-3">
                  <div>
                    <p class="text-caption text-medium-emphasis mb-0">
                      Account holder name
                    </p>
                    <span class="text-body-1">Textzi</span>
                  </div>
                  <div v-if="virtualAccount.account_number">
                    <p class="text-caption text-medium-emphasis mb-0">
                      Account number
                    </p>
                    <div class="d-flex align-center ga-2">
                      <span class="text-body-1">{{ virtualAccount.account_number }}</span>
                      <VBtn icon="tabler-copy" size="x-small" variant="text" @click="copyValue(virtualAccount.account_number!, 'account')" />
                      <span v-if="copied === 'account'" class="text-caption text-success">Copied</span>
                    </div>
                  </div>
                  <div v-if="virtualAccount.ifsc">
                    <p class="text-caption text-medium-emphasis mb-0">
                      IFSC
                    </p>
                    <div class="d-flex align-center ga-2">
                      <span class="text-body-1">{{ virtualAccount.ifsc }}</span>
                      <VBtn icon="tabler-copy" size="x-small" variant="text" @click="copyValue(virtualAccount.ifsc!, 'ifsc')" />
                      <span v-if="copied === 'ifsc'" class="text-caption text-success">Copied</span>
                    </div>
                  </div>
                </div>
                <VAlert type="info" variant="tonal" density="compact" class="mt-4">
                  Transfer any amount via IMPS, NEFT, or RTGS only — UPI transfers to this account are not supported.
                  <template v-if="smartCollectFeeLabel">
                    A flat fee of {{ smartCollectFeeLabel }} applies; the rest is added to your Textzi Wallet, usually within a few minutes.
                  </template>
                  <template v-else>
                    A flat fee applies; the rest is added to your Textzi Wallet, usually within a few minutes.
                  </template>
                </VAlert>
                <VBtn variant="text" color="error" size="small" class="mt-3" @click="removeConfirmOpen = true">
                  Remove this account
                </VBtn>
              </template>
            </VCardText>
          </VCard>
        </VCol>

        <VCol cols="12" md="7">
          <VCard>
            <VCardText>
              <h2 class="text-h6 mb-3">
                Transaction history
              </h2>
              <VTable density="compact">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Amount</th>
                    <th>Balance after</th>
                    <th>Date</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="txn in textziTransactions" :key="txn.id">
                    <td>{{ txn.type }}</td>
                    <td :class="txn.amount >= 0 ? 'text-success' : 'text-error'">
                      {{ txn.amount >= 0 ? '+' : '' }}{{ inr(txn.amount) }}
                    </td>
                    <td>{{ inr(txn.balance_after) }}</td>
                    <td>{{ new Date(txn.created_at).toLocaleString() }}</td>
                  </tr>
                </tbody>
              </VTable>
              <p v-if="!textziLoading && !textziTransactions.length" class="text-medium-emphasis text-center pa-6 mb-0">
                No transactions yet.
              </p>
            </VCardText>
          </VCard>
        </VCol>
      </VRow>
    </VWindowItem>
  </VWindow>

  <VDialog v-model="removeConfirmOpen" max-width="420">
    <VCard title="Remove this account?">
      <VCardText>
        <p class="text-body-2 text-medium-emphasis mb-0">
          This account number will stop working for new transfers. You'll be able to generate a new one right after — any balance already in your Textzi Wallet is unaffected.
        </p>
      </VCardText>
      <VCardText class="d-flex gap-3 justify-end">
        <VBtn variant="outlined" :disabled="removingAccount" @click="removeConfirmOpen = false">
          Cancel
        </VBtn>
        <VBtn color="error" :loading="removingAccount" @click="removeAccount">
          Remove account
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>
</template>
