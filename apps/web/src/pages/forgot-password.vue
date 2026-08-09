<script setup lang="ts">
import { VNodeRenderer } from '@layouts/components/VNodeRenderer'
import { themeConfig } from '@themeConfig'

definePage({
  meta: {
    layout: 'blank',
    public: true,
    unauthenticatedOnly: true,
  },
})

const router = useRouter()

const step = ref(1)
const submitting = ref(false)
const errorMessage = ref('')

// See verify-account.vue for why this is needed: Vuetify's VStepper transition leaves
// .v-stepper-window's scrollLeft drifted to a small non-zero value on some (not all) step
// changes, clipping the first character(s) of every line -- confirmed live via repeated
// production testing across 5 independent runs that the drift isn't tied to the .3s transition
// window at all (a fixed one-shot + delayed reset both proved insufficient), so this polls for a
// few seconds after every step change instead of guessing a delay.
function resetStepperScroll() {
  document.querySelectorAll<HTMLElement>('.v-stepper-header, .v-stepper-window').forEach(el => {
    if (el.scrollLeft !== 0)
      el.scrollLeft = 0
  })
}
watch(step, async () => {
  await nextTick()
  const stopAt = Date.now() + 3000
  const tick = () => {
    resetStepperScroll()
    if (Date.now() < stopAt)
      requestAnimationFrame(tick)
  }
  tick()
})

const email = ref('')
const userId = ref('')
const devCode = ref('')

const code = ref('')
const newPassword = ref('')
const totpCode = ref('')
const isPasswordVisible = ref(false)

const turnstileToken = ref('')
const turnstileRef = ref<InstanceType<typeof TurnstileWidget>>()

async function submitEmail() {
  errorMessage.value = ''
  submitting.value = true
  try {
    const data = await $api<{ message: string, dev_code?: string | null, dev_user_id?: string | null }>('/v1/auth/forgot-password', {
      method: 'POST',
      body: { email: email.value, turnstile_token: turnstileToken.value },
    })
    userId.value = data.dev_user_id ?? ''
    devCode.value = data.dev_code ?? ''
    step.value = 2
  }
  catch (error: any) {
    errorMessage.value = extractErrorMessage(error, 'Could not process this request. Please try again.')
    // Single-use token -- reset before a retry, or Cloudflare rejects the already-redeemed token
    // as timeout-or-duplicate instead of accepting a fresh one.
    turnstileRef.value?.reset()
  }
  finally {
    submitting.value = false
  }
}

async function submitReset() {
  errorMessage.value = ''
  submitting.value = true
  try {
    await $api('/v1/auth/reset-password', {
      method: 'POST',
      body: { user_id: userId.value, code: code.value, new_password: newPassword.value, totp_code: totpCode.value || undefined },
    })
    step.value = 3
  }
  catch (error: any) {
    errorMessage.value = extractErrorMessage(error, 'Incorrect or expired code.')
  }
  finally {
    submitting.value = false
  }
}
</script>

<template>
  <RouterLink to="/">
    <div class="auth-logo d-flex align-center gap-x-3">
      <VNodeRenderer :nodes="themeConfig.app.logo" />
      <h1 class="auth-title">
        {{ themeConfig.app.title }}
      </h1>
    </div>
  </RouterLink>

  <div class="forgot-password-wrapper d-flex align-center justify-center bg-surface">
    <VCard
      flat
      max-width="480"
      class="ma-4 pa-6 w-100"
    >
      <VCardText>
        <h4 class="text-h4 mb-1">
          Forgot your password?
        </h4>
        <p class="mb-0">
          Enter your account email and we'll send you a reset code.
        </p>
      </VCardText>

      <VCardText>
        <VStepper
          v-model="step"
          flat
          :items="['Email', 'Reset', 'Done']"
          hide-actions
        >
          <template #item.1>
            <VAlert
              v-if="errorMessage"
              type="error"
              variant="tonal"
              density="compact"
              class="mb-4"
            >
              {{ errorMessage }}
            </VAlert>
            <VForm @submit.prevent="submitEmail">
              <VRow>
                <VCol cols="12">
                  <AppTextField
                    v-model="email"
                    label="Email"
                    type="email"
                    placeholder="you@company.com"
                    autofocus
                  />
                </VCol>
                <VCol cols="12">
                  <TurnstileWidget
                    id="turnstile-forgot-password"
                    ref="turnstileRef"
                    v-model="turnstileToken"
                  />
                </VCol>
                <VCol cols="12">
                  <VBtn
                    block
                    type="submit"
                    :loading="submitting"
                  >
                    Send Reset Code
                  </VBtn>
                </VCol>
              </VRow>
            </VForm>
          </template>

          <template #item.2>
            <VAlert
              v-if="errorMessage"
              type="error"
              variant="tonal"
              density="compact"
              class="mb-4"
            >
              {{ errorMessage }}
            </VAlert>
            <p class="mb-4">
              If an account exists for <strong>{{ email }}</strong>, we've sent a reset code to that email.
              Platform-staff accounts can't be reset this way — contact another admin instead.
            </p>
            <VAlert
              v-if="devCode"
              type="info"
              variant="tonal"
              density="compact"
              class="mb-4"
            >
              Development mode — no email sender configured yet. Your code is <strong>{{ devCode }}</strong>.
            </VAlert>
            <VForm @submit.prevent="submitReset">
              <VRow>
                <VCol cols="12">
                  <AppTextField
                    v-model="code"
                    label="Reset code"
                    placeholder="123456"
                    autofocus
                  />
                </VCol>
                <VCol cols="12">
                  <AppTextField
                    v-model="newPassword"
                    label="New password"
                    :type="isPasswordVisible ? 'text' : 'password'"
                    placeholder="At least 8 characters"
                    :append-inner-icon="isPasswordVisible ? 'tabler-eye-off' : 'tabler-eye'"
                    @click:append-inner="isPasswordVisible = !isPasswordVisible"
                  />
                </VCol>
                <VCol cols="12">
                  <AppTextField
                    v-model="totpCode"
                    label="Two-factor code (only if you have 2FA enabled)"
                    placeholder="123456 or a recovery code"
                    hint="Leave blank if you don't have two-factor authentication set up."
                    persistent-hint
                  />
                </VCol>
                <VCol cols="12">
                  <VBtn
                    block
                    type="submit"
                    :loading="submitting"
                  >
                    Reset Password
                  </VBtn>
                </VCol>
              </VRow>
            </VForm>
          </template>

          <template #item.3>
            <div class="text-center py-6">
              <VIcon
                icon="tabler-circle-check-filled"
                color="success"
                size="56"
                class="mb-4"
              />
              <h5 class="text-h5 mb-2">
                Password reset!
              </h5>
              <p class="mb-6">
                Your password has been changed. You can now sign in with your new password.
              </p>
              <VBtn
                block
                @click="router.push('/login')"
              >
                Go to login
              </VBtn>
            </div>
          </template>
        </VStepper>
      </VCardText>

      <VCardText class="text-center">
        <RouterLink
          class="text-primary"
          to="/login"
        >
          Back to login
        </RouterLink>
      </VCardText>
    </VCard>
  </div>
</template>

<style lang="scss">
@use "@core/scss/template/pages/page-auth";

.forgot-password-wrapper {
  min-block-size: 100dvh;
}
</style>
