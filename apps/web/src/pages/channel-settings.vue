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
const stepUp = useStepUpAuth()

type FeeConfig = { channel: string, subscription_price: number, dlt_platform_fee: number, dlt_service_fee: number }

const loadError = ref('')
const fees = ref<FeeConfig | null>(null)
const subscriptionPrice = ref(0)
const dltPlatformFee = ref(0)
const dltServiceFee = ref(0)
const saving = ref(false)
const saveError = ref('')
const saveSuccess = ref('')

async function load() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const result = await stepUp.withStepUp(() => $api<FeeConfig>('/v1/admin/channel-fees/sms'))
    fees.value = result
    subscriptionPrice.value = result.subscription_price
    dltPlatformFee.value = result.dlt_platform_fee
    dltServiceFee.value = result.dlt_service_fee
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load channel fee configuration.')
  }
}

async function onSave() {
  saveError.value = ''
  saveSuccess.value = ''
  saving.value = true
  try {
    fees.value = await stepUp.withStepUp(() => $api<FeeConfig>('/v1/admin/channel-fees/sms', {
      method: 'PUT',
      body: {
        subscription_price: subscriptionPrice.value,
        dlt_platform_fee: dltPlatformFee.value,
        dlt_service_fee: dltServiceFee.value,
      },
    }))
    saveSuccess.value = 'Saved.'
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save fee configuration.')
  }
  finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Channel Settings
  </h1>
  <p class="text-medium-emphasis mb-6">
    Configure activation fees for the SMS channel. The two DLT fee components are summed and shown to customers as one combined figure — never itemised to them.
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
    v-else-if="isAdmin && fees"
    max-width="520"
  >
    <VCardText>
      <h6 class="text-h6 mb-4">
        SMS Channel
      </h6>
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
        <AppTextField
          v-model.number="subscriptionPrice"
          type="number"
          label="Channel subscription price (₹)"
          hint="0 means the channel activates on DLT registration alone, with no separate payment step."
          persistent-hint
          class="mb-6"
        />
        <AppTextField
          v-model.number="dltPlatformFee"
          type="number"
          label="DLT platform fee (₹)"
          hint="What the DLT aggregator/platform itself charges for registration."
          persistent-hint
          class="mb-6"
        />
        <AppTextField
          v-model.number="dltServiceFee"
          type="number"
          label="Textzi service fee (₹)"
          hint="Textzi's own markup for handling the registration on the customer's behalf."
          persistent-hint
          class="mb-6"
        />
        <p class="text-body-2 text-medium-emphasis mb-6">
          Customers requesting DLT registration help will see a combined fee of ₹{{ (dltPlatformFee + dltServiceFee).toLocaleString('en-IN') }} + GST.
        </p>
        <VBtn
          type="submit"
          :loading="saving"
        >
          Save
        </VBtn>
      </VForm>
    </VCardText>
  </VCard>

  <StepUpDialog
    v-model="stepUp.dialogOpen.value"
    :code="stepUp.code.value"
    :error="stepUp.error.value"
    :submitting="stepUp.submitting.value"
    @update:code="v => stepUp.code.value = v"
    @submit="stepUp.submit"
    @cancel="stepUp.cancel"
  />
</template>
