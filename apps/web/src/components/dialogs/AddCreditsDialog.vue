<script setup lang="ts">
interface Props {
  isDialogVisible: boolean
  currentBalance: number
}

interface Emit {
  (e: 'update:isDialogVisible', val: boolean): void
  (e: 'recharged'): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emit>()

type Quote = {
  amount: number
  gst_amount: number
  total_amount: number
  credits: number
  price_per_sms: number
  rate_card_name: string
  min_recharge_amount: number
  dev_recharge_available: boolean
}

const amount = ref(500)
const minRecharge = ref(500)
const quote = ref<Quote | null>(null)
const quoteError = ref('')
const quoteLoading = ref(false)
const payError = ref('')
const paying = ref(false)

// --- Payment method picker (Razorpay Checkout vs Textzi Wallet) ----------------------------

type PaymentMethod = { payment_method: string, enabled: boolean, flat_fee_paise: number }
type TextziWallet = { entity_id: string, balance: number }

const paymentMethods = ref<PaymentMethod[]>([])
const textziWalletBalance = ref(0)
const selectedMethod = ref<'razorpay_checkout' | 'razorpay_smart_collect'>('razorpay_checkout')

const checkoutEnabled = computed(() => paymentMethods.value.find(m => m.payment_method === 'razorpay_checkout')?.enabled ?? true)
const walletMethodEnabled = computed(() => paymentMethods.value.find(m => m.payment_method === 'razorpay_smart_collect')?.enabled ?? false)
const canPayWithWallet = computed(() => walletMethodEnabled.value && quote.value !== null && textziWalletBalance.value >= quote.value.total_amount)

async function loadPaymentOptions() {
  try {
    const [methods, wallet] = await Promise.all([
      $api<PaymentMethod[]>('/v1/wallet/payment-methods').catch(() => [] as PaymentMethod[]),
      $api<TextziWallet>('/v1/wallet/textzi').catch(() => ({ entity_id: '', balance: 0 })),
    ])
    paymentMethods.value = methods
    textziWalletBalance.value = wallet.balance
    selectedMethod.value = checkoutEnabled.value ? 'razorpay_checkout' : 'razorpay_smart_collect'
  }
  catch {
    // Payment-method listing is admin-only in some deployments -- fall back to Checkout-only, the existing default behavior.
  }
}

// --- OTP confirmation for Textzi Wallet spend -----------------------------------------------

const otpDialogOpen = ref(false)
const otpCode = ref('')
const otpError = ref('')
const otpSubmitting = ref(false)
const otpSentVia = ref<'mobile' | 'email' | null>(null)
const otpMaskedDestination = ref('')

async function openOtpDialog() {
  payError.value = ''
  try {
    const result = await $api<{ sent_via: 'mobile' | 'email', masked_destination: string, dev_otp_code: string | null }>('/v1/wallet/textzi/spend/request-otp', {
      method: 'POST',
      body: { purpose: 'sms_credit' },
    })
    otpSentVia.value = result.sent_via
    otpMaskedDestination.value = result.masked_destination
    otpCode.value = result.dev_otp_code ?? ''
    otpError.value = ''
    otpDialogOpen.value = true
  }
  catch (error: any) {
    payError.value = extractErrorMessage(error, 'Could not send a verification code.')
  }
}

async function onSubmitOtp() {
  if (!quote.value)
    return
  otpSubmitting.value = true
  otpError.value = ''
  try {
    await $api('/v1/wallet/textzi/spend/sms-credit', { method: 'POST', body: { amount: amount.value, otp_code: otpCode.value } })
    otpDialogOpen.value = false
    emit('recharged')
    emit('update:isDialogVisible', false)
  }
  catch (error: any) {
    otpError.value = extractErrorMessage(error, 'Incorrect or expired code.')
  }
  finally {
    otpSubmitting.value = false
  }
}

let quoteTimer: ReturnType<typeof setTimeout> | null = null

async function fetchQuote() {
  quoteError.value = ''
  if (!amount.value || amount.value < minRecharge.value) {
    quote.value = null
    return
  }
  quoteLoading.value = true
  try {
    quote.value = await $api<Quote>('/v1/wallet/quote', { method: 'POST', body: { amount: amount.value } })
    minRecharge.value = quote.value.min_recharge_amount
  }
  catch (error: any) {
    quote.value = null
    quoteError.value = extractErrorMessage(error, 'Could not calculate pricing for this amount.')
  }
  finally {
    quoteLoading.value = false
  }
}

watch(amount, () => {
  if (quoteTimer)
    clearTimeout(quoteTimer)
  quoteTimer = setTimeout(fetchQuote, 350)
})

watch(() => props.isDialogVisible, async visible => {
  if (visible) {
    payError.value = ''
    try {
      const rateCard = await $api<{ name: string, min_recharge_amount: number }>('/v1/wallet/rate-card')
      minRecharge.value = rateCard.min_recharge_amount
      amount.value = rateCard.min_recharge_amount
    }
    catch {
      // Keep the previous default if the resolved card can't be fetched yet (e.g. no entity).
    }
    fetchQuote()
    loadPaymentOptions()
  }
})

function formatNumber(value: number): string {
  return value.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

let razorpayScriptPromise: Promise<void> | null = null

function loadRazorpayScript(): Promise<void> {
  if ((window as any).Razorpay)
    return Promise.resolve()
  if (!razorpayScriptPromise) {
    razorpayScriptPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script')
      script.src = 'https://checkout.razorpay.com/v1/checkout.js'
      script.onload = () => resolve()
      script.onerror = () => reject(new Error('Could not load Razorpay checkout script.'))
      document.head.appendChild(script)
    })
  }
  return razorpayScriptPromise
}

async function onContinueToPay() {
  payError.value = ''
  if (!amount.value || amount.value < minRecharge.value) {
    payError.value = `Minimum top-up is ₹${minRecharge.value.toLocaleString('en-IN')}.`
    return
  }
  if (selectedMethod.value === 'razorpay_smart_collect') {
    await openOtpDialog()
    return
  }
  paying.value = true
  try {
    const order = await $api<{ order_id: string, key_id: string, amount_paise: number }>('/v1/wallet/recharge/razorpay/order', {
      method: 'POST',
      body: { amount: amount.value },
    })
    await loadRazorpayScript()

    const razorpayInstance = new (window as any).Razorpay({
      key: order.key_id,
      amount: order.amount_paise,
      currency: 'INR',
      name: 'Textzi',
      description: 'SMS wallet recharge',
      order_id: order.order_id,
      theme: { color: '#F1600D' },
      handler: async (response: { razorpay_order_id: string, razorpay_payment_id: string, razorpay_signature: string }) => {
        try {
          await $api('/v1/wallet/recharge/razorpay/verify', { method: 'POST', body: response })
          emit('recharged')
          emit('update:isDialogVisible', false)
        }
        catch (error: any) {
          payError.value = extractErrorMessage(error, 'Payment succeeded but could not be verified. Contact support.')
        }
      },
      modal: {
        ondismiss: () => { paying.value = false },
      },
    })
    razorpayInstance.open()
  }
  catch (error: any) {
    payError.value = extractErrorMessage(error, 'Could not start Razorpay checkout.')
  }
  finally {
    paying.value = false
  }
}

async function onSimulateRecharge() {
  payError.value = ''
  if (!amount.value || amount.value < minRecharge.value) {
    payError.value = `Minimum top-up is ₹${minRecharge.value.toLocaleString('en-IN')}.`
    return
  }
  paying.value = true
  try {
    await $api('/v1/wallet/recharge', { method: 'POST', body: { amount: amount.value } })
    emit('recharged')
    emit('update:isDialogVisible', false)
  }
  catch (error: any) {
    payError.value = extractErrorMessage(error, 'Could not add funds. Please try again.')
  }
  finally {
    paying.value = false
  }
}
</script>

<template>
  <VDialog
    :model-value="props.isDialogVisible"
    :width="$vuetify.display.smAndDown ? 'auto' : 480"
    @update:model-value="(val: boolean) => emit('update:isDialogVisible', val)"
  >
    <DialogCloseBtn @click="emit('update:isDialogVisible', false)" />

    <VCard>
      <VCardText>
        <h4 class="text-h5 mb-6">
          Add Credits
        </h4>

        <AppTextField
          v-model.number="amount"
          type="number"
          label="Enter Amount"
          class="mb-1"
        />
        <p class="text-body-2 text-medium-emphasis mb-6">
          Minimum Top-up is ₹{{ minRecharge.toLocaleString('en-IN') }}.
        </p>

        <VAlert
          v-if="quoteError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ quoteError }}
        </VAlert>

        <VAlert
          v-if="payError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ payError }}
        </VAlert>

        <template v-if="quote">
          <h6 class="text-h6 mb-3">
            Order Summary
          </h6>
          <div class="d-flex justify-space-between mb-2">
            <span class="text-medium-emphasis">Order amount</span>
            <span>₹{{ formatNumber(quote.amount) }}</span>
          </div>
          <div class="d-flex justify-space-between mb-2">
            <span class="text-medium-emphasis">Taxation amount - GST (18%)</span>
            <span>₹{{ formatNumber(quote.gst_amount) }}</span>
          </div>
          <VDivider class="my-3" />
          <div class="d-flex justify-space-between mb-2">
            <span class="font-weight-medium">Total amount</span>
            <span class="font-weight-medium">₹{{ formatNumber(quote.total_amount) }}</span>
          </div>
          <div class="d-flex justify-space-between mb-2">
            <span class="text-medium-emphasis">SMS credits (@ ₹{{ quote.price_per_sms.toFixed(2) }}/SMS, {{ quote.rate_card_name }})</span>
            <span>{{ formatNumber(quote.credits) }}</span>
          </div>
          <div class="d-flex justify-space-between mb-6">
            <span class="text-medium-emphasis">Balance after payment</span>
            <span>{{ formatNumber(props.currentBalance + quote.credits) }} SMS</span>
          </div>
        </template>

        <VProgressLinear
          v-else-if="quoteLoading"
          indeterminate
          color="primary"
          class="mb-6"
        />

        <VRadioGroup v-if="checkoutEnabled && walletMethodEnabled" v-model="selectedMethod" density="compact" class="mb-2">
          <VRadio label="Pay now (card / UPI / netbanking)" value="razorpay_checkout" />
          <VRadio
            :label="`Textzi Wallet (balance: ₹${formatNumber(textziWalletBalance)}${!canPayWithWallet && quote ? ' — insufficient' : ''})`"
            value="razorpay_smart_collect"
            :disabled="!canPayWithWallet"
          />
        </VRadioGroup>
      </VCardText>

      <VCardText class="d-flex flex-column gap-3">
        <div class="d-flex gap-3 justify-end">
          <VBtn
            variant="outlined"
            @click="emit('update:isDialogVisible', false)"
          >
            Cancel
          </VBtn>
          <VBtn
            :loading="paying"
            :disabled="!quote || (selectedMethod === 'razorpay_smart_collect' && !canPayWithWallet)"
            @click="onContinueToPay"
          >
            {{ selectedMethod === 'razorpay_smart_collect' ? 'Pay with Textzi Wallet' : 'Continue to Pay' }}
          </VBtn>
        </div>
        <div v-if="quote?.dev_recharge_available" class="text-end">
          <VBtn
            variant="text"
            size="small"
            :loading="paying"
            :disabled="!quote"
            @click="onSimulateRecharge"
          >
            Simulate recharge (dev)
          </VBtn>
        </div>
      </VCardText>
    </VCard>
  </VDialog>

  <WalletOtpDialog
    v-model="otpDialogOpen"
    v-model:code="otpCode"
    :error="otpError"
    :submitting="otpSubmitting"
    :sent-via="otpSentVia"
    :masked-destination="otpMaskedDestination"
    @submit="onSubmitOtp"
    @cancel="otpDialogOpen = false"
  />
</template>
