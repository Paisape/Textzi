<script setup lang="ts">
import { VNodeRenderer } from '@layouts/components/VNodeRenderer'
import { themeConfig } from '@themeConfig'

definePage({
  meta: {
    layout: 'blank',
    public: true,
  },
})

type LinkInfo = { duration_minutes: number, entity_name: string }

const route = useRoute()
const slug = route.params.slug as string

const linkInfo = ref<LinkInfo | null>(null)
const loadError = ref('')
const loading = ref(true)

async function loadLink() {
  loading.value = true
  loadError.value = ''
  try {
    linkInfo.value = await $api<LinkInfo>(`/v1/public/booking/${slug}`)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'This booking link is invalid or no longer active.')
  }
  finally {
    loading.value = false
  }
}

// --- Date + slot picking ---

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

const selectedDate = ref(todayIso())
const slots = ref<string[]>([])
const slotsLoading = ref(false)
const selectedSlot = ref<string | null>(null)

async function loadSlots() {
  slotsLoading.value = true
  selectedSlot.value = null
  try {
    const result = await $api<{ date: string, slots: string[] }>(`/v1/public/booking/${slug}/availability`, { params: { on: selectedDate.value } })
    slots.value = result.slots
  }
  catch {
    slots.value = []
  }
  finally {
    slotsLoading.value = false
  }
}

watch(selectedDate, loadSlots)

// --- Booking form ---

const name = ref('')
const email = ref('')
const phone = ref('')
const turnstileToken = ref('')
const turnstileRef = ref<InstanceType<typeof TurnstileWidget>>()
const booking = ref(false)
const bookError = ref('')
const confirmed = ref(false)

function slotStartIso() {
  // selectedDate + selectedSlot (local "HH:MM") -> a real ISO datetime with the browser's own
  // offset, matching what the backend's availability endpoint itself computed the slot against.
  const [h, m] = (selectedSlot.value || '00:00').split(':').map(Number)
  const d = new Date(`${selectedDate.value}T00:00:00`)
  d.setHours(h, m, 0, 0)
  return d.toISOString()
}

async function book() {
  if (!name.value.trim() || (!email.value.trim() && !phone.value.trim()) || !selectedSlot.value) {
    bookError.value = 'Enter your name and either an email or phone number, then pick a slot.'
    return
  }
  booking.value = true
  bookError.value = ''
  try {
    await $api(`/v1/public/booking/${slug}/book`, {
      method: 'POST',
      body: {
        name: name.value.trim(), email: email.value.trim() || null, phone: phone.value.trim() || null,
        slot_start: slotStartIso(), turnstile_token: turnstileToken.value,
      },
    })
    confirmed.value = true
  }
  catch (error: any) {
    bookError.value = extractErrorMessage(error, 'Could not confirm this booking. Please try another slot.')
    turnstileRef.value?.reset()
    loadSlots()
  }
  finally {
    booking.value = false
  }
}

onMounted(async () => {
  await loadLink()
  if (linkInfo.value)
    loadSlots()
})
</script>

<template>
  <RouterLink to="/">
    <div class="auth-logo d-flex align-center gap-x-3">
      <VNodeRenderer :nodes="themeConfig.app.logo" />
      <h1 class="auth-title">
        {{ themeConfig.app.title }}
      </h1>
    </div>
  </RouterLink>

  <div class="d-flex align-center justify-center bg-surface" style="min-block-size: calc(100vh - 80px); padding: 24px;">
    <VCard max-width="640" class="w-100">
      <VCardText v-if="loading" class="text-center pa-8">
        <VProgressCircular indeterminate color="primary" />
      </VCardText>

      <VCardText v-else-if="loadError" class="pa-8">
        <VAlert type="error" variant="tonal">
          {{ loadError }}
        </VAlert>
      </VCardText>

      <VCardText v-else-if="confirmed" class="pa-8 text-center">
        <VIcon icon="tabler-circle-check-filled" color="success" size="48" class="mb-3" />
        <h2 class="text-h6 mb-1">
          Meeting confirmed
        </h2>
        <p class="text-body-2 text-medium-emphasis mb-0">
          {{ new Date(slotStartIso()).toLocaleString() }}
        </p>
      </VCardText>

      <VCardText v-else-if="linkInfo" class="pa-6">
        <h1 class="text-h5 mb-1">
          Book a meeting with {{ linkInfo.entity_name }}
        </h1>
        <p class="text-body-2 text-medium-emphasis mb-4">
          {{ linkInfo.duration_minutes }} minutes
        </p>

        <VTextField v-model="selectedDate" type="date" label="Date" density="compact" class="mb-4" style="max-inline-size: 220px;" />

        <div v-if="slotsLoading" class="text-center pa-4">
          <VProgressCircular indeterminate color="primary" size="24" />
        </div>
        <div v-else-if="slots.length" class="d-flex flex-wrap ga-2 mb-4">
          <VChip
            v-for="slot in slots" :key="slot" :variant="selectedSlot === slot ? 'flat' : 'outlined'"
            :color="selectedSlot === slot ? 'primary' : undefined" @click="selectedSlot = slot"
          >
            {{ slot }}
          </VChip>
        </div>
        <p v-else class="text-medium-emphasis mb-4">
          No open slots on this date — try another day.
        </p>

        <template v-if="selectedSlot">
          <VDivider class="mb-4" />
          <VAlert v-if="bookError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ bookError }}
          </VAlert>
          <VTextField v-model="name" label="Your name" density="compact" class="mb-3" />
          <VTextField v-model="email" label="Email" density="compact" class="mb-3" />
          <VTextField v-model="phone" label="Phone" density="compact" class="mb-3" />
          <TurnstileWidget id="turnstile-booking" ref="turnstileRef" v-model="turnstileToken" class="mb-3" />
          <VBtn color="primary" :loading="booking" @click="book">
            Confirm booking
          </VBtn>
        </template>
      </VCardText>
    </VCard>
  </div>
</template>
