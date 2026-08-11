<script setup lang="ts">
type AssignableUser = { id: string, full_name: string, email: string }

const users = ref<AssignableUser[]>([])
const capacities = ref<Record<string, number | null>>({})
const loading = ref(false)
const error = ref('')
const savingId = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    users.value = await $api<AssignableUser[]>('/v1/waba/assignable-users')
  }
  catch (err: any) {
    error.value = extractErrorMessage(err, 'Could not load teammates.')
  }
  finally {
    loading.value = false
  }
}

async function saveCapacity(user: AssignableUser) {
  savingId.value = user.id
  error.value = ''
  try {
    await $api(`/v1/waba/assignable-users/${user.id}/capacity`, { method: 'PUT', body: { max_open_conversations: capacities.value[user.id] || null } })
  }
  catch (err: any) {
    error.value = extractErrorMessage(err, 'Could not save this teammate\'s capacity.')
  }
  finally {
    savingId.value = null
  }
}

onMounted(load)
</script>

<template>
  <VCard max-width="560">
    <VCardText>
      <h2 class="text-h6 mb-1">
        Agent capacity
      </h2>
      <p class="text-body-2 text-medium-emphasis mb-4">
        Maximum open conversations a teammate can be assigned at once. Leave blank for unlimited.
      </p>
      <VAlert v-if="error" type="error" variant="tonal" density="compact" class="mb-3">
        {{ error }}
      </VAlert>
      <div v-for="user in users" :key="user.id" class="d-flex align-center ga-3 mb-2">
        <span class="flex-grow-1">{{ user.full_name }}</span>
        <VTextField
          v-model.number="capacities[user.id]"
          type="number"
          placeholder="Unlimited"
          density="compact"
          hide-details
          style="max-width: 140px;"
        />
        <VBtn size="small" :loading="savingId === user.id" @click="saveCapacity(user)">
          Save
        </VBtn>
      </div>
      <p v-if="!loading && !users.length" class="text-medium-emphasis mb-0">
        No teammates yet.
      </p>
    </VCardText>
  </VCard>
</template>
