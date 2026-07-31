<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
  },
})

const authStore = useAuthStore()

type MemberRow = { id: string, email: string, full_name: string, role: string, status: string }

const ROLES = [
  { value: 'sub_user', title: 'Sub User' },
  { value: 'finance_user', title: 'Finance User' },
  { value: 'marketing_user', title: 'Marketing User' },
  { value: 'read_only_user', title: 'Read Only User' },
]

const members = ref<MemberRow[]>([])
const loadError = ref('')

const inviteEmail = ref('')
const inviteRole = ref('sub_user')
const inviting = ref(false)
const inviteError = ref('')
const inviteSuccess = ref('')

async function loadMembers() {
  loadError.value = ''
  try {
    members.value = await $api<MemberRow[]>('/v1/team/members')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load team members.')
  }
}

const copiedMemberId = ref('')
function copyMemberId(id: string) {
  navigator.clipboard?.writeText(id)
  copiedMemberId.value = id
  setTimeout(() => { if (copiedMemberId.value === id) copiedMemberId.value = '' }, 1500)
}

async function onInvite() {
  inviteError.value = ''
  inviteSuccess.value = ''
  if (!inviteEmail.value.trim()) {
    inviteError.value = 'Enter an email address.'
    return
  }
  inviting.value = true
  try {
    await $api('/v1/team/invite', { method: 'POST', body: { email: inviteEmail.value.trim(), role: inviteRole.value } })
    inviteSuccess.value = `Invite sent to ${inviteEmail.value.trim()}.`
    inviteEmail.value = ''
  }
  catch (error: any) {
    inviteError.value = extractErrorMessage(error, 'Could not send this invite.')
  }
  finally {
    inviting.value = false
  }
}

onMounted(() => {
  authStore.load().then(loadMembers)
})
</script>

<template>
  <h1 class="text-h4 mb-1">
    Team
  </h1>
  <p class="text-medium-emphasis mb-6">
    Invite teammates to your organization. They'll share your organization's channels, wallet,
    and DLT registration.
  </p>

  <VCard
    v-if="authStore.can('team:invite')"
    class="mb-6"
    max-width="640"
  >
    <VCardText>
      <h6 class="text-h6 mb-4">
        Invite a teammate
      </h6>
      <VAlert
        v-if="inviteError"
        type="error"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        {{ inviteError }}
      </VAlert>
      <VAlert
        v-if="inviteSuccess"
        type="success"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        {{ inviteSuccess }}
      </VAlert>
      <VForm @submit.prevent="onInvite">
        <VRow>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="inviteEmail"
              label="Email"
              placeholder="teammate@company.com"
            />
          </VCol>
          <VCol cols="12" sm="4">
            <VSelect
              v-model="inviteRole"
              :items="ROLES"
              item-title="title"
              item-value="value"
              label="Role"
            />
          </VCol>
          <VCol cols="12" sm="2" class="d-flex align-end">
            <VBtn
              type="submit"
              :loading="inviting"
              block
            >
              Invite
            </VBtn>
          </VCol>
        </VRow>
      </VForm>
    </VCardText>
  </VCard>

  <VAlert
    v-if="loadError"
    type="error"
    variant="tonal"
    class="mb-4"
  >
    {{ loadError }}
  </VAlert>

  <VCard>
    <VTable>
      <thead>
        <tr>
          <th>Name</th>
          <th>Email</th>
          <th>Role</th>
          <th>Status</th>
          <th>User ID <span class="text-medium-emphasis font-weight-regular">(for X-User-Id)</span></th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="member in members"
          :key="member.id"
        >
          <td>{{ member.full_name }}</td>
          <td>{{ member.email }}</td>
          <td class="text-capitalize">
            {{ member.role.replaceAll('_', ' ') }}
          </td>
          <td class="text-capitalize">
            {{ member.status.replaceAll('_', ' ') }}
          </td>
          <td>
            <div class="d-flex align-center gap-1">
              <code class="text-caption">{{ member.id }}</code>
              <VBtn
                size="x-small"
                variant="text"
                icon
                @click="copyMemberId(member.id)"
              >
                <VIcon :icon="copiedMemberId === member.id ? 'tabler-check' : 'tabler-copy'" size="16" />
              </VBtn>
            </div>
          </td>
        </tr>
        <tr v-if="!members.length">
          <td
            colspan="5"
            class="text-center text-medium-emphasis"
          >
            No team members yet.
          </td>
        </tr>
      </tbody>
    </VTable>
  </VCard>
</template>
