<script setup lang="ts">
const props = defineProps<{ channel: 'waba' | 'crm' }>()

type Plan = {
  id: string
  channel: string
  name: string
  period: string
  price: number
  message_limit: number | null
  user_limit: number | null
  active: boolean
}
type Subscription = {
  channel: string
  plan: Plan | null
  period_start: string | null
  period_end: string | null
  messages_used: number
  seats_used: number
}

const plans = ref<Plan[]>([])
const subscription = ref<Subscription | null>(null)
const loading = ref(false)
const loadError = ref('')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [planResult, subResult] = await Promise.all([
      $api<Plan[]>('/v1/billing/plans', { params: { channel: props.channel } }),
      $api<Subscription>('/v1/billing/subscription', { params: { channel: props.channel } }),
    ])
    plans.value = planResult
    subscription.value = subResult
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load billing information.')
  }
  finally {
    loading.value = false
  }
}

const isActive = computed(() => {
  if (!subscription.value?.period_end)
    return false
  return new Date(subscription.value.period_end).getTime() > Date.now()
})

const periodLabel: Record<string, string> = { monthly: '/month', quarterly: '/quarter', yearly: '/year' }

// --- Razorpay checkout, same pattern as AddCreditsDialog.vue ---

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

const subscribing = ref<string | null>(null)
const payError = ref('')

async function subscribeToPlan(plan: Plan) {
  subscribing.value = plan.id
  payError.value = ''
  try {
    const order = await $api<{ order_id: string, key_id: string, amount_paise: number }>('/v1/billing/razorpay/order', {
      method: 'POST',
      body: { plan_id: plan.id },
    })
    await loadRazorpayScript()

    const razorpayInstance = new (window as any).Razorpay({
      key: order.key_id,
      amount: order.amount_paise,
      currency: 'INR',
      name: 'Textzi',
      description: `${plan.name} (${plan.period})`,
      order_id: order.order_id,
      theme: { color: '#F1600D' },
      handler: async (response: { razorpay_order_id: string, razorpay_payment_id: string, razorpay_signature: string }) => {
        try {
          subscription.value = await $api<Subscription>('/v1/billing/razorpay/verify', { method: 'POST', body: response })
        }
        catch (error: any) {
          payError.value = extractErrorMessage(error, 'Payment succeeded but could not be verified. Contact support.')
        }
        finally {
          subscribing.value = null
        }
      },
      modal: {
        ondismiss: () => { subscribing.value = null },
      },
    })
    razorpayInstance.open()
  }
  catch (error: any) {
    payError.value = extractErrorMessage(error, 'Could not start checkout.')
    subscribing.value = null
  }
}

onMounted(load)
</script>

<template>
  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>
  <VAlert v-if="payError" type="error" variant="tonal" class="mb-4">
    {{ payError }}
  </VAlert>

  <VCard v-if="subscription?.plan" class="mb-6" max-width="640">
    <VCardText>
      <div class="d-flex align-center justify-space-between mb-3">
        <h2 class="text-h6">
          Current plan
        </h2>
        <VChip size="small" :color="isActive ? 'success' : 'error'">
          {{ isActive ? 'Active' : 'Expired' }}
        </VChip>
      </div>
      <p class="text-body-1 mb-1">
        <strong>{{ subscription.plan.name }}</strong> -- ₹{{ subscription.plan.price.toLocaleString('en-IN') }}{{ periodLabel[subscription.plan.period] }}
      </p>
      <p class="text-body-2 text-medium-emphasis mb-3">
        {{ isActive ? 'Renews' : 'Expired' }} {{ subscription.period_end ? new Date(subscription.period_end).toLocaleDateString('en-IN') : '' }}
      </p>
      <div v-if="subscription.plan.message_limit" class="mb-2">
        <div class="d-flex justify-space-between text-body-2 mb-1">
          <span>Messages this period</span>
          <span>{{ subscription.messages_used }} / {{ subscription.plan.message_limit }}</span>
        </div>
        <VProgressLinear
          :model-value="(subscription.messages_used / subscription.plan.message_limit) * 100"
          :color="subscription.messages_used >= subscription.plan.message_limit ? 'error' : 'primary'"
          height="6"
          rounded
        />
      </div>
      <div v-if="subscription.plan.user_limit">
        <div class="d-flex justify-space-between text-body-2 mb-1">
          <span>Team seats</span>
          <span>{{ subscription.seats_used }} / {{ subscription.plan.user_limit }}</span>
        </div>
        <VProgressLinear
          :model-value="(subscription.seats_used / subscription.plan.user_limit) * 100"
          :color="subscription.seats_used >= subscription.plan.user_limit ? 'error' : 'primary'"
          height="6"
          rounded
        />
      </div>
    </VCardText>
  </VCard>

  <h2 class="text-h6 mb-3">
    {{ subscription?.plan ? 'Change plan' : 'Choose a plan' }}
  </h2>
  <VRow>
    <VCol v-for="plan in plans" :key="plan.id" cols="12" sm="6" md="4">
      <VCard :variant="subscription?.plan?.id === plan.id && isActive ? 'tonal' : 'outlined'" class="h-100 d-flex flex-column">
        <VCardText class="flex-grow-1">
          <h3 class="text-h6 mb-1">
            {{ plan.name }}
          </h3>
          <p class="text-h5 mb-2">
            ₹{{ plan.price.toLocaleString('en-IN') }}<span class="text-body-2 text-medium-emphasis">{{ periodLabel[plan.period] }}</span>
          </p>
          <p v-if="plan.message_limit" class="text-body-2 text-medium-emphasis mb-1">
            {{ plan.message_limit.toLocaleString('en-IN') }} messages / period
          </p>
          <p v-if="plan.user_limit" class="text-body-2 text-medium-emphasis mb-0">
            Up to {{ plan.user_limit }} team seats
          </p>
        </VCardText>
        <VCardText class="pt-0">
          <VBtn
            block
            :disabled="subscription?.plan?.id === plan.id && isActive"
            :loading="subscribing === plan.id"
            @click="subscribeToPlan(plan)"
          >
            {{ subscription?.plan?.id === plan.id && isActive ? 'Current plan' : 'Subscribe' }}
          </VBtn>
        </VCardText>
      </VCard>
    </VCol>
  </VRow>
  <p v-if="!loading && !plans.length" class="text-medium-emphasis">
    No plans published yet for this channel.
  </p>
</template>
