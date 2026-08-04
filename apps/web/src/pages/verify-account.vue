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
const route = useRoute()

const userId = ref(typeof route.query.user_id === 'string' ? route.query.user_id : '')
const step = ref(1)
const submitting = ref(false)
const errorMessage = ref('')

// Vuetify's VStepper transition leaves .v-stepper-window's scrollLeft drifted to a small non-zero
// value on some (not all) step changes -- overflow-anchor: none (page-auth.scss) helps but doesn't
// eliminate it, confirmed live via repeated production testing across 5 independent runs: 3 came
// back clean, one drifted 21px after 500ms, one drifted 520px -- i.e. the drift isn't tied to the
// .3s transition window at all (a fixed one-shot + delayed reset both proved insufficient in that
// same test), so this polls for a few seconds after every step change instead of guessing a delay.
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

// Otherwise this always starts at "verify email" regardless of actual backend state -- confirmed
// live this left an already-email-verified account with no way to reach the mobile step at all,
// since submitting any code there now correctly refuses (see the auth.py fix) instead of the
// previous bug where it silently pretended to succeed. Errors here are swallowed on purpose: a
// missing/bad user_id is already surfaced by the existing per-step submit handlers.
async function checkExistingProgress() {
  if (!userId.value)
    return
  try {
    const result = await $api<{ email_verified: boolean, mobile_verified: boolean, status: string }>(`/v1/auth/registration-status/${userId.value}`)
    if (result.status === 'active' || (result.email_verified && result.mobile_verified))
      step.value = 3
    else if (result.email_verified)
      step.value = 2
  }
  catch {
    // fall through -- stay on step 1, the normal starting point
  }
}
onMounted(checkExistingProgress)

const emailCode = ref('')

const mobile = ref('')
const devMobileCode = ref('')
const mobileCode = ref('')
const mobileOtpRequested = ref(false)

async function submitEmailCode() {
  errorMessage.value = ''
  if (!userId.value) {
    errorMessage.value = 'This link is missing your account id — use the link from your welcome email.'
    return
  }
  submitting.value = true
  try {
    await $api('/v1/auth/verify-email', { method: 'POST', body: { user_id: userId.value, code: emailCode.value } })
    step.value = 2
  }
  catch (error: any) {
    errorMessage.value = extractErrorMessage(error, 'Incorrect or expired code.')
  }
  finally {
    submitting.value = false
  }
}

async function requestMobileOtp() {
  errorMessage.value = ''
  submitting.value = true
  try {
    const data = await $api<{ dev_mobile_code?: string | null }>('/v1/auth/request-mobile-otp', {
      method: 'POST',
      body: { user_id: userId.value, mobile: mobile.value },
    })
    devMobileCode.value = data.dev_mobile_code ?? ''
    mobileOtpRequested.value = true
  }
  catch (error: any) {
    errorMessage.value = extractErrorMessage(error, 'Could not send a verification code to that number.')
  }
  finally {
    submitting.value = false
  }
}

async function submitMobileCode() {
  errorMessage.value = ''
  submitting.value = true
  try {
    await $api('/v1/auth/verify-mobile', { method: 'POST', body: { user_id: userId.value, code: mobileCode.value } })
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

  <div class="verify-account-wrapper d-flex align-center justify-center bg-surface">
    <VCard
      flat
      max-width="640"
      class="ma-4 pa-6 w-100"
    >
      <VCardText>
        <h4 class="text-h4 mb-1">
          Activate your Textzi account
        </h4>
        <p class="mb-0">
          Verify your email and mobile number to finish setting up the account created for you.
        </p>
      </VCardText>

      <VCardText>
        <VStepper
          v-model="step"
          flat
          :items="['Verify email', 'Verify mobile', 'Done']"
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
            <p class="mb-4">
              Enter the verification code from your welcome email.
            </p>
            <VForm @submit.prevent="submitEmailCode">
              <VRow>
                <VCol cols="12">
                  <AppTextField
                    v-model="emailCode"
                    label="Verification code"
                    placeholder="123456"
                    autofocus
                  />
                </VCol>
                <VCol cols="12">
                  <VBtn
                    block
                    type="submit"
                    :loading="submitting"
                  >
                    Verify email
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
              Email verified. Now confirm your mobile number.
            </p>
            <VForm
              v-if="!mobileOtpRequested"
              @submit.prevent="requestMobileOtp"
            >
              <VRow>
                <VCol cols="12">
                  <AppTextField
                    v-model="mobile"
                    label="Mobile number"
                    placeholder="9876543210"
                    autofocus
                  />
                </VCol>
                <VCol cols="12">
                  <VBtn
                    block
                    type="submit"
                    :loading="submitting"
                  >
                    Send OTP
                  </VBtn>
                </VCol>
              </VRow>
            </VForm>
            <VForm
              v-else
              @submit.prevent="submitMobileCode"
            >
              <VAlert
                v-if="devMobileCode"
                type="info"
                variant="tonal"
                density="compact"
                class="mb-4"
              >
                Development mode — no SMS sender configured yet. Your code is <strong>{{ devMobileCode }}</strong>.
              </VAlert>
              <VRow>
                <VCol cols="12">
                  <AppTextField
                    v-model="mobileCode"
                    label="OTP code"
                    placeholder="123456"
                    autofocus
                  />
                </VCol>
                <VCol cols="12">
                  <VBtn
                    block
                    type="submit"
                    :loading="submitting"
                  >
                    Verify mobile
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
                You're all set!
              </h5>
              <p class="mb-6">
                Your email and mobile are verified. Sign in with the temporary password from your welcome email.
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
    </VCard>
  </div>
</template>

<style lang="scss">
@use "@core/scss/template/pages/page-auth";

.verify-account-wrapper {
  min-block-size: 100dvh;
}
</style>
