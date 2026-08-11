<script setup lang="ts">
type DayHours = { open: string, close: string }
const DAYS = [
  { key: 'mon', label: 'Monday' },
  { key: 'tue', label: 'Tuesday' },
  { key: 'wed', label: 'Wednesday' },
  { key: 'thu', label: 'Thursday' },
  { key: 'fri', label: 'Friday' },
  { key: 'sat', label: 'Saturday' },
  { key: 'sun', label: 'Sunday' },
]

const hoursForm = ref({ enabled: false, timezone: 'Asia/Kolkata', outside_hours_message: '', days: {} as Record<string, DayHours | null> })
const hoursLoading = ref(false)
const hoursSaving = ref(false)
const hoursError = ref('')
const hoursSaved = ref(false)

async function loadHours() {
  hoursLoading.value = true
  hoursError.value = ''
  try {
    const result = await $api<{ enabled: boolean, timezone: string, schedule: Record<string, DayHours>, outside_hours_message: string | null }>('/v1/waba/business-hours')
    hoursForm.value = {
      enabled: result.enabled,
      timezone: result.timezone,
      outside_hours_message: result.outside_hours_message || '',
      days: Object.fromEntries(DAYS.map(d => [d.key, result.schedule[d.key] || null])),
    }
  }
  catch (error: any) {
    hoursError.value = extractErrorMessage(error, 'Could not load business hours.')
  }
  finally {
    hoursLoading.value = false
  }
}

function toggleDay(key: string, enabled: boolean) {
  hoursForm.value.days[key] = enabled ? { open: '09:00', close: '18:00' } : null
}

async function saveHours() {
  hoursSaving.value = true
  hoursError.value = ''
  hoursSaved.value = false
  try {
    const schedule = Object.fromEntries(Object.entries(hoursForm.value.days).filter(([, v]) => v !== null)) as Record<string, DayHours>
    await $api('/v1/waba/business-hours', {
      method: 'PUT',
      body: { enabled: hoursForm.value.enabled, timezone: hoursForm.value.timezone, schedule, outside_hours_message: hoursForm.value.outside_hours_message || null },
    })
    hoursSaved.value = true
  }
  catch (error: any) {
    hoursError.value = extractErrorMessage(error, 'Could not save business hours.')
  }
  finally {
    hoursSaving.value = false
  }
}

const slaForm = ref({ enabled: false, first_response_minutes: 60 })
const slaSaving = ref(false)
const slaError = ref('')
const slaSaved = ref(false)

async function loadSla() {
  try {
    slaForm.value = await $api('/v1/waba/sla-policy')
  }
  catch (error: any) {
    slaError.value = extractErrorMessage(error, 'Could not load SLA policy.')
  }
}

async function saveSla() {
  slaSaving.value = true
  slaError.value = ''
  slaSaved.value = false
  try {
    slaForm.value = await $api('/v1/waba/sla-policy', { method: 'PUT', body: slaForm.value })
    slaSaved.value = true
  }
  catch (error: any) {
    slaError.value = extractErrorMessage(error, 'Could not save SLA policy.')
  }
  finally {
    slaSaving.value = false
  }
}

onMounted(() => {
  loadHours()
  loadSla()
})
</script>

<template>
  <VRow>
    <VCol cols="12" md="6">
      <VCard>
        <VCardText>
          <h2 class="text-h6 mb-1">
            Business hours
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            An auto-reply sent (at most once every 12 hours per conversation) when a message
            arrives outside these hours.
          </p>
          <VAlert v-if="hoursError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ hoursError }}
          </VAlert>
          <VAlert v-if="hoursSaved" type="success" variant="tonal" density="compact" class="mb-3">
            Saved.
          </VAlert>
          <VSwitch v-model="hoursForm.enabled" label="Enable business hours" density="compact" class="mb-3" />
          <template v-if="hoursForm.enabled">
            <AppTextField v-model="hoursForm.timezone" label="Timezone" class="mb-3" />
            <div v-for="day in DAYS" :key="day.key" class="d-flex align-center ga-3 mb-2">
              <VSwitch
                :model-value="!!hoursForm.days[day.key]"
                density="compact"
                hide-details
                style="width: 140px;"
                :label="day.label"
                @update:model-value="(v: boolean) => toggleDay(day.key, v)"
              />
              <template v-if="hoursForm.days[day.key]">
                <VTextField v-model="hoursForm.days[day.key]!.open" type="time" density="compact" hide-details style="max-width: 130px;" />
                <span>to</span>
                <VTextField v-model="hoursForm.days[day.key]!.close" type="time" density="compact" hide-details style="max-width: 130px;" />
              </template>
            </div>
            <VTextarea v-model="hoursForm.outside_hours_message" label="Outside-hours auto-reply" rows="2" class="mt-3" />
          </template>
          <VBtn class="mt-2" :loading="hoursSaving" @click="saveHours">
            Save
          </VBtn>
        </VCardText>
      </VCard>
    </VCol>

    <VCol cols="12" md="6">
      <VCard>
        <VCardText>
          <h2 class="text-h6 mb-1">
            SLA policy
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            How long a conversation can wait for its first reply before it's flagged as breached.
          </p>
          <VAlert v-if="slaError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ slaError }}
          </VAlert>
          <VAlert v-if="slaSaved" type="success" variant="tonal" density="compact" class="mb-3">
            Saved.
          </VAlert>
          <VSwitch v-model="slaForm.enabled" label="Enable SLA tracking" density="compact" class="mb-3" />
          <VTextField v-if="slaForm.enabled" v-model.number="slaForm.first_response_minutes" type="number" label="First response due within (minutes)" class="mb-3" />
          <VBtn :loading="slaSaving" @click="saveSla">
            Save
          </VBtn>
        </VCardText>
      </VCard>
    </VCol>
  </VRow>
</template>
