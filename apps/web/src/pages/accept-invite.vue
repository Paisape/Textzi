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

const token = ref(typeof route.query.token === 'string' ? route.query.token : '')
const fullName = ref('')
const mobile = ref('')
const password = ref('')
const isPasswordVisible = ref(false)
const submitting = ref(false)
const errorMessage = ref('')

async function onSubmit() {
  errorMessage.value = ''
  if (!token.value) {
    errorMessage.value = 'This invite link is missing its token.'
    return
  }
  submitting.value = true
  try {
    const data = await $api<{ access_token: string }>('/v1/team/accept-invite', {
      method: 'POST',
      body: { token: token.value, full_name: fullName.value, mobile: mobile.value, password: password.value },
    })
    useCookie('accessToken').value = data.access_token
    await nextTick()
    router.push('/dashboard')
  }
  catch (error: any) {
    errorMessage.value = extractErrorMessage(error, 'This invite link is invalid or has expired.')
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

  <div class="accept-invite-wrapper d-flex align-center justify-center bg-surface">
    <VCard
      flat
      max-width="480"
      class="ma-4 pa-6 w-100"
    >
      <VCardText>
        <h4 class="text-h4 mb-1">
          Join your team on Textzi
        </h4>
        <p class="mb-0">
          Set a password to finish setting up your account.
        </p>
      </VCardText>

      <VCardText>
        <VAlert
          v-if="errorMessage"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ errorMessage }}
        </VAlert>
        <VForm @submit.prevent="onSubmit">
          <VRow>
            <VCol cols="12">
              <AppTextField
                v-model="fullName"
                label="Full name"
                placeholder="Ananya Rao"
                autofocus
              />
            </VCol>
            <VCol cols="12">
              <AppTextField
                v-model="mobile"
                label="Mobile number"
                placeholder="9876543210"
              />
            </VCol>
            <VCol cols="12">
              <AppTextField
                v-model="password"
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
                Accept invite
              </VBtn>
            </VCol>
          </VRow>
        </VForm>
      </VCardText>
    </VCard>
  </div>
</template>

<style lang="scss">
@use "@core/scss/template/pages/page-auth";

.accept-invite-wrapper {
  min-block-size: 100dvh;
}
</style>
