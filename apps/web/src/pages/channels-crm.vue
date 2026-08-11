<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type CrmSettings = {
  pipeline_stages: string[]
  notify_email: boolean
  notify_sms: boolean
  notify_whatsapp: boolean
  logo_url: string | null
  brand_color: string | null
}

const activeTab = ref<'pipeline' | 'notifications' | 'branding' | 'company' | 'scoring' | 'territories' | 'targets' | 'team' | 'webform' | 'billing'>('pipeline')

const settings = ref<CrmSettings | null>(null)
const loading = ref(false)
const loadError = ref('')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    settings.value = await $api<CrmSettings>('/v1/crm/settings')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load CRM settings.')
  }
  finally {
    loading.value = false
  }
}

// --- Pipeline stages ---

const stagesForm = ref<string[]>([])
const stagesSaving = ref(false)
const stagesError = ref('')
const stagesSaved = ref(false)

watch(settings, value => {
  if (value)
    stagesForm.value = [...value.pipeline_stages]
}, { immediate: true })

function addStage() {
  stagesForm.value.push('')
}

function removeStage(i: number) {
  stagesForm.value.splice(i, 1)
}

async function saveStages() {
  stagesSaving.value = true
  stagesError.value = ''
  stagesSaved.value = false
  try {
    settings.value = await $api<CrmSettings>('/v1/crm/settings/pipeline-stages', {
      method: 'PUT',
      body: { stages: stagesForm.value.map(s => s.trim()).filter(Boolean) },
    })
    stagesSaved.value = true
  }
  catch (error: any) {
    stagesError.value = extractErrorMessage(error, 'Could not save pipeline stages.')
  }
  finally {
    stagesSaving.value = false
  }
}

// --- Notifications ---

const notifyForm = ref({ notify_email: false, notify_sms: false, notify_whatsapp: false, brand_color: '' })
const notifySaving = ref(false)
const notifyError = ref('')
const notifySaved = ref(false)

watch(settings, value => {
  if (value)
    notifyForm.value = { notify_email: value.notify_email, notify_sms: value.notify_sms, notify_whatsapp: value.notify_whatsapp, brand_color: value.brand_color || '' }
}, { immediate: true })

async function saveNotifications() {
  notifySaving.value = true
  notifyError.value = ''
  notifySaved.value = false
  try {
    settings.value = await $api<CrmSettings>('/v1/crm/settings', {
      method: 'PUT',
      body: { notify_email: notifyForm.value.notify_email, notify_sms: notifyForm.value.notify_sms, notify_whatsapp: notifyForm.value.notify_whatsapp, brand_color: settings.value?.brand_color || null },
    })
    notifySaved.value = true
  }
  catch (error: any) {
    notifyError.value = extractErrorMessage(error, 'Could not save notification settings.')
  }
  finally {
    notifySaving.value = false
  }
}

// --- Branding ---

const brandColorForm = ref('')
const brandSaving = ref(false)
const brandError = ref('')
const brandSaved = ref(false)
const logoUploading = ref(false)
const logoError = ref('')

watch(settings, value => {
  if (value)
    brandColorForm.value = value.brand_color || ''
}, { immediate: true })

async function saveBrandColor() {
  brandSaving.value = true
  brandError.value = ''
  brandSaved.value = false
  try {
    settings.value = await $api<CrmSettings>('/v1/crm/settings', {
      method: 'PUT',
      body: {
        notify_email: settings.value?.notify_email || false,
        notify_sms: settings.value?.notify_sms || false,
        notify_whatsapp: settings.value?.notify_whatsapp || false,
        brand_color: brandColorForm.value || null,
      },
    })
    brandSaved.value = true
  }
  catch (error: any) {
    brandError.value = extractErrorMessage(error, 'Could not save brand color.')
  }
  finally {
    brandSaving.value = false
  }
}

async function uploadLogo(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file)
    return
  logoUploading.value = true
  logoError.value = ''
  try {
    const formData = new FormData()
    formData.append('logo', file)
    settings.value = await $api<CrmSettings>('/v1/crm/settings/logo', { method: 'POST', body: formData })
  }
  catch (error: any) {
    logoError.value = extractErrorMessage(error, 'Could not upload this logo.')
  }
  finally {
    logoUploading.value = false
  }
}

// --- Scoring rules ---

type ScoringRule = { id: string, name: string, condition_type: 'has_label' | 'custom_field_set' | 'source', condition_value: string, points: number, active: boolean }

const scoringRules = ref<ScoringRule[]>([])
const scoringDialog = ref(false)
const scoringForm = reactive({ name: '', condition_type: 'source' as ScoringRule['condition_type'], condition_value: '', points: 10 })
const scoringSaving = ref(false)
const scoringError = ref('')

function openScoringDialog() {
  scoringForm.name = ''
  scoringForm.condition_type = 'source'
  scoringForm.condition_value = ''
  scoringForm.points = 10
  scoringError.value = ''
  scoringDialog.value = true
}

async function saveScoringRule() {
  if (!scoringForm.name.trim() || !scoringForm.condition_value.trim())
    return
  scoringSaving.value = true
  scoringError.value = ''
  try {
    const created = await $api<ScoringRule>('/v1/crm/scoring-rules', { method: 'POST', body: { ...scoringForm, name: scoringForm.name.trim(), active: true } })
    scoringRules.value.push(created)
    scoringDialog.value = false
  }
  catch (error: any) {
    scoringError.value = extractErrorMessage(error, 'Could not create this scoring rule.')
  }
  finally {
    scoringSaving.value = false
  }
}

async function deleteScoringRule(rule: ScoringRule) {
  try {
    await $api(`/v1/crm/scoring-rules/${rule.id}`, { method: 'DELETE' })
    scoringRules.value = scoringRules.value.filter(r => r.id !== rule.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this scoring rule.')
  }
}

// --- Territories ---

type AssignableUser = { id: string, full_name: string, email: string }
type Territory = { id: string, name: string, pincodes: string[], owner_user_id: string | null }

const territories = ref<Territory[]>([])
const assignableUsers = ref<AssignableUser[]>([])
const territoryDialog = ref(false)
const territoryForm = reactive({ name: '', pincodesText: '', owner_user_id: null as string | null })
const territorySaving = ref(false)
const territoryError = ref('')

function openTerritoryDialog() {
  territoryForm.name = ''
  territoryForm.pincodesText = ''
  territoryForm.owner_user_id = null
  territoryError.value = ''
  territoryDialog.value = true
}

async function saveTerritory() {
  const pincodes = territoryForm.pincodesText.split(',').map(p => p.trim()).filter(Boolean)
  if (!territoryForm.name.trim() || !pincodes.length)
    return
  territorySaving.value = true
  territoryError.value = ''
  try {
    const created = await $api<Territory>('/v1/crm/territories', {
      method: 'POST',
      body: { name: territoryForm.name.trim(), pincodes, owner_user_id: territoryForm.owner_user_id },
    })
    territories.value.push(created)
    territoryDialog.value = false
  }
  catch (error: any) {
    territoryError.value = extractErrorMessage(error, 'Could not create this territory.')
  }
  finally {
    territorySaving.value = false
  }
}

async function deleteTerritory(territory: Territory) {
  try {
    await $api(`/v1/crm/territories/${territory.id}`, { method: 'DELETE' })
    territories.value = territories.value.filter(t => t.id !== territory.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this territory.')
  }
}

function ownerName(id: string | null) {
  return assignableUsers.value.find(u => u.id === id)?.full_name || 'Unassigned'
}

// --- Sales targets ---

type SalesTarget = { id: string, user_id: string, period_start: string, period_end: string, target_value: number, actual_value: number }

const salesTargets = ref<SalesTarget[]>([])
const targetDialog = ref(false)
const targetForm = reactive({ user_id: '', period_start: '', period_end: '', target_value: 0 })
const targetSaving = ref(false)
const targetError = ref('')

function openTargetDialog() {
  targetForm.user_id = ''
  targetForm.period_start = ''
  targetForm.period_end = ''
  targetForm.target_value = 0
  targetError.value = ''
  targetDialog.value = true
}

async function saveTarget() {
  if (!targetForm.user_id || !targetForm.period_start || !targetForm.period_end || !targetForm.target_value)
    return
  targetSaving.value = true
  targetError.value = ''
  try {
    const created = await $api<SalesTarget>('/v1/crm/sales-targets', {
      method: 'POST',
      body: {
        user_id: targetForm.user_id,
        period_start: new Date(targetForm.period_start).toISOString(),
        period_end: new Date(targetForm.period_end).toISOString(),
        target_value: targetForm.target_value,
      },
    })
    salesTargets.value.push(created)
    targetDialog.value = false
  }
  catch (error: any) {
    targetError.value = extractErrorMessage(error, 'Could not create this sales target.')
  }
  finally {
    targetSaving.value = false
  }
}

function inr(value: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value)
}

async function deleteTarget(target: SalesTarget) {
  try {
    await $api(`/v1/crm/sales-targets/${target.id}`, { method: 'DELETE' })
    salesTargets.value = salesTargets.value.filter(t => t.id !== target.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this sales target.')
  }
}

// --- Team / manager hierarchy ---

type TeamMember = { id: string, email: string, full_name: string, role: string, status: string, manager_id: string | null }

const teamMembers = ref<TeamMember[]>([])
const managerSaving = ref<string | null>(null)

async function setManager(member: TeamMember, managerId: string | null) {
  managerSaving.value = member.id
  try {
    await $api(`/v1/crm/users/${member.id}/manager`, { method: 'PUT', body: { manager_id: managerId } })
    member.manager_id = managerId
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this teammate\'s manager.')
  }
  finally {
    managerSaving.value = null
  }
}

async function loadExtras() {
  try {
    const [scoringResult, territoryResult, userResult, targetResult, teamResult] = await Promise.all([
      $api<ScoringRule[]>('/v1/crm/scoring-rules'),
      $api<Territory[]>('/v1/crm/territories'),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
      $api<SalesTarget[]>('/v1/crm/sales-targets'),
      $api<TeamMember[]>('/v1/team/members'),
    ])
    scoringRules.value = scoringResult
    territories.value = territoryResult
    assignableUsers.value = userResult
    salesTargets.value = targetResult
    teamMembers.value = teamResult
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load some CRM settings.')
  }
}

// --- Web lead-capture form ---

type Pipeline = { id: string, name: string }
type WebForm = { enabled: boolean, fields: string[], success_message: string, target_pipeline_id: string | null, embed_snippet: string }

const AVAILABLE_FIELDS = ['name', 'email', 'phone', 'message']
const pipelines = ref<Pipeline[]>([])
const webForm = ref<WebForm | null>(null)
const webFormSaving = ref(false)
const webFormError = ref('')
const webFormSaved = ref(false)
const webFormCopied = ref(false)

async function loadWebForm() {
  try {
    const [formResult, pipelineResult] = await Promise.all([
      $api<WebForm>('/v1/crm/web-form'),
      $api<Pipeline[]>('/v1/crm/pipelines'),
    ])
    webForm.value = formResult
    pipelines.value = pipelineResult
  }
  catch (error: any) {
    webFormError.value = extractErrorMessage(error, 'Could not load the web form settings.')
  }
}

function toggleField(field: string) {
  if (!webForm.value)
    return
  if (webForm.value.fields.includes(field))
    webForm.value.fields = webForm.value.fields.filter(f => f !== field)
  else
    webForm.value.fields = [...webForm.value.fields, field]
}

async function saveWebForm() {
  if (!webForm.value)
    return
  webFormSaving.value = true
  webFormError.value = ''
  webFormSaved.value = false
  try {
    webForm.value = await $api<WebForm>('/v1/crm/web-form', {
      method: 'PUT',
      body: {
        enabled: webForm.value.enabled,
        fields: webForm.value.fields,
        success_message: webForm.value.success_message,
        target_pipeline_id: webForm.value.target_pipeline_id,
      },
    })
    webFormSaved.value = true
  }
  catch (error: any) {
    webFormError.value = extractErrorMessage(error, 'Could not save the web form settings.')
  }
  finally {
    webFormSaving.value = false
  }
}

async function copyEmbedSnippet() {
  if (!webForm.value)
    return
  await navigator.clipboard.writeText(webForm.value.embed_snippet)
  webFormCopied.value = true
  setTimeout(() => { webFormCopied.value = false }, 2000)
}

onMounted(() => {
  load()
  loadExtras()
  loadWebForm()
})
</script>

<template>
  <h1 class="text-h4 mb-1">
    Manage CRM
  </h1>
  <p class="text-medium-emphasis mb-6">
    Settings for how your CRM works -- sales pipeline stages, notification channels, and branding.
    Tickets, Leads, and Customers themselves live in the CRM section of the main menu.
  </p>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>

  <VTabs v-model="activeTab" class="mb-6">
    <VTab value="pipeline">
      Pipeline
    </VTab>
    <VTab value="notifications">
      Notifications
    </VTab>
    <VTab value="branding">
      Branding
    </VTab>
    <VTab value="company">
      Company
    </VTab>
    <VTab value="scoring">
      Lead Scoring
    </VTab>
    <VTab value="territories">
      Territories
    </VTab>
    <VTab value="targets">
      Sales Targets
    </VTab>
    <VTab value="team">
      Team
    </VTab>
    <VTab value="webform">
      Web Form
    </VTab>
    <VTab value="billing">
      Billing
    </VTab>
  </VTabs>

  <VWindow v-model="activeTab">
    <VWindowItem value="pipeline">
      <VCard max-width="560">
        <VCardText>
          <h2 class="text-h6 mb-1">
            Lead pipeline stages
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            The stages a lead moves through, in order. Used in the "Create lead" form and the
            Leads list.
          </p>
          <VAlert v-if="stagesError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ stagesError }}
          </VAlert>
          <VAlert v-if="stagesSaved" type="success" variant="tonal" density="compact" class="mb-3">
            Saved.
          </VAlert>
          <div v-for="(stage, i) in stagesForm" :key="i" class="d-flex align-center ga-2 mb-2">
            <AppTextField v-model="stagesForm[i]" density="compact" hide-details />
            <VBtn v-if="stagesForm.length > 1" size="small" variant="text" icon="tabler-trash" @click="removeStage(i)" />
          </div>
          <VBtn size="small" variant="text" prepend-icon="tabler-plus" class="mb-4" @click="addStage">
            Add stage
          </VBtn>
          <div>
            <VBtn :loading="stagesSaving" @click="saveStages">
              Save
            </VBtn>
          </div>
        </VCardText>
      </VCard>
    </VWindowItem>

    <VWindowItem value="notifications">
      <VCard max-width="560">
        <VCardText>
          <h2 class="text-h6 mb-1">
            Notification channels
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            When a lead, customer, or ticket event happens, which channels should notify the
            owner. Takes effect once cross-channel automation is enabled for your account.
          </p>
          <VAlert v-if="notifyError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ notifyError }}
          </VAlert>
          <VAlert v-if="notifySaved" type="success" variant="tonal" density="compact" class="mb-3">
            Saved.
          </VAlert>
          <VSwitch v-model="notifyForm.notify_email" label="Email" density="compact" />
          <VSwitch v-model="notifyForm.notify_sms" label="SMS" density="compact" />
          <VSwitch v-model="notifyForm.notify_whatsapp" label="WhatsApp" density="compact" class="mb-4" />
          <div>
            <VBtn :loading="notifySaving" @click="saveNotifications">
              Save
            </VBtn>
          </div>
        </VCardText>
      </VCard>
    </VWindowItem>

    <VWindowItem value="branding">
      <VCard max-width="560">
        <VCardText>
          <h2 class="text-h6 mb-1">
            Branding
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Your logo and brand color, used on CRM-facing customer communications.
          </p>
          <VAlert v-if="logoError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ logoError }}
          </VAlert>
          <p class="text-body-2 mb-2">
            Logo: <strong>{{ settings?.logo_url ? 'Uploaded' : 'Not uploaded' }}</strong>
          </p>
          <VBtn size="small" variant="tonal" :loading="logoUploading" prepend-icon="tabler-upload" class="mb-4">
            {{ settings?.logo_url ? 'Replace logo' : 'Upload logo' }}
            <input type="file" accept="image/png,image/jpeg" class="file-input-overlay" @change="uploadLogo">
          </VBtn>

          <VAlert v-if="brandError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ brandError }}
          </VAlert>
          <VAlert v-if="brandSaved" type="success" variant="tonal" density="compact" class="mb-3">
            Saved.
          </VAlert>
          <AppTextField v-model="brandColorForm" label="Brand color (hex)" placeholder="#FF5722" class="mb-4" />
          <div>
            <VBtn :loading="brandSaving" @click="saveBrandColor">
              Save
            </VBtn>
          </div>
        </VCardText>
      </VCard>
    </VWindowItem>

    <VWindowItem value="company">
      <VCard max-width="560">
        <VCardText>
          <h2 class="text-h6 mb-1">
            Company details
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Your organization's GST, PAN, and address are managed from your account profile, not
            here, so there's one place they're ever edited.
          </p>
          <VBtn :to="{ name: 'profile' }" variant="tonal" prepend-icon="tabler-building">
            Go to company profile
          </VBtn>
        </VCardText>
      </VCard>
    </VWindowItem>

    <VWindowItem value="scoring">
      <div class="d-flex justify-end mb-3">
        <VBtn color="primary" prepend-icon="tabler-plus" @click="openScoringDialog">
          New rule
        </VBtn>
      </div>
      <VCard>
        <VTable>
          <thead>
            <tr>
              <th>Name</th>
              <th>Condition</th>
              <th>Points</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="rule in scoringRules" :key="rule.id">
              <td>{{ rule.name }}</td>
              <td>{{ rule.condition_type }} = {{ rule.condition_value }}</td>
              <td>{{ rule.points }}</td>
              <td class="text-end">
                <VBtn icon="tabler-trash" size="small" variant="text" @click="deleteScoringRule(rule)" />
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!scoringRules.length" class="text-medium-emphasis text-center pa-6">
          No scoring rules yet — every lead scores 0.
        </p>
      </VCard>
    </VWindowItem>

    <VWindowItem value="territories">
      <div class="d-flex justify-end mb-3">
        <VBtn color="primary" prepend-icon="tabler-plus" @click="openTerritoryDialog">
          New territory
        </VBtn>
      </div>
      <VCard>
        <VTable>
          <thead>
            <tr>
              <th>Name</th>
              <th>Pincodes</th>
              <th>Owner</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="territory in territories" :key="territory.id">
              <td>{{ territory.name }}</td>
              <td>{{ territory.pincodes.join(', ') }}</td>
              <td>{{ ownerName(territory.owner_user_id) }}</td>
              <td class="text-end">
                <VBtn icon="tabler-trash" size="small" variant="text" @click="deleteTerritory(territory)" />
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!territories.length" class="text-medium-emphasis text-center pa-6">
          No territories yet.
        </p>
      </VCard>
    </VWindowItem>

    <VWindowItem value="targets">
      <div class="d-flex justify-end mb-3">
        <VBtn color="primary" prepend-icon="tabler-plus" @click="openTargetDialog">
          New target
        </VBtn>
      </div>
      <VCard>
        <VTable>
          <thead>
            <tr>
              <th>User</th>
              <th>Period</th>
              <th>Target</th>
              <th>Actual</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="target in salesTargets" :key="target.id">
              <td>{{ ownerName(target.user_id) }}</td>
              <td>{{ new Date(target.period_start).toLocaleDateString() }} – {{ new Date(target.period_end).toLocaleDateString() }}</td>
              <td>{{ inr(target.target_value) }}</td>
              <td :class="target.actual_value >= target.target_value ? 'text-success' : ''">
                {{ inr(target.actual_value) }}
              </td>
              <td class="text-end">
                <VBtn icon="tabler-trash" size="small" variant="text" @click="deleteTarget(target)" />
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!salesTargets.length" class="text-medium-emphasis text-center pa-6">
          No sales targets yet.
        </p>
      </VCard>
    </VWindowItem>

    <VWindowItem value="team">
      <VCard>
        <VCardText>
          <h2 class="text-h6 mb-1">
            Manager hierarchy
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Who each teammate reports to — used for sales-target roll-ups. One level only.
          </p>
        </VCardText>
        <VTable>
          <thead>
            <tr>
              <th>Name</th>
              <th>Role</th>
              <th>Manager</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="member in teamMembers" :key="member.id">
              <td>{{ member.full_name }}</td>
              <td>{{ member.role }}</td>
              <td>
                <VSelect
                  :model-value="member.manager_id"
                  :items="[{ title: 'None', value: null }, ...teamMembers.filter(m => m.id !== member.id).map(m => ({ title: m.full_name, value: m.id }))]"
                  density="compact" hide-details variant="plain" style="max-width: 200px;"
                  :loading="managerSaving === member.id"
                  @update:model-value="(v: string | null) => setManager(member, v)"
                />
              </td>
            </tr>
          </tbody>
        </VTable>
      </VCard>
    </VWindowItem>

    <VWindowItem value="webform">
      <VCard max-width="640">
        <VCardText>
          <h2 class="text-h6 mb-1">
            Web lead-capture form
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            An embeddable form for your website — submissions become leads here automatically.
          </p>
          <VAlert v-if="webFormError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ webFormError }}
          </VAlert>
          <VAlert v-if="webFormSaved" type="success" variant="tonal" density="compact" class="mb-3">
            Saved.
          </VAlert>
          <template v-if="webForm">
            <VSwitch v-model="webForm.enabled" label="Enabled" density="compact" class="mb-2" />
            <p class="text-body-2 mb-2">
              Fields to collect
            </p>
            <div class="d-flex flex-wrap ga-2 mb-4">
              <VChip
                v-for="field in AVAILABLE_FIELDS" :key="field" size="small"
                :variant="webForm.fields.includes(field) ? 'flat' : 'outlined'"
                :color="webForm.fields.includes(field) ? 'primary' : undefined"
                class="text-capitalize" @click="toggleField(field)"
              >
                {{ field }}
              </VChip>
            </div>
            <VTextarea v-model="webForm.success_message" label="Success message" rows="2" density="compact" class="mb-4" />
            <VSelect
              v-model="webForm.target_pipeline_id" label="Target pipeline" density="compact" clearable class="mb-4"
              :items="pipelines.map(p => ({ title: p.name, value: p.id }))"
              placeholder="Default pipeline"
            />
            <div class="mb-4">
              <VBtn :loading="webFormSaving" @click="saveWebForm">
                Save
              </VBtn>
            </div>
            <p class="text-body-2 mb-2">
              Embed snippet
            </p>
            <VTextarea :model-value="webForm.embed_snippet" readonly rows="2" density="compact" class="mb-2" />
            <VBtn size="small" variant="tonal" prepend-icon="tabler-copy" @click="copyEmbedSnippet">
              {{ webFormCopied ? 'Copied' : 'Copy snippet' }}
            </VBtn>
          </template>
        </VCardText>
      </VCard>
    </VWindowItem>

    <VWindowItem value="billing">
      <ChannelBillingPanel channel="crm" />
    </VWindowItem>
  </VWindow>

  <VDialog v-model="scoringDialog" max-width="420">
    <VCard title="New scoring rule">
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="scoringError" type="error" variant="tonal" density="compact">
          {{ scoringError }}
        </VAlert>
        <VTextField v-model="scoringForm.name" label="Rule name" density="compact" />
        <VSelect
          v-model="scoringForm.condition_type" label="Condition" density="compact"
          :items="[{ title: 'Has label', value: 'has_label' }, { title: 'Custom field set', value: 'custom_field_set' }, { title: 'Source', value: 'source' }]"
        />
        <VTextField v-model="scoringForm.condition_value" label="Value (label name / field key / source)" density="compact" />
        <VTextField v-model.number="scoringForm.points" type="number" label="Points" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="scoringDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="scoringSaving" :disabled="!scoringForm.name.trim() || !scoringForm.condition_value.trim()" @click="saveScoringRule">
          Create
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="territoryDialog" max-width="420">
    <VCard title="New territory">
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="territoryError" type="error" variant="tonal" density="compact">
          {{ territoryError }}
        </VAlert>
        <VTextField v-model="territoryForm.name" label="Territory name" density="compact" />
        <VTextField v-model="territoryForm.pincodesText" label="Pincodes (comma-separated)" density="compact" />
        <VSelect
          v-model="territoryForm.owner_user_id" label="Owner" density="compact" clearable
          :items="assignableUsers.map(u => ({ title: u.full_name, value: u.id }))"
        />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="territoryDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="territorySaving" :disabled="!territoryForm.name.trim() || !territoryForm.pincodesText.trim()" @click="saveTerritory">
          Create
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="targetDialog" max-width="420">
    <VCard title="New sales target">
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="targetError" type="error" variant="tonal" density="compact">
          {{ targetError }}
        </VAlert>
        <VSelect
          v-model="targetForm.user_id" label="User" density="compact"
          :items="assignableUsers.map(u => ({ title: u.full_name, value: u.id }))"
        />
        <VTextField v-model="targetForm.period_start" label="Period start" type="date" density="compact" />
        <VTextField v-model="targetForm.period_end" label="Period end" type="date" density="compact" />
        <VTextField v-model.number="targetForm.target_value" label="Target value (INR)" type="number" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="targetDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="targetSaving" :disabled="!targetForm.user_id || !targetForm.period_start || !targetForm.period_end || !targetForm.target_value" @click="saveTarget">
          Create
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>

<style scoped>
.file-input-overlay {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}
</style>
