<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

import { addRecentlyViewed } from '@/composables/useRecentlyViewed'

const route = useRoute('crm-customers-id')
const router = useRouter()

type CrmContact = { id: string, name: string | null, phone: string | null, email: string | null, title: string | null, company_id: string | null }
type Task = { id: string, title: string, type: string, due_at: string | null, done: boolean, priority: string }
type Customer = {
  id: string
  contact: CrmContact
  deal_id: string | null
  converted_from_conversation_id: string | null
  owner_user_id: string | null
  notes: string | null
  custom_fields: Record<string, any>
  created_at: string
}
type CustomerDetail = Customer & { tasks: Task[] }
type AssignableUser = { id: string, full_name: string }
type CustomField = { id: string, name: string, field_type: 'text' | 'number' | 'date' | 'dropdown', options: string[], required: boolean }

const detail = ref<CustomerDetail | null>(null)
const users = ref<AssignableUser[]>([])
const customFields = ref<CustomField[]>([])
const loading = ref(false)
const loadError = ref('')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [detailResult, userResult, fieldResult] = await Promise.all([
      $api<CustomerDetail>(`/v1/crm/customers/${route.params.id}`),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
      $api<CustomField[]>('/v1/crm/custom-fields?applies_to=customer'),
    ])
    detail.value = detailResult
    users.value = userResult
    customFields.value = fieldResult
    addRecentlyViewed({
      type: 'customer', id: detailResult.id,
      label: detailResult.contact.name || detailResult.contact.phone || detailResult.contact.email || 'Unknown',
      sublabel: 'Customer',
    })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load this customer.')
  }
  finally {
    loading.value = false
  }
}

function initial() {
  const c = detail.value?.contact
  return (c?.name || c?.phone || c?.email || '?').slice(0, 1).toUpperCase()
}

function ownerName(ownerUserId: string | null) {
  return users.value.find(u => u.id === ownerUserId)?.full_name || 'Unassigned'
}

async function updateNotes(notes: string) {
  if (!detail.value)
    return
  try {
    const updated = await $api<Customer>(`/v1/crm/customers/${detail.value.id}`, { method: 'PATCH', body: { notes } })
    detail.value = { ...detail.value, ...updated }
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not save notes.')
  }
}

async function updateOwner(ownerUserId: string | null) {
  if (!detail.value)
    return
  try {
    const updated = await $api<Customer>(`/v1/crm/customers/${detail.value.id}`, { method: 'PATCH', body: { owner_user_id: ownerUserId } })
    detail.value = { ...detail.value, ...updated }
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not reassign this customer.')
  }
}

async function updateCustomField(name: string, value: any) {
  if (!detail.value)
    return
  const custom_fields = { ...detail.value.custom_fields, [name]: value }
  try {
    const updated = await $api<Customer>(`/v1/crm/customers/${detail.value.id}`, { method: 'PATCH', body: { custom_fields } })
    detail.value = { ...detail.value, ...updated }
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not save this field.')
  }
}

const deleting = ref(false)

async function deleteCustomer() {
  if (!detail.value)
    return
  deleting.value = true
  try {
    await $api(`/v1/crm/customers/${detail.value.id}`, { method: 'DELETE' })
    router.push({ name: 'crm-customers' })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this customer.')
  }
  finally {
    deleting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="d-flex align-center gap-3 mb-4">
    <VBtn icon="tabler-arrow-left" variant="text" :to="{ name: 'crm-customers' }" />
    <h1 class="text-h5 mb-0">
      Customer
    </h1>
  </div>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <VProgressLinear v-if="loading" indeterminate class="mb-4" />

  <VRow v-if="detail">
    <VCol cols="12" md="8">
      <VCard class="mb-4">
        <VCardText class="d-flex align-center gap-4">
          <VAvatar color="primary" variant="tonal" size="56">
            <span class="text-h6">{{ initial() }}</span>
          </VAvatar>
          <div class="flex-grow-1">
            <p class="text-h6 mb-0">
              {{ detail.contact.name || detail.contact.phone || detail.contact.email || 'Unknown' }}
            </p>
            <p v-if="detail.contact.title" class="text-body-2 text-medium-emphasis mb-0">
              {{ detail.contact.title }}
            </p>
            <p class="text-body-2 text-medium-emphasis mb-0">
              {{ detail.contact.phone || detail.contact.email || '—' }}
            </p>
          </div>
        </VCardText>
        <VDivider />
        <VCardText class="d-flex flex-wrap gap-3">
          <RouterLink :to="`/crm-contacts/${detail.contact.id}`" class="d-flex align-center gap-2 text-body-2">
            <VIcon icon="tabler-user" size="16" />
            View contact
          </RouterLink>
          <RouterLink v-if="detail.deal_id" :to="`/crm-deals/${detail.deal_id}`" class="d-flex align-center gap-2 text-body-2">
            <VIcon icon="tabler-briefcase" size="16" />
            View originating deal
          </RouterLink>
        </VCardText>
      </VCard>

      <VCard v-if="customFields.length" class="mb-4" title="Custom fields">
        <VCardText class="d-flex flex-column gap-4">
          <template v-for="field in customFields" :key="field.id">
            <VSelect
              v-if="field.field_type === 'dropdown'"
              :model-value="detail.custom_fields[field.name]" :label="field.name" :items="field.options" density="compact" hide-details clearable
              @update:model-value="(v: string) => updateCustomField(field.name, v)"
            />
            <VTextField
              v-else
              :model-value="detail.custom_fields[field.name]" :label="field.name"
              :type="field.field_type === 'number' ? 'number' : field.field_type === 'date' ? 'date' : 'text'" density="compact" hide-details
              @blur="(e: FocusEvent) => updateCustomField(field.name, (e.target as HTMLInputElement).value)"
            />
          </template>
        </VCardText>
      </VCard>

      <VCard class="mb-4" title="Notes">
        <VCardText>
          <VTextarea
            :model-value="detail.notes || ''" rows="3" density="compact" placeholder="Add notes about this customer..."
            @blur="(e: FocusEvent) => updateNotes((e.target as HTMLTextAreaElement).value)"
          />
        </VCardText>
      </VCard>

      <VCard title="Tasks">
        <VList v-if="detail.tasks.length" density="compact">
          <VListItem v-for="task in detail.tasks" :key="task.id">
            <VListItemTitle :class="task.done ? 'text-decoration-line-through text-medium-emphasis' : ''">
              {{ task.title }}
            </VListItemTitle>
            <VListItemSubtitle>
              {{ task.type }} · {{ task.due_at ? new Date(task.due_at).toLocaleDateString() : 'no due date' }}
            </VListItemSubtitle>
          </VListItem>
        </VList>
        <p v-else class="text-medium-emphasis text-center pa-6">
          No tasks yet.
        </p>
      </VCard>
    </VCol>

    <VCol cols="12" md="4">
      <VCard class="mb-4" title="Details">
        <VCardText class="d-flex flex-column gap-4">
          <div>
            <p class="text-caption text-medium-emphasis mb-1">
              Owner
            </p>
            <VSelect
              :model-value="detail.owner_user_id"
              :items="users.map(u => ({ title: u.full_name, value: u.id }))"
              placeholder="Unassigned" density="compact" hide-details clearable
              @update:model-value="updateOwner"
            />
          </div>
          <div>
            <p class="text-caption text-medium-emphasis mb-1">
              Created
            </p>
            <p class="mb-0">
              {{ new Date(detail.created_at).toLocaleDateString() }}
            </p>
          </div>
        </VCardText>
      </VCard>

      <VCard title="Actions">
        <VCardText>
          <VBtn color="error" variant="tonal" block :loading="deleting" @click="deleteCustomer">
            Delete customer
          </VBtn>
        </VCardText>
      </VCard>
    </VCol>
  </VRow>
</template>
