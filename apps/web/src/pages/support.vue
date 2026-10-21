<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
  },
})

const authStore = useAuthStore()

const name = ref('')
const email = ref('')
const phone = ref('')
const company = ref('')
const message = ref('')
const turnstileToken = ref('')
const turnstileRef = ref<InstanceType<typeof TurnstileWidget>>()
const sending = ref(false)
const sendError = ref('')
const sendSuccess = ref(false)

onMounted(async () => {
  await authStore.load()
  if (authStore.profile) {
    name.value = authStore.profile.full_name
    email.value = authStore.profile.email
  }
})

async function onSend() {
  sendError.value = ''
  sendSuccess.value = false
  sending.value = true
  try {
    await $api('/v1/public/contact', {
      method: 'POST',
      body: {
        name: name.value.trim(),
        email: email.value.trim(),
        phone: phone.value.trim(),
        company: company.value.trim(),
        message: message.value.trim(),
        turnstile_token: turnstileToken.value,
      },
    })
    sendSuccess.value = true
    message.value = ''
    turnstileRef.value?.reset()
    turnstileToken.value = ''
  }
  catch (error: any) {
    sendError.value = extractErrorMessage(error, 'Could not send your message.')
  }
  finally {
    sending.value = false
  }
}
</script>

<template>
  <div>
    <h1 class="text-h4 mb-1">
      Support
    </h1>
    <p class="text-medium-emphasis mb-6">
      Send us a message and we'll reply by email. We typically respond within a few hours during business hours.
    </p>

    <VCard max-width="640">
      <VCardText>
        <VAlert v-if="sendSuccess" type="success" variant="tonal" class="mb-4" closable @click:close="sendSuccess = false">
          Thanks for reaching out — our team will get back to you shortly.
        </VAlert>
        <VAlert v-if="sendError" type="error" variant="tonal" class="mb-4">
          {{ sendError }}
        </VAlert>

        <VForm @submit.prevent="onSend">
          <VRow>
            <VCol cols="12" sm="6">
              <AppTextField v-model="name" label="Name" />
            </VCol>
            <VCol cols="12" sm="6">
              <AppTextField v-model="email" label="Email" type="email" />
            </VCol>
            <VCol cols="12" sm="6">
              <AppTextField v-model="phone" label="Phone" />
            </VCol>
            <VCol cols="12" sm="6">
              <AppTextField v-model="company" label="Company" />
            </VCol>
            <VCol cols="12">
              <VTextarea v-model="message" label="Message" rows="4" auto-grow />
            </VCol>
            <VCol cols="12">
              <TurnstileWidget
                id="turnstile-support"
                ref="turnstileRef"
                v-model="turnstileToken"
              />
            </VCol>
            <VCol cols="12" class="d-flex justify-end">
              <VBtn
                type="submit"
                color="primary"
                :loading="sending"
                :disabled="!name.trim() || !email.trim() || !phone.trim() || !company.trim() || !message.trim()"
              >
                Send message
              </VBtn>
            </VCol>
          </VRow>
        </VForm>
      </VCardText>
    </VCard>
  </div>
</template>
