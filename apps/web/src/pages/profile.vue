<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type Profile = {
  full_name: string
  email: string
  mobile: string | null
  email_verified: boolean
  mobile_verified: boolean
  role: string
}
type CompanyProfile = {
  company_name: string | null
  pan: string | null
  gstin: string | null
  state_code: string | null
  address: string | null
}
type ChangeRequest = {
  id: string
  status: string
  requested_full_name: string | null
  requested_email: string | null
  requested_mobile: string | null
  requested_company_name: string | null
  requested_gstin: string | null
  requested_pan: string | null
  requested_address: string | null
  requested_state_code: string | null
  customer_note: string | null
  admin_note: string | null
  created_at: string
  reviewed_at: string | null
}

const profile = ref<Profile | null>(null)
const company = ref<CompanyProfile | null>(null)
const requests = ref<ChangeRequest[]>([])
const loadError = ref('')
const loading = ref(true)

async function load() {
  loadError.value = ''
  loading.value = true
  try {
    const [p, c, r] = await Promise.all([
      $api<Profile>('/v1/auth/me'),
      // No organization yet (e.g. platform staff) -- company details simply don't apply.
      $api<CompanyProfile>('/v1/onboarding/company-profile').catch(() => null),
      $api<ChangeRequest[]>('/v1/auth/profile-change-requests'),
    ])
    profile.value = p
    company.value = c
    requests.value = r
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load your profile.')
  }
  finally {
    loading.value = false
  }
}

onMounted(load)

const hasPendingRequest = computed(() => requests.value.some(r => r.status === 'pending'))

const showRequestForm = ref(false)
const form = reactive({
  requested_full_name: '',
  requested_email: '',
  requested_mobile: '',
  requested_company_name: '',
  requested_gstin: '',
  requested_pan: '',
  requested_address: '',
  requested_state_code: '',
  customer_note: '',
})

function resetForm() {
  for (const key of Object.keys(form))
    (form as Record<string, string>)[key] = ''
}

const submitting = ref(false)
const submitError = ref('')
const submitSuccess = ref('')

async function onSubmitRequest() {
  submitError.value = ''
  submitSuccess.value = ''
  submitting.value = true
  try {
    const body: Record<string, string> = {}
    for (const [key, value] of Object.entries(form)) {
      if (value.trim())
        body[key] = value.trim()
    }
    if (!Object.keys(body).length) {
      submitError.value = 'Fill in at least one field you want changed.'
      return
    }
    await $api('/v1/auth/profile-change-requests', { method: 'POST', body })
    submitSuccess.value = 'Your change request has been submitted for admin review.'
    showRequestForm.value = false
    resetForm()
    await load()
  }
  catch (error: any) {
    submitError.value = extractErrorMessage(error, 'Could not submit your request.')
  }
  finally {
    submitting.value = false
  }
}

const FIELD_LABELS: Record<string, string> = {
  requested_full_name: 'Full name',
  requested_email: 'Email',
  requested_mobile: 'Mobile',
  requested_company_name: 'Company name',
  requested_gstin: 'GSTIN',
  requested_pan: 'PAN',
  requested_address: 'Address',
  requested_state_code: 'State code',
}

function requestedFields(r: ChangeRequest) {
  return Object.entries(FIELD_LABELS)
    .map(([key, label]) => ({ label, value: (r as unknown as Record<string, string | null>)[key] }))
    .filter(f => f.value)
}

function statusColor(status: string) {
  if (status === 'approved')
    return 'success'
  if (status === 'rejected')
    return 'error'
  return 'warning'
}
</script>

<template>
  <h1 class="text-h4 mb-1">
    Profile
  </h1>
  <p class="text-medium-emphasis mb-6">
    Your account and company details. These aren't directly editable — submit a change request
    below and an admin will review it.
  </p>

  <VAlert
    v-if="loadError"
    type="error"
    variant="tonal"
    class="mb-6"
  >
    {{ loadError }}
  </VAlert>

  <template v-else-if="!loading && profile">
    <VCard max-width="640" class="mb-6">
      <VCardText>
        <h6 class="text-h6 mb-4">
          Account
        </h6>
        <VTable density="compact">
          <tbody>
            <tr>
              <td class="text-medium-emphasis">
                Full name
              </td>
              <td>{{ profile.full_name }}</td>
            </tr>
            <tr>
              <td class="text-medium-emphasis">
                Email
              </td>
              <td>
                {{ profile.email }}
                <VChip
                  size="x-small"
                  :color="profile.email_verified ? 'success' : 'warning'"
                  class="ms-2"
                >
                  {{ profile.email_verified ? 'Verified' : 'Unverified' }}
                </VChip>
              </td>
            </tr>
            <tr>
              <td class="text-medium-emphasis">
                Mobile
              </td>
              <td>
                {{ profile.mobile || '—' }}
                <VChip
                  v-if="profile.mobile"
                  size="x-small"
                  :color="profile.mobile_verified ? 'success' : 'warning'"
                  class="ms-2"
                >
                  {{ profile.mobile_verified ? 'Verified' : 'Unverified' }}
                </VChip>
              </td>
            </tr>
            <tr>
              <td class="text-medium-emphasis">
                Role
              </td>
              <td class="text-capitalize">
                {{ profile.role.replaceAll('_', ' ') }}
              </td>
            </tr>
          </tbody>
        </VTable>
      </VCardText>
    </VCard>

    <VCard v-if="company" max-width="640" class="mb-6">
      <VCardText>
        <h6 class="text-h6 mb-4">
          Company
        </h6>
        <VTable density="compact">
          <tbody>
            <tr>
              <td class="text-medium-emphasis">
                Company name
              </td>
              <td>{{ company.company_name || '—' }}</td>
            </tr>
            <tr>
              <td class="text-medium-emphasis">
                GSTIN
              </td>
              <td>{{ company.gstin || '—' }}</td>
            </tr>
            <tr>
              <td class="text-medium-emphasis">
                PAN
              </td>
              <td>{{ company.pan || '—' }}</td>
            </tr>
            <tr>
              <td class="text-medium-emphasis">
                Address
              </td>
              <td>{{ company.address || '—' }}</td>
            </tr>
            <tr>
              <td class="text-medium-emphasis">
                State code
              </td>
              <td>{{ company.state_code || '—' }}</td>
            </tr>
          </tbody>
        </VTable>
      </VCardText>
    </VCard>

    <VCard max-width="640">
      <VCardText>
        <div class="d-flex align-center justify-space-between mb-4">
          <h6 class="text-h6">
            Change Requests
          </h6>
          <VBtn
            v-if="!showRequestForm"
            size="small"
            :disabled="hasPendingRequest"
            @click="showRequestForm = true"
          >
            Request a change
          </VBtn>
        </div>

        <VAlert
          v-if="hasPendingRequest && !showRequestForm"
          type="info"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          You already have a change request awaiting review. You can submit another once it's been reviewed.
        </VAlert>

        <VAlert
          v-if="submitSuccess"
          type="success"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ submitSuccess }}
        </VAlert>

        <VForm v-if="showRequestForm" class="mb-6" @submit.prevent="onSubmitRequest">
          <VAlert
            v-if="submitError"
            type="error"
            variant="tonal"
            density="compact"
            class="mb-4"
          >
            {{ submitError }}
          </VAlert>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Only fill in the fields you want changed — leave the rest blank.
          </p>
          <VRow>
            <VCol cols="12" sm="6">
              <AppTextField v-model="form.requested_full_name" label="New full name" />
            </VCol>
            <VCol cols="12" sm="6">
              <AppTextField v-model="form.requested_email" label="New email" type="email" />
            </VCol>
            <VCol cols="12" sm="6">
              <AppTextField v-model="form.requested_mobile" label="New mobile" />
            </VCol>
            <VCol cols="12" sm="6">
              <AppTextField v-model="form.requested_company_name" label="New company name" />
            </VCol>
            <VCol cols="12" sm="6">
              <AppTextField v-model="form.requested_gstin" label="New GSTIN" />
            </VCol>
            <VCol cols="12" sm="6">
              <AppTextField v-model="form.requested_pan" label="New PAN" />
            </VCol>
            <VCol cols="12" sm="6">
              <AppTextField v-model="form.requested_address" label="New address" />
            </VCol>
            <VCol cols="12" sm="6">
              <AppTextField v-model="form.requested_state_code" label="New state code" />
            </VCol>
            <VCol cols="12">
              <AppTextField v-model="form.customer_note" label="Why? (optional)" />
            </VCol>
            <VCol cols="12" class="d-flex ga-3">
              <VBtn type="submit" :loading="submitting">
                Submit request
              </VBtn>
              <VBtn variant="tonal" @click="showRequestForm = false; resetForm(); submitError = ''">
                Cancel
              </VBtn>
            </VCol>
          </VRow>
        </VForm>

        <VTable v-if="requests.length" density="compact">
          <thead>
            <tr>
              <th>Requested changes</th>
              <th>Note</th>
              <th>Submitted</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in requests" :key="r.id">
              <td>
                <div v-for="f in requestedFields(r)" :key="f.label" class="text-body-2">
                  <strong>{{ f.label }}:</strong> {{ f.value }}
                </div>
              </td>
              <td class="text-body-2">
                {{ r.admin_note || r.customer_note || '—' }}
              </td>
              <td>{{ new Date(r.created_at).toLocaleString('en-IN') }}</td>
              <td>
                <VChip :color="statusColor(r.status)" size="small" class="text-capitalize">
                  {{ r.status }}
                </VChip>
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-else class="text-body-2 text-medium-emphasis">
          No change requests yet.
        </p>
      </VCardText>
    </VCard>
  </template>
</template>
