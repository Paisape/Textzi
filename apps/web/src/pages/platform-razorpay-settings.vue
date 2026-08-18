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
}

const keyId = ref('')
const keySecret = ref('')
const keySecretConfigured = ref(false)

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
      },
    })
    keyId.value = result.key_id ?? ''
    keySecretConfigured.value = result.key_secret_configured
    keySecret.value = ''
    saveSuccess.value = 'Saved.'
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save Razorpay settings.')
  }
  finally {
    saving.value = false
  }
}

onMounted(loadSettings)
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
</template>
