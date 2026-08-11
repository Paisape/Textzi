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

type WabaSettings = {
  app_id: string | null
  config_id: string | null
  configured: boolean
  webhook_url: string | null
  webhook_verify_token: string | null
}

const appId = ref('')
const configId = ref('')
const appSecret = ref('')
const configured = ref(false)
const webhookUrl = ref<string | null>(null)
const webhookVerifyToken = ref<string | null>(null)

const loadError = ref('')
const saveError = ref('')
const saveSuccess = ref('')
const saving = ref(false)
const testing = ref(false)
const testResult = ref<{ ok: boolean, detail: string } | null>(null)
const generatingToken = ref(false)
const generateTokenError = ref('')

async function loadSettings() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const result = await $api<WabaSettings>('/v1/admin/platform/waba-settings')
    appId.value = result.app_id ?? ''
    configId.value = result.config_id ?? ''
    configured.value = result.configured
    webhookUrl.value = result.webhook_url
    webhookVerifyToken.value = result.webhook_verify_token
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load WhatsApp settings.')
  }
}

async function onGenerateWebhookToken() {
  generateTokenError.value = ''
  generatingToken.value = true
  try {
    const result = await $api<{ webhook_url: string | null, webhook_verify_token: string }>('/v1/admin/platform/waba-settings/generate-webhook-token', { method: 'POST' })
    webhookUrl.value = result.webhook_url
    webhookVerifyToken.value = result.webhook_verify_token
  }
  catch (error: any) {
    generateTokenError.value = extractErrorMessage(error, 'Could not generate a webhook verify token.')
  }
  finally {
    generatingToken.value = false
  }
}

async function onSave() {
  saveError.value = ''
  saveSuccess.value = ''
  saving.value = true
  try {
    const result = await $api<WabaSettings>('/v1/admin/platform/waba-settings', {
      method: 'PUT',
      body: {
        app_id: appId.value || null,
        config_id: configId.value || null,
        app_secret: appSecret.value || null,
      },
    })
    configured.value = result.configured
    appSecret.value = ''
    saveSuccess.value = 'Saved.'
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save WhatsApp settings.')
  }
  finally {
    saving.value = false
  }
}

async function onTestConnection() {
  testResult.value = null
  testing.value = true
  try {
    testResult.value = await $api('/v1/admin/platform/waba-settings/test-connection', { method: 'POST' })
  }
  catch (error: any) {
    testResult.value = { ok: false, detail: extractErrorMessage(error, 'Could not test the WhatsApp connection.') }
  }
  finally {
    testing.value = false
  }
}

onMounted(loadSettings)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Platform WhatsApp Setting
  </h1>
  <p class="text-medium-emphasis mb-6">
    Textzi's own Meta Tech Provider app credentials, used to power WhatsApp Embedded Signup on
    every customer's "Connect WhatsApp" flow. App ID and Configuration ID aren't secret (the App
    ID ships to every customer's browser via Meta's own SDK regardless); the App Secret is used
    server-side only, to exchange a signup code for a real access token, and is never shown back
    once saved.
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
        {{ configured ? 'Configured' : 'Not configured' }}
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
              v-model="appId"
              label="Meta App ID"
            />
          </VCol>
          <VCol cols="12">
            <AppTextField
              v-model="configId"
              label="Embedded Signup Configuration ID"
            />
          </VCol>
          <VCol cols="12">
            <AppTextField
              v-model="appSecret"
              type="password"
              label="Meta App Secret"
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

      <VDivider class="my-6" />

      <h2 class="text-h6 mb-1">
        Webhook
      </h2>
      <p class="text-body-2 text-medium-emphasis mb-4">
        Register this callback URL and verify token under Meta App Dashboard &gt; WhatsApp &gt;
        Configuration so Textzi receives incoming messages and delivery status updates. One URL
        covers every connected customer -- Meta identifies which customer each event belongs to.
      </p>

      <VAlert
        v-if="generateTokenError"
        type="error"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        {{ generateTokenError }}
      </VAlert>

      <VTable density="compact" class="mb-4">
        <tbody>
          <tr>
            <td class="text-medium-emphasis">
              Callback URL
            </td>
            <td>{{ webhookUrl || '— configure Company > Public API base URL first —' }}</td>
          </tr>
          <tr>
            <td class="text-medium-emphasis">
              Verify token
            </td>
            <td>{{ webhookVerifyToken || '— not generated yet —' }}</td>
          </tr>
        </tbody>
      </VTable>

      <VBtn
        size="small"
        variant="tonal"
        :loading="generatingToken"
        @click="onGenerateWebhookToken"
      >
        {{ webhookVerifyToken ? 'Regenerate token' : 'Generate token' }}
      </VBtn>
    </VCardText>
  </VCard>
</template>
