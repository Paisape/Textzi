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

type GeneralSettings = {
  company_name: string
  company_address: string
  company_gstin: string
  company_state: string
  company_state_code: string
  company_phone: string
  support_email: string
  public_api_base_url: string
}

const form = ref<GeneralSettings>({
  company_name: '', company_address: '', company_gstin: '', company_state: '', company_state_code: '', company_phone: '', support_email: '', public_api_base_url: '',
})

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
    form.value = await $api<GeneralSettings>('/v1/admin/platform/general-settings')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load platform settings.')
  }
}

async function onSave() {
  saveError.value = ''
  saveSuccess.value = ''
  saving.value = true
  try {
    form.value = await $api<GeneralSettings>('/v1/admin/platform/general-settings', {
      method: 'PUT',
      body: {
        company_name: form.value.company_name || null,
        company_address: form.value.company_address || null,
        company_gstin: form.value.company_gstin || null,
        company_state: form.value.company_state || null,
        company_state_code: form.value.company_state_code || null,
        company_phone: form.value.company_phone || null,
        support_email: form.value.support_email || null,
        public_api_base_url: form.value.public_api_base_url || null,
      },
    })
    saveSuccess.value = 'Saved.'
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save platform settings.')
  }
  finally {
    saving.value = false
  }
}

onMounted(loadSettings)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Platform General Setting
  </h1>
  <p class="text-medium-emphasis mb-6">
    Company/invoice details, the support inbox, and this API's own public base URL (used to
    build provider delivery-report webhook URLs) -- editable here instead of requiring a `.env`
    change and a redeploy. Leave a field blank to fall back to its deployment default.
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
    max-width="760"
  >
    <VCardText>
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
        <h6 class="text-h6 mb-4">
          Invoice / company details
        </h6>
        <VRow>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="form.company_name"
              label="Company name"
              placeholder="Textzi"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="form.company_gstin"
              label="GSTIN"
              placeholder="27ABCDE1234F1Z5"
            />
          </VCol>
          <VCol cols="12">
            <AppTextarea
              v-model="form.company_address"
              label="Company address"
              rows="2"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="form.company_state"
              label="State"
              placeholder="Maharashtra"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="form.company_state_code"
              label="State code"
              placeholder="27"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="form.company_phone"
              label="Phone"
              placeholder="022-68833223"
            />
          </VCol>
        </VRow>

        <VDivider class="my-6" />

        <h6 class="text-h6 mb-4">
          Support & infrastructure
        </h6>
        <VRow>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="form.support_email"
              label="Support email"
              placeholder="support@textzi.in"
              hint="Contact-form submissions are emailed here."
              persistent-hint
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="form.public_api_base_url"
              label="Public API base URL"
              placeholder="https://api.textzi.in"
              hint="Externally-reachable base URL of this API. Blank = provider delivery-report webhooks aren't requested."
              persistent-hint
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
