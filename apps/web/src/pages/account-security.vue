<script setup lang="ts">
import QRCode from 'qrcode'

definePage({
  meta: {
    layout: 'default',
  },
})

const enabled = ref<boolean | null>(null)
const statusError = ref('')

const enrolling = ref(false)
const enrollError = ref('')
const secret = ref('')
const otpauthUri = ref('')
const qrDataUrl = ref('')
const confirmCode = ref('')
const confirming = ref(false)

const disabling = ref(false)
const disableCode = ref('')
const disableError = ref('')
const showDisableForm = ref(false)

async function loadStatus() {
  statusError.value = ''
  try {
    const result = await $api<{ enabled: boolean }>('/v1/auth/2fa/status')
    enabled.value = result.enabled
  }
  catch (error: any) {
    statusError.value = extractErrorMessage(error, 'Could not load two-factor authentication status.')
  }
}

onMounted(loadStatus)

async function onStartEnroll() {
  enrollError.value = ''
  enrolling.value = true
  try {
    const result = await $api<{ secret: string, otpauth_uri: string }>('/v1/auth/2fa/enroll', { method: 'POST' })
    secret.value = result.secret
    otpauthUri.value = result.otpauth_uri
    qrDataUrl.value = await QRCode.toDataURL(result.otpauth_uri)
  }
  catch (error: any) {
    enrollError.value = extractErrorMessage(error, 'Could not start enrollment.')
  }
  finally {
    enrolling.value = false
  }
}

async function onConfirmEnroll() {
  enrollError.value = ''
  confirming.value = true
  try {
    await $api('/v1/auth/2fa/confirm', { method: 'POST', body: { code: confirmCode.value } })
    secret.value = ''
    otpauthUri.value = ''
    qrDataUrl.value = ''
    confirmCode.value = ''
    enabled.value = true
  }
  catch (error: any) {
    enrollError.value = extractErrorMessage(error, 'Incorrect authenticator code.')
  }
  finally {
    confirming.value = false
  }
}

async function onDisable() {
  disableError.value = ''
  disabling.value = true
  try {
    await $api('/v1/auth/2fa/disable', { method: 'POST', body: { code: disableCode.value } })
    enabled.value = false
    showDisableForm.value = false
    disableCode.value = ''
  }
  catch (error: any) {
    disableError.value = extractErrorMessage(error, 'Incorrect authenticator code.')
  }
  finally {
    disabling.value = false
  }
}

const currentPassword = ref('')
const newPassword = ref('')
const changingPassword = ref(false)
const changePasswordError = ref('')
const changePasswordSuccess = ref('')

async function onChangePassword() {
  changePasswordError.value = ''
  changePasswordSuccess.value = ''
  changingPassword.value = true
  try {
    await $api('/v1/auth/change-password', { method: 'POST', body: { current_password: currentPassword.value, new_password: newPassword.value } })
    changePasswordSuccess.value = 'Password changed.'
    currentPassword.value = ''
    newPassword.value = ''
  }
  catch (error: any) {
    changePasswordError.value = extractErrorMessage(error, 'Could not change your password.')
  }
  finally {
    changingPassword.value = false
  }
}

type SessionRow = { id: string, ip_address: string | null, user_agent: string | null, created_at: string, is_current: boolean }

const sessions = ref<SessionRow[]>([])
const sessionsError = ref('')
const revokingId = ref<string | null>(null)
const revokingOthers = ref(false)

async function loadSessions() {
  sessionsError.value = ''
  try {
    sessions.value = await $api<SessionRow[]>('/v1/auth/sessions')
  }
  catch (error: any) {
    sessionsError.value = extractErrorMessage(error, 'Could not load active sessions.')
  }
}

async function onRevokeSession(session: SessionRow) {
  revokingId.value = session.id
  try {
    await $api(`/v1/auth/sessions/${session.id}`, { method: 'DELETE' })
    await loadSessions()
  }
  catch (error: any) {
    sessionsError.value = extractErrorMessage(error, 'Could not sign out this session.')
  }
  finally {
    revokingId.value = null
  }
}

async function onRevokeOthers() {
  revokingOthers.value = true
  try {
    await $api('/v1/auth/sessions/revoke-others', { method: 'POST' })
    await loadSessions()
  }
  catch (error: any) {
    sessionsError.value = extractErrorMessage(error, 'Could not sign out other sessions.')
  }
  finally {
    revokingOthers.value = false
  }
}

onMounted(loadSessions)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Account Security
  </h1>
  <p class="text-medium-emphasis mb-6">
    Two-factor authentication adds a second check with an authenticator app, required at login
    and again before viewing sensitive settings.
  </p>

  <VCard max-width="640">
    <VCardText>
      <VAlert
        v-if="statusError"
        type="error"
        variant="tonal"
        class="mb-4"
      >
        {{ statusError }}
      </VAlert>

      <div
        v-if="enabled === true"
        class="mb-4"
      >
        <VChip
          color="success"
          class="mb-4"
        >
          Two-factor authentication is ON
        </VChip>

        <div v-if="!showDisableForm">
          <p class="text-body-2 text-medium-emphasis mb-4">
            Disabling requires a current code from your authenticator app.
          </p>
          <VBtn
            color="error"
            variant="tonal"
            @click="showDisableForm = true"
          >
            Disable 2FA
          </VBtn>
        </div>
        <div v-else>
          <VAlert
            v-if="disableError"
            type="error"
            variant="tonal"
            density="compact"
            class="mb-4"
          >
            {{ disableError }}
          </VAlert>
          <AppTextField
            v-model="disableCode"
            label="Authenticator code"
            placeholder="123456"
            maxlength="6"
            class="mb-4"
            style="max-inline-size: 220px;"
          />
          <div class="d-flex gap-3">
            <VBtn
              color="error"
              :loading="disabling"
              @click="onDisable"
            >
              Confirm disable
            </VBtn>
            <VBtn
              variant="tonal"
              @click="showDisableForm = false; disableCode = ''; disableError = ''"
            >
              Cancel
            </VBtn>
          </div>
        </div>
      </div>

      <div v-else-if="enabled === false">
        <VChip
          color="warning"
          class="mb-4"
        >
          Two-factor authentication is OFF
        </VChip>

        <div v-if="!otpauthUri">
          <p class="text-body-2 text-medium-emphasis mb-4">
            Scan a QR code with an authenticator app (Google Authenticator, Authy, etc.) to get
            started.
          </p>
          <VAlert
            v-if="enrollError"
            type="error"
            variant="tonal"
            density="compact"
            class="mb-4"
          >
            {{ enrollError }}
          </VAlert>
          <VBtn
            :loading="enrolling"
            @click="onStartEnroll"
          >
            Enable 2FA
          </VBtn>
        </div>

        <div v-else>
          <VAlert
            v-if="enrollError"
            type="error"
            variant="tonal"
            density="compact"
            class="mb-4"
          >
            {{ enrollError }}
          </VAlert>
          <div class="d-flex flex-column align-center mb-4">
            <img
              :src="qrDataUrl"
              alt="2FA QR code"
              width="200"
              height="200"
            >
            <p class="text-body-2 text-medium-emphasis mt-2 mb-0">
              Or enter this key manually:
            </p>
            <code>{{ secret }}</code>
          </div>
          <AppTextField
            v-model="confirmCode"
            label="Enter the 6-digit code to confirm"
            placeholder="123456"
            maxlength="6"
            class="mb-4"
            style="max-inline-size: 260px;"
          />
          <VBtn
            :loading="confirming"
            @click="onConfirmEnroll"
          >
            Confirm and enable
          </VBtn>
        </div>
      </div>
    </VCardText>
  </VCard>

  <VCard max-width="640" class="mt-6">
    <VCardText>
      <h6 class="text-h6 mb-4">
        Change Password
      </h6>
      <VAlert
        v-if="changePasswordError"
        type="error"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        {{ changePasswordError }}
      </VAlert>
      <VAlert
        v-if="changePasswordSuccess"
        type="success"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        {{ changePasswordSuccess }}
      </VAlert>
      <VForm @submit.prevent="onChangePassword">
        <VRow>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="currentPassword"
              label="Current password"
              type="password"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="newPassword"
              label="New password"
              type="password"
              placeholder="At least 8 characters"
            />
          </VCol>
          <VCol cols="12">
            <VBtn
              type="submit"
              :loading="changingPassword"
            >
              Change Password
            </VBtn>
          </VCol>
        </VRow>
      </VForm>
    </VCardText>
  </VCard>

  <VCard max-width="640" class="mt-6">
    <VCardText>
      <div class="d-flex align-center justify-space-between mb-4">
        <h6 class="text-h6">
          Active Sessions
        </h6>
        <VBtn
          v-if="sessions.length > 1"
          size="small"
          variant="tonal"
          color="error"
          :loading="revokingOthers"
          @click="onRevokeOthers"
        >
          Sign out all other sessions
        </VBtn>
      </div>
      <VAlert
        v-if="sessionsError"
        type="error"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        {{ sessionsError }}
      </VAlert>
      <VTable density="compact">
        <thead>
          <tr>
            <th>Device / Browser</th>
            <th>IP Address</th>
            <th>Signed in</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="session in sessions"
            :key="session.id"
          >
            <td>
              {{ session.user_agent ?? 'Unknown device' }}
              <VChip
                v-if="session.is_current"
                size="x-small"
                color="success"
                class="ms-2"
              >
                This device
              </VChip>
            </td>
            <td>{{ session.ip_address ?? '—' }}</td>
            <td>{{ new Date(session.created_at).toLocaleString('en-IN') }}</td>
            <td>
              <VBtn
                v-if="!session.is_current"
                size="small"
                variant="text"
                color="error"
                :loading="revokingId === session.id"
                @click="onRevokeSession(session)"
              >
                Sign out
              </VBtn>
            </td>
          </tr>
          <tr v-if="!sessions.length">
            <td colspan="4" class="text-center text-medium-emphasis">
              No active sessions.
            </td>
          </tr>
        </tbody>
      </VTable>
    </VCardText>
  </VCard>
</template>
