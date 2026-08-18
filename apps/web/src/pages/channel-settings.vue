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

type FeeConfig = { channel: string, subscription_price: number, dlt_platform_fee: number, dlt_service_fee: number, enabled: boolean }

const loadError = ref('')
const fees = ref<FeeConfig | null>(null)
const subscriptionPrice = ref(0)
const dltPlatformFee = ref(0)
const dltServiceFee = ref(0)
const saving = ref(false)
const saveError = ref('')
const saveSuccess = ref('')

// --- Global per-channel kill switch -- independent of the SMS-specific fee form below. Off means
// dead for every customer regardless of their own subscription/connection state. ------------------

const CHANNELS = ['sms', 'waba', 'crm'] as const
const channelConfigs = ref<Record<string, FeeConfig>>({})
const channelToggleBusy = ref<string | null>(null)
const channelToggleError = ref('')

async function loadChannelConfig(channel: string): Promise<FeeConfig> {
  try {
    return await stepUp.withStepUp(() => $api<FeeConfig>(`/v1/admin/channel-fees/${channel}`))
  }
  catch (error: any) {
    if (error?.statusCode === 404 || error?.response?.status === 404)
      return { channel, subscription_price: 0, dlt_platform_fee: 0, dlt_service_fee: 0, enabled: true }
    throw error
  }
}

async function loadChannelToggles() {
  channelToggleError.value = ''
  try {
    const results = await Promise.all(CHANNELS.map(loadChannelConfig))
    for (const result of results)
      channelConfigs.value[result.channel] = result
  }
  catch (error: any) {
    channelToggleError.value = extractErrorMessage(error, 'Could not load channel status.')
  }
}

async function toggleChannel(channel: string, enabled: boolean) {
  const current = channelConfigs.value[channel]
  if (!current)
    return
  channelToggleBusy.value = channel
  channelToggleError.value = ''
  try {
    channelConfigs.value[channel] = await stepUp.withStepUp(() => $api<FeeConfig>(`/v1/admin/channel-fees/${channel}`, {
      method: 'PUT',
      body: {
        subscription_price: current.subscription_price, dlt_platform_fee: current.dlt_platform_fee,
        dlt_service_fee: current.dlt_service_fee, enabled,
      },
    }))
    if (channel === 'sms')
      fees.value = channelConfigs.value.sms
  }
  catch (error: any) {
    channelToggleError.value = extractErrorMessage(error, `Could not update ${channel.toUpperCase()}.`)
  }
  finally {
    channelToggleBusy.value = null
  }
}

async function load() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const result = await loadChannelConfig('sms')
    fees.value = result
    channelConfigs.value.sms = result
    subscriptionPrice.value = result.subscription_price
    dltPlatformFee.value = result.dlt_platform_fee
    dltServiceFee.value = result.dlt_service_fee
    await loadChannelToggles()
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
        enabled: fees.value?.enabled ?? true,
      },
    }))
    channelConfigs.value.sms = fees.value
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

  <VCard v-if="isAdmin && fees" max-width="520" class="mb-6">
    <VCardText>
      <h6 class="text-h6 mb-1">
        Channels
      </h6>
      <p class="text-body-2 text-medium-emphasis mb-4">
        Global on/off per channel — independent of any customer's own subscription or connection
        state. Off means dead for every customer immediately, no matter what.
      </p>
      <VAlert v-if="channelToggleError" type="error" variant="tonal" density="compact" class="mb-4">
        {{ channelToggleError }}
      </VAlert>
      <div v-for="channel in CHANNELS" :key="channel" class="d-flex align-center justify-space-between py-1">
        <span class="text-body-2 text-uppercase">{{ channel }}</span>
        <VSwitch
          :model-value="channelConfigs[channel]?.enabled ?? true" :loading="channelToggleBusy === channel"
          density="compact" hide-details color="success"
          @update:model-value="(v: boolean | null) => toggleChannel(channel, !!v)"
        />
      </div>
    </VCardText>
  </VCard>

  <VCard
    v-if="isAdmin && fees"
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
