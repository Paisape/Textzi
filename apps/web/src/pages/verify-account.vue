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
      max-width="480"
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
