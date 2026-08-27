<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

type AssignableUser = { id: string, full_name: string, email: string }
type Territory = { id: string, name: string, pincodes: string[], owner_user_id: string | null }
type RoutingRule = {
  id: string
  name: string
  trigger_type: 'pincode' | 'source' | 'product' | 'territory'
  trigger_value: string
  assign_to_user_id: string
  active: boolean
  priority: number
}
type SequenceStep = { id?: string, day_offset: number, channel: 'whatsapp_template' | 'task', content: Record<string, any>, only_if_stage: string | null }
type Sequence = { id: string, name: string, active: boolean, exit_stage: string | null, steps: SequenceStep[], enrolled_count: number, created_at: string }
type CrmContact = { id: string, name: string | null, phone: string | null, email: string | null }
type Deal = { id: string, contact: CrmContact, status: string }
type Pipeline = { id: string, name: string, stages: { name: string }[] }

const tab = ref<'routing' | 'sequences'>('routing')
const users = ref<AssignableUser[]>([])
const territories = ref<Territory[]>([])
const routingRules = ref<RoutingRule[]>([])
const sequences = ref<Sequence[]>([])
const deals = ref<Deal[]>([])
const pipelines = ref<Pipeline[]>([])
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)

const stageOptions = computed(() => {
  const names = new Set<string>()
  for (const pipeline of pipelines.value) {
    for (const stage of pipeline.stages)
      names.add(stage.name)
  }
  return [...names]
})

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    const [userResult, territoryResult, ruleResult, sequenceResult, dealResult, pipelineResult] = await Promise.all([
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
      $api<Territory[]>('/v1/crm/territories'),
      $api<RoutingRule[]>('/v1/crm/routing-rules'),
      $api<Sequence[]>('/v1/crm/sequences'),
      $api<Deal[]>('/v1/crm/deals'),
      $api<Pipeline[]>('/v1/crm/pipelines'),
    ])
    users.value = userResult
    territories.value = territoryResult
    routingRules.value = ruleResult
    sequences.value = sequenceResult
    deals.value = dealResult
    pipelines.value = pipelineResult
  }
  catch (error: any) {
    if (error?.response?.status === 422)
      crmInactive.value = true
    else
      loadError.value = extractErrorMessage(error, 'Could not load automation settings.')
  }
  finally {
    loading.value = false
  }
}

function userName(id: string) {
  return users.value.find(u => u.id === id)?.full_name || id
}

function triggerValueLabel(rule: RoutingRule) {
  if (rule.trigger_type === 'territory')
    return territories.value.find(t => t.id === rule.trigger_value)?.name || rule.trigger_value
  return rule.trigger_value
}

// --- Routing rules dialog --------------------------------------------------------------------

const ruleDialog = ref(false)
const ruleForm = reactive({ name: '', trigger_type: 'source' as RoutingRule['trigger_type'], trigger_value: '', assign_to_user_id: '', priority: 0 })
const ruleSaving = ref(false)
const ruleError = ref('')

function openRuleDialog() {
  ruleForm.name = ''
  ruleForm.trigger_type = 'source'
  ruleForm.trigger_value = ''
  ruleForm.assign_to_user_id = ''
  ruleForm.priority = routingRules.value.length
  ruleError.value = ''
  ruleDialog.value = true
}

async function saveRule() {
  if (!ruleForm.name.trim() || !ruleForm.trigger_value || !ruleForm.assign_to_user_id)
    return
  ruleSaving.value = true
  ruleError.value = ''
  try {
    const created = await $api<RoutingRule>('/v1/crm/routing-rules', { method: 'POST', body: { ...ruleForm, name: ruleForm.name.trim(), active: true } })
    routingRules.value.push(created)
    ruleDialog.value = false
  }
  catch (error: any) {
    ruleError.value = extractErrorMessage(error, 'Could not create this routing rule.')
  }
  finally {
    ruleSaving.value = false
  }
}

const busyRuleId = ref<string | null>(null)

async function deleteRule(rule: RoutingRule) {
  busyRuleId.value = rule.id
  try {
    await $api(`/v1/crm/routing-rules/${rule.id}`, { method: 'DELETE' })
    routingRules.value = routingRules.value.filter(r => r.id !== rule.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this rule.')
  }
  finally {
    busyRuleId.value = null
  }
}

async function toggleRuleActive(rule: RoutingRule) {
  busyRuleId.value = rule.id
  try {
    const updated = await $api<RoutingRule>(`/v1/crm/routing-rules/${rule.id}`, { method: 'PATCH', body: { active: !rule.active } })
    rule.active = updated.active
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this rule.')
  }
  finally {
    busyRuleId.value = null
  }
}

// --- Sequences dialog ------------------------------------------------------------------------

const seqDialog = ref(false)
const seqForm = reactive({ name: '', exit_stage: null as string | null, steps: [{ day_offset: 0, channel: 'task' as SequenceStep['channel'], content: {} as Record<string, any>, only_if_stage: null }] as SequenceStep[] })
const seqSaving = ref(false)
const seqError = ref('')

function openSeqDialog() {
  seqForm.name = ''
  seqForm.exit_stage = null
  seqForm.steps = [{ day_offset: 0, channel: 'task', content: {}, only_if_stage: null }]
  seqError.value = ''
  seqDialog.value = true
}

function addStep() {
  const last = seqForm.steps[seqForm.steps.length - 1]
  seqForm.steps.push({ day_offset: (last?.day_offset ?? 0) + 1, channel: 'task', content: {}, only_if_stage: null })
}

function removeStep(index: number) {
  if (seqForm.steps.length > 1)
    seqForm.steps.splice(index, 1)
}

function stepContentField(step: SequenceStep, key: string): string {
  return step.content[key] || ''
}

function setStepContentField(step: SequenceStep, key: string, value: string) {
  step.content = { ...step.content, [key]: value }
}

async function saveSequence() {
  if (!seqForm.name.trim())
    return
  seqSaving.value = true
  seqError.value = ''
  try {
    const created = await $api<Sequence>('/v1/crm/sequences', {
      method: 'POST',
      body: {
        name: seqForm.name.trim(), exit_stage: seqForm.exit_stage,
        steps: seqForm.steps.map(s => ({ day_offset: s.day_offset, channel: s.channel, content: s.content, only_if_stage: s.only_if_stage })),
      },
    })
    sequences.value.push(created)
    seqDialog.value = false
  }
  catch (error: any) {
    seqError.value = extractErrorMessage(error, 'Could not create this sequence.')
  }
  finally {
    seqSaving.value = false
  }
}

const busySequenceId = ref<string | null>(null)

async function deleteSequence(sequence: Sequence) {
  busySequenceId.value = sequence.id
  try {
    await $api(`/v1/crm/sequences/${sequence.id}`, { method: 'DELETE' })
    sequences.value = sequences.value.filter(s => s.id !== sequence.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this sequence.')
  }
  finally {
    busySequenceId.value = null
  }
}

async function toggleSequenceActive(sequence: Sequence) {
  busySequenceId.value = sequence.id
  try {
    const updated = await $api<Sequence>(`/v1/crm/sequences/${sequence.id}`, { method: 'PATCH', body: { active: !sequence.active } })
    sequence.active = updated.active
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this sequence.')
  }
  finally {
    busySequenceId.value = null
  }
}

// --- Enrollment --------------------------------------------------------------------------

const enrollDialog = ref(false)
const enrollSequence = ref<Sequence | null>(null)
const enrollDealId = ref('')
const enrolling = ref(false)
const enrollError = ref('')

function openEnroll(sequence: Sequence) {
  enrollSequence.value = sequence
  enrollDealId.value = ''
  enrollError.value = ''
  enrollDialog.value = true
}

async function submitEnroll() {
  if (!enrollSequence.value || !enrollDealId.value)
    return
  enrolling.value = true
  enrollError.value = ''
  try {
    await $api(`/v1/crm/sequences/${enrollSequence.value.id}/enroll`, { method: 'POST', body: { deal_id: enrollDealId.value } })
    enrollSequence.value.enrolled_count += 1
    enrollDialog.value = false
  }
  catch (error: any) {
    enrollError.value = extractErrorMessage(error, 'Could not enroll this deal.')
  }
  finally {
    enrolling.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Automation
  </h1>
  <p class="text-medium-emphasis mb-6">
    Rule-based lead routing and multi-touch sales sequences — no AI, every match is explainable.
  </p>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    Upgrade to the CRM plan to use leads, tickets, and customers.
  </VAlert>
  <VAlert v-else-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <template v-if="!crmInactive">
    <VTabs v-model="tab" class="mb-4">
      <VTab value="routing">
        Lead routing
      </VTab>
      <VTab value="sequences">
        Sequences
      </VTab>
    </VTabs>

    <div v-if="tab === 'routing'">
      <div class="d-flex justify-end mb-3">
        <VBtn color="primary" prepend-icon="tabler-plus" @click="openRuleDialog">
          New rule
        </VBtn>
      </div>
      <VCard>
        <VTable>
          <thead>
            <tr>
              <th>Priority</th>
              <th>Name</th>
              <th>Trigger</th>
              <th>Assign to</th>
              <th>Active</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="rule in routingRules" :key="rule.id">
              <td>{{ rule.priority }}</td>
              <td>{{ rule.name }}</td>
              <td>{{ rule.trigger_type }} = {{ triggerValueLabel(rule) }}</td>
              <td>{{ userName(rule.assign_to_user_id) }}</td>
              <td>
                <VSwitch :model-value="rule.active" density="compact" hide-details :disabled="busyRuleId === rule.id" @update:model-value="toggleRuleActive(rule)" />
              </td>
              <td class="text-end">
                <VBtn icon="tabler-trash" size="small" variant="text" :loading="busyRuleId === rule.id" :disabled="busyRuleId === rule.id" @click="deleteRule(rule)" />
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!loading && !routingRules.length" class="text-medium-emphasis text-center pa-6">
          No routing rules yet — new leads stay unassigned until manually claimed.
        </p>
      </VCard>
    </div>

    <div v-else>
      <div class="d-flex justify-end mb-3">
        <VBtn color="primary" prepend-icon="tabler-plus" @click="openSeqDialog">
          New sequence
        </VBtn>
      </div>
      <VRow>
        <VCol v-for="sequence in sequences" :key="sequence.id" cols="12" md="6">
          <VCard>
            <VCardItem>
              <VCardTitle>{{ sequence.name }}</VCardTitle>
              <VCardSubtitle>{{ sequence.enrolled_count }} active enrollment{{ sequence.enrolled_count === 1 ? '' : 's' }}</VCardSubtitle>
              <template #append>
                <VSwitch
                  :model-value="sequence.active" label="Active" density="compact" hide-details class="me-2"
                  :disabled="busySequenceId === sequence.id"
                  @update:model-value="toggleSequenceActive(sequence)"
                />
                <VBtn size="small" variant="tonal" class="me-2" :disabled="busySequenceId === sequence.id" @click="openEnroll(sequence)">
                  Enroll lead
                </VBtn>
                <VBtn icon="tabler-trash" variant="text" size="small" :loading="busySequenceId === sequence.id" :disabled="busySequenceId === sequence.id" @click="deleteSequence(sequence)" />
              </template>
            </VCardItem>
            <VCardText>
              <div v-for="step in sequence.steps" :key="step.id" class="d-flex ga-3 mb-2">
                <VChip size="small" variant="tonal" style="min-width: 64px;" class="justify-center">
                  Day {{ step.day_offset }}
                </VChip>
                <span class="text-body-2">
                  {{ step.channel === 'whatsapp_template' ? `WhatsApp: ${step.content.template_name || '(template)'}` : `Task: ${step.content.title || 'Follow up'}` }}
                </span>
              </div>
              <p v-if="sequence.exit_stage" class="text-caption text-medium-emphasis mb-0 mt-2">
                Stops once the deal reaches "{{ sequence.exit_stage }}" (or is won/lost)
              </p>
              <p v-else class="text-caption text-medium-emphasis mb-0 mt-2">
                Stops once the deal is won/lost
              </p>
            </VCardText>
          </VCard>
        </VCol>
        <VCol v-if="!loading && !sequences.length" cols="12">
          <p class="text-medium-emphasis text-center pa-6">
            No sequences yet.
          </p>
        </VCol>
      </VRow>
    </div>
  </template>

  <VDialog v-model="ruleDialog" max-width="480" persistent>
    <VCard title="New routing rule">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="ruleDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="ruleError" type="error" variant="tonal" density="compact">
          {{ ruleError }}
        </VAlert>
        <VTextField v-model="ruleForm.name" label="Rule name" density="compact" />
        <VSelect
          v-model="ruleForm.trigger_type" label="Trigger" density="compact"
          :items="[{ title: 'Lead source', value: 'source' }, { title: 'Pincode', value: 'pincode' }, { title: 'Product', value: 'product' }, { title: 'Territory', value: 'territory' }]"
          @update:model-value="ruleForm.trigger_value = ''"
        />
        <VSelect
          v-if="ruleForm.trigger_type === 'territory'"
          v-model="ruleForm.trigger_value" label="Territory" density="compact"
          :items="territories.map(t => ({ title: t.name, value: t.id }))"
        />
        <VTextField
          v-else v-model="ruleForm.trigger_value" density="compact"
          :label="ruleForm.trigger_type === 'source' ? 'Source value (e.g. whatsapp_conversation, web_form)' : ruleForm.trigger_type === 'pincode' ? 'Pincode' : 'Product keyword'"
        />
        <VSelect
          v-model="ruleForm.assign_to_user_id" label="Assign to" density="compact"
          :items="users.map(u => ({ title: u.full_name, value: u.id }))"
        />
        <VTextField v-model.number="ruleForm.priority" type="number" label="Priority (lower runs first)" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="ruleDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="ruleSaving" :disabled="!ruleForm.name.trim() || !ruleForm.trigger_value || !ruleForm.assign_to_user_id" @click="saveRule">
          Create
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="seqDialog" max-width="600" persistent>
    <VCard title="New sequence">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="seqDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="seqError" type="error" variant="tonal" density="compact">
          {{ seqError }}
        </VAlert>
        <VTextField v-model="seqForm.name" label="Sequence name" density="compact" />
        <VSelect
          v-model="seqForm.exit_stage" :items="stageOptions" label="Stop once the deal reaches this stage (optional)"
          density="compact" hide-details clearable
        />
        <div>
          <div class="d-flex align-center justify-space-between mb-2">
            <span class="text-subtitle-2">Steps</span>
            <VBtn size="small" variant="text" prepend-icon="tabler-plus" @click="addStep">
              Add step
            </VBtn>
          </div>
          <div v-for="(step, index) in seqForm.steps" :key="index" class="border rounded pa-2 mb-2">
            <div class="d-flex ga-2 align-center">
              <VTextField v-model.number="step.day_offset" type="number" label="Day" density="compact" hide-details style="max-width: 80px;" />
              <VSelect
                v-model="step.channel" label="Channel" density="compact" hide-details style="max-width: 160px;"
                :items="[{ title: 'Task', value: 'task' }, { title: 'WhatsApp template', value: 'whatsapp_template' }]"
              />
              <VTextField
                v-if="step.channel === 'task'" :model-value="stepContentField(step, 'title')" placeholder="Task title"
                density="compact" hide-details @update:model-value="(v: string) => setStepContentField(step, 'title', v)"
              />
              <VTextField
                v-else :model-value="stepContentField(step, 'template_name')" placeholder="Template name"
                density="compact" hide-details @update:model-value="(v: string) => setStepContentField(step, 'template_name', v)"
              />
              <VBtn icon="tabler-x" size="small" variant="text" :disabled="seqForm.steps.length === 1" @click="removeStep(index)" />
            </div>
            <VSelect
              v-model="step.only_if_stage" :items="stageOptions" label="Only send if deal is still in this stage (optional)"
              density="compact" hide-details clearable class="mt-2"
            />
          </div>
        </div>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="seqDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="seqSaving" :disabled="!seqForm.name.trim()" @click="saveSequence">
          Create
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="enrollDialog" max-width="420" persistent>
    <VCard title="Enroll a deal">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="enrollDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="enrollError" type="error" variant="tonal" density="compact">
          {{ enrollError }}
        </VAlert>
        <VSelect
          v-model="enrollDealId" label="Deal" density="compact"
          :items="deals.filter(d => d.status === 'open').map(d => ({ title: d.contact.name || d.contact.phone || d.contact.email || 'Unknown', value: d.id }))"
        />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="enrollDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="enrolling" :disabled="!enrollDealId" @click="submitEnroll">
          Enroll
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
