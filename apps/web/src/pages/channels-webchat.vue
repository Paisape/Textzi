<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type WebchatSettings = {
  enabled: boolean
  widget_key: string
  allowed_origins: string[]
  bubble_color: string
  greeting_message: string
  offline_message: string
  proactive_trigger_enabled: boolean
  proactive_trigger_delay_seconds: number
  proactive_trigger_message: string | null
  embed_snippet: string
}

const settings = ref<WebchatSettings | null>(null)
const loading = ref(false)
const loadError = ref('')
const saving = ref(false)
const saveError = ref('')
const saveSuccess = ref('')
const newOrigin = ref('')
const copied = ref(false)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    settings.value = await $api<WebchatSettings>('/v1/webchat/settings')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load website chat settings.')
  }
  finally {
    loading.value = false
  }
}

function addOrigin() {
  if (!settings.value)
    return
  const value = newOrigin.value.trim()
  if (!value)
    return
  if (!settings.value.allowed_origins.includes(value))
    settings.value.allowed_origins.push(value)
  newOrigin.value = ''
}

function removeOrigin(origin: string) {
  if (!settings.value)
    return
  settings.value.allowed_origins = settings.value.allowed_origins.filter(o => o !== origin)
}

async function save() {
  if (!settings.value)
    return
  saving.value = true
  saveError.value = ''
  saveSuccess.value = ''
  try {
    settings.value = await $api<WebchatSettings>('/v1/webchat/settings', {
      method: 'PUT',
      body: {
        enabled: settings.value.enabled,
        allowed_origins: settings.value.allowed_origins,
        bubble_color: settings.value.bubble_color,
        greeting_message: settings.value.greeting_message,
        offline_message: settings.value.offline_message,
        proactive_trigger_enabled: settings.value.proactive_trigger_enabled,
        proactive_trigger_delay_seconds: settings.value.proactive_trigger_delay_seconds,
        proactive_trigger_message: settings.value.proactive_trigger_message,
      },
    })
    saveSuccess.value = 'Saved.'
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save website chat settings.')
  }
  finally {
    saving.value = false
  }
}

async function copySnippet() {
  if (!settings.value?.embed_snippet)
    return
  await navigator.clipboard.writeText(settings.value.embed_snippet)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

onMounted(load)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-1">
    <h1 class="text-h4 mb-0">
      Website Chat
    </h1>
    <RouterLink to="/webchat-inbox" class="font-weight-medium">
      Open inbox
    </RouterLink>
  </div>
  <p class="text-medium-emphasis mb-6">
    A live chat widget your customers embed on their own website — visitor messages land in this same inbox, alongside WhatsApp and email.
  </p>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>
  <VAlert v-if="saveError" type="error" variant="tonal" class="mb-4" closable @click:close="saveError = ''">
    {{ saveError }}
  </VAlert>
  <VAlert v-if="saveSuccess" type="success" variant="tonal" class="mb-4" closable @click:close="saveSuccess = ''">
    {{ saveSuccess }}
  </VAlert>

  <VProgressLinear v-if="loading" indeterminate color="primary" class="mb-4" />

  <VRow v-if="settings">
    <VCol cols="12" md="7">
      <VCard class="mb-6">
        <VCardText>
          <div class="d-flex align-center justify-space-between mb-4">
            <h2 class="text-h6">
              Widget
            </h2>
            <VSwitch v-model="settings.enabled" label="Enabled" hide-details />
          </div>

          <AppTextField
            v-model="settings.greeting_message"
            label="Greeting message"
            class="mb-4"
          />
          <AppTextField
            v-model="settings.offline_message"
            label="Offline message"
            class="mb-4"
          />
          <AppTextField
            v-model="settings.bubble_color"
            label="Bubble color"
            type="color"
            class="mb-4"
          />

          <p class="text-body-2 text-medium-emphasis mb-2">
            Allowed domains — the widget only works when embedded on one of these origins (e.g. <code>https://example.com</code>).
          </p>
          <div class="d-flex gap-2 mb-2">
            <AppTextField v-model="newOrigin" placeholder="https://example.com" density="compact" @keydown.enter.prevent="addOrigin" />
            <VBtn variant="outlined" @click="addOrigin">
              Add
            </VBtn>
          </div>
          <div class="d-flex flex-wrap gap-2 mb-4">
            <VChip v-for="origin in settings.allowed_origins" :key="origin" closable @click:close="removeOrigin(origin)">
              {{ origin }}
            </VChip>
            <p v-if="!settings.allowed_origins.length" class="text-caption text-medium-emphasis mb-0">
              No domains added yet — the widget will not load anywhere until you add one.
            </p>
          </div>

          <VDivider class="mb-4" />

          <div class="d-flex align-center justify-space-between mb-2">
            <span class="text-body-1">Proactive greeting</span>
            <VSwitch v-model="settings.proactive_trigger_enabled" hide-details />
          </div>
          <template v-if="settings.proactive_trigger_enabled">
            <AppTextField
              v-model.number="settings.proactive_trigger_delay_seconds"
              type="number"
              label="Show after (seconds)"
              class="mb-4"
            />
            <AppTextField
              v-model="settings.proactive_trigger_message"
              label="Proactive message"
              class="mb-4"
            />
          </template>

          <VBtn :loading="saving" @click="save">
            Save
          </VBtn>
        </VCardText>
      </VCard>
    </VCol>

    <VCol cols="12" md="5">
      <VCard>
        <VCardText>
          <h2 class="text-h6 mb-3">
            Embed on your website
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Paste this snippet just before the closing <code>&lt;/body&gt;</code> tag on any page you want the chat widget to appear on.
          </p>
          <VTextarea
            :model-value="settings.embed_snippet"
            readonly
            rows="3"
            class="mb-3"
          />
          <VBtn variant="outlined" :disabled="!settings.embed_snippet" @click="copySnippet">
            {{ copied ? 'Copied' : 'Copy snippet' }}
          </VBtn>
          <VAlert v-if="!settings.embed_snippet" type="warning" variant="tonal" density="compact" class="mt-4">
            Set Platform Settings &gt; Company &gt; Public API base URL before this snippet can be generated.
          </VAlert>
        </VCardText>
      </VCard>
    </VCol>
  </VRow>
</template>
