<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

const route = useRoute()
const router = useRouter()

const status = ref<'connecting' | 'success' | 'error'>('connecting')
const errorMessage = ref('')

async function completeConnection() {
  const code = route.query.code as string | undefined
  const state = route.query.state as string | undefined
  const oauthError = route.query.error_description as string | undefined
  if (oauthError) {
    status.value = 'error'
    errorMessage.value = oauthError
    return
  }
  if (!code || !state) {
    status.value = 'error'
    errorMessage.value = 'Microsoft did not return the expected authorization code.'
    return
  }
  try {
    await $api('/v1/crm/email/microsoft/callback', { method: 'POST', body: { code, state } })
    status.value = 'success'
    setTimeout(() => router.replace('/channels-crm?tab=channels'), 1500)
  }
  catch (error: any) {
    status.value = 'error'
    errorMessage.value = extractErrorMessage(error, 'Could not complete the Microsoft 365 connection.')
  }
}

onMounted(completeConnection)
</script>

<template>
  <div class="d-flex align-center justify-center" style="min-block-size: 60vh;">
    <VCard max-width="440" class="pa-2">
      <VCardText class="text-center">
        <template v-if="status === 'connecting'">
          <VProgressCircular indeterminate color="primary" class="mb-4" />
          <p class="text-body-1 mb-0">
            Finishing your Microsoft 365 connection…
          </p>
        </template>
        <template v-else-if="status === 'success'">
          <VIcon icon="tabler-circle-check" color="success" size="48" class="mb-4" />
          <p class="text-body-1 mb-0">
            Connected. Taking you back to Email settings…
          </p>
        </template>
        <template v-else>
          <VIcon icon="tabler-circle-x" color="error" size="48" class="mb-4" />
          <p class="text-body-1 mb-4">
            {{ errorMessage }}
          </p>
          <VBtn color="primary" :to="{ path: '/channels-crm', query: { tab: 'channels' } }">
            Back to Email settings
          </VBtn>
        </template>
      </VCardText>
    </VCard>
  </div>
</template>
