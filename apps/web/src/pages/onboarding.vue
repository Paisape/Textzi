<script setup lang="ts">
import { VNodeRenderer } from '@layouts/components/VNodeRenderer'
import { themeConfig } from '@themeConfig'

definePage({
  meta: {
    layout: 'blank',
  },
})

const router = useRouter()

const form = ref({
  organizationName: '',
  entityName: '',
  gstin: '',
  pan: '',
  industry: '',
  address: '',
})

const errorMessage = ref('')
const submitting = ref(false)

async function onSubmit() {
  errorMessage.value = ''
  submitting.value = true
  try {
    await $api('/v1/onboarding/organization', {
      method: 'POST',
      body: {
        organization_name: form.value.organizationName,
        entity_name: form.value.entityName || null,
        gstin: form.value.gstin || null,
        pan: form.value.pan || null,
        industry: form.value.industry || null,
        address: form.value.address || null,
      },
    })
    router.push('/dashboard')
  }
  catch (error: any) {
    errorMessage.value = extractErrorMessage(error, 'Could not set up your organization. Please try again.')
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

  <div class="onboarding-wrapper d-flex align-center justify-center bg-surface">
    <VCard
      flat
      max-width="560"
      class="ma-4 pa-6 w-100"
    >
      <VCardText>
        <h4 class="text-h4 mb-1">
          Set up your organisation
        </h4>
        <p class="mb-0">
          One last step &mdash; tell us about your business so we can create your first entity and wallet.
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
                v-model="form.organizationName"
                label="Organisation name"
                placeholder="Acme Pvt Ltd"
                autofocus
              />
            </VCol>
            <VCol
              cols="12"
              md="6"
            >
              <AppTextField
                v-model="form.entityName"
                label="First entity name (optional)"
                placeholder="Defaults to organisation name"
              />
            </VCol>
            <VCol
              cols="12"
              md="6"
            >
              <AppTextField
                v-model="form.industry"
                label="Industry (optional)"
                placeholder="Retail, Finance, ..."
              />
            </VCol>
            <VCol
              cols="12"
              md="6"
            >
              <AppTextField
                v-model="form.gstin"
                label="GSTIN (optional)"
                placeholder="15-character GSTIN"
              />
            </VCol>
            <VCol
              cols="12"
              md="6"
            >
              <AppTextField
                v-model="form.pan"
                label="PAN (optional)"
                placeholder="10-character PAN"
              />
            </VCol>
            <VCol cols="12">
              <AppTextField
                v-model="form.address"
                label="Business address (optional)"
                placeholder="Registered office address"
              />
            </VCol>
            <VCol cols="12">
              <VBtn
                block
                type="submit"
                :loading="submitting"
              >
                Create organisation and continue
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

.onboarding-wrapper {
  min-block-size: 100dvh;
}
</style>
