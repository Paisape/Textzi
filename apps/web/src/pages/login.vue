<script setup lang="ts">
import AuthProvider from '@/views/pages/authentication/AuthProvider.vue'
import { VNodeRenderer } from '@layouts/components/VNodeRenderer'
import { useAuthStore } from '@/stores/auth'
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
const authStore = useAuthStore()

const form = ref({
  email: '',
  password: '',
  remember: false,
})

const isPasswordVisible = ref(false)
const errorMessage = ref('')
const submitting = ref(false)

const mfaRequired = ref(false)
const mfaToken = ref('')
const mfaCode = ref('')

// Set by the router guard / the global 401 handler (utils/api.ts) when they detect a dead
// session and redirect here -- without this, a user who got logged out purely from inactivity
// had no way to tell that apart from having never been logged in at all.
const sessionExpiredNotice = route.query.sessionExpired === '1'

async function afterLogin(accessToken: string) {
  useCookie('accessToken').value = accessToken
  await nextTick()

  // Forces the shared auth store to refetch, not just this function's own local variable --
  // without this, any earlier authStore.load() call this session (e.g. the router guard's dead-
  // session detection redirecting here) had already set loaded=true with a null/stale profile,
  // and a plain client-side router.push to /dashboard would never trigger a fresh fetch there
  // (authStore.load() short-circuits once loaded=true), leaving the dashboard looking logged-out
  // until a manual page refresh reset the whole store. Every other page reads authStore.profile
  // directly, so refreshing it here (not just a local variable) is what actually fixes that.
  await authStore.load(true)
  const profile = authStore.profile
  const rawRedirect = typeof route.query.redirect === 'string' ? route.query.redirect : null
  // Must be a same-app relative path -- a bare "/" prefix isn't enough on its own since "//evil.com"
  // is a protocol-relative URL the browser would treat as off-origin.
  const redirectTo = rawRedirect && rawRedirect.startsWith('/') && !rawRedirect.startsWith('//') ? rawRedirect : null
  const needsOnboarding = profile?.role === 'enterprise_customer' && !profile?.organization_id
  router.push(redirectTo || (needsOnboarding ? '/onboarding' : '/dashboard'))
}

async function onSubmit() {
  errorMessage.value = ''
  submitting.value = true
  try {
    const data = await $api<{ access_token: string | null, mfa_required: boolean, mfa_token: string | null }>('/v1/auth/login', {
      method: 'POST',
      body: { email: form.value.email, password: form.value.password },
    })
    if (data.mfa_required && data.mfa_token) {
      mfaRequired.value = true
      mfaToken.value = data.mfa_token
    }
    else if (data.access_token) {
      await afterLogin(data.access_token)
    }
  }
  catch (error: any) {
    errorMessage.value = extractErrorMessage(error, 'Unable to sign in. Please check your details and try again.')
  }
  finally {
    submitting.value = false
  }
}

async function onSubmitMfa() {
  errorMessage.value = ''
  submitting.value = true
  try {
    const data = await $api<{ access_token: string }>('/v1/auth/login/verify-2fa', {
      method: 'POST',
      body: { mfa_token: mfaToken.value, code: mfaCode.value },
    })
    await afterLogin(data.access_token)
  }
  catch (error: any) {
    errorMessage.value = extractErrorMessage(error, 'Incorrect authenticator code.')
  }
  finally {
    submitting.value = false
  }
}

</script>

<template>
  <a href="javascript:void(0)">
    <div class="auth-logo d-flex align-center gap-x-3">
      <VNodeRenderer :nodes="themeConfig.app.logo" />
      <h1 class="auth-title">
        {{ themeConfig.app.title }}
      </h1>
    </div>
  </a>

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
        :max-width="500"
        class="mt-12 mt-sm-0 pa-6"
      >
        <VCardText v-if="!mfaRequired">
          <h4 class="text-h4 mb-1">
            Welcome to <span class="text-capitalize">{{ themeConfig.app.title }}</span>! 👋🏻
          </h4>
          <p class="mb-0">
            Please sign-in to your account and start the adventure
          </p>
        </VCardText>
        <VCardText v-else>
          <h4 class="text-h4 mb-1">
            Two-factor authentication 🔐
          </h4>
          <p class="mb-0">
            Enter the 6-digit code from your authenticator app.
          </p>
        </VCardText>
        <VCardText>
          <VAlert
            v-if="sessionExpiredNotice && !errorMessage"
            type="info"
            variant="tonal"
            density="compact"
            class="mb-4"
          >
            Your session has expired. Please sign in again.
          </VAlert>
          <VAlert
            v-if="errorMessage"
            type="error"
            variant="tonal"
            density="compact"
            class="mb-4"
            closable
            @click:close="errorMessage = ''"
          >
            {{ errorMessage }}
          </VAlert>

          <VForm
            v-if="mfaRequired"
            @submit.prevent="onSubmitMfa"
          >
            <VRow>
              <VCol cols="12">
                <AppTextField
                  v-model="mfaCode"
                  autofocus
                  label="Authenticator code"
                  placeholder="123456"
                  maxlength="6"
                />
              </VCol>
              <VCol cols="12">
                <VBtn
                  block
                  type="submit"
                  :loading="submitting"
                >
                  Verify
                </VBtn>
              </VCol>
            </VRow>
          </VForm>

          <VForm
            v-else
            @submit.prevent="onSubmit"
          >
            <VRow>
              <!-- email -->
              <VCol cols="12">
                <AppTextField
                  v-model="form.email"
                  autofocus
                  label="Email"
                  type="email"
                  placeholder="johndoe@email.com"
                />
              </VCol>

              <!-- password -->
              <VCol cols="12">
                <AppTextField
                  v-model="form.password"
                  label="Password"
                  placeholder="············"
                  :type="isPasswordVisible ? 'text' : 'password'"
                  autocomplete="password"
                  :append-inner-icon="isPasswordVisible ? 'tabler-eye-off' : 'tabler-eye'"
                  @click:append-inner="isPasswordVisible = !isPasswordVisible"
                />

                <div class="d-flex align-center flex-wrap justify-space-between my-6">
                  <VCheckbox
                    v-model="form.remember"
                    label="Remember me"
                  />
                  <RouterLink
                    class="text-primary"
                    to="/forgot-password"
                  >
                    Forgot Password?
                  </RouterLink>
                </div>

                <VBtn
                  block
                  type="submit"
                  :loading="submitting"
                >
                  Login
                </VBtn>
              </VCol>

              <!-- create account -->
              <VCol
                cols="12"
                class="text-body-1 text-center"
              >
                <span class="d-inline-block">
                  New on our platform?
                </span>
                <RouterLink
                  class="text-primary ms-1 d-inline-block text-body-1"
                  to="/register"
                >
                  Create an account
                </RouterLink>
              </VCol>

              <VCol
                cols="12"
                class="d-flex align-center"
              >
                <VDivider />
                <span class="mx-4">or</span>
                <VDivider />
              </VCol>

              <!-- auth providers -->
              <VCol
                cols="12"
                class="text-center"
              >
                <AuthProvider />
              </VCol>
            </VRow>
          </VForm>
        </VCardText>
      </VCard>
    </VCol>
  </VRow>
</template>

<style lang="scss">
@use "@core/scss/template/pages/page-auth";
</style>
