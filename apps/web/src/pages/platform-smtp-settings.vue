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

type SmtpSettings = {
  host: string | null
  port: number
  username: string | null
  from_address: string
  use_tls: boolean
  configured: boolean
}

const host = ref('')
const port = ref(587)
const username = ref('')
const password = ref('')
const fromAddress = ref('no-reply@textzi.in')
const useTls = ref(true)
const configured = ref(false)

const loadError = ref('')
const saveError = ref('')
const saveSuccess = ref('')
const saving = ref(false)

const testEmail = ref('')
const testing = ref(false)
const testResult = ref<{ ok: boolean, detail: string } | null>(null)

async function loadSettings() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    if (!testEmail.value && authStore.profile?.email)
      testEmail.value = authStore.profile.email
    const result = await $api<SmtpSettings>('/v1/admin/platform/smtp-settings')
    host.value = result.host ?? ''
    port.value = result.port
    username.value = result.username ?? ''
    fromAddress.value = result.from_address
    useTls.value = result.use_tls
    configured.value = result.configured
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load SMTP settings.')
  }
}

async function onSave() {
  saveError.value = ''
  saveSuccess.value = ''
  saving.value = true
  try {
    const result = await $api<SmtpSettings>('/v1/admin/platform/smtp-settings', {
      method: 'PUT',
      body: {
        host: host.value || null,
        port: port.value,
        username: username.value || null,
        password: password.value || null,
        from_address: fromAddress.value,
        use_tls: useTls.value,
      },
    })
    configured.value = result.configured
    password.value = ''
    saveSuccess.value = 'Saved.'
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save SMTP settings.')
  }
  finally {
    saving.value = false
  }
}

async function onSendTestEmail() {
  testResult.value = null
  testing.value = true
  try {
    testResult.value = await $api('/v1/admin/platform/smtp-settings/test', {
      method: 'POST',
      body: { to_email: testEmail.value.trim() },
    })
  }
  catch (error: any) {
    testResult.value = { ok: false, detail: extractErrorMessage(error, 'Could not send test email.') }
  }
  finally {
    testing.value = false
  }
}

onMounted(loadSettings)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Platform SMTP Setting
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every platform-to-user email (account verification, invoices, team invites) is sent through
    this configuration. Until it's set, emails are logged instead of sent -- safe for
    development.
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
        {{ configured ? 'Configured' : 'Not configured (emails are logged, not sent)' }}
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
          <VCol cols="12" sm="8">
            <AppTextField
              v-model="host"
              label="SMTP host"
              placeholder="smtp.sendgrid.net"
            />
          </VCol>
          <VCol cols="12" sm="4">
            <AppTextField
              v-model.number="port"
              type="number"
              label="Port"
              placeholder="587"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="username"
              label="Username"
              placeholder="apikey"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="password"
              type="password"
              label="Password"
              placeholder="Leave blank to keep the current password"
            />
          </VCol>
          <VCol cols="12" sm="8">
            <AppTextField
              v-model="fromAddress"
              label="From address"
              placeholder="no-reply@textzi.in"
            />
          </VCol>
          <VCol cols="12" sm="4" class="d-flex align-center">
            <VSwitch
              v-model="useTls"
              label="Use TLS"
              color="success"
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

      <h2 class="text-subtitle-1 font-weight-medium mb-1">
        Send Test Email
      </h2>
      <p class="text-body-2 text-medium-emphasis mb-4">
        Sends a test email using the currently saved SMTP settings.
      </p>

      <VAlert
        v-if="testResult"
        :type="testResult.ok ? 'success' : 'error'"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        {{ testResult.detail }}
      </VAlert>

      <VForm @submit.prevent="onSendTestEmail">
        <VRow align="end">
          <VCol cols="12" sm="8">
            <AppTextField
              v-model="testEmail"
              type="email"
              label="Recipient email"
              placeholder="admin@textzi.in"
              :disabled="!configured"
            />
          </VCol>
          <VCol cols="12" sm="4">
            <VBtn
              type="submit"
              variant="tonal"
              block
              :loading="testing"
              :disabled="!configured || !testEmail.trim()"
            >
              Send Test Email
            </VBtn>
          </VCol>
        </VRow>
      </VForm>
    </VCardText>
  </VCard>
</template>
