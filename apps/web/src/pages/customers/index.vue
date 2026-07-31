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

type CustomerRow = {
  organization_id: string
  organization_name: string
  primary_contact_name: string | null
  primary_contact_email: string | null
  primary_contact_mobile: string | null
  entity_count: number
  wallet_balance: number
  messages_sent: number
  last_activity: string | null
}

const customers = ref<CustomerRow[]>([])
const loadError = ref('')
const search = ref('')
let searchTimer: ReturnType<typeof setTimeout> | undefined

function onExportCsv() {
  downloadCsv(
    'customers.csv',
    [
      { key: 'primary_contact_name', label: 'Customer' },
      { key: 'primary_contact_email', label: 'Email' },
      { key: 'primary_contact_mobile', label: 'Mobile' },
      { key: 'organization_name', label: 'Organization' },
      { key: 'entity_count', label: 'Entities' },
      { key: 'wallet_balance', label: 'Wallet Balance' },
      { key: 'messages_sent', label: 'Messages Sent' },
      { key: 'last_activity', label: 'Last Activity' },
    ],
    customers.value,
  )
}

async function loadCustomers() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    customers.value = await $api<CustomerRow[]>('/v1/admin/customers', { query: search.value ? { search: search.value } : {} })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load customers.')
  }
}

watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(loadCustomers, 300)
})

const showCreateDialog = ref(false)
const creating = ref(false)
const createError = ref('')
const createForm = ref({
  organizationName: '',
  contactFullName: '',
  contactEmail: '',
  contactMobile: '',
})
const createSuccess = ref<{ user_id: string, dev_email_code?: string | null, dev_generated_password?: string | null } | null>(null)

async function onCreateCustomer() {
  createError.value = ''
  creating.value = true
  try {
    const result = await $api<{ organization_id: string, entity_id: string, user_id: string, dev_email_code?: string | null, dev_generated_password?: string | null }>('/v1/admin/customers', {
      method: 'POST',
      body: {
        organization_name: createForm.value.organizationName.trim(),
        contact_full_name: createForm.value.contactFullName.trim(),
        contact_email: createForm.value.contactEmail.trim(),
        contact_mobile: createForm.value.contactMobile.trim() || null,
      },
    })
    createSuccess.value = { user_id: result.user_id, dev_email_code: result.dev_email_code, dev_generated_password: result.dev_generated_password }
    await loadCustomers()
  }
  catch (error: any) {
    createError.value = extractErrorMessage(error, 'Could not create this customer.')
  }
  finally {
    creating.value = false
  }
}

function closeCreateDialog() {
  showCreateDialog.value = false
  createError.value = ''
  createSuccess.value = null
  createForm.value = { organizationName: '', contactFullName: '', contactEmail: '', contactMobile: '' }
}

onMounted(loadCustomers)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Customers
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every organization on Textzi, identified by who actually runs it — not just the registered
    business name.
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

  <template v-else-if="isAdmin">
    <div class="d-flex align-center justify-space-between mb-4 gap-4 flex-wrap">
      <AppTextField
        v-model="search"
        placeholder="Search by customer name, email, or organization"
        prepend-inner-icon="tabler-search"
        style="max-inline-size: 420px;"
        clearable
      />
      <div class="d-flex gap-2">
        <VBtn
          variant="tonal"
          prepend-icon="tabler-file-export"
          @click="onExportCsv"
        >
          Export CSV
        </VBtn>
        <VBtn
          prepend-icon="tabler-building-store"
          @click="showCreateDialog = true"
        >
          Create Customer
        </VBtn>
      </div>
    </div>

    <VCard>
      <VTable>
        <thead>
          <tr>
            <th>Customer</th>
            <th>Mobile</th>
            <th>Organization</th>
            <th>Entities</th>
            <th>Wallet Balance</th>
            <th>Messages Sent</th>
            <th>Last Activity</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="customer in customers"
            :key="customer.organization_id"
          >
            <td>
              <div class="font-weight-medium">
                {{ customer.primary_contact_name || '—' }}
              </div>
              <div class="text-body-2 text-medium-emphasis">
                {{ customer.primary_contact_email || '—' }}
              </div>
            </td>
            <td>{{ customer.primary_contact_mobile || '—' }}</td>
            <td>{{ customer.organization_name }}</td>
            <td>{{ customer.entity_count }}</td>
            <td>{{ customer.wallet_balance.toLocaleString('en-IN') }}</td>
            <td>{{ customer.messages_sent.toLocaleString('en-IN') }}</td>
            <td>{{ customer.last_activity ? new Date(customer.last_activity).toLocaleString('en-IN') : '—' }}</td>
            <td>
              <RouterLink :to="`/customers/${customer.organization_id}`">
                View
              </RouterLink>
            </td>
          </tr>
          <tr v-if="!customers.length">
            <td
              colspan="8"
              class="text-center text-medium-emphasis"
            >
              No customers found.
            </td>
          </tr>
        </tbody>
      </VTable>
    </VCard>
  </template>

  <VDialog
    v-model="showCreateDialog"
    max-width="520"
    @update:model-value="value => { if (!value) closeCreateDialog() }"
  >
    <VCard>
      <VCardTitle>Create a customer</VCardTitle>
      <VCardText>
        <VAlert
          v-if="createError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ createError }}
        </VAlert>

        <template v-if="createSuccess">
          <VAlert
            type="success"
            variant="tonal"
            density="compact"
            class="mb-4"
          >
            Customer created. A welcome email with their temporary password and verification code has been sent — they'll verify email and mobile, then can sign in.
          </VAlert>
          <VAlert
            v-if="createSuccess.dev_generated_password"
            type="info"
            variant="tonal"
            density="compact"
          >
            Development mode — no email sender configured yet.
            <br>
            Temporary password: <code>{{ createSuccess.dev_generated_password }}</code>
            <br>
            Email verification code: <code>{{ createSuccess.dev_email_code }}</code>
            <br>
            Activation link: <code>/verify-account?user_id={{ createSuccess.user_id }}</code>
          </VAlert>
        </template>

        <VForm
          v-else
          @submit.prevent="onCreateCustomer"
        >
          <p class="text-body-2 text-medium-emphasis mb-4">
            Enter the organization and primary contact's details. The system generates the login credentials — the customer verifies their email and mobile before they can sign in.
          </p>
          <VRow>
            <VCol cols="12">
              <AppTextField
                v-model="createForm.organizationName"
                label="Organization name"
                placeholder="Acme Retail Pvt Ltd"
                autofocus
              />
            </VCol>
            <VCol cols="12">
              <AppTextField
                v-model="createForm.contactFullName"
                label="Primary contact name"
                placeholder="Ananya Rao"
              />
            </VCol>
            <VCol cols="12">
              <AppTextField
                v-model="createForm.contactEmail"
                label="Primary contact email"
                type="email"
                placeholder="ananya@acme.com"
              />
            </VCol>
            <VCol cols="12">
              <AppTextField
                v-model="createForm.contactMobile"
                label="Primary contact mobile"
                placeholder="9876543210"
              />
            </VCol>
            <VCol cols="12">
              <VBtn
                type="submit"
                :loading="creating"
                block
              >
                Create Customer
              </VBtn>
            </VCol>
          </VRow>
        </VForm>
      </VCardText>
      <VCardActions v-if="createSuccess">
        <VSpacer />
        <VBtn @click="closeCreateDialog">
          Close
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
