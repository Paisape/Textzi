<script setup lang="ts">
import { VNodeRenderer } from '@layouts/components/VNodeRenderer'
import { themeConfig } from '@themeConfig'

definePage({
  meta: {
    layout: 'blank',
  },
})

const router = useRouter()

const INDUSTRY_OPTIONS = [
  'E-commerce & Retail',
  'Banking & Financial Services',
  'Insurance',
  'Healthcare & Pharma',
  'Education',
  'Real Estate',
  'Travel & Hospitality',
  'Logistics & Transportation',
  'IT & Software Services',
  'Telecom',
  'Media & Entertainment',
  'Food & Beverage',
  'Automotive',
  'Manufacturing',
  'Government & Public Sector',
  'NGO & Non-Profit',
  'Other',
]

const form = ref({
  organizationName: '',
  entityName: '',
  industry: '',
  gstin: '',
  stateCode: '',
  pan: '',
  address: '',
  contactPersonName: '',
  contactEmail: '',
  contactMobile: '',
})

const noGstin = ref(false)

const gstinValidator = (v: string) => (!!v && v.length === 15) || 'GSTIN must be 15 characters'
const panValidator = (v: string) => (!!v && v.length === 10) || 'PAN must be 10 characters'
const mobileValidator = (v: string) => /^[1-9][0-9]{9,14}$/.test(v) || 'Enter a valid mobile number'

const refForm = ref()
const errorMessage = ref('')
const submitting = ref(false)

async function onSubmit() {
  const { valid } = await refForm.value.validate()
  if (!valid)
    return

  errorMessage.value = ''
  submitting.value = true
  try {
    await $api('/v1/onboarding/organization', {
      method: 'POST',
      body: {
        organization_name: form.value.organizationName,
        entity_name: form.value.entityName || null,
        industry: form.value.industry,
        gstin: noGstin.value ? null : form.value.gstin,
        state_code: noGstin.value ? form.value.stateCode : null,
        pan: form.value.pan,
        address: form.value.address,
        contact_person_name: form.value.contactPersonName,
        contact_email: form.value.contactEmail,
        contact_mobile: form.value.contactMobile,
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
        <VForm
          ref="refForm"
          @submit.prevent="onSubmit"
        >
          <VRow>
            <VCol cols="12">
              <AppTextField
                v-model="form.organizationName"
                :rules="[requiredValidator]"
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
              <AppSelect
                v-model="form.industry"
                :items="INDUSTRY_OPTIONS"
                :rules="[requiredValidator]"
                label="Industry"
                placeholder="Select an industry"
              />
            </VCol>
            <VCol
              v-if="!noGstin"
              cols="12"
              md="6"
            >
              <AppTextField
                v-model="form.gstin"
                :rules="[requiredValidator, gstinValidator]"
                label="GSTIN"
                placeholder="15-character GSTIN"
              />
            </VCol>
            <VCol
              v-else
              cols="12"
              md="6"
            >
              <AppSelect
                v-model="form.stateCode"
                :items="GST_STATES"
                :rules="[requiredValidator]"
                label="State"
                placeholder="Select your business's state"
              />
            </VCol>
            <VCol
              cols="12"
              md="6"
              class="d-flex align-center mt-n2"
            >
              <VCheckbox
                v-model="noGstin"
                label="I don't have a GSTIN"
                @update:model-value="form.gstin = ''"
              />
            </VCol>
            <VCol
              cols="12"
              md="6"
            >
              <AppTextField
                v-model="form.pan"
                :rules="[requiredValidator, panValidator]"
                label="PAN"
                placeholder="10-character PAN"
              />
            </VCol>
            <VCol
              cols="12"
              md="6"
            >
              <AppTextField
                v-model="form.address"
                :rules="[requiredValidator]"
                label="Business address"
                placeholder="Registered office address"
              />
            </VCol>
            <VCol cols="12">
              <h6 class="text-h6 mb-2">
                Primary contact person
              </h6>
            </VCol>
            <VCol
              cols="12"
              md="4"
            >
              <AppTextField
                v-model="form.contactPersonName"
                :rules="[requiredValidator]"
                label="Contact person name"
                placeholder="Full name"
              />
            </VCol>
            <VCol
              cols="12"
              md="4"
            >
              <AppTextField
                v-model="form.contactEmail"
                :rules="[requiredValidator, emailValidator]"
                label="Contact person email"
                placeholder="name@company.com"
              />
            </VCol>
            <VCol
              cols="12"
              md="4"
            >
              <AppTextField
                v-model="form.contactMobile"
                :rules="[requiredValidator, mobileValidator]"
                label="Contact person mobile"
                placeholder="9876543210"
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
