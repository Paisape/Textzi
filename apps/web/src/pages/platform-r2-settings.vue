<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
    requiresAdmin: true,
  },
})

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.loaded ? authStore.isAdmin : null)

type R2Settings = {
  account_id: string | null
  access_key_id: string | null
  bucket_name: string | null
  configured: boolean
}

const accountId = ref('')
const accessKeyId = ref('')
const secretAccessKey = ref('')
const bucketName = ref('')
const configured = ref(false)

const loadError = ref('')
const saveError = ref('')
const saveSuccess = ref('')
const saving = ref(false)

async function loadSettings() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const result = await $api<R2Settings>('/v1/admin/platform/r2-settings')
    accountId.value = result.account_id ?? ''
    accessKeyId.value = result.access_key_id ?? ''
    bucketName.value = result.bucket_name ?? ''
    configured.value = result.configured
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load R2 settings.')
  }
}

async function onSave() {
  saveError.value = ''
  saveSuccess.value = ''
  saving.value = true
  try {
    const result = await $api<R2Settings>('/v1/admin/platform/r2-settings', {
      method: 'PUT',
      body: {
        account_id: accountId.value || null,
        access_key_id: accessKeyId.value || null,
        secret_access_key: secretAccessKey.value || null,
        bucket_name: bucketName.value || null,
      },
    })
    configured.value = result.configured
    secretAccessKey.value = ''
    saveSuccess.value = 'Saved.'
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save R2 settings.')
  }
  finally {
    saving.value = false
  }
}

onMounted(loadSettings)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Platform R2 Setting
  </h1>
  <p class="text-medium-emphasis mb-6">
    Cloudflare R2 credentials for the cold-storage archive tier -- once configured, message
    telemetry older than 30 days is promoted from local disk to R2 as compressed Parquet files.
    Until it's set, that promotion step is simply skipped (nothing errors); the local gzip tier
    and live reporting are unaffected either way.
  </p>

  <VAlert
    v-if="isAdmin === false"
    type="warning"
    variant="tonal"
  >
    This page is restricted to Super Admin and Operator Admin roles.
  </VAlert>

  <VAlert
    v-else-if="loadError"
    type="error"
    variant="tonal"
  >
    {{ loadError }}
  </VAlert>

  <VCard
    v-else-if="isAdmin"
    max-width="640"
  >
    <VCardText>
      <VChip
        :color="configured ? 'success' : 'warning'"
        size="small"
        class="mb-4"
      >
        {{ configured ? 'Configured' : 'Not configured (R2 promotion is skipped)' }}
      </VChip>

      <VAlert
        v-if="saveError"
        type="error"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        {{ saveError }}
      </VAlert>
      <VAlert
        v-if="saveSuccess"
        type="success"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        {{ saveSuccess }}
      </VAlert>

      <VForm @submit.prevent="onSave">
        <VRow>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="accountId"
              label="Account ID"
              placeholder="292a88cc841a66683d40f805c5bf4451"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="bucketName"
              label="Bucket name"
              placeholder="textzi-archives"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="accessKeyId"
              label="Access Key ID"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="secretAccessKey"
              type="password"
              label="Secret Access Key"
              placeholder="Leave blank to keep the current key"
            />
          </VCol>
          <VCol cols="12">
            <VBtn
              type="submit"
              :loading="saving"
            >
              Save
            </VBtn>
          </VCol>
        </VRow>
      </VForm>
    </VCardText>
  </VCard>
</template>
