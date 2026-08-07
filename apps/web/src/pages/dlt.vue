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

type Organization = { id: string, name: string, gstin: string | null, pan: string | null, industry: string | null, address: string | null }
type Entity = { id: string, organization_id: string, name: string, status: string }
type PeId = { id: string, value: string, operator: string, status: string }
type HeaderRow = { id: string, pe_id: string, header_id: string, value: string, status: string }
type TemplateRow = { id: string, pe_id: string, header_id: string, alias: string, dlt_template_id: string, body: string, category: string, status: string }
type ApiKeyRow = { id: string, active: boolean }

const CATEGORY_OPTIONS = [
  { value: 'transactional', title: 'Transactional' },
  { value: 'otp', title: 'OTP' },
  { value: 'service_explicit', title: 'Service — Explicit' },
  { value: 'service_implicit', title: 'Service — Implicit' },
  { value: 'promotional', title: 'Promotional' },
]
const CATEGORY_LABELS: Record<string, string> = Object.fromEntries(CATEGORY_OPTIONS.map(o => [o.value, o.title]))

const loadError = ref('')
const organizations = ref<Organization[]>([])
const entities = ref<Entity[]>([])
const peIds = ref<PeId[]>([])
const headers = ref<HeaderRow[]>([])
const templates = ref<TemplateRow[]>([])
const apiKeys = ref<ApiKeyRow[]>([])

const selectedOrgId = ref<string | null>(null)
const selectedEntityId = ref<string | null>(null)
const activeTab = ref('pe-ids')

const entitiesForOrg = computed(() => entities.value.filter(e => e.organization_id === selectedOrgId.value))

async function loadOrganizations() {
  organizations.value = await $api<Organization[]>('/v1/admin/organizations')
}

async function loadEntities() {
  entities.value = await $api<Entity[]>('/v1/admin/entities')
}

async function loadDltAssets() {
  if (!selectedEntityId.value) {
    peIds.value = []; headers.value = []; templates.value = []
    return
  }
  const [assets, keys] = await Promise.all([
    $api<{ pe_ids: PeId[], headers: HeaderRow[], templates: TemplateRow[] }>(`/v1/admin/entities/${selectedEntityId.value}/dlt-assets`),
    $api<ApiKeyRow[]>(`/v1/admin/entities/${selectedEntityId.value}/api-keys`),
  ])
  peIds.value = assets.pe_ids
  headers.value = assets.headers
  templates.value = assets.templates
  apiKeys.value = keys
}

async function load() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    await Promise.all([loadOrganizations(), loadEntities()])
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load organisations and entities.')
  }
}

watch(selectedOrgId, () => {
  selectedEntityId.value = null
})

watch(selectedEntityId, () => {
  loadDltAssets().catch((error: any) => {
    loadError.value = extractErrorMessage(error, 'Could not load DLT assets for this entity.')
  })
})

// Organization create
const newOrgName = ref('')
const orgSubmitting = ref(false)
const orgError = ref('')
async function onCreateOrg() {
  orgError.value = ''
  if (!newOrgName.value.trim()) {
    orgError.value = 'Enter an organisation name.'
    return
  }
  orgSubmitting.value = true
  try {
    const created = await $api<{ id: string, name: string }>(`/v1/admin/organizations?name=${encodeURIComponent(newOrgName.value.trim())}`, { method: 'POST' })
    newOrgName.value = ''
    await loadOrganizations()
    selectedOrgId.value = created.id
  }
  catch (error: any) {
    orgError.value = extractErrorMessage(error, 'Could not create organisation.')
  }
  finally {
    orgSubmitting.value = false
  }
}

// Entity create
const newEntityName = ref('')
const entitySubmitting = ref(false)
const entityError = ref('')

async function onCreateEntity() {
  entityError.value = ''
  if (!selectedOrgId.value) {
    entityError.value = 'Select an organisation first.'
    return
  }
  if (!newEntityName.value.trim()) {
    entityError.value = 'Enter an entity name.'
    return
  }
  entitySubmitting.value = true
  try {
    const created = await $api<{ id: string, name: string, status: string }>('/v1/admin/entities', {
      method: 'POST',
      body: { organization_id: selectedOrgId.value, name: newEntityName.value.trim() },
    })
    newEntityName.value = ''
    await loadEntities()
    selectedEntityId.value = created.id
  }
  catch (error: any) {
    entityError.value = extractErrorMessage(error, 'Could not create entity.')
  }
  finally {
    entitySubmitting.value = false
  }
}

// PE ID create
const newPeValue = ref('')
const newPeOperator = ref('')
const peSubmitting = ref(false)
const peError = ref('')
async function onCreatePe() {
  peError.value = ''
  if (!selectedEntityId.value)
    return
  if (!newPeValue.value.trim() || !newPeOperator.value.trim()) {
    peError.value = 'Enter both the PE ID value and operator.'
    return
  }
  peSubmitting.value = true
  try {
    await $api(`/v1/admin/entities/${selectedEntityId.value}/pe-ids`, {
      method: 'POST',
      body: { value: newPeValue.value.trim(), operator: newPeOperator.value.trim() },
    })
    newPeValue.value = ''; newPeOperator.value = ''
    await loadDltAssets()
  }
  catch (error: any) {
    peError.value = extractErrorMessage(error, 'Could not register this PE ID.')
  }
  finally {
    peSubmitting.value = false
  }
}

// Header create
const newHeaderPeId = ref<string | null>(null)
const newHeaderId = ref('')
const newHeaderValue = ref('')
const headerSubmitting = ref(false)
const headerError = ref('')
async function onCreateHeader() {
  headerError.value = ''
  if (!newHeaderPeId.value) {
    headerError.value = 'Select the PE ID this header belongs to.'
    return
  }
  if (!newHeaderId.value.trim() || !newHeaderValue.value.trim()) {
    headerError.value = 'Enter both the DLT header id and the sender header value.'
    return
  }
  headerSubmitting.value = true
  try {
    await $api(`/v1/admin/pe-ids/${newHeaderPeId.value}/headers`, {
      method: 'POST',
      body: { header_id: newHeaderId.value.trim(), value: newHeaderValue.value.trim() },
    })
    newHeaderId.value = ''; newHeaderValue.value = ''
    await loadDltAssets()
  }
  catch (error: any) {
    headerError.value = extractErrorMessage(error, 'Could not register this header.')
  }
  finally {
    headerSubmitting.value = false
  }
}

// Template create
const newTemplatePeId = ref<string | null>(null)
const newTemplateHeaderId = ref<string | null>(null)
const newTemplateAlias = ref('')
const newTemplateDltId = ref('')
const newTemplateBody = ref('')
const newTemplateCategory = ref('transactional')
const templateSubmitting = ref(false)
const templateError = ref('')
const headersForNewTemplatePe = computed(() => headers.value.filter(h => h.pe_id === newTemplatePeId.value))
watch(newTemplatePeId, () => { newTemplateHeaderId.value = null })
async function onCreateTemplate() {
  templateError.value = ''
  if (!selectedEntityId.value)
    return
  if (!newTemplatePeId.value || !newTemplateHeaderId.value) {
    templateError.value = 'Select the PE ID and header this template will send from.'
    return
  }
  if (!newTemplateAlias.value.trim() || !newTemplateDltId.value.trim() || !newTemplateBody.value.trim()) {
    templateError.value = 'Fill in the alias, DLT template id, and message body.'
    return
  }
  templateSubmitting.value = true
  try {
    await $api(`/v1/admin/entities/${selectedEntityId.value}/templates`, {
      method: 'POST',
      body: {
        pe_id: newTemplatePeId.value,
        header_id: newTemplateHeaderId.value,
        alias: newTemplateAlias.value.trim(),
        dlt_template_id: newTemplateDltId.value.trim(),
        body: newTemplateBody.value.trim(),
        category: newTemplateCategory.value,
      },
    })
    newTemplateAlias.value = ''; newTemplateDltId.value = ''; newTemplateBody.value = ''; newTemplateCategory.value = 'transactional'
    await loadDltAssets()
  }
  catch (error: any) {
    templateError.value = extractErrorMessage(error, 'Could not register this template.')
  }
  finally {
    templateSubmitting.value = false
  }
}

const deleteTemplateTarget = ref<TemplateRow | null>(null)
const deletingTemplate = ref(false)
const deleteTemplateError = ref('')

function onOpenDeleteTemplateDialog(template: TemplateRow) {
  deleteTemplateTarget.value = template
  deleteTemplateError.value = ''
}

function closeDeleteTemplateDialog() {
  deleteTemplateTarget.value = null
  deleteTemplateError.value = ''
}

async function onConfirmDeleteTemplate() {
  if (!deleteTemplateTarget.value || !selectedEntityId.value)
    return
  deleteTemplateError.value = ''
  deletingTemplate.value = true
  try {
    await $api(`/v1/admin/entities/${selectedEntityId.value}/templates/${deleteTemplateTarget.value.id}`, { method: 'DELETE' })
    closeDeleteTemplateDialog()
    await loadDltAssets()
  }
  catch (error: any) {
    deleteTemplateError.value = extractErrorMessage(error, 'Could not delete this template.')
  }
  finally {
    deletingTemplate.value = false
  }
}

// API key create
const keySubmitting = ref(false)
const keyError = ref('')
const revealedKey = ref('')
async function onCreateApiKey() {
  keyError.value = ''
  revealedKey.value = ''
  if (!selectedEntityId.value)
    return
  keySubmitting.value = true
  try {
    const result = await $api<{ api_key: string }>(`/v1/admin/entities/${selectedEntityId.value}/api-keys`, { method: 'POST' })
    revealedKey.value = result.api_key
    await loadDltAssets()
  }
  catch (error: any) {
    keyError.value = extractErrorMessage(error, 'Could not create an API key.')
  }
  finally {
    keySubmitting.value = false
  }
}

function peLabel(peId: string): string {
  const pe = peIds.value.find(p => p.id === peId)
  return pe ? `${pe.value} (${pe.operator})` : peId
}

function headerLabel(headerId: string): string {
  const header = headers.value.find(h => h.id === headerId)
  return header ? `${header.header_id} — ${header.value}` : headerId
}

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    DLT Hierarchy
  </h1>
  <p class="text-medium-emphasis mb-6">
    Provision organisations, entities, PE IDs, sender headers, and DLT-approved templates without touching the API directly.
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
    <VRow class="mb-2">
      <VCol
        cols="12"
        md="6"
      >
        <VCard>
          <VCardText>
            <h6 class="text-h6 mb-4">
              1. Organisation
            </h6>
            <VSelect
              v-model="selectedOrgId"
              :items="organizations"
              item-title="name"
              item-value="id"
              label="Select organisation"
              clearable
              class="mb-4"
            />
            <VAlert
              v-if="orgError"
              type="error"
              variant="tonal"
              density="compact"
              class="mb-4"
            >
              {{ orgError }}
            </VAlert>
            <VForm @submit.prevent="onCreateOrg">
              <div class="d-flex gap-3">
                <AppTextField
                  v-model="newOrgName"
                  label="New organisation name"
                  placeholder="Acme Retail Pvt Ltd"
                  class="flex-grow-1"
                />
                <VBtn
                  type="submit"
                  :loading="orgSubmitting"
                  class="align-self-end"
                >
                  Create
                </VBtn>
              </div>
            </VForm>
          </VCardText>
        </VCard>
      </VCol>

      <VCol
        cols="12"
        md="6"
      >
        <VCard>
          <VCardText>
            <h6 class="text-h6 mb-4">
              2. Entity
            </h6>
            <VSelect
              v-model="selectedEntityId"
              :items="entitiesForOrg"
              item-title="name"
              item-value="id"
              label="Select entity"
              :disabled="!selectedOrgId"
              clearable
              class="mb-4"
            />
            <VAlert
              v-if="entityError"
              type="error"
              variant="tonal"
              density="compact"
              class="mb-4"
            >
              {{ entityError }}
            </VAlert>
            <VForm @submit.prevent="onCreateEntity">
              <div class="d-flex gap-3">
                <AppTextField
                  v-model="newEntityName"
                  label="New entity name"
                  placeholder="Acme Retail — Mumbai"
                  :disabled="!selectedOrgId"
                  class="flex-grow-1"
                />
                <VBtn
                  type="submit"
                  :loading="entitySubmitting"
                  :disabled="!selectedOrgId"
                  class="align-self-end"
                >
                  Create
                </VBtn>
              </div>
            </VForm>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>

    <VAlert
      v-if="!selectedEntityId"
      type="info"
      variant="tonal"
    >
      Select or create an entity above to manage its PE IDs, headers, templates, and API keys.
    </VAlert>

    <VCard v-else>
      <VTabs v-model="activeTab">
        <VTab value="pe-ids">
          PE IDs
        </VTab>
        <VTab value="headers">
          Headers
        </VTab>
        <VTab value="templates">
          Templates
        </VTab>
        <VTab value="api-keys">
          API Keys
        </VTab>
      </VTabs>
      <VDivider />
      <VWindow v-model="activeTab">
        <!-- PE IDs -->
        <VWindowItem value="pe-ids">
          <VCardText>
            <VAlert
              v-if="peError"
              type="error"
              variant="tonal"
              density="compact"
              class="mb-4"
            >
              {{ peError }}
            </VAlert>
            <VForm
              class="mb-6"
              @submit.prevent="onCreatePe"
            >
              <VRow>
                <VCol
                  cols="12"
                  sm="4"
                >
                  <AppTextField
                    v-model="newPeValue"
                    label="PE ID"
                    placeholder="1701234567890123456"
                  />
                </VCol>
                <VCol
                  cols="12"
                  sm="4"
                >
                  <AppTextField
                    v-model="newPeOperator"
                    label="Operator"
                    placeholder="Jio / Airtel / Vi"
                  />
                </VCol>
                <VCol
                  cols="12"
                  sm="4"
                  class="d-flex align-end"
                >
                  <VBtn
                    type="submit"
                    :loading="peSubmitting"
                  >
                    Register PE ID
                  </VBtn>
                </VCol>
              </VRow>
            </VForm>
            <VTable>
              <thead>
                <tr>
                  <th>PE ID</th>
                  <th>Operator</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="pe in peIds"
                  :key="pe.id"
                >
                  <td>{{ pe.value }}</td>
                  <td>{{ pe.operator }}</td>
                  <td class="text-capitalize">
                    {{ pe.status }}
                  </td>
                </tr>
                <tr v-if="!peIds.length">
                  <td
                    colspan="3"
                    class="text-center text-medium-emphasis"
                  >
                    No PE IDs registered yet.
                  </td>
                </tr>
              </tbody>
            </VTable>
          </VCardText>
        </VWindowItem>

        <!-- Headers -->
        <VWindowItem value="headers">
          <VCardText>
            <VAlert
              v-if="!peIds.length"
              type="info"
              variant="tonal"
              class="mb-4"
            >
              Register a PE ID first — headers are registered against a PE ID.
            </VAlert>
            <template v-else>
              <VAlert
                v-if="headerError"
                type="error"
                variant="tonal"
                density="compact"
                class="mb-4"
              >
                {{ headerError }}
              </VAlert>
              <VForm
                class="mb-6"
                @submit.prevent="onCreateHeader"
              >
                <VRow>
                  <VCol
                    cols="12"
                    sm="3"
                  >
                    <VSelect
                      v-model="newHeaderPeId"
                      :items="peIds"
                      item-value="id"
                      :item-title="(pe: PeId) => `${pe.value} (${pe.operator})`"
                      label="PE ID"
                    />
                  </VCol>
                  <VCol
                    cols="12"
                    sm="3"
                  >
                    <AppTextField
                      v-model="newHeaderId"
                      label="DLT header id"
                      placeholder="1701234567890123456"
                    />
                  </VCol>
                  <VCol
                    cols="12"
                    sm="3"
                  >
                    <AppTextField
                      v-model="newHeaderValue"
                      label="Sender header"
                      placeholder="TEXTZI"
                    />
                  </VCol>
                  <VCol
                    cols="12"
                    sm="3"
                    class="d-flex align-end"
                  >
                    <VBtn
                      type="submit"
                      :loading="headerSubmitting"
                    >
                      Register header
                    </VBtn>
                  </VCol>
                </VRow>
              </VForm>
              <VTable>
                <thead>
                  <tr>
                    <th>Sender header</th>
                    <th>DLT header id</th>
                    <th>PE ID</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="header in headers"
                    :key="header.id"
                  >
                    <td class="font-weight-medium">
                      {{ header.value }}
                    </td>
                    <td>{{ header.header_id }}</td>
                    <td>{{ peLabel(header.pe_id) }}</td>
                    <td class="text-capitalize">
                      {{ header.status }}
                    </td>
                  </tr>
                  <tr v-if="!headers.length">
                    <td
                      colspan="4"
                      class="text-center text-medium-emphasis"
                    >
                      No headers registered yet.
                    </td>
                  </tr>
                </tbody>
              </VTable>
            </template>
          </VCardText>
        </VWindowItem>

        <!-- Templates -->
        <VWindowItem value="templates">
          <VCardText>
            <VAlert
              v-if="!headers.length"
              type="info"
              variant="tonal"
              class="mb-4"
            >
              Register a PE ID and a header first — templates are registered against a PE ID + header pair.
            </VAlert>
            <template v-else>
              <VAlert
                v-if="templateError"
                type="error"
                variant="tonal"
                density="compact"
                class="mb-4"
              >
                {{ templateError }}
              </VAlert>
              <VForm
                class="mb-6"
                @submit.prevent="onCreateTemplate"
              >
                <VRow>
                  <VCol
                    cols="12"
                    sm="3"
                  >
                    <VSelect
                      v-model="newTemplatePeId"
                      :items="peIds"
                      item-value="id"
                      :item-title="(pe: PeId) => `${pe.value} (${pe.operator})`"
                      label="PE ID"
                    />
                  </VCol>
                  <VCol
                    cols="12"
                    sm="3"
                  >
                    <VSelect
                      v-model="newTemplateHeaderId"
                      :items="headersForNewTemplatePe"
                      item-value="id"
                      :item-title="(header: HeaderRow) => `${header.header_id} — ${header.value}`"
                      label="Header"
                      :disabled="!newTemplatePeId"
                    />
                  </VCol>
                  <VCol
                    cols="12"
                    sm="3"
                  >
                    <AppTextField
                      v-model="newTemplateAlias"
                      label="Alias"
                      placeholder="order_confirmation"
                    />
                  </VCol>
                  <VCol
                    cols="12"
                    sm="3"
                  >
                    <AppTextField
                      v-model="newTemplateDltId"
                      label="DLT template id"
                      placeholder="1707123456789012345"
                    />
                  </VCol>
                  <VCol
                    cols="12"
                    sm="4"
                  >
                    <VSelect
                      v-model="newTemplateCategory"
                      :items="CATEGORY_OPTIONS"
                      item-title="title"
                      item-value="value"
                      label="Message category"
                      hint="Determines the per-message rate charged — see Rate Slabs."
                      persistent-hint
                    />
                  </VCol>
                  <VCol cols="12">
                    <AppTextarea
                      v-model="newTemplateBody"
                      label="Approved message body"
                      placeholder="Your order {{order_id}} has been confirmed."
                      hint="Use {{variable_name}} for parts that change per message — must match the DLT-approved template wording exactly."
                      persistent-hint
                      rows="2"
                    />
                  </VCol>
                  <VCol cols="12">
                    <VBtn
                      type="submit"
                      :loading="templateSubmitting"
                    >
                      Register template
                    </VBtn>
                  </VCol>
                </VRow>
              </VForm>
              <VTable>
                <thead>
                  <tr>
                    <th>Alias</th>
                    <th>DLT template id</th>
                    <th>PE ID</th>
                    <th>Header</th>
                    <th>Category</th>
                    <th>Status</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="template in templates"
                    :key="template.id"
                  >
                    <td class="font-weight-medium">
                      {{ template.alias }}
                    </td>
                    <td>{{ template.dlt_template_id }}</td>
                    <td>{{ peLabel(template.pe_id) }}</td>
                    <td>{{ headerLabel(template.header_id) }}</td>
                    <td>{{ CATEGORY_LABELS[template.category] ?? template.category }}</td>
                    <td class="text-capitalize">
                      {{ template.status }}
                    </td>
                    <td>
                      <VBtn
                        size="small"
                        variant="text"
                        color="error"
                        @click="onOpenDeleteTemplateDialog(template)"
                      >
                        Delete
                      </VBtn>
                    </td>
                  </tr>
                  <tr v-if="!templates.length">
                    <td
                      colspan="7"
                      class="text-center text-medium-emphasis"
                    >
                      No templates registered yet.
                    </td>
                  </tr>
                </tbody>
              </VTable>
            </template>
          </VCardText>
        </VWindowItem>

        <!-- API Keys -->
        <VWindowItem value="api-keys">
          <VCardText>
            <VAlert
              v-if="keyError"
              type="error"
              variant="tonal"
              density="compact"
              class="mb-4"
            >
              {{ keyError }}
            </VAlert>
            <VAlert
              v-if="revealedKey"
              type="success"
              variant="tonal"
              density="compact"
              class="mb-4"
            >
              <div class="mb-1">
                New API key — copy it now, it will not be shown again:
              </div>
              <code>{{ revealedKey }}</code>
            </VAlert>
            <VBtn
              class="mb-6"
              :loading="keySubmitting"
              @click="onCreateApiKey"
            >
              Generate new API key
            </VBtn>
            <VTable>
              <thead>
                <tr>
                  <th>Key id</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="key in apiKeys"
                  :key="key.id"
                >
                  <td>
                    <code>{{ key.id }}</code>
                  </td>
                  <td>
                    <VChip
                      :color="key.active ? 'success' : 'error'"
                      size="small"
                    >
                      {{ key.active ? 'Active' : 'Revoked' }}
                    </VChip>
                  </td>
                </tr>
                <tr v-if="!apiKeys.length">
                  <td
                    colspan="2"
                    class="text-center text-medium-emphasis"
                  >
                    No API keys created yet.
                  </td>
                </tr>
              </tbody>
            </VTable>
          </VCardText>
        </VWindowItem>
      </VWindow>
    </VCard>
  </template>

  <VDialog
    :model-value="!!deleteTemplateTarget"
    max-width="480"
    @update:model-value="value => { if (!value) closeDeleteTemplateDialog() }"
  >
    <VCard v-if="deleteTemplateTarget">
      <VCardTitle class="text-error">
        Delete this template permanently
      </VCardTitle>
      <VCardText>
        <VAlert type="error" variant="tonal" density="compact" class="mb-4">
          This permanently deletes <strong>{{ deleteTemplateTarget.alias }}</strong>. There is no
          undo. Only allowed while this template has never been used to send a message -- if it
          has, the delete is blocked to keep that message history intact.
        </VAlert>
        <VAlert v-if="deleteTemplateError" type="error" variant="tonal" density="compact">
          {{ deleteTemplateError }}
        </VAlert>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="tonal" @click="closeDeleteTemplateDialog">
          Cancel
        </VBtn>
        <VBtn
          color="error"
          :loading="deletingTemplate"
          @click="onConfirmDeleteTemplate"
        >
          Delete Permanently
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
