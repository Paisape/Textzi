<script setup lang="ts">
const enabled = ref(false)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const saved = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await $api<{ enabled: boolean }>('/v1/waba/csat-settings')
    enabled.value = result.enabled
  }
  catch (err: any) {
    error.value = extractErrorMessage(err, 'Could not load CSAT settings.')
  }
  finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    await $api('/v1/waba/csat-settings', { method: 'PUT', body: { enabled: enabled.value } })
    saved.value = true
  }
  catch (err: any) {
    error.value = extractErrorMessage(err, 'Could not save CSAT settings.')
  }
  finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <VCard max-width="560">
    <VCardText>
      <h2 class="text-h6 mb-1">
        Customer satisfaction (CSAT)
      </h2>
      <p class="text-body-2 text-medium-emphasis mb-4">
        When enabled, resolving a conversation sends a 1-5 rating request to the customer. Ratings
        show up in Reports.
      </p>
      <VAlert v-if="error" type="error" variant="tonal" density="compact" class="mb-3">
        {{ error }}
      </VAlert>
      <VAlert v-if="saved" type="success" variant="tonal" density="compact" class="mb-3">
        Saved.
      </VAlert>
      <VSwitch v-model="enabled" label="Ask for a rating when a conversation is resolved" density="compact" class="mb-4" />
      <VBtn :loading="saving" @click="save">
        Save
      </VBtn>
    </VCardText>
  </VCard>
</template>
