<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
    staffArea: 'support',
  },
})

const authStore = useAuthStore()

// Platform staff roles only -- customer-side roles (enterprise_customer, sub_user, etc.) belong
// to organizations and are managed from the Customers section instead.
const ROLES = [
  { value: 'super_admin', title: 'Super Admin' },
  { value: 'operator_admin', title: 'Operator Admin' },
  { value: 'finance_team', title: 'Finance Team' },
  { value: 'support_team', title: 'Support Team' },
  { value: 'sales_team', title: 'Sales Team' },
  { value: 'reseller', title: 'Reseller' },
  { value: 'agency', title: 'Agency' },
  { value: 'developer', title: 'Developer' },
]

// finance_team/sales_team/support_team now have their own scoped admin-panel slice (see
// admin.STAFF_AREA_ROLES) so they have somewhere to land after being invited -- reseller/agency/
// developer still don't have any wired-up area, so they stay off this list until that exists.
const INVITABLE_STAFF_ROLES = [
  { value: 'super_admin', title: 'Super Admin' },
  { value: 'operator_admin', title: 'Operator Admin' },
  { value: 'finance_team', title: 'Finance Team' },
  { value: 'sales_team', title: 'Sales Team' },
  { value: 'support_team', title: 'Support Team' },
]
type AdminUser = {
  id: string
  email: string
  full_name: string
  role: string
  status: string
  organization_id: string | null
  email_verified: boolean
  mobile_verified: boolean
  two_factor_enabled: boolean
}

const users = ref<AdminUser[]>([])
const loadError = ref('')
const savingId = ref<string | null>(null)
const saveError = ref('')
const search = ref('')
let searchTimer: ReturnType<typeof setTimeout> | undefined

const PAGE_SIZE = 50
const offset = ref(0)
const hasMore = ref(false)

const hasAccess = computed(() => authStore.loaded ? (authStore.isAdmin || authStore.staffArea === 'support') : null)
// Support Team can view this page but not act on it -- every mutation endpoint (invite,
// role-change, status-change, reset-password, force-disable-2FA) stays require_admin-only on the
// backend, so the controls that would call them are hidden rather than left visible-but-broken.
const canManage = computed(() => authStore.isAdmin)

// Guards against a real race: clicking "Load more" then immediately typing a search. Both fire
// their own request; if the Load-More one resolves after the search one, it would otherwise
// append its (now-stale, unfiltered) page onto the just-set filtered results. Each call captures
// the current generation and only applies its result if nothing newer has been issued since.
let loadGeneration = 0

async function load(reset = true) {
  loadError.value = ''
  if (reset)
    offset.value = 0
  const generation = ++loadGeneration
  try {
    await authStore.load()
    if (!hasAccess.value)
      return
    const query: Record<string, any> = { limit: PAGE_SIZE, offset: offset.value }
    if (search.value)
      query.search = search.value
    const page = await $api<AdminUser[]>('/v1/admin/users', { query })
    if (generation !== loadGeneration)
      return
    users.value = reset ? page : [...users.value, ...page]
    hasMore.value = page.length === PAGE_SIZE
  }
  catch (error: any) {
    if (generation === loadGeneration)
      loadError.value = extractErrorMessage(error, 'Could not load users.')
  }
}

async function onLoadMore() {
  offset.value += PAGE_SIZE
  await load(false)
}

watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => load(true), 300)
})

const showInviteDialog = ref(false)
const inviteEmail = ref('')
const inviteRole = ref('operator_admin')
const inviting = ref(false)
const inviteError = ref('')
const inviteSuccessEmail = ref('')
const devInviteToken = ref('')

async function onInvite() {
  inviteError.value = ''
  inviting.value = true
  try {
    const result = await $api<{ email: string, dev_invite_token?: string | null }>('/v1/admin/users/invite', {
      method: 'POST',
      body: { email: inviteEmail.value.trim(), role: inviteRole.value },
    })
    inviteSuccessEmail.value = result.email
    devInviteToken.value = result.dev_invite_token ?? ''
    inviteEmail.value = ''
    await load()
  }
  catch (error: any) {
    inviteError.value = extractErrorMessage(error, 'Could not send this invite.')
  }
  finally {
    inviting.value = false
  }
}

function closeInviteDialog() {
  showInviteDialog.value = false
  inviteError.value = ''
  inviteSuccessEmail.value = ''
  devInviteToken.value = ''
}

async function onRoleChange(user: AdminUser, role: string) {
  saveError.value = ''
  savingId.value = user.id
  try {
    const updated = await $api<AdminUser>(`/v1/admin/users/${user.id}/role`, { method: 'PATCH', body: { role } })
    user.role = updated.role
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not update this user\'s role.')
  }
  finally {
    savingId.value = null
  }
}

const togglingStatusId = ref<string | null>(null)

async function onToggleStatus(user: AdminUser) {
  saveError.value = ''
  togglingStatusId.value = user.id
  const nextStatus = user.status === 'suspended' ? 'active' : 'suspended'
  try {
    const updated = await $api<AdminUser>(`/v1/admin/users/${user.id}/status`, { method: 'PATCH', body: { status: nextStatus } })
    user.status = updated.status
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not update this user\'s status.')
  }
  finally {
    togglingStatusId.value = null
  }
}

const disabling2faId = ref<string | null>(null)

async function onForceDisable2fa(user: AdminUser) {
  saveError.value = ''
  disabling2faId.value = user.id
  try {
    await $api(`/v1/admin/users/${user.id}/two-factor`, { method: 'PATCH', body: { enabled: false } })
    user.two_factor_enabled = false
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not disable 2FA for this user.')
  }
  finally {
    disabling2faId.value = null
  }
}

const showResetDialog = ref(false)
const resetTargetEmail = ref('')
const resettingPassword = ref(false)
const resetError = ref('')
const resetResultMessage = ref('')
const resetDevPassword = ref('')
let resetTargetUser: AdminUser | null = null

function openResetDialog(user: AdminUser) {
  resetTargetUser = user
  resetTargetEmail.value = user.email
  resetError.value = ''
  resetResultMessage.value = ''
  resetDevPassword.value = ''
  showResetDialog.value = true
}

async function onConfirmReset() {
  if (!resetTargetUser)
    return
  resetError.value = ''
  resettingPassword.value = true
  try {
    const result = await $api<{ message: string, dev_generated_password?: string | null }>(`/v1/admin/users/${resetTargetUser.id}/reset-password`, { method: 'POST' })
    resetResultMessage.value = result.message
    resetDevPassword.value = result.dev_generated_password ?? ''
  }
  catch (error: any) {
    resetError.value = extractErrorMessage(error, 'Could not reset this user\'s password.')
  }
  finally {
    resettingPassword.value = false
  }
}

function closeResetDialog() {
  showResetDialog.value = false
  resetTargetUser = null
}

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Users
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every platform-staff account and its role. Customer-side accounts live under Customers instead.
    Super Admin and Operator Admin can manage this; Support Team can view it.
  </p>

  <VAlert
    v-if="hasAccess === false"
    type="warning"
    variant="tonal"
  >
    This page is restricted to Super Admin, Operator Admin, and Support Team roles.
  </VAlert>

  <VAlert
    v-else-if="loadError"
    type="error"
    variant="tonal"
  >
    {{ loadError }}
  </VAlert>

  <div
    v-if="hasAccess"
    class="d-flex align-center justify-space-between mb-4 gap-4 flex-wrap"
  >
    <AppTextField
      v-model="search"
      placeholder="Search by name or email"
      prepend-inner-icon="tabler-search"
      style="max-inline-size: 420px;"
      clearable
    />
    <VBtn
      v-if="canManage"
      prepend-icon="tabler-user-plus"
      @click="showInviteDialog = true"
    >
      Invite User
    </VBtn>
  </div>

  <VCard v-if="hasAccess">
    <VCardText>
      <VAlert
        v-if="saveError"
        type="error"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        {{ saveError }}
      </VAlert>
      <VTable>
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Role</th>
            <th>Status</th>
            <th>Verified</th>
            <th>2FA</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="user in users"
            :key="user.id"
          >
            <td>{{ user.full_name }}</td>
            <td>{{ user.email }}</td>
            <td style="min-inline-size: 220px;">
              <VSelect
                v-if="canManage"
                :model-value="user.role"
                :items="ROLES"
                item-title="title"
                item-value="value"
                density="compact"
                variant="outlined"
                hide-details
                :loading="savingId === user.id"
                :disabled="savingId === user.id"
                @update:model-value="(value: string) => onRoleChange(user, value)"
              />
              <span v-else class="text-capitalize">{{ user.role.replace('_', ' ') }}</span>
            </td>
            <td>
              <VChip
                size="small"
                :color="user.status === 'suspended' ? 'error' : user.status === 'active' ? 'success' : 'warning'"
                class="text-capitalize"
              >
                {{ user.status.replace('_', ' ') }}
              </VChip>
            </td>
            <td>
              <VIcon
                :icon="user.email_verified ? 'tabler-mail-check' : 'tabler-mail-x'"
                :color="user.email_verified ? 'success' : 'error'"
                size="18"
                class="me-1"
              />
              <VIcon
                :icon="user.mobile_verified ? 'tabler-phone-check' : 'tabler-phone-x'"
                :color="user.mobile_verified ? 'success' : 'error'"
                size="18"
              />
            </td>
            <td>
              <VChip
                v-if="user.two_factor_enabled"
                size="small"
                color="success"
              >
                On
              </VChip>
              <span
                v-else
                class="text-medium-emphasis"
              >—</span>
            </td>
            <td>
              <div v-if="canManage" class="d-flex gap-1">
                <VBtn
                  size="small"
                  variant="text"
                  @click="openResetDialog(user)"
                >
                  Reset Password
                </VBtn>
                <VBtn
                  v-if="user.two_factor_enabled"
                  size="small"
                  variant="text"
                  :loading="disabling2faId === user.id"
                  @click="onForceDisable2fa(user)"
                >
                  Disable 2FA
                </VBtn>
                <VBtn
                  size="small"
                  variant="text"
                  :color="user.status === 'suspended' ? 'success' : 'error'"
                  :loading="togglingStatusId === user.id"
                  @click="onToggleStatus(user)"
                >
                  {{ user.status === 'suspended' ? 'Reactivate' : 'Suspend' }}
                </VBtn>
              </div>
              <span v-else class="text-medium-emphasis">—</span>
            </td>
          </tr>
        </tbody>
      </VTable>
      <div v-if="hasMore" class="text-center mt-4">
        <VBtn size="small" variant="text" @click="onLoadMore">
          Load more
        </VBtn>
      </div>
    </VCardText>
  </VCard>

  <VDialog
    v-model="showResetDialog"
    max-width="480"
    @update:model-value="value => { if (!value) closeResetDialog() }"
  >
    <VCard>
      <VCardTitle>Reset password for {{ resetTargetEmail }}</VCardTitle>
      <VCardText>
        <VAlert
          v-if="resetError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ resetError }}
        </VAlert>
        <template v-if="resetResultMessage">
          <VAlert
            type="success"
            variant="tonal"
            density="compact"
            class="mb-4"
          >
            {{ resetResultMessage }}
          </VAlert>
          <VAlert
            v-if="resetDevPassword"
            type="info"
            variant="tonal"
            density="compact"
          >
            Development mode — no email sender configured yet. New temporary password: <code>{{ resetDevPassword }}</code>
          </VAlert>
        </template>
        <p v-else class="text-body-2 text-medium-emphasis">
          This generates a new temporary password and emails it to the user. Their current password stops working immediately.
        </p>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn
          v-if="!resetResultMessage"
          :loading="resettingPassword"
          @click="onConfirmReset"
        >
          Reset Password
        </VBtn>
        <VBtn
          v-else
          @click="closeResetDialog"
        >
          Close
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog
    v-model="showInviteDialog"
    max-width="480"
    @update:model-value="value => { if (!value) closeInviteDialog() }"
  >
    <VCard>
      <VCardTitle>Invite a platform-staff user</VCardTitle>
      <VCardText>
        <VAlert
          v-if="inviteError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ inviteError }}
        </VAlert>

        <template v-if="inviteSuccessEmail">
          <VAlert
            type="success"
            variant="tonal"
            density="compact"
            class="mb-4"
          >
            Invite sent to {{ inviteSuccessEmail }}. They'll set their own name, mobile number, and password when they accept.
          </VAlert>
          <VAlert
            v-if="devInviteToken"
            type="info"
            variant="tonal"
            density="compact"
          >
            Development mode — no email sender configured yet. Accept-invite link:
            <br>
            <code>/accept-invite?token={{ devInviteToken }}</code>
          </VAlert>
        </template>

        <VForm
          v-else
          @submit.prevent="onInvite"
        >
          <p class="text-body-2 text-medium-emphasis mb-4">
            The invitee fills in their own name, mobile number, and password when they accept — you only pick who and what role.
          </p>
          <VRow>
            <VCol cols="12">
              <AppTextField
                v-model="inviteEmail"
                label="Email"
                type="email"
                placeholder="teammate@textzi.in"
                autofocus
              />
            </VCol>
            <VCol cols="12">
              <VSelect
                v-model="inviteRole"
                :items="INVITABLE_STAFF_ROLES"
                item-title="title"
                item-value="value"
                label="Role"
              />
            </VCol>
            <VCol cols="12">
              <VBtn
                type="submit"
                :loading="inviting"
                block
              >
                Send Invite
              </VBtn>
            </VCol>
          </VRow>
        </VForm>
      </VCardText>
      <VCardActions v-if="inviteSuccessEmail">
        <VSpacer />
        <VBtn @click="closeInviteDialog">
          Close
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
