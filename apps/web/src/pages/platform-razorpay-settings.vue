<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
    requiresAdmin: true,
  },
})

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.loaded ? authStore.isAdmin : null)

type RazorpaySettings = {
  key_id: string | null
  key_secret_configured: boolean
  webhook_secret_configured: boolean
}

const keyId = ref('')
const keySecret = ref('')
const keySecretConfigured = ref(false)
const webhookSecret = ref('')
const webhookSecretConfigured = ref(false)

const loadError = ref('')
const saveError = ref('')
const saveSuccess = ref('')
const saving = ref(false)

async function loadSettings() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const result = await $api<RazorpaySettings>('/v1/admin/platform/razorpay-settings')
    keyId.value = result.key_id ?? ''
    keySecretConfigured.value = result.key_secret_configured
    webhookSecretConfigured.value = result.webhook_secret_configured
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load Razorpay settings.')
  }
}

async function onSave() {
  saveError.value = ''
  saveSuccess.value = ''
  saving.value = true
  try {
    const result = await $api<RazorpaySettings>('/v1/admin/platform/razorpay-settings', {
      method: 'PUT',
      body: {
        key_id: keyId.value || null,
        key_secret: keySecret.value || null,
        webhook_secret: webhookSecret.value || null,
      },
    })
    keyId.value = result.key_id ?? ''
    keySecretConfigured.value = result.key_secret_configured
    webhookSecretConfigured.value = result.webhook_secret_configured
    keySecret.value = ''
    webhookSecret.value = ''
    saveSuccess.value = 'Saved.'
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save Razorpay settings.')
  }
  finally {
    saving.value = false
  }
}

// --- Payment methods (Checkout / Smart Collect) -------------------------------------------

type PaymentMethod = { payment_method: string, enabled: boolean, flat_fee_paise: number }

const paymentMethods = ref<PaymentMethod[]>([])
const methodsError = ref('')
const methodsSaving = ref<string | null>(null)

const METHOD_LABELS: Record<string, string> = {
  razorpay_checkout: 'Razorpay Checkout (instant, card/UPI/netbanking)',
  razorpay_smart_collect: 'Razorpay Smart Collect (bank transfer, funds Textzi Wallet)',
}

async function loadPaymentMethods() {
  methodsError.value = ''
  try {
    paymentMethods.value = await $api<PaymentMethod[]>('/v1/admin/payment-methods')
  }
  catch (error: any) {
    methodsError.value = extractErrorMessage(error, 'Could not load payment methods.')
  }
}

async function saveMethod(method: PaymentMethod) {
  methodsSaving.value = method.payment_method
  methodsError.value = ''
  try {
    const updated = await $api<PaymentMethod>(`/v1/admin/payment-methods/${method.payment_method}`, {
      method: 'PUT',
      body: { enabled: method.enabled, flat_fee_paise: method.flat_fee_paise },
    })
    const idx = paymentMethods.value.findIndex(m => m.payment_method === updated.payment_method)
    if (idx !== -1)
      paymentMethods.value[idx] = updated
  }
  catch (error: any) {
    methodsError.value = extractErrorMessage(error, 'Could not save this payment method.')
  }
  finally {
    methodsSaving.value = null
  }
}

onMounted(() => {
  loadSettings()
  loadPaymentMethods()
})
</script>

<template>
  <h1 class="text-h4 mb-1">
    Platform Razorpay Setting
  </h1>
  <p class="text-medium-emphasis mb-6">
    Razorpay credentials used for wallet recharge, channel-plan checkout, and DLT registration
    payment -- these are live keys used by real customer checkout today. Set here, or leave blank
    to keep using RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET from .env.
  </p>

  <VAlert
    v-if="isAdmin === false"
    type="warning"
    variant="tonal"
  >
    This page is restricted to Super Admin and Operator Admin roles.
  </VAlert>

  <VAlert
    v-else-if="loadError"
    type="error"
    variant="tonal"
  >
    {{ loadError }}
  </VAlert>

  <VCard
    v-else-if="isAdmin"
    max-width="640"
  >
    <VCardText>
      <VAlert type="warning" variant="tonal" density="compact" class="mb-4">
        These keys are live and in use by real customer payments right now. Saving the wrong
        values here will break checkout immediately -- double-check before saving.
      </VAlert>

      <VChip
        :color="keySecretConfigured ? 'success' : 'warning'"
        size="small"
        class="mb-4"
      >
        {{ keySecretConfigured ? 'Configured' : 'Not configured (falls back to .env)' }}
      </VChip>

      <VAlert
        v-if="saveError"
        type="error"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        {{ saveError }}
      </VAlert>
      <VAlert
        v-if="saveSuccess"
        type="success"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        {{ saveSuccess }}
      </VAlert>

      <VForm @submit.prevent="onSave">
        <VRow>
          <VCol cols="12">
            <AppTextField
              v-model="keyId"
              label="Key ID"
              placeholder="rzp_live_xxxxxxxxxxxx"
            />
          </VCol>
          <VCol cols="12">
            <AppTextField
              v-model="keySecret"
              type="password"
              label="Key Secret"
              placeholder="Leave blank to keep the current secret"
            />
          </VCol>
          <VCol cols="12">
            <VChip
              :color="webhookSecretConfigured ? 'success' : 'warning'"
              size="small"
              class="mb-2"
            >
              Webhook secret: {{ webhookSecretConfigured ? 'Configured' : 'Not configured' }}
            </VChip>
            <AppTextField
              v-model="webhookSecret"
              type="password"
              label="Smart Collect Webhook Secret"
              placeholder="From Razorpay Dashboard > Webhooks -- leave blank to keep the current one"
              hint="Verifies the virtual_account.credited webhook signature. Required before Smart Collect can credit any Textzi Wallet."
              persistent-hint
            />
          </VCol>
          <VCol cols="12">
            <VBtn
              type="submit"
              :loading="saving"
            >
              Save
            </VBtn>
          </VCol>
        </VRow>
      </VForm>
    </VCardText>
  </VCard>

  <VCard
    v-if="isAdmin"
    max-width="640"
    class="mt-6"
  >
    <VCardText>
      <h2 class="text-h6 mb-1">
        Payment methods
      </h2>
      <p class="text-body-2 text-medium-emphasis mb-4">
        Enable or disable each way a customer can pay -- for wallet top-up, WABA subscription, and CRM subscription. Both can be on at once.
      </p>
      <VAlert v-if="methodsError" type="error" variant="tonal" density="compact" class="mb-4">
        {{ methodsError }}
      </VAlert>
      <div v-for="method in paymentMethods" :key="method.payment_method" class="mb-4">
        <div class="d-flex align-center justify-space-between">
          <span class="text-body-2">{{ METHOD_LABELS[method.payment_method] || method.payment_method }}</span>
          <VSwitch v-model="method.enabled" density="compact" hide-details @update:model-value="saveMethod(method)" />
        </div>
        <AppTextField
          v-if="method.payment_method === 'razorpay_smart_collect'"
          v-model.number="method.flat_fee_paise"
          type="number"
          density="compact"
          label="Flat fee (paise) deducted from every transfer"
          class="mt-2"
          style="max-inline-size: 320px;"
          :loading="methodsSaving === method.payment_method"
          @change="saveMethod(method)"
        />
      </div>
    </VCardText>
  </VCard>
</template>
