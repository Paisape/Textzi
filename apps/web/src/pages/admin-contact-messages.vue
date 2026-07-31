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

type ContactMessageRow = {
  id: string
  name: string
  email: string
  phone: string | null
  company: string | null
  message: string
  email_sent: boolean
  created_at: string
}

const rows = ref<ContactMessageRow[]>([])
const loadError = ref('')
const loading = ref(false)

async function load() {
  loadError.value = ''
  loading.value = true
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    rows.value = await stepUp.withStepUp(() => $api<ContactMessageRow[]>('/v1/admin/contact-messages'))
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load contact form submissions.')
  }
  finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Contact Us Submissions
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every message submitted through the public site's Contact form, newest first.
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

  <VCard v-else-if="isAdmin">
    <VTable>
      <thead>
        <tr>
          <th>Date</th>
          <th>Name</th>
          <th>Email</th>
          <th>Phone</th>
          <th>Company</th>
          <th>Message</th>
          <th>Notified</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="row.id"
        >
          <td class="text-no-wrap">
            {{ new Date(row.created_at).toLocaleString('en-IN') }}
          </td>
          <td>{{ row.name }}</td>
          <td>
            <a :href="`mailto:${row.email}`">{{ row.email }}</a>
          </td>
          <td>{{ row.phone ?? '—' }}</td>
          <td>{{ row.company ?? '—' }}</td>
          <td style="max-inline-size: 360px; white-space: pre-wrap;">
            {{ row.message }}
          </td>
          <td>
            <VChip
              size="small"
              :color="row.email_sent ? 'success' : 'warning'"
            >
              {{ row.email_sent ? 'Yes' : 'No' }}
            </VChip>
          </td>
        </tr>
        <tr v-if="!loading && !rows.length">
          <td
            colspan="7"
            class="text-center text-medium-emphasis"
          >
            No contact form submissions yet.
          </td>
        </tr>
      </tbody>
    </VTable>
  </VCard>

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
