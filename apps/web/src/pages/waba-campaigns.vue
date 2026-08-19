<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'waba',
  },
})

type Segment = { id: string, name: string, label_ids: string[], custom_attributes: Record<string, string>, contact_count: number, created_at: string }
type Campaign = {
  id: string
  name: string
  template_name: string
  template_language: string
  body_params: string[]
  segment_id: string
  status: string
  total_recipients: number
  sent_count: number
  failed_count: number
  created_at: string
  completed_at: string | null
  scheduled_at: string | null
}
type Template = { name: string, status: string, language: string, body: string | null }
type Label = { id: string, scope: string, name: string, color: string }

const activeTab = ref<'campaigns' | 'segments'>('campaigns')

const campaigns = ref<Campaign[]>([])
const segments = ref<Segment[]>([])
const templates = ref<Template[]>([])
const conversationLabels = ref<Label[]>([])
const loading = ref(false)
const loadError = ref('')

async function loadAll() {
  loading.value = true
  loadError.value = ''
  try {
    const [campaignResult, segmentResult, templateResult, labelResult] = await Promise.all([
      $api<Campaign[]>('/v1/waba/campaigns'),
      $api<Segment[]>('/v1/waba/segments'),
      $api<Template[]>('/v1/waba/templates'),
      $api<Label[]>('/v1/waba/labels', { params: { scope: 'contact' } }),
    ])
    campaigns.value = campaignResult
    segments.value = segmentResult
    templates.value = templateResult.filter(t => t.status === 'APPROVED')
    conversationLabels.value = labelResult
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load campaigns.')
  }
  finally {
    loading.value = false
  }
}

function statusColor(status: string) {
  if (status === 'completed')
    return 'success'
  if (status === 'failed')
    return 'error'
  if (status === 'sending')
    return 'warning'
  if (status === 'scheduled')
    return 'info'
  return 'default'
}

function segmentName(id: string) {
  return segments.value.find(s => s.id === id)?.name || '—'
}

// --- Segments ---

const segmentDialog = ref(false)
const segmentForm = ref({ name: '', label_ids: [] as string[] })
const segmentSaving = ref(false)
const segmentError = ref('')

function openSegmentDialog() {
  segmentForm.value = { name: '', label_ids: [] }
  segmentError.value = ''
  segmentDialog.value = true
}

async function createSegment() {
  if (!segmentForm.value.name.trim())
    return
  segmentSaving.value = true
  segmentError.value = ''
  try {
    segments.value.unshift(await $api<Segment>('/v1/waba/segments', {
      method: 'POST',
      body: { name: segmentForm.value.name.trim(), label_ids: segmentForm.value.label_ids, custom_attributes: {} },
    }))
    segmentDialog.value = false
  }
  catch (error: any) {
    segmentError.value = extractErrorMessage(error, 'Could not create this segment.')
  }
  finally {
    segmentSaving.value = false
  }
}

async function deleteSegment(segment: Segment) {
  try {
    await $api(`/v1/waba/segments/${segment.id}`, { method: 'DELETE' })
    segments.value = segments.value.filter(s => s.id !== segment.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this segment.')
  }
}

// --- Campaigns ---

const campaignDialog = ref(false)
const campaignForm = ref({ name: '', template_name: '', template_language: '', body_params: '', segment_id: '' })
const campaignSaving = ref(false)
const campaignError = ref('')

function openCampaignDialog() {
  campaignForm.value = { name: '', template_name: '', template_language: '', body_params: '', segment_id: '' }
  campaignError.value = ''
  campaignDialog.value = true
}

function onTemplateSelect(name: string) {
  const template = templates.value.find(t => t.name === name)
  campaignForm.value.template_language = template?.language || ''
}

async function createCampaign() {
  if (!campaignForm.value.name.trim() || !campaignForm.value.template_name || !campaignForm.value.segment_id)
    return
  campaignSaving.value = true
  campaignError.value = ''
  try {
    const campaign = await $api<Campaign>('/v1/waba/campaigns', {
      method: 'POST',
      body: {
        name: campaignForm.value.name.trim(),
        template_name: campaignForm.value.template_name,
        template_language: campaignForm.value.template_language,
        body_params: campaignForm.value.body_params ? campaignForm.value.body_params.split(',').map(p => p.trim()).filter(Boolean) : [],
        segment_id: campaignForm.value.segment_id,
      },
    })
    campaigns.value.unshift(campaign)
    campaignDialog.value = false
  }
  catch (error: any) {
    campaignError.value = extractErrorMessage(error, 'Could not create this campaign.')
  }
  finally {
    campaignSaving.value = false
  }
}

const sending = ref<string | null>(null)

async function sendCampaign(campaign: Campaign) {
  sending.value = campaign.id
  loadError.value = ''
  try {
    const updated = await $api<Campaign>(`/v1/waba/campaigns/${campaign.id}/send`, { method: 'POST' })
    const i = campaigns.value.findIndex(c => c.id === updated.id)
    if (i !== -1)
      campaigns.value[i] = updated
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not send this campaign.')
  }
  finally {
    sending.value = null
  }
}

const scheduleDialog = ref(false)
const scheduleCampaignId = ref<string | null>(null)
const scheduleAt = ref('')
const scheduleSaving = ref(false)
const scheduleError = ref('')

function openScheduleDialog(campaign: Campaign) {
  scheduleCampaignId.value = campaign.id
  scheduleAt.value = ''
  scheduleError.value = ''
  scheduleDialog.value = true
}

async function confirmSchedule() {
  if (!scheduleCampaignId.value || !scheduleAt.value)
    return
  scheduleSaving.value = true
  scheduleError.value = ''
  try {
    const iso = new Date(scheduleAt.value).toISOString()
    const updated = await $api<Campaign>(`/v1/waba/campaigns/${scheduleCampaignId.value}/schedule`, { method: 'POST', body: { scheduled_at: iso } })
    const i = campaigns.value.findIndex(c => c.id === updated.id)
    if (i !== -1)
      campaigns.value[i] = updated
    scheduleDialog.value = false
  }
  catch (error: any) {
    scheduleError.value = extractErrorMessage(error, 'Could not schedule this campaign.')
  }
  finally {
    scheduleSaving.value = false
  }
}

async function unscheduleCampaign(campaign: Campaign) {
  loadError.value = ''
  try {
    const updated = await $api<Campaign>(`/v1/waba/campaigns/${campaign.id}/unschedule`, { method: 'POST' })
    const i = campaigns.value.findIndex(c => c.id === updated.id)
    if (i !== -1)
      campaigns.value[i] = updated
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not unschedule this campaign.')
  }
}

async function deleteCampaign(campaign: Campaign) {
  try {
    await $api(`/v1/waba/campaigns/${campaign.id}`, { method: 'DELETE' })
    campaigns.value = campaigns.value.filter(c => c.id !== campaign.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this campaign.')
  }
}

onMounted(loadAll)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Campaigns
  </h1>
  <p class="text-medium-emphasis mb-6">
    Bulk template sends to a segment of your contacts. Always uses an approved template -- Meta
    only allows business-initiated bulk sends that way.
  </p>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>

  <VTabs v-model="activeTab" class="mb-6">
    <VTab value="campaigns">
      Campaigns
    </VTab>
    <VTab value="segments">
      Segments
    </VTab>
  </VTabs>

  <VWindow v-model="activeTab">
    <VWindowItem value="campaigns">
      <div class="d-flex justify-end mb-4">
        <VBtn prepend-icon="tabler-plus" @click="openCampaignDialog">
          New campaign
        </VBtn>
      </div>
      <VCard>
        <VTable>
          <thead>
            <tr>
              <th>Name</th>
              <th>Template</th>
              <th>Segment</th>
              <th>Status</th>
              <th>Progress</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="campaign in campaigns" :key="campaign.id">
              <td>{{ campaign.name }}</td>
              <td>{{ campaign.template_name }}</td>
              <td>{{ segmentName(campaign.segment_id) }}</td>
              <td>
                <VChip size="small" :color="statusColor(campaign.status)">
                  {{ campaign.status }}
                </VChip>
                <p v-if="campaign.scheduled_at" class="text-caption text-medium-emphasis mb-0 mt-1">
                  {{ new Date(campaign.scheduled_at).toLocaleString() }}
                </p>
              </td>
              <td>{{ campaign.sent_count }} sent, {{ campaign.failed_count }} failed / {{ campaign.total_recipients }}</td>
              <td>
                <template v-if="campaign.status === 'draft'">
                  <VBtn size="small" variant="tonal" :loading="sending === campaign.id" @click="sendCampaign(campaign)">
                    Send now
                  </VBtn>
                  <VBtn size="small" variant="text" @click="openScheduleDialog(campaign)">
                    Schedule
                  </VBtn>
                  <VBtn size="small" variant="text" icon="tabler-trash" @click="deleteCampaign(campaign)" />
                </template>
                <VBtn v-else-if="campaign.status === 'scheduled'" size="small" variant="text" @click="unscheduleCampaign(campaign)">
                  Unschedule
                </VBtn>
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!loading && !campaigns.length" class="text-medium-emphasis text-center pa-6">
          No campaigns yet.
        </p>
      </VCard>
    </VWindowItem>

    <VWindowItem value="segments">
      <div class="d-flex justify-end mb-4">
        <VBtn prepend-icon="tabler-plus" @click="openSegmentDialog">
          New segment
        </VBtn>
      </div>
      <VCard>
        <VTable>
          <thead>
            <tr>
              <th>Name</th>
              <th>Labels</th>
              <th>Contacts</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="segment in segments" :key="segment.id">
              <td>{{ segment.name }}</td>
              <td>{{ segment.label_ids.length }} label(s)</td>
              <td>{{ segment.contact_count }}</td>
              <td>
                <VBtn size="small" variant="text" icon="tabler-trash" @click="deleteSegment(segment)" />
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!loading && !segments.length" class="text-medium-emphasis text-center pa-6">
          No segments yet.
        </p>
      </VCard>
    </VWindowItem>
  </VWindow>

  <VDialog v-model="campaignDialog" max-width="480">
    <VCard>
      <VCardTitle>New campaign</VCardTitle>
      <VCardText>
        <VAlert v-if="campaignError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ campaignError }}
        </VAlert>
        <AppTextField v-model="campaignForm.name" label="Campaign name" class="mb-3" />
        <VSelect
          v-model="campaignForm.template_name"
          label="Template"
          :items="templates.map(t => ({ title: t.name, value: t.name }))"
          class="mb-3"
          @update:model-value="onTemplateSelect"
        />
        <AppTextField v-model="campaignForm.body_params" label="Body params (comma-separated, same for every recipient)" class="mb-3" />
        <VSelect
          v-model="campaignForm.segment_id"
          label="Segment"
          :items="segments.map(s => ({ title: `${s.name} (${s.contact_count})`, value: s.id }))"
        />
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="campaignDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="campaignSaving" @click="createCampaign">
          Create
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="scheduleDialog" max-width="380">
    <VCard>
      <VCardTitle>Schedule send</VCardTitle>
      <VCardText>
        <VAlert v-if="scheduleError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ scheduleError }}
        </VAlert>
        <VTextField v-model="scheduleAt" type="datetime-local" label="Send at" density="compact" />
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="scheduleDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="scheduleSaving" @click="confirmSchedule">
          Schedule
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="segmentDialog" max-width="420">
    <VCard>
      <VCardTitle>New segment</VCardTitle>
      <VCardText>
        <VAlert v-if="segmentError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ segmentError }}
        </VAlert>
        <AppTextField v-model="segmentForm.name" label="Segment name" class="mb-3" />
        <VSelect
          v-model="segmentForm.label_ids"
          label="Must have all these contact labels"
          :items="conversationLabels.map(l => ({ title: l.name, value: l.id }))"
          multiple
          chips
        />
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="segmentDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="segmentSaving" @click="createSegment">
          Create
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>
</template>
