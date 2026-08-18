<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'waba',
  },
})

type VolumePoint = { date: string, inbound: number, outbound: number }
type AgentRow = { user_id: string, full_name: string, messages_sent: number, conversations_resolved: number, avg_first_response_minutes: number | null }
type LabelRow = { label_id: string, name: string, color: string, conversation_count: number }
type Reports = {
  volume: VolumePoint[]
  agents: AgentRow[]
  labels: LabelRow[]
  total_conversations: number
  open_conversations: number
  resolved_conversations: number
  sla_breached_count: number
  avg_csat: number | null
  csat_response_count: number
}

const days = ref(30)
const reports = ref<Reports | null>(null)
const loading = ref(false)
const loadError = ref('')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    reports.value = await $api<Reports>('/v1/waba/reports', { params: { days: days.value } })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load reports.')
  }
  finally {
    loading.value = false
  }
}

const maxVolume = computed(() => {
  if (!reports.value?.volume.length)
    return 1
  return Math.max(1, ...reports.value.volume.map(v => v.inbound + v.outbound))
})

watch(days, load)
onMounted(load)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-1 flex-wrap ga-3">
    <h1 class="text-h4">
      Reports
    </h1>
    <VSelect
      v-model="days"
      :items="[{ title: 'Last 7 days', value: 7 }, { title: 'Last 30 days', value: 30 }, { title: 'Last 90 days', value: 90 }]"
      density="compact"
      variant="outlined"
      style="max-width: 200px;"
    />
  </div>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>

  <template v-if="reports">
    <VRow class="mb-2">
      <VCol cols="6" sm="4" md="2">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              Total conversations
            </p>
            <p class="text-h5 mb-0">
              {{ reports.total_conversations }}
            </p>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="6" sm="4" md="2">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              Open
            </p>
            <p class="text-h5 mb-0">
              {{ reports.open_conversations }}
            </p>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="6" sm="4" md="2">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              Resolved
            </p>
            <p class="text-h5 mb-0">
              {{ reports.resolved_conversations }}
            </p>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="6" sm="4" md="2">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              SLA breaches
            </p>
            <p class="text-h5 mb-0" :class="reports.sla_breached_count ? 'text-error' : ''">
              {{ reports.sla_breached_count }}
            </p>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="6" sm="4" md="2">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              Avg CSAT
            </p>
            <p class="text-h5 mb-0">
              {{ reports.avg_csat ?? '—' }} <span v-if="reports.avg_csat" class="text-body-2 text-medium-emphasis">/ 5</span>
            </p>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="6" sm="4" md="2">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              CSAT responses
            </p>
            <p class="text-h5 mb-0">
              {{ reports.csat_response_count }}
            </p>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>

    <VCard class="mb-6">
      <VCardText>
        <h2 class="text-h6 mb-4">
          Message volume
        </h2>
        <div v-if="reports.volume.length" class="d-flex align-end ga-2" style="height: 160px;">
          <div v-for="point in reports.volume" :key="point.date" class="d-flex flex-column align-center justify-end flex-grow-1" style="height: 100%;">
            <div class="d-flex flex-column justify-end" style="height: 130px; width: 100%;">
              <div
                class="bg-success rounded-t"
                :style="{ height: `${(point.outbound / maxVolume) * 130}px`, width: '100%' }"
                :title="`${point.outbound} outbound`"
              />
              <div
                class="bg-primary"
                :style="{ height: `${(point.inbound / maxVolume) * 130}px`, width: '100%' }"
                :title="`${point.inbound} inbound`"
              />
            </div>
            <span class="text-caption text-medium-emphasis mt-1">{{ point.date.slice(5) }}</span>
          </div>
        </div>
        <p v-else class="text-medium-emphasis mb-0">
          No messages in this period.
        </p>
        <div class="d-flex ga-4 mt-4">
          <div class="d-flex align-center ga-1">
            <div class="bg-primary rounded" style="width: 12px; height: 12px;" />
            <span class="text-caption">Inbound</span>
          </div>
          <div class="d-flex align-center ga-1">
            <div class="bg-success rounded" style="width: 12px; height: 12px;" />
            <span class="text-caption">Outbound</span>
          </div>
        </div>
      </VCardText>
    </VCard>

    <VRow>
      <VCol cols="12" md="6">
        <VCard>
          <VCardText>
            <h2 class="text-h6 mb-3">
              Agent activity
            </h2>
            <VTable density="compact">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Sent</th>
                  <th>Resolved</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="agent in reports.agents" :key="agent.user_id">
                  <td>{{ agent.full_name }}</td>
                  <td>{{ agent.messages_sent }}</td>
                  <td>{{ agent.conversations_resolved }}</td>
                </tr>
              </tbody>
            </VTable>
            <p v-if="!reports.agents.length" class="text-medium-emphasis text-center pa-4 mb-0">
              No agent activity in this period.
            </p>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" md="6">
        <VCard>
          <VCardText>
            <h2 class="text-h6 mb-3">
              Labels
            </h2>
            <VTable density="compact">
              <thead>
                <tr>
                  <th>Label</th>
                  <th>Conversations</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="label in reports.labels" :key="label.label_id">
                  <td>
                    <VChip size="small" :color="label.color">
                      {{ label.name }}
                    </VChip>
                  </td>
                  <td>{{ label.conversation_count }}</td>
                </tr>
              </tbody>
            </VTable>
            <p v-if="!reports.labels.length" class="text-medium-emphasis text-center pa-4 mb-0">
              No labelled conversations.
            </p>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>
  </template>
</template>
