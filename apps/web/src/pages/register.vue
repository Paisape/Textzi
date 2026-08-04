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
// production testing that overflow-anchor: none (page-auth.scss) reduces but doesn't eliminate
// it, a genuine race against the browser's own scroll heuristics during the .3s slide animation.
function resetStepperScroll() {
  document.querySelectorAll<HTMLElement>('.v-stepper-header, .v-stepper-window').forEach(el => { el.scrollLeft = 0 })
}
watch(step, async () => {
  await nextTick()
  resetStepperScroll()
  setTimeout(resetStepperScroll, 350)
})

const accountForm = ref({ fullName: '', email: '', password: '' })
const userId = ref('')
const devEmailCode = ref('')
const emailCode = ref('')

const mobile = ref('')
const devMobileCode = ref('')
const mobileCode = ref('')
const mobileOtpRequested = ref(false)

const isPasswordVisible = ref(false)

async function submitAccountDetails() {
  errorMessage.value = ''
  submitting.value = true
  try {
    const data = await $api<{ user_id: string, dev_email_code?: string | null }>('/v1/auth/register', {
      method: 'POST',
      body: { email: accountForm.value.email, password: accountForm.value.password, full_name: accountForm.value.fullName },
    })
    userId.value = data.user_id
    devEmailCode.value = data.dev_email_code ?? ''
    step.value = 2
  }
  catch (error: any) {
    errorMessage.value = extractErrorMessage(error, 'Could not create your account. Please try again.')
  }
  finally {
    submitting.value = false
  }
}

async function submitEmailCode() {
  errorMessage.value = ''
  submitting.value = true
  try {
    await $api('/v1/auth/verify-email', { method: 'POST', body: { user_id: userId.value, code: emailCode.value } })
    step.value = 3
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
    step.value = 4
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

  <VRow
    no-gutters
    class="auth-wrapper bg-surface"
  >
    <VCol
      md="8"
      class="d-none d-md-flex"
    >
      <div class="position-relative bg-background w-100 h-100 me-0 d-flex align-center justify-center">
        <AuthCpaasIllustration />
      </div>
    </VCol>

    <VCol
      cols="12"
      md="4"
      class="auth-card-v2 d-flex align-center justify-center"
    >
      <VCard
        flat
        max-width="480"
        class="mt-12 mt-sm-0 pa-6 w-100"
      >
        <VCardText>
          <h4 class="text-h4 mb-1">
            Create your Textzi account
          </h4>
          <p class="mb-0">
            Sign up, verify your email and mobile, and start messaging your customers.
          </p>
        </VCardText>

        <VCardText>
          <VStepper
            v-model="step"
            flat
            :items="['Account', 'Verify email', 'Verify mobile', 'Done']"
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
              <VForm @submit.prevent="submitAccountDetails">
                <VRow>
                  <VCol cols="12">
                    <AppTextField
                      v-model="accountForm.fullName"
                      label="Full name"
                      placeholder="Ananya Rao"
                      autofocus
                    />
                  </VCol>
                  <VCol cols="12">
                    <AppTextField
                      v-model="accountForm.email"
                      label="Email"
                      type="email"
                      placeholder="you@company.com"
                    />
                  </VCol>
                  <VCol cols="12">
                    <AppTextField
                      v-model="accountForm.password"
                      label="Password"
                      :type="isPasswordVisible ? 'text' : 'password'"
                      placeholder="At least 8 characters"
                      :append-inner-icon="isPasswordVisible ? 'tabler-eye-off' : 'tabler-eye'"
                      @click:append-inner="isPasswordVisible = !isPasswordVisible"
                    />
                  </VCol>
                  <VCol cols="12">
                    <VBtn
                      block
                      type="submit"
                      :loading="submitting"
                    >
                      Create account
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
                We've sent a 6-digit verification code to <strong>{{ accountForm.email }}</strong>.
              </p>
              <VAlert
                v-if="devEmailCode"
                type="info"
                variant="tonal"
                density="compact"
                class="mb-4"
              >
                Development mode &mdash; no email sender configured yet. Your code is <strong>{{ devEmailCode }}</strong>.
              </VAlert>
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

            <template #item.3>
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
                Email verified. Now add your mobile number so we can reach you for OTPs and delivery alerts.
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
                  Development mode &mdash; no SMS sender configured yet. Your code is <strong>{{ devMobileCode }}</strong>.
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

            <template #item.4>
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
                  Your email and mobile are verified. You can now sign in to your Textzi account.
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
          <span>Already have an account?</span>
          <RouterLink
            class="text-primary ms-1"
            to="/login"
          >
            Sign in instead
          </RouterLink>
        </VCardText>
      </VCard>
    </VCol>
  </VRow>
</template>

<style lang="scss">
@use "@core/scss/template/pages/page-auth";
</style>
