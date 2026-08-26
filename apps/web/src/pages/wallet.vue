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
const smartCollectEnabled = ref(false)
const bankTransferEnabled = ref(false)

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
    smartCollectEnabled.value = methodsResult.find(m => m.payment_method === 'razorpay_smart_collect')?.enabled ?? false
    bankTransferEnabled.value = methodsResult.find(m => m.payment_method === 'bank_transfer')?.enabled ?? false
  }
  catch (error: any) {
    textziError.value = extractErrorMessage(error, 'Could not load your Textzi Wallet.')
  }
  finally {
    textziLoading.value = false
  }
  if (bankTransferEnabled.value)
    loadBankTransferData()
}

// --- Manual bank-transfer top-up request ---------------------------------------------------

type BankDetails = { bank_account_holder_name: string | null, bank_account_number: string | null, bank_ifsc: string | null, bank_name: string | null }
type BankTransferRequest = {
  id: string
  transfer_date: string
  mode: string
  amount: number
  utr_number: string
  notes: string | null
  status: string
  credited_amount: number | null
  admin_note: string | null
  reviewed_at: string | null
  created_at: string
}

const bankDetails = ref<BankDetails | null>(null)
const bankTransferRequests = ref<BankTransferRequest[]>([])
const bankTransferForm = ref({ transfer_date: '', mode: 'neft', amount: null as number | null, utr_number: '', notes: '' })
const bankTransferReceipt = ref<File | null>(null)
const bankTransferSubmitting = ref(false)
const bankTransferError = ref('')
const bankTransferSuccess = ref('')

const statusColor: Record<string, string> = { pending: 'warning', approved: 'success', rejected: 'error' }

async function loadBankTransferData() {
  try {
    const [details, requests] = await Promise.all([
      $api<BankDetails>('/v1/wallet/textzi/bank-details'),
      $api<BankTransferRequest[]>('/v1/wallet/textzi/bank-transfer-requests'),
    ])
    bankDetails.value = details
    bankTransferRequests.value = requests
  }
  catch (error: any) {
    bankTransferError.value = extractErrorMessage(error, 'Could not load bank transfer details.')
  }
}

async function submitBankTransferRequest() {
  bankTransferError.value = ''
  bankTransferSuccess.value = ''
  if (!bankTransferForm.value.transfer_date || !bankTransferForm.value.amount || !bankTransferForm.value.utr_number.trim() || !bankTransferReceipt.value) {
    bankTransferError.value = 'Fill in the transfer date, amount, UTR number, and attach a receipt.'
    return
  }
  bankTransferSubmitting.value = true
  try {
    const formData = new FormData()
    formData.append('transfer_date', bankTransferForm.value.transfer_date)
    formData.append('mode', bankTransferForm.value.mode)
    formData.append('amount', String(bankTransferForm.value.amount))
    formData.append('utr_number', bankTransferForm.value.utr_number.trim())
    if (bankTransferForm.value.notes.trim())
      formData.append('notes', bankTransferForm.value.notes.trim())
    formData.append('receipt', bankTransferReceipt.value)
    const created = await $api<BankTransferRequest>('/v1/wallet/textzi/bank-transfer-requests', { method: 'POST', body: formData })
    bankTransferRequests.value.unshift(created)
    bankTransferForm.value = { transfer_date: '', mode: 'neft', amount: null, utr_number: '', notes: '' }
    bankTransferReceipt.value = null
    bankTransferSuccess.value = 'Request submitted -- we\'ll verify it against our bank statement and credit your wallet shortly.'
  }
  catch (error: any) {
    bankTransferError.value = extractErrorMessage(error, 'Could not submit this request.')
  }
  finally {
    bankTransferSubmitting.value = false
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
          <VCard class="mb-6">
            <VCardText>
              <p class="text-caption text-medium-emphasis mb-1">
                Balance
              </p>
              <p class="text-h4 mb-4">
                {{ textziWallet ? inr(textziWallet.balance) : '—' }}
              </p>
              <p class="text-body-2 text-medium-emphasis mb-0">
                Spendable on SMS credit top-up, WhatsApp subscription, or CRM subscription — each spend requires a one-time code sent to your mobile or email.
              </p>
            </VCardText>
          </VCard>

          <VCard v-if="smartCollectEnabled" class="mb-6">
            <VCardText>
              <h2 class="text-h6 mb-1">
                Instant bank transfer (Smart Collect)
              </h2>
              <p class="text-body-2 text-medium-emphasis mb-4">
                Get a dedicated account number and transfer any amount via IMPS, NEFT, or RTGS — credited automatically, usually within a few minutes.
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
                    A flat fee of {{ smartCollectFeeLabel }} (inclusive of GST) applies; the rest is added to your Textzi Wallet, usually within a few minutes.
                  </template>
                  <template v-else>
                    A flat fee (inclusive of GST) applies; the rest is added to your Textzi Wallet, usually within a few minutes.
                  </template>
                </VAlert>
                <VBtn variant="text" color="error" size="small" class="mt-3" @click="removeConfirmOpen = true">
                  Remove this account
                </VBtn>
              </template>
            </VCardText>
          </VCard>

          <VCard v-if="bankTransferEnabled">
            <VCardText>
              <h2 class="text-h6 mb-1">
                Pay by bank transfer
              </h2>
              <p class="text-body-2 text-medium-emphasis mb-4">
                Send a transfer from your own bank to the account below, then submit the details for us to verify and credit your wallet.
              </p>

              <template v-if="bankDetails && bankDetails.bank_account_number">
                <div class="d-flex flex-column ga-3 mb-4">
                  <div>
                    <p class="text-caption text-medium-emphasis mb-0">
                      Account holder name
                    </p>
                    <span class="text-body-1">{{ bankDetails.bank_account_holder_name }}</span>
                  </div>
                  <div>
                    <p class="text-caption text-medium-emphasis mb-0">
                      Bank name
                    </p>
                    <span class="text-body-1">{{ bankDetails.bank_name }}</span>
                  </div>
                  <div>
                    <p class="text-caption text-medium-emphasis mb-0">
                      Account number
                    </p>
                    <div class="d-flex align-center ga-2">
                      <span class="text-body-1">{{ bankDetails.bank_account_number }}</span>
                      <VBtn icon="tabler-copy" size="x-small" variant="text" @click="copyValue(bankDetails.bank_account_number!, 'bank-account')" />
                      <span v-if="copied === 'bank-account'" class="text-caption text-success">Copied</span>
                    </div>
                  </div>
                  <div>
                    <p class="text-caption text-medium-emphasis mb-0">
                      IFSC
                    </p>
                    <div class="d-flex align-center ga-2">
                      <span class="text-body-1">{{ bankDetails.bank_ifsc }}</span>
                      <VBtn icon="tabler-copy" size="x-small" variant="text" @click="copyValue(bankDetails.bank_ifsc!, 'bank-ifsc')" />
                      <span v-if="copied === 'bank-ifsc'" class="text-caption text-success">Copied</span>
                    </div>
                  </div>
                </div>

                <VDivider class="mb-4" />

                <VAlert v-if="bankTransferError" type="error" variant="tonal" density="compact" class="mb-4" closable @click:close="bankTransferError = ''">
                  {{ bankTransferError }}
                </VAlert>
                <VAlert v-if="bankTransferSuccess" type="success" variant="tonal" density="compact" class="mb-4" closable @click:close="bankTransferSuccess = ''">
                  {{ bankTransferSuccess }}
                </VAlert>

                <h3 class="text-body-1 font-weight-medium mb-3">
                  Submit a transfer request
                </h3>
                <VRow dense>
                  <VCol cols="12" sm="6">
                    <AppTextField v-model="bankTransferForm.transfer_date" type="date" label="Transfer date" />
                  </VCol>
                  <VCol cols="12" sm="6">
                    <VSelect
                      v-model="bankTransferForm.mode"
                      label="Mode"
                      :items="[{ title: 'NEFT', value: 'neft' }, { title: 'IMPS', value: 'imps' }, { title: 'RTGS', value: 'rtgs' }, { title: 'UPI', value: 'upi' }]"
                    />
                  </VCol>
                  <VCol cols="12" sm="6">
                    <AppTextField v-model.number="bankTransferForm.amount" type="number" label="Amount sent (₹)" />
                  </VCol>
                  <VCol cols="12" sm="6">
                    <AppTextField v-model="bankTransferForm.utr_number" label="UTR / reference number" />
                  </VCol>
                  <VCol cols="12">
                    <AppTextField v-model="bankTransferForm.notes" label="Notes (optional)" />
                  </VCol>
                  <VCol cols="12">
                    <VFileInput
                      v-model="bankTransferReceipt"
                      label="Transfer receipt (PDF, JPG, or PNG)"
                      accept=".pdf,.jpg,.jpeg,.png"
                      prepend-icon=""
                      prepend-inner-icon="tabler-paperclip"
                    />
                  </VCol>
                  <VCol cols="12">
                    <VBtn :loading="bankTransferSubmitting" @click="submitBankTransferRequest">
                      Submit for verification
                    </VBtn>
                  </VCol>
                </VRow>

                <VDivider class="my-4" />

                <h3 class="text-body-1 font-weight-medium mb-3">
                  Your requests
                </h3>
                <VTable density="compact">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Mode</th>
                      <th>Amount</th>
                      <th>Status</th>
                      <th>Credited</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="req in bankTransferRequests" :key="req.id">
                      <td>{{ req.transfer_date }}</td>
                      <td class="text-uppercase">
                        {{ req.mode }}
                      </td>
                      <td>{{ inr(req.amount) }}</td>
                      <td>
                        <VChip :color="statusColor[req.status]" size="small">
                          {{ req.status }}
                        </VChip>
                      </td>
                      <td>{{ req.credited_amount != null ? inr(req.credited_amount) : '—' }}</td>
                    </tr>
                  </tbody>
                </VTable>
                <p v-if="!bankTransferRequests.length" class="text-medium-emphasis text-center pa-4 mb-0">
                  No requests yet.
                </p>
              </template>
              <p v-else class="text-medium-emphasis mb-0">
                Bank transfer details haven't been configured yet — contact support.
              </p>
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
