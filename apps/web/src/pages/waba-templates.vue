<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type TemplateButton = { type: 'QUICK_REPLY' | 'URL' | 'PHONE_NUMBER', text: string, url?: string, phone_number?: string }
type Template = {
  name: string
  status: string
  language: string
  category: string
  header_text: string | null
  header_format: string
  body: string | null
  footer_text: string | null
  buttons: TemplateButton[]
}

const HEADER_FORMATS = [
  { title: 'Text (or none)', value: 'TEXT' as const },
  { title: 'Image', value: 'IMAGE' as const },
  { title: 'Video', value: 'VIDEO' as const },
  { title: 'Document', value: 'DOCUMENT' as const },
]

const templates = ref<Template[]>([])
const loading = ref(false)
const loadError = ref('')

async function loadTemplates() {
  loading.value = true
  loadError.value = ''
  try {
    templates.value = await $api<Template[]>('/v1/waba/templates')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load templates.')
  }
  finally {
    loading.value = false
  }
}

function statusColor(status: string) {
  if (status === 'APPROVED')
    return 'success'
  if (status === 'REJECTED')
    return 'error'
  return 'warning'
}

async function deleteTemplate(name: string) {
  try {
    await $api(`/v1/waba/templates/${name}`, { method: 'DELETE' })
    templates.value = templates.value.filter(t => t.name !== name)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this template.')
  }
}

// --- Create dialog ---

const createDialog = ref(false)
const createError = ref('')
const creating = ref(false)
const form = ref({
  name: '',
  category: 'UTILITY',
  language: 'en_US',
  header_text: '',
  header_format: 'TEXT' as 'TEXT' | 'IMAGE' | 'VIDEO' | 'DOCUMENT',
  header_file: null as File | null,
  body_text: '',
  example_params: '',
  footer_text: '',
  buttons: [] as TemplateButton[],
})
const headerUploading = ref(false)

const placeholderCount = computed(() => {
  const matches = form.value.body_text.match(/\{\{\d+\}\}/g)
  return matches ? matches.length : 0
})

const quickReplyCount = computed(() => form.value.buttons.filter(b => b.type === 'QUICK_REPLY').length)
const ctaButtonCount = computed(() => form.value.buttons.filter(b => b.type !== 'QUICK_REPLY').length)

function openCreateDialog() {
  form.value = { name: '', category: 'UTILITY', language: 'en_US', header_text: '', header_format: 'TEXT', header_file: null, body_text: '', example_params: '', footer_text: '', buttons: [] }
  createError.value = ''
  createDialog.value = true
}

function addButton(type: TemplateButton['type']) {
  if (form.value.buttons.length >= 10)
    return
  form.value.buttons.push(type === 'URL' ? { type, text: '', url: '' } : type === 'PHONE_NUMBER' ? { type, text: '', phone_number: '' } : { type, text: '' })
}

function removeButton(index: number) {
  form.value.buttons.splice(index, 1)
}

async function createTemplate() {
  if (!form.value.name.trim() || !form.value.body_text.trim())
    return
  if (form.value.header_format !== 'TEXT' && !form.value.header_file) {
    createError.value = 'Upload a sample file for this header type.'
    return
  }
  creating.value = true
  createError.value = ''
  try {
    let headerHandle: string | null = null
    if (form.value.header_format !== 'TEXT' && form.value.header_file) {
      headerUploading.value = true
      const uploadForm = new FormData()
      uploadForm.set('file', form.value.header_file)
      const uploadResult = await $api<{ header_handle: string }>('/v1/waba/templates/header-media', { method: 'POST', body: uploadForm })
      headerHandle = uploadResult.header_handle
      headerUploading.value = false
    }
    const template = await $api<Template>('/v1/waba/templates', {
      method: 'POST',
      body: {
        name: form.value.name.trim(),
        category: form.value.category,
        language: form.value.language,
        header_text: form.value.header_format === 'TEXT' ? (form.value.header_text.trim() || null) : null,
        header_format: form.value.header_format,
        header_handle: headerHandle,
        body_text: form.value.body_text.trim(),
        example_params: form.value.example_params ? form.value.example_params.split(',').map(p => p.trim()).filter(Boolean) : [],
        footer_text: form.value.footer_text.trim() || null,
        buttons: form.value.buttons,
      },
    })
    templates.value.push(template)
    createDialog.value = false
  }
  catch (error: any) {
    createError.value = extractErrorMessage(error, 'Could not submit this template.')
  }
  finally {
    creating.value = false
    headerUploading.value = false
  }
}

function buttonIcon(type: TemplateButton['type']) {
  if (type === 'URL')
    return 'tabler-external-link'
  if (type === 'PHONE_NUMBER')
    return 'tabler-phone'
  return 'tabler-corner-up-left'
}

onMounted(loadTemplates)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-1 flex-wrap ga-3">
    <h1 class="text-h4">
      Templates
    </h1>
    <div class="d-flex ga-3">
      <VBtn variant="tonal" prepend-icon="tabler-refresh" :loading="loading" @click="loadTemplates">
        Sync
      </VBtn>
      <VBtn
        variant="tonal"
        prepend-icon="tabler-external-link"
        href="https://business.facebook.com/"
        target="_blank"
        rel="noopener"
      >
        Open WhatsApp Manager
      </VBtn>
      <VBtn prepend-icon="tabler-plus" @click="openCreateDialog">
        Create template
      </VBtn>
    </div>
  </div>
  <p class="text-medium-emphasis mb-6">
    Pre-approved messages you can send outside WhatsApp's 24-hour reply window. New templates go
    to Meta for review (usually a few minutes to 24 hours) before they're usable -- "Sync" pulls
    the latest status from Meta, and "Open WhatsApp Manager" takes you to Meta's own template
    tools if you'd rather create or review one there directly.
  </p>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>

  <VCard>
    <VTable>
      <thead>
        <tr>
          <th>Name</th>
          <th>Category</th>
          <th>Language</th>
          <th>Status</th>
          <th>Preview</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr v-for="template in templates" :key="template.name + template.language">
          <td>{{ template.name }}</td>
          <td>{{ template.category }}</td>
          <td>{{ template.language }}</td>
          <td>
            <VChip size="small" :color="statusColor(template.status)">
              {{ template.status }}
            </VChip>
          </td>
          <td class="text-truncate" style="max-width: 280px;">
            {{ template.body }}
          </td>
          <td>
            <VBtn size="small" variant="text" icon="tabler-trash" @click="deleteTemplate(template.name)" />
          </td>
        </tr>
      </tbody>
    </VTable>
    <p v-if="!loading && !templates.length" class="text-medium-emphasis text-center pa-6">
      No templates yet.
    </p>
  </VCard>

  <VDialog v-model="createDialog" max-width="880">
    <VCard>
      <VCardTitle>New template</VCardTitle>
      <VCardText>
        <VAlert v-if="createError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ createError }}
        </VAlert>
        <VRow>
          <VCol cols="12" md="7">
            <AppTextField
              v-model="form.name"
              label="Name (lowercase, digits, underscores only)"
              placeholder="order_shipped"
              class="mb-3"
            />
            <VRow>
              <VCol cols="6">
                <VSelect
                  v-model="form.category"
                  label="Category"
                  :items="[{ title: 'Utility', value: 'UTILITY' }, { title: 'Marketing', value: 'MARKETING' }, { title: 'Authentication', value: 'AUTHENTICATION' }]"
                />
              </VCol>
              <VCol cols="6">
                <AppTextField v-model="form.language" label="Language code" placeholder="en_US" />
              </VCol>
            </VRow>
            <VSelect v-model="form.header_format" label="Header type" :items="HEADER_FORMATS" class="mb-3" />
            <AppTextField v-if="form.header_format === 'TEXT'" v-model="form.header_text" label="Header text (optional)" placeholder="Order Update" :maxlength="60" class="mb-3" />
            <VFileInput
              v-else
              v-model="form.header_file" :label="`Sample ${form.header_format.toLowerCase()} for review`" :loading="headerUploading"
              :accept="form.header_format === 'IMAGE' ? 'image/*' : form.header_format === 'VIDEO' ? 'video/*' : undefined"
              class="mb-3"
            />
            <VTextarea
              v-model="form.body_text"
              label="Body"
              placeholder="Hi {{1}}, your order {{2}} has shipped."
              rows="3"
              :maxlength="1024"
              class="mb-3"
            />
            <AppTextField
              v-if="placeholderCount > 0"
              v-model="form.example_params"
              :label="`Example values for {{1}}..{{${placeholderCount}}} (comma-separated)`"
              placeholder="Priya, TX-4482"
              class="mb-3"
            />
            <AppTextField v-model="form.footer_text" label="Footer (optional)" placeholder="Thank you for shopping with us" :maxlength="60" class="mb-3" />

            <p class="text-body-2 text-medium-emphasis mb-2">
              Buttons (optional, up to 10 -- quick-reply buttons can't be mixed with URL/phone buttons)
            </p>
            <div v-for="(button, i) in form.buttons" :key="i" class="d-flex align-center ga-2 mb-2">
              <VChip size="small" class="flex-shrink-0" style="width: 110px;">
                {{ button.type.replace('_', ' ') }}
              </VChip>
              <AppTextField v-model="button.text" placeholder="Button label" :maxlength="25" density="compact" hide-details />
              <AppTextField v-if="button.type === 'URL'" v-model="button.url" placeholder="https://..." density="compact" hide-details />
              <AppTextField v-if="button.type === 'PHONE_NUMBER'" v-model="button.phone_number" placeholder="+91..." density="compact" hide-details />
              <VBtn size="small" variant="text" icon="tabler-trash" @click="removeButton(i)" />
            </div>
            <div class="d-flex ga-2">
              <VBtn size="small" variant="tonal" :disabled="ctaButtonCount > 0 || form.buttons.length >= 10" @click="addButton('QUICK_REPLY')">
                Add quick reply
              </VBtn>
              <VBtn size="small" variant="tonal" :disabled="quickReplyCount > 0 || ctaButtonCount >= 2" @click="addButton('URL')">
                Add URL button
              </VBtn>
              <VBtn size="small" variant="tonal" :disabled="quickReplyCount > 0 || form.buttons.some(b => b.type === 'PHONE_NUMBER')" @click="addButton('PHONE_NUMBER')">
                Add phone button
              </VBtn>
            </div>
          </VCol>

          <VCol cols="12" md="5">
            <p class="text-body-2 text-medium-emphasis mb-2">
              Preview
            </p>
            <div class="template-preview">
              <p v-if="form.header_text" class="template-preview-header">
                {{ form.header_text }}
              </p>
              <p class="template-preview-body">
                {{ form.body_text || 'Your message body will appear here.' }}
              </p>
              <p v-if="form.footer_text" class="template-preview-footer">
                {{ form.footer_text }}
              </p>
              <div v-if="form.buttons.length" class="template-preview-buttons">
                <div v-for="(button, i) in form.buttons" :key="i" class="template-preview-button">
                  <VIcon :icon="buttonIcon(button.type)" size="16" class="me-1" />
                  {{ button.text || 'Button' }}
                </div>
              </div>
            </div>
          </VCol>
        </VRow>
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="createDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="creating" @click="createTemplate">
          Submit for review
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>
</template>

<style scoped>
.template-preview {
  border-radius: 8px;
  background: rgba(var(--v-theme-on-surface), 0.04);
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  padding: 12px 14px;
}

.template-preview-header {
  font-weight: 600;
  margin-bottom: 4px;
}

.template-preview-body {
  white-space: pre-wrap;
  margin-bottom: 4px;
}

.template-preview-footer {
  font-size: 0.75rem;
  opacity: 0.6;
  margin-bottom: 0;
}

.template-preview-buttons {
  margin-top: 8px;
  border-top: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  padding-top: 4px;
}

.template-preview-button {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px 4px;
  color: rgb(var(--v-theme-primary));
  font-size: 0.875rem;
}
</style>
