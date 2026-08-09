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

type TurnstileSettings = {
  site_key: string | null
  configured: boolean
}

const siteKey = ref('')
const secretKey = ref('')
const configured = ref(false)

const loadError = ref('')
const saveError = ref('')
const saveSuccess = ref('')
const saving = ref(false)
const testing = ref(false)
const testResult = ref<{ ok: boolean, detail: string } | null>(null)

async function loadSettings() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const result = await $api<TurnstileSettings>('/v1/admin/platform/turnstile-settings')
    siteKey.value = result.site_key ?? ''
    configured.value = result.configured
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load Turnstile settings.')
  }
}

async function onSave() {
  saveError.value = ''
  saveSuccess.value = ''
  saving.value = true
  try {
    const result = await $api<TurnstileSettings>('/v1/admin/platform/turnstile-settings', {
      method: 'PUT',
      body: {
        site_key: siteKey.value || null,
        secret_key: secretKey.value || null,
      },
    })
    configured.value = result.configured
    secretKey.value = ''
    saveSuccess.value = 'Saved.'
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save Turnstile settings.')
  }
  finally {
    saving.value = false
  }
}

async function onTestConnection() {
  testResult.value = null
  testing.value = true
  try {
    testResult.value = await $api('/v1/admin/platform/turnstile-settings/test-connection', { method: 'POST' })
  }
  catch (error: any) {
    testResult.value = { ok: false, detail: extractErrorMessage(error, 'Could not test the Turnstile connection.') }
  }
  finally {
    testing.value = false
  }
}

onMounted(loadSettings)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Platform Turnstile Setting
  </h1>
  <p class="text-medium-emphasis mb-6">
    Cloudflare Turnstile credentials for the bot-check widget shown on the public contact form,
    register, login, and forgot-password pages. The site key isn't secret (it's already visible in
    every visitor's browser) and updates those pages immediately without a redeploy; the secret key
    is used server-side to verify each submission and is never shown back once saved.
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
      <VChip
        :color="configured ? 'success' : 'warning'"
        size="small"
        class="mb-4"
      >
        {{ configured ? 'Configured' : 'Not configured (falls back to .env / development mode)' }}
      </VChip>

      <div v-if="configured" class="d-flex align-center ga-3 mb-4">
        <VBtn
          size="small"
          variant="tonal"
          :loading="testing"
          @click="onTestConnection"
        >
          Test Connection
        </VBtn>
        <span
          v-if="testResult"
          :class="testResult.ok ? 'text-success' : 'text-error'"
          class="text-body-2"
        >
          {{ testResult.detail }}
        </span>
      </div>

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
              v-model="siteKey"
              label="Site Key"
              placeholder="0x4AAAAAAEK61ZxTLsoU-BJ5"
            />
          </VCol>
          <VCol cols="12">
            <AppTextField
              v-model="secretKey"
              type="password"
              label="Secret Key"
              placeholder="Leave blank to keep the current key"
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
