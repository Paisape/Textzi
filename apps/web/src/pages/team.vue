<script setup lang="ts">
import { CRM_NAV_ITEMS, SMS_NAV_ITEMS, WABA_NAV_ITEMS } from '@/navigation/vertical'
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
  },
})

const authStore = useAuthStore()

type MemberRow = { id: string, email: string, full_name: string, role: string, status: string, channel_scope: string | null, page_scope: string[] | null }

const ROLES = [
  { value: 'sub_user', title: 'Sub User' },
  { value: 'finance_user', title: 'Finance User' },
  { value: 'marketing_user', title: 'Marketing User' },
  { value: 'read_only_user', title: 'Read Only User' },
]

// null = full access to whatever channels the org has active (default) -- picking one locks this
// teammate to only that channel's focused workspace from their next login onward (see the router
// guard in plugins/1.router/index.ts).
const CHANNEL_SCOPES = [
  { value: null, title: 'All channels' },
  { value: 'sms', title: 'SMS only' },
  { value: 'waba', title: 'WhatsApp only' },
  { value: 'crm', title: 'CRM only' },
]

const members = ref<MemberRow[]>([])
const loadError = ref('')

const inviteEmail = ref('')
const inviteRole = ref('sub_user')
const inviteChannelScope = ref<string | null>(null)
const invitePageScope = ref<string[]>([])
const inviting = ref(false)
const inviteError = ref('')
const inviteSuccess = ref('')

// Flattened { title, name } pairs for whichever channel is currently picked -- sourced directly
// from the same nav arrays that render the real sidebar, so this list can never drift out of
// sync with what pages actually exist. Nothing is checked by default: the owner has to
// explicitly grant each page, including "Manage" -- narrowing to a channel alone no longer
// implies the whole channel.
function flattenPages(items: any[]): { title: string, name: string }[] {
  return items.flatMap(item => item.children ? flattenPages(item.children) : (item.to?.name ? [{ title: item.title, name: item.to.name }] : []))
}
const channelPages = computed(() => {
  if (inviteChannelScope.value === 'waba')
    return flattenPages(WABA_NAV_ITEMS)
  if (inviteChannelScope.value === 'crm')
    return flattenPages(CRM_NAV_ITEMS)
  if (inviteChannelScope.value === 'sms')
    return flattenPages(SMS_NAV_ITEMS)
  return []
})
watch(inviteChannelScope, () => { invitePageScope.value = [] })

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
  // A channel is picked but nothing checked would otherwise silently fall back to full access
  // within that channel -- the opposite of what the helper text above promises ("nothing is
  // granted until you check it"). Require at least one page instead of guessing what was meant.
  if (inviteChannelScope.value && !invitePageScope.value.length) {
    inviteError.value = 'Check at least one page this teammate can access, or clear the channel selection for full access.'
    return
  }
  inviting.value = true
  try {
    await $api('/v1/team/invite', {
      method: 'POST',
      body: {
        email: inviteEmail.value.trim(), role: inviteRole.value, channel_scope: inviteChannelScope.value,
        page_scope: inviteChannelScope.value ? invitePageScope.value : null,
      },
    })
    inviteSuccess.value = `Invite sent to ${inviteEmail.value.trim()}.`
    inviteEmail.value = ''
    inviteChannelScope.value = null
    invitePageScope.value = []
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
          <VCol cols="12" sm="3">
            <VSelect
              v-model="inviteRole"
              :items="ROLES"
              item-title="title"
              item-value="value"
              label="Role"
            />
          </VCol>
          <VCol cols="12" sm="3">
            <VSelect
              v-model="inviteChannelScope"
              :items="CHANNEL_SCOPES"
              item-title="title"
              item-value="value"
              label="Channel access"
            />
          </VCol>
          <VCol v-if="inviteChannelScope && channelPages.length" cols="12">
            <p class="text-body-2 text-medium-emphasis mb-2">
              Pages this teammate can access within {{ inviteChannelScope }} — nothing is granted until you check it, including Manage.
            </p>
            <div class="d-flex flex-wrap ga-4">
              <VCheckbox
                v-for="page in channelPages" :key="page.name"
                v-model="invitePageScope" :value="page.name" :label="page.title"
                density="compact" hide-details
              />
            </div>
          </VCol>
          <VCol cols="12" class="d-flex justify-end">
            <VBtn
              type="submit"
              :loading="inviting"
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
          <th>Channel access</th>
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
            {{ member.channel_scope ? `${member.channel_scope} only` : 'All channels' }}
            <span v-if="member.page_scope?.length" class="text-caption text-medium-emphasis d-block text-lowercase">
              {{ member.page_scope.length }} page{{ member.page_scope.length === 1 ? '' : 's' }}
            </span>
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
            colspan="6"
            class="text-center text-medium-emphasis"
          >
            No team members yet.
          </td>
        </tr>
      </tbody>
    </VTable>
  </VCard>
</template>
