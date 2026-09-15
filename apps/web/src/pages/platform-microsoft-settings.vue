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

type MicrosoftSettings = {
  client_id: string | null
  tenant_id: string | null
  configured: boolean
  redirect_uri: string | null
}

const form = ref({ client_id: '', tenant_id: '', client_secret: '' })
const configured = ref(false)
const redirectUri = ref('')

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
    const result = await $api<MicrosoftSettings>('/v1/admin/platform/microsoft-settings')
    form.value.client_id = result.client_id ?? ''
    form.value.tenant_id = result.tenant_id ?? ''
    configured.value = result.configured
    redirectUri.value = result.redirect_uri ?? ''
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load Microsoft 365 settings.')
  }
}

async function onSave() {
  saveError.value = ''
  saveSuccess.value = ''
  saving.value = true
  try {
    const result = await $api<MicrosoftSettings>('/v1/admin/platform/microsoft-settings', {
      method: 'PUT',
      body: {
        client_id: form.value.client_id || null,
        tenant_id: form.value.tenant_id || null,
        client_secret: form.value.client_secret || null,
      },
    })
    configured.value = result.configured
    redirectUri.value = result.redirect_uri ?? ''
    form.value.client_secret = ''
    saveSuccess.value = 'Saved.'
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save Microsoft 365 settings.')
  }
  finally {
    saving.value = false
  }
}

function copy(value: string) {
  navigator.clipboard?.writeText(value)
}

onMounted(loadSettings)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Microsoft 365 Setting
  </h1>
  <p class="text-medium-emphasis mb-6">
    Azure App Registration credentials for the CRM Email channel's "Connect Microsoft 365" option -- lets any customer connect their own Microsoft 365/Outlook mailbox via OAuth2, since Microsoft no longer allows plain SMTP/IMAP login for Exchange Online.
  </p>

  <VAlert v-if="isAdmin === false" type="error" variant="tonal" class="mb-4">
    You don't have access to this page.
  </VAlert>

  <template v-else>
    <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
      {{ loadError }}
    </VAlert>

    <VCard>
      <VCardText>
        <VForm @submit.prevent="onSave">
          <VAlert v-if="saveError" type="error" variant="tonal" class="mb-4">
            {{ saveError }}
          </VAlert>
          <VAlert v-if="saveSuccess" type="success" variant="tonal" class="mb-4" closable @click:close="saveSuccess = ''">
            {{ saveSuccess }}
          </VAlert>
          <VAlert :type="configured ? 'success' : 'warning'" variant="tonal" class="mb-4">
            {{ configured ? 'Microsoft 365 connection is configured.' : 'Not configured yet -- customers cannot connect a Microsoft 365 mailbox until this is saved.' }}
          </VAlert>

          <VRow>
            <VCol cols="12">
              <p class="text-body-2 text-medium-emphasis mb-1">
                Redirect URI (paste this into the Azure App Registration's Authentication &gt; Web &gt; Redirect URIs)
              </p>
              <VTextField
                :model-value="redirectUri || '— configure Company > Public API base URL first —'"
                density="compact" readonly
              >
                <template #append-inner>
                  <VBtn v-if="redirectUri" icon="tabler-copy" size="small" variant="text" @click="copy(redirectUri)" />
                </template>
              </VTextField>
            </VCol>
            <VCol cols="12" sm="6">
              <AppTextField v-model="form.client_id" label="Application (client) ID" placeholder="6fbd8725-0aa9-40f8-83f4-4db2dac7cdd0" />
            </VCol>
            <VCol cols="12" sm="6">
              <AppTextField v-model="form.tenant_id" label="Directory (tenant) ID" placeholder="2342bec6-0572-42e0-b033-b289cdee0ec3" hint="Leave blank to allow any organization's or personal Microsoft account to connect (uses Microsoft's 'common' authority)." persistent-hint />
            </VCol>
            <VCol cols="12">
              <AppTextField
                v-model="form.client_secret" label="Client secret value" type="password"
                :placeholder="configured ? 'Leave blank to keep the existing secret' : 'Paste the secret value from Certificates & secrets'"
              />
            </VCol>
          </VRow>

          <VBtn type="submit" color="primary" :loading="saving">
            Save
          </VBtn>
        </VForm>
      </VCardText>
    </VCard>
  </template>
</template>
