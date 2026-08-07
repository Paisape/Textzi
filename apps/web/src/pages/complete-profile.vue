<script setup lang="ts">
import { VNodeRenderer } from '@layouts/components/VNodeRenderer'
import { themeConfig } from '@themeConfig'
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'blank',
    public: false,
  },
})

const router = useRouter()
const authStore = useAuthStore()

type CompanyProfile = {
  organization_id: string
  company_name: string
  pan: string | null
  gstin: string | null
  address: string | null
  contact_email: string | null
  contact_mobile: string | null
  gst_certificate_uploaded: boolean
  profile_completed: boolean
}

const loading = ref(true)
const loadError = ref('')

const form = ref({
  companyName: '',
  pan: '',
  gstin: '',
  address: '',
  contactEmail: '',
  contactMobile: '',
})

const noGstin = ref(false)
const hasExistingCertificate = ref(false)
const gstCertificate = ref<File | File[] | null>(null)

function firstFile(value: File | File[] | null): File | null {
  if (Array.isArray(value))
    return value[0] ?? null
  return value
}

const gstinValidator = (v: string) => !v || v.length === 15 || 'GSTIN must be 15 characters'
const panValidator = (v: string) => (!!v && v.length === 10) || 'PAN must be 10 characters'
const mobileValidator = (v: string) => /^[1-9][0-9]{9,14}$/.test(v) || 'Enter a valid mobile number'

const refForm = ref()
const errorMessage = ref('')
const submitting = ref(false)

async function loadProfile() {
  loading.value = true
  loadError.value = ''
  try {
    const profile = await $api<CompanyProfile>('/v1/onboarding/company-profile')
    form.value.companyName = profile.company_name || ''
    form.value.pan = profile.pan || ''
    form.value.gstin = profile.gstin || ''
    form.value.address = profile.address || ''
    form.value.contactEmail = profile.contact_email || ''
    form.value.contactMobile = profile.contact_mobile || ''
    noGstin.value = !profile.gstin
    hasExistingCertificate.value = profile.gst_certificate_uploaded
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load your company profile.')
  }
  finally {
    loading.value = false
  }
}

loadProfile()

async function onSubmit() {
  const { valid } = await refForm.value.validate()
  if (!valid)
    return

  const certificate = firstFile(gstCertificate.value)
  if (!noGstin.value && !hasExistingCertificate.value && !certificate) {
    errorMessage.value = 'Upload your GST certificate, or check "I don\'t have a GSTIN" if you\'re not GST-registered.'
    return
  }

  errorMessage.value = ''
  submitting.value = true
  try {
    const body = new FormData()
    body.set('company_name', form.value.companyName.trim())
    body.set('pan', form.value.pan.trim())
    body.set('gstin', noGstin.value ? '' : form.value.gstin.trim())
    body.set('address', form.value.address.trim())
    body.set('contact_email', form.value.contactEmail.trim())
    body.set('contact_mobile', form.value.contactMobile.trim())
    if (certificate)
      body.set('gst_certificate', certificate)
    await $api('/v1/onboarding/company-profile', { method: 'PUT', body })
    await authStore.load(true)
    router.push('/dashboard')
  }
  catch (error: any) {
    errorMessage.value = extractErrorMessage(error, 'Could not save your company profile. Please try again.')
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

  <div class="complete-profile-wrapper d-flex align-center justify-center bg-surface">
    <VCard
      flat
      max-width="560"
      class="ma-4 pa-6 w-100"
    >
      <VCardText>
        <h4 class="text-h4 mb-1">
          Complete your profile
        </h4>
        <p class="mb-0">
          Before you continue, confirm your company details -- this only takes a minute.
        </p>
      </VCardText>

      <VCardText v-if="loading">
        <div class="d-flex justify-center pa-6">
          <VProgressCircular indeterminate />
        </div>
      </VCardText>

      <VCardText v-else-if="loadError">
        <VAlert
          type="error"
          variant="tonal"
          density="compact"
        >
          {{ loadError }}
        </VAlert>
      </VCardText>

      <VCardText v-else>
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
                v-model="form.companyName"
                :rules="[requiredValidator]"
                label="Company name"
                placeholder="Acme Pvt Ltd"
                autofocus
              />
            </VCol>
            <VCol
              cols="12"
              md="6"
            >
              <AppTextField
                v-model="form.pan"
                :rules="[requiredValidator, panValidator]"
                label="Company PAN"
                placeholder="10-character PAN"
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
                label="Company GSTIN"
                placeholder="15-character GSTIN"
              />
            </VCol>
            <VCol
              cols="12"
              :md="noGstin ? 12 : 6"
              class="d-flex align-center"
              :class="noGstin ? '' : 'mt-n2'"
            >
              <VCheckbox
                v-model="noGstin"
                label="I don't have a GSTIN"
                @update:model-value="form.gstin = ''"
              />
            </VCol>
            <VCol
              v-if="!noGstin"
              cols="12"
            >
              <VFileInput
                v-model="gstCertificate"
                :label="hasExistingCertificate ? 'GST certificate (already uploaded -- choose a file to replace it)' : 'GST certificate (PDF/JPG/PNG)'"
                accept=".pdf,.jpg,.jpeg,.png"
                prepend-icon="tabler-file-certificate"
              />
            </VCol>
            <VCol cols="12">
              <AppTextField
                v-model="form.address"
                :rules="[requiredValidator]"
                label="Company address"
                placeholder="Registered office address"
              />
            </VCol>
            <VCol
              cols="12"
              md="6"
            >
              <AppTextField
                v-model="form.contactEmail"
                :rules="[requiredValidator, emailValidator]"
                label="Company email"
                placeholder="name@company.com"
              />
            </VCol>
            <VCol
              cols="12"
              md="6"
            >
              <AppTextField
                v-model="form.contactMobile"
                :rules="[requiredValidator, mobileValidator]"
                label="Company mobile"
                placeholder="9876543210"
              />
            </VCol>
            <VCol cols="12">
              <VBtn
                block
                type="submit"
                :loading="submitting"
              >
                Save and continue
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

.complete-profile-wrapper {
  min-block-size: 100dvh;
}
</style>
