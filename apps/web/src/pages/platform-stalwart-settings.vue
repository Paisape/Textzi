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

type StalwartSettings = {
  admin_url: string | null
  admin_user: string | null
  mail_domain: string | null
  admin_password_configured: boolean
  cloudflare_configured: boolean
}

const adminUrl = ref('')
const adminUser = ref('')
const adminPassword = ref('')
const mailDomain = ref('')
const cloudflareApiToken = ref('')
const adminPasswordConfigured = ref(false)
const cloudflareConfigured = ref(false)

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
    const result = await $api<StalwartSettings>('/v1/admin/platform/stalwart-settings')
    adminUrl.value = result.admin_url ?? ''
    adminUser.value = result.admin_user ?? ''
    mailDomain.value = result.mail_domain ?? ''
    adminPasswordConfigured.value = result.admin_password_configured
    cloudflareConfigured.value = result.cloudflare_configured
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load Stalwart settings.')
  }
}

async function onSave() {
  saveError.value = ''
  saveSuccess.value = ''
  saving.value = true
  try {
    const result = await $api<StalwartSettings>('/v1/admin/platform/stalwart-settings', {
      method: 'PUT',
      body: {
        admin_url: adminUrl.value || null,
        admin_user: adminUser.value || null,
        admin_password: adminPassword.value || null,
        mail_domain: mailDomain.value || null,
        cloudflare_api_token: cloudflareApiToken.value || null,
      },
    })
    adminPasswordConfigured.value = result.admin_password_configured
    cloudflareConfigured.value = result.cloudflare_configured
    adminPassword.value = ''
    cloudflareApiToken.value = ''
    saveSuccess.value = 'Saved.'
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save Stalwart settings.')
  }
  finally {
    saving.value = false
  }
}

async function onTestConnection() {
  testResult.value = null
  testing.value = true
  try {
    testResult.value = await $api('/v1/admin/platform/stalwart-settings/test-connection', { method: 'POST' })
  }
  catch (error: any) {
    testResult.value = { ok: false, detail: extractErrorMessage(error, 'Could not test the Stalwart connection.') }
  }
  finally {
    testing.value = false
  }
}

onMounted(loadSettings)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Platform Stalwart Setting
  </h1>
  <p class="text-medium-emphasis mb-6">
    Connection details for Textzi's own self-hosted Stalwart mail server -- used to provision
    Textzi-hosted CRM mailboxes (Channels &gt; Email &gt; "Create a Textzi mailbox"). The
    Cloudflare API token is only needed once a real domain's DNS is on Cloudflare, for automatic
    MX/SPF/DKIM/DMARC record management; leave it blank for local development.
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
      <div class="d-flex flex-wrap ga-2 mb-4">
        <VChip
          :color="adminPasswordConfigured ? 'success' : 'warning'"
          size="small"
        >
          {{ adminPasswordConfigured ? 'Configured' : 'Not configured (falls back to .env / development mode)' }}
        </VChip>
        <VChip
          :color="cloudflareConfigured ? 'success' : undefined"
          size="small"
        >
          {{ cloudflareConfigured ? 'Cloudflare token set' : 'Cloudflare token not set' }}
        </VChip>
      </div>

      <div v-if="adminPasswordConfigured" class="d-flex align-center ga-3 mb-4">
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
              v-model="adminUrl"
              label="Admin API URL"
              placeholder="http://stalwart:8080"
            />
          </VCol>
          <VCol cols="12">
            <AppTextField
              v-model="adminUser"
              label="Admin Username"
              placeholder="admin"
            />
          </VCol>
          <VCol cols="12">
            <AppTextField
              v-model="adminPassword"
              type="password"
              label="Admin Password"
              placeholder="Leave blank to keep the current password"
            />
          </VCol>
          <VCol cols="12">
            <AppTextField
              v-model="mailDomain"
              label="Mail Domain"
              placeholder="mail.textzi.in"
            />
          </VCol>
          <VCol cols="12">
            <AppTextField
              v-model="cloudflareApiToken"
              type="password"
              label="Cloudflare API Token"
              placeholder="Leave blank to keep the current token"
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
