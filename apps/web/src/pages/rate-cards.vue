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

type RateCardSlab = { id: string, min_amount: number, max_amount: number | null, price_per_sms: number }
type RateCard = { id: string, name: string, channel: string, is_default: boolean, min_recharge_amount: number, show_on_public_pricing: boolean, public_tagline: string | null, slabs: RateCardSlab[] }
type Assignment = { user_id: string, user_email: string, rate_card_id: string, rate_card_name: string }
type AdminUser = { id: string, email: string, full_name: string }

const CHANNEL_OPTIONS = [
  { title: 'SMS', value: 'sms' },
  { title: 'WhatsApp', value: 'whatsapp' },
]

const loadError = ref('')
const cards = ref<RateCard[]>([])
const assignments = ref<Assignment[]>([])
const users = ref<AdminUser[]>([])
const cardSearch = ref('')
const filteredCards = computed(() => cards.value.filter(c => c.name.toLowerCase().includes(cardSearch.value.toLowerCase())))
const assignableCards = computed(() => cards.value.filter(c => c.channel === 'sms'))

async function load() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const [cardList, assignmentList, userList] = await Promise.all([
      $api<RateCard[]>('/v1/admin/rate-cards'),
      $api<Assignment[]>('/v1/admin/rate-cards/assignments'),
      $api<AdminUser[]>('/v1/admin/customer-users'),
    ])
    cards.value = cardList
    assignments.value = assignmentList
    users.value = userList
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load rate cards.')
  }
}

// Create card
const newCardName = ref('')
const newCardChannel = ref('sms')
const newMinRecharge = ref(500)
const newSlabs = ref([{ min_amount: 1, max_amount: null as number | null, price_per_sms: null as number | null }])
const cardSubmitting = ref(false)
const cardError = ref('')

function addSlabRow() {
  newSlabs.value.push({ min_amount: null as unknown as number, max_amount: null, price_per_sms: null })
}

function removeSlabRow(index: number) {
  newSlabs.value.splice(index, 1)
}

async function onCreateCard() {
  cardError.value = ''
  if (!newCardName.value.trim()) {
    cardError.value = 'Enter a name for this rate card.'
    return
  }
  if (!newMinRecharge.value || newMinRecharge.value <= 0) {
    cardError.value = 'Enter a minimum top-up amount greater than zero.'
    return
  }
  const slabs = newSlabs.value
  if (!slabs.length || slabs.some(s => !s.min_amount || !s.price_per_sms)) {
    cardError.value = 'Fill in min amount and price for every slab.'
    return
  }
  cardSubmitting.value = true
  try {
    await $api('/v1/admin/rate-cards', {
      method: 'POST',
      body: {
        name: newCardName.value.trim(),
        channel: newCardChannel.value,
        min_recharge_amount: newMinRecharge.value,
        slabs: slabs.map(s => ({ min_amount: s.min_amount, max_amount: s.max_amount, price_per_sms: s.price_per_sms })),
      },
    })
    newCardName.value = ''
    newCardChannel.value = 'sms'
    newMinRecharge.value = 500
    newSlabs.value = [{ min_amount: 1, max_amount: null, price_per_sms: null }]
    await load()
  }
  catch (error: any) {
    cardError.value = extractErrorMessage(error, 'Could not create this rate card.')
  }
  finally {
    cardSubmitting.value = false
  }
}

const settingDefault = ref<string | null>(null)
async function onSetDefault(cardId: string) {
  settingDefault.value = cardId
  try {
    await $api(`/v1/admin/rate-cards/${cardId}/set-default`, { method: 'POST' })
    await load()
  }
  catch (error: any) {
    cardError.value = extractErrorMessage(error, 'Could not set this card as default.')
  }
  finally {
    settingDefault.value = null
  }
}

// Public pricing page visibility + tagline
const savingPublicSettings = ref<string | null>(null)
const publicSettingsError = ref('')
const taglineDraft = ref<Record<string, string>>({})

function taglineFor(card: RateCard): string {
  if (!(card.id in taglineDraft.value))
    taglineDraft.value[card.id] = card.public_tagline || ''
  return taglineDraft.value[card.id]
}

async function onTogglePublicVisibility(card: RateCard, value: boolean) {
  savingPublicSettings.value = card.id
  publicSettingsError.value = ''
  try {
    await $api(`/v1/admin/rate-cards/${card.id}/public-settings`, {
      method: 'PUT',
      body: { show_on_public_pricing: value, public_tagline: taglineFor(card) || null },
    })
    await load()
  }
  catch (error: any) {
    publicSettingsError.value = extractErrorMessage(error, 'Could not update public-pricing visibility.')
  }
  finally {
    savingPublicSettings.value = null
  }
}

async function onSaveTagline(card: RateCard) {
  savingPublicSettings.value = card.id
  publicSettingsError.value = ''
  try {
    await $api(`/v1/admin/rate-cards/${card.id}/public-settings`, {
      method: 'PUT',
      body: { show_on_public_pricing: card.show_on_public_pricing, public_tagline: taglineFor(card) || null },
    })
    await load()
  }
  catch (error: any) {
    publicSettingsError.value = extractErrorMessage(error, 'Could not save this tagline.')
  }
  finally {
    savingPublicSettings.value = null
  }
}

// Edit slabs + minimum recharge on an existing card
const editingCardId = ref<string | null>(null)
const editSlabs = ref<{ min_amount: number | null, max_amount: number | null, price_per_sms: number | null }[]>([])
const editMinRecharge = ref<number | null>(null)
const editSubmitting = ref(false)
const editError = ref('')

function startEdit(card: RateCard) {
  editingCardId.value = card.id
  editError.value = ''
  editMinRecharge.value = card.min_recharge_amount
  editSlabs.value = card.slabs.map(s => ({ min_amount: s.min_amount, max_amount: s.max_amount, price_per_sms: s.price_per_sms }))
}

function cancelEdit() {
  editingCardId.value = null
  editSlabs.value = []
  editMinRecharge.value = null
  editError.value = ''
}

function addEditSlabRow() {
  editSlabs.value.push({ min_amount: null, max_amount: null, price_per_sms: null })
}

function removeEditSlabRow(index: number) {
  editSlabs.value.splice(index, 1)
}

async function onSaveSlabs(cardId: string) {
  editError.value = ''
  if (!editMinRecharge.value || editMinRecharge.value <= 0) {
    editError.value = 'Enter a minimum top-up amount greater than zero.'
    return
  }
  if (!editSlabs.value.length || editSlabs.value.some(s => !s.min_amount || !s.price_per_sms)) {
    editError.value = 'Fill in min amount and price for every slab.'
    return
  }
  editSubmitting.value = true
  try {
    await Promise.all([
      $api(`/v1/admin/rate-cards/${cardId}/slabs`, {
        method: 'PUT',
        body: { slabs: editSlabs.value.map(s => ({ min_amount: s.min_amount, max_amount: s.max_amount, price_per_sms: s.price_per_sms })) },
      }),
      $api(`/v1/admin/rate-cards/${cardId}/min-recharge`, {
        method: 'PUT',
        body: { min_recharge_amount: editMinRecharge.value },
      }),
    ])
    cancelEdit()
    await load()
  }
  catch (error: any) {
    editError.value = extractErrorMessage(error, 'Could not save these changes.')
  }
  finally {
    editSubmitting.value = false
  }
}

const deletingCard = ref<string | null>(null)
async function onDeleteCard(cardId: string) {
  deletingCard.value = cardId
  try {
    await $api(`/v1/admin/rate-cards/${cardId}`, { method: 'DELETE' })
    await load()
  }
  catch (error: any) {
    cardError.value = extractErrorMessage(error, 'Could not delete this rate card.')
  }
  finally {
    deletingCard.value = null
  }
}

// Assignment
const newAssignUserId = ref<string | null>(null)
const newAssignCardId = ref<string | null>(null)
const assignSubmitting = ref(false)
const assignError = ref('')

async function onAssign() {
  assignError.value = ''
  if (!newAssignUserId.value || !newAssignCardId.value) {
    assignError.value = 'Select both a user and a rate card.'
    return
  }
  assignSubmitting.value = true
  try {
    await $api('/v1/admin/rate-cards/assignments', {
      method: 'POST',
      body: { user_id: newAssignUserId.value, rate_card_id: newAssignCardId.value },
    })
    newAssignUserId.value = null
    newAssignCardId.value = null
    await load()
  }
  catch (error: any) {
    assignError.value = extractErrorMessage(error, 'Could not assign this rate card.')
  }
  finally {
    assignSubmitting.value = false
  }
}

const removingAssignment = ref<string | null>(null)
async function onRemoveAssignment(userId: string) {
  removingAssignment.value = userId
  try {
    await $api(`/v1/admin/rate-cards/assignments/${userId}`, { method: 'DELETE' })
    await load()
  }
  catch (error: any) {
    assignError.value = extractErrorMessage(error, 'Could not remove this assignment.')
  }
  finally {
    removingAssignment.value = null
  }
}

function slabLabel(slab: RateCardSlab): string {
  const range = slab.max_amount ? `₹${slab.min_amount.toLocaleString('en-IN')}–₹${slab.max_amount.toLocaleString('en-IN')}` : `₹${slab.min_amount.toLocaleString('en-IN')}+`
  return `${range} @ ₹${slab.price_per_sms.toFixed(2)}/SMS`
}

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Rate Cards
  </h1>
  <p class="text-medium-emphasis mb-6">
    One rate applies to every SMS regardless of type — the per-SMS price depends on how much a user recharges at once. The default card applies to everyone unless a user has a custom assignment.
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
    <VCard class="mb-6">
      <VCardText>
        <h6 class="text-h6 mb-4">
          Rate cards
        </h6>
        <VAlert
          v-if="cardError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ cardError }}
        </VAlert>

        <AppTextField
          v-model="cardSearch"
          placeholder="Search by rate card name"
          prepend-inner-icon="tabler-search"
          class="mb-4"
          style="max-inline-size: 320px;"
          clearable
        />

        <VRow class="mb-6">
          <VCol
            v-for="card in filteredCards"
            :key="card.id"
            cols="12"
            md="6"
          >
            <VCard variant="outlined">
              <VCardText>
                <div class="d-flex align-center justify-space-between mb-3">
                  <span class="text-h6">{{ card.name }}</span>
                  <div class="d-flex gap-2">
                    <VChip
                      size="small"
                      :color="card.channel === 'whatsapp' ? 'success' : 'info'"
                    >
                      {{ card.channel === 'whatsapp' ? 'WhatsApp' : 'SMS' }}
                    </VChip>
                    <VChip
                      v-if="card.is_default"
                      color="primary"
                      size="small"
                    >
                      Default
                    </VChip>
                  </div>
                </div>

                <template v-if="editingCardId === card.id">
                  <VAlert
                    v-if="editError"
                    type="error"
                    variant="tonal"
                    density="compact"
                    class="mb-3"
                  >
                    {{ editError }}
                  </VAlert>
                  <AppTextField
                    v-model.number="editMinRecharge"
                    type="number"
                    label="Minimum top-up (₹)"
                    density="compact"
                    class="mb-4"
                    style="max-inline-size: 200px;"
                  />
                  <div
                    v-for="(slab, index) in editSlabs"
                    :key="index"
                    class="d-flex gap-2 mb-3 align-center"
                  >
                    <AppTextField
                      v-model.number="slab.min_amount"
                      type="number"
                      label="Min ₹"
                      density="compact"
                      style="max-inline-size: 110px;"
                    />
                    <AppTextField
                      v-model.number="slab.max_amount"
                      type="number"
                      label="Max ₹"
                      density="compact"
                      style="max-inline-size: 110px;"
                    />
                    <AppTextField
                      v-model.number="slab.price_per_sms"
                      type="number"
                      step="0.01"
                      label="₹/SMS"
                      density="compact"
                      style="max-inline-size: 110px;"
                    />
                    <VBtn
                      icon
                      size="small"
                      variant="text"
                      color="error"
                      :disabled="editSlabs.length === 1"
                      @click="removeEditSlabRow(index)"
                    >
                      <VIcon icon="tabler-trash" />
                    </VBtn>
                  </div>
                  <div class="d-flex gap-3 mb-4">
                    <VBtn
                      variant="outlined"
                      size="small"
                      prepend-icon="tabler-plus"
                      @click="addEditSlabRow"
                    >
                      Add slab
                    </VBtn>
                  </div>
                  <div class="d-flex gap-3">
                    <VBtn
                      size="small"
                      :loading="editSubmitting"
                      @click="onSaveSlabs(card.id)"
                    >
                      Save
                    </VBtn>
                    <VBtn
                      size="small"
                      variant="outlined"
                      @click="cancelEdit"
                    >
                      Cancel
                    </VBtn>
                  </div>
                </template>

                <template v-else>
                  <p class="text-body-2 text-medium-emphasis mb-2">
                    Minimum top-up: ₹{{ card.min_recharge_amount.toLocaleString('en-IN') }}
                  </p>
                  <ul class="mb-4" style="list-style: none; padding-inline-start: 0;">
                    <li
                      v-for="slab in card.slabs"
                      :key="slab.id"
                      class="text-body-2 mb-1"
                    >
                      {{ slabLabel(slab) }}
                    </li>
                  </ul>
                  <div class="d-flex gap-3">
                    <VBtn
                      size="small"
                      variant="outlined"
                      @click="startEdit(card)"
                    >
                      Edit slabs
                    </VBtn>
                    <VBtn
                      v-if="!card.is_default && card.channel === 'sms'"
                      size="small"
                      variant="outlined"
                      :loading="settingDefault === card.id"
                      @click="onSetDefault(card.id)"
                    >
                      Make default
                    </VBtn>
                    <VBtn
                      v-if="!card.is_default"
                      size="small"
                      variant="text"
                      color="error"
                      :loading="deletingCard === card.id"
                      @click="onDeleteCard(card.id)"
                    >
                      Delete
                    </VBtn>
                  </div>

                  <VDivider class="my-4" />
                  <p class="text-caption text-medium-emphasis text-uppercase mb-2">
                    Public pricing page
                  </p>
                  <VAlert
                    v-if="publicSettingsError && savingPublicSettings === card.id"
                    type="error"
                    variant="tonal"
                    density="compact"
                    class="mb-3"
                  >
                    {{ publicSettingsError }}
                  </VAlert>
                  <VSwitch
                    :model-value="card.show_on_public_pricing"
                    :label="card.show_on_public_pricing ? 'Shown on public pricing page' : 'Hidden from public pricing page'"
                    density="compact"
                    hide-details
                    :loading="savingPublicSettings === card.id"
                    class="mb-2"
                    @update:model-value="(v: boolean | null) => onTogglePublicVisibility(card, !!v)"
                  />
                  <div class="d-flex gap-2 align-center">
                    <AppTextField
                      :model-value="taglineFor(card)"
                      label="Tagline shown under the plan name (optional)"
                      density="compact"
                      style="max-inline-size: 320px;"
                      @update:model-value="(v: string) => (taglineDraft[card.id] = v)"
                    />
                    <VBtn
                      size="small"
                      variant="outlined"
                      :loading="savingPublicSettings === card.id"
                      @click="onSaveTagline(card)"
                    >
                      Save
                    </VBtn>
                  </div>
                </template>
              </VCardText>
            </VCard>
          </VCol>
        </VRow>

        <h6 class="text-h6 mb-4">
          Create a new rate card
        </h6>
        <VForm @submit.prevent="onCreateCard">
          <div class="d-flex gap-4 mb-4">
            <AppTextField
              v-model="newCardName"
              label="Card name"
              placeholder="Enterprise Discount"
              style="max-inline-size: 300px;"
            />
            <VSelect
              v-model="newCardChannel"
              :items="CHANNEL_OPTIONS"
              label="Channel"
              style="max-inline-size: 180px;"
            />
            <AppTextField
              v-model.number="newMinRecharge"
              type="number"
              label="Minimum top-up (₹)"
              style="max-inline-size: 200px;"
            />
          </div>
          <VAlert
            v-if="newCardChannel === 'whatsapp'"
            type="info"
            variant="tonal"
            density="compact"
            class="mb-4"
          >
            WhatsApp cards are for the public pricing page only right now — WABA billing is
            still a flat wallet recharge, not priced by these slabs.
          </VAlert>
          <p class="text-body-2 text-medium-emphasis mb-3">
            Each slab's range is the rupee amount recharged — e.g. a ₹1–₹1000 top-up buys credits at that slab's price per SMS.
          </p>
          <div
            v-for="(slab, index) in newSlabs"
            :key="index"
            class="d-flex gap-3 mb-3 align-center"
          >
            <AppTextField
              v-model.number="slab.min_amount"
              type="number"
              label="Min amount (₹)"
              style="max-inline-size: 160px;"
            />
            <AppTextField
              v-model.number="slab.max_amount"
              type="number"
              label="Max amount (₹, blank = unbounded)"
              style="max-inline-size: 220px;"
            />
            <AppTextField
              v-model.number="slab.price_per_sms"
              type="number"
              step="0.01"
              label="Price per SMS (₹)"
              style="max-inline-size: 180px;"
            />
            <VBtn
              icon
              size="small"
              variant="text"
              color="error"
              :disabled="newSlabs.length === 1"
              @click="removeSlabRow(index)"
            >
              <VIcon icon="tabler-trash" />
            </VBtn>
          </div>
          <div class="d-flex gap-3">
            <VBtn
              variant="outlined"
              size="small"
              prepend-icon="tabler-plus"
              @click="addSlabRow"
            >
              Add slab
            </VBtn>
            <VBtn
              type="submit"
              :loading="cardSubmitting"
            >
              Create rate card
            </VBtn>
          </div>
        </VForm>
      </VCardText>
    </VCard>

    <VCard>
      <VCardText>
        <h6 class="text-h6 mb-4">
          Per-user rate card assignments
        </h6>
        <p class="text-body-2 text-medium-emphasis mb-4">
          Assign an individual user a different card than the default — useful for a discounted or enterprise pricing arrangement.
        </p>
        <VAlert
          v-if="assignError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ assignError }}
        </VAlert>
        <VForm
          class="mb-6"
          @submit.prevent="onAssign"
        >
          <VRow>
            <VCol
              cols="12"
              sm="5"
            >
              <VSelect
                v-model="newAssignUserId"
                :items="users"
                item-value="id"
                :item-title="(u: AdminUser) => `${u.full_name} (${u.email})`"
                label="User"
              />
            </VCol>
            <VCol
              cols="12"
              sm="4"
            >
              <VSelect
                v-model="newAssignCardId"
                :items="assignableCards"
                item-value="id"
                item-title="name"
                label="Rate card"
              />
            </VCol>
            <VCol
              cols="12"
              sm="3"
              class="d-flex align-end"
            >
              <VBtn
                type="submit"
                :loading="assignSubmitting"
              >
                Assign
              </VBtn>
            </VCol>
          </VRow>
        </VForm>

        <VTable>
          <thead>
            <tr>
              <th>User</th>
              <th>Rate card</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="assignment in assignments"
              :key="assignment.user_id"
            >
              <td>{{ assignment.user_email }}</td>
              <td>{{ assignment.rate_card_name }}</td>
              <td>
                <VBtn
                  size="small"
                  variant="text"
                  color="error"
                  :loading="removingAssignment === assignment.user_id"
                  @click="onRemoveAssignment(assignment.user_id)"
                >
                  Remove
                </VBtn>
              </td>
            </tr>
            <tr v-if="!assignments.length">
              <td
                colspan="3"
                class="text-center text-medium-emphasis"
              >
                No custom assignments — every user is on the default card.
              </td>
            </tr>
          </tbody>
        </VTable>
      </VCardText>
    </VCard>
  </template>
</template>
