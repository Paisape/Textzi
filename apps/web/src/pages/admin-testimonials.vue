<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { useStepUpAuth } from '@/composables/useStepUpAuth'

definePage({
  meta: {
    layout: 'default',
    requiresAdmin: true,
  },
})

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.loaded ? authStore.isAdmin : null)
const stepUp = useStepUpAuth()

type TestimonialRow = {
  id: string
  organization_name: string | null
  submitted_by_email: string | null
  author_name: string
  author_role: string
  quote: string
  status: string
  created_at: string
  reviewed_at: string | null
  reviewed_by: string | null
}

const STATUS_COLORS: Record<string, string> = { pending: 'warning', approved: 'success', rejected: 'error' }

const rows = ref<TestimonialRow[]>([])
const loadError = ref('')
const statusFilter = ref<string | null>('pending')
const loading = ref(false)
const actionError = ref('')

const createForm = ref({ author_name: '', author_role: '', quote: '' })
const creating = ref(false)
const createError = ref('')

async function load() {
  loadError.value = ''
  loading.value = true
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    rows.value = await stepUp.withStepUp(() =>
      $api<TestimonialRow[]>('/v1/admin/testimonials', { query: statusFilter.value ? { status_filter: statusFilter.value } : {} }),
    )
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load testimonials.')
  }
  finally {
    loading.value = false
  }
}

async function setStatus(id: string, status: 'approved' | 'rejected') {
  actionError.value = ''
  try {
    await stepUp.withStepUp(() => $api(`/v1/admin/testimonials/${id}/status`, { method: 'PATCH', body: { status } }))
    await load()
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not update this testimonial.')
  }
}

async function remove(id: string) {
  actionError.value = ''
  try {
    await stepUp.withStepUp(() => $api(`/v1/admin/testimonials/${id}`, { method: 'DELETE' }))
    await load()
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not delete this testimonial.')
  }
}

async function onCreate() {
  createError.value = ''
  creating.value = true
  try {
    await stepUp.withStepUp(() => $api('/v1/admin/testimonials', { method: 'POST', body: createForm.value }))
    createForm.value = { author_name: '', author_role: '', quote: '' }
    await load()
  }
  catch (error: any) {
    createError.value = extractErrorMessage(error, 'Could not add this testimonial.')
  }
  finally {
    creating.value = false
  }
}

watch(statusFilter, load)
onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Testimonials
  </h1>
  <p class="text-medium-emphasis mb-6">
    Approve or reject customer-submitted testimonials, or add one directly (e.g. a quote a
    customer emailed in) -- only approved testimonials ever appear on the public site.
  </p>

  <VAlert v-if="isAdmin === false" type="warning" variant="tonal">
    This page is restricted to Super Admin and Operator Admin roles.
  </VAlert>

  <VAlert v-else-if="loadError" type="error" variant="tonal">
    {{ loadError }}
  </VAlert>

  <template v-else-if="isAdmin">
    <VCard class="mb-6" title="Add a testimonial">
      <VCardText>
        <VAlert v-if="createError" type="error" variant="tonal" density="compact" class="mb-4">
          {{ createError }}
        </VAlert>
        <VForm @submit.prevent="onCreate">
          <VRow>
            <VCol cols="12" sm="4">
              <AppTextField v-model="createForm.author_name" label="Name" placeholder="Ananya Rao" />
            </VCol>
            <VCol cols="12" sm="4">
              <AppTextField v-model="createForm.author_role" label="Role & company" placeholder="Founder, UrbanCart" />
            </VCol>
            <VCol cols="12" sm="4" class="d-flex align-end">
              <VBtn type="submit" :loading="creating" block>
                Add (published immediately)
              </VBtn>
            </VCol>
            <VCol cols="12">
              <AppTextarea v-model="createForm.quote" label="Quote" rows="2" />
            </VCol>
          </VRow>
        </VForm>
      </VCardText>
    </VCard>

    <VAlert v-if="actionError" type="error" variant="tonal" density="compact" class="mb-4" closable @click:close="actionError = ''">
      {{ actionError }}
    </VAlert>

    <VBtnToggle v-model="statusFilter" class="mb-4" density="comfortable" mandatory color="primary">
      <VBtn value="pending">
        Pending
      </VBtn>
      <VBtn value="approved">
        Approved
      </VBtn>
      <VBtn value="rejected">
        Rejected
      </VBtn>
      <VBtn :value="null">
        All
      </VBtn>
    </VBtnToggle>

    <VCard>
      <VTable>
        <thead>
          <tr>
            <th>Date</th>
            <th>Name</th>
            <th>Role</th>
            <th>Quote</th>
            <th>Submitted by</th>
            <th>Status</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td class="text-no-wrap">
              {{ new Date(row.created_at).toLocaleString('en-IN') }}
            </td>
            <td>{{ row.author_name }}</td>
            <td>{{ row.author_role }}</td>
            <td style="max-inline-size: 320px; white-space: pre-wrap;">
              {{ row.quote }}
            </td>
            <td>{{ row.submitted_by_email ?? row.organization_name ?? '— (admin-added)' }}</td>
            <td>
              <VChip size="small" :color="STATUS_COLORS[row.status] ?? 'default'">
                {{ row.status }}
              </VChip>
            </td>
            <td class="text-no-wrap">
              <VBtn v-if="row.status !== 'approved'" size="small" variant="tonal" color="success" class="me-2" @click="setStatus(row.id, 'approved')">
                Approve
              </VBtn>
              <VBtn v-if="row.status !== 'rejected'" size="small" variant="tonal" color="warning" class="me-2" @click="setStatus(row.id, 'rejected')">
                Reject
              </VBtn>
              <VBtn size="small" variant="text" color="error" @click="remove(row.id)">
                Delete
              </VBtn>
            </td>
          </tr>
          <tr v-if="!loading && !rows.length">
            <td colspan="7" class="text-center text-medium-emphasis">
              No testimonials in this view.
            </td>
          </tr>
        </tbody>
      </VTable>
    </VCard>
  </template>

  <StepUpDialog
    v-model="stepUp.dialogOpen.value"
    :code="stepUp.code.value"
    :error="stepUp.error.value"
    :submitting="stepUp.submitting.value"
    @update:code="v => stepUp.code.value = v"
    @submit="stepUp.submit"
    @cancel="stepUp.cancel"
  />
</template>
