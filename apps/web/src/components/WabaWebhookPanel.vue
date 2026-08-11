<script setup lang="ts">
const form = ref({ url: '', enabled: false })
const secret = ref<string | null>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const saved = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await $api<{ url: string | null, enabled: boolean, secret: string | null }>('/v1/waba/webhook-subscription')
    form.value = { url: result.url || '', enabled: result.enabled }
    secret.value = result.secret
  }
  catch (err: any) {
    error.value = extractErrorMessage(err, 'Could not load webhook settings.')
  }
  finally {
    loading.value = false
  }
}

async function save() {
  if (!form.value.url.trim())
    return
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    const result = await $api<{ url: string | null, enabled: boolean, secret: string | null }>('/v1/waba/webhook-subscription', {
      method: 'PUT',
      body: { url: form.value.url.trim(), enabled: form.value.enabled },
    })
    secret.value = result.secret
    saved.value = true
  }
  catch (err: any) {
    error.value = extractErrorMessage(err, 'Could not save webhook settings.')
  }
  finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <VCard max-width="640">
    <VCardText>
      <h2 class="text-h6 mb-1">
        Outbound webhooks
      </h2>
      <p class="text-body-2 text-medium-emphasis mb-4">
        Textzi POSTs a JSON payload to this URL for every new WhatsApp message and status update
        (<code>message.received</code>, <code>message.status</code>). Each request is signed with
        your secret in the <code>X-Textzi-Signature</code> header (<code>sha256=&lt;hmac&gt;</code>
        over the raw body), the same way Meta signs webhooks to Textzi.
      </p>
      <VAlert v-if="error" type="error" variant="tonal" density="compact" class="mb-3">
        {{ error }}
      </VAlert>
      <VAlert v-if="saved" type="success" variant="tonal" density="compact" class="mb-3">
        Saved.
      </VAlert>
      <AppTextField v-model="form.url" label="Webhook URL" placeholder="https://your-server.com/webhooks/textzi" class="mb-3" />
      <VSwitch v-model="form.enabled" label="Enabled" density="compact" class="mb-3" />
      <VAlert v-if="secret" type="info" variant="tonal" density="compact" class="mb-4">
        Signing secret: <code>{{ secret }}</code>
      </VAlert>
      <VBtn :loading="saving" @click="save">
        Save
      </VBtn>
    </VCardText>
  </VCard>
</template>
