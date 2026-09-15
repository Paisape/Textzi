<script setup lang="ts">
definePage({
  meta: {
    layout: 'blank',
    public: true,
  },
})

type CustomField = { id: string, name: string, field_type: 'text' | 'number' | 'date' | 'dropdown', options: string[], required: boolean }
type PublicWebForm = { enabled: boolean, name: string, fields: string[], custom_fields: CustomField[] }

const route = useRoute()
const formId = route.params.id as string

const form = ref<PublicWebForm | null>(null)
const loading = ref(true)
const loadError = ref('')

const values = reactive<Record<string, string>>({})
const turnstileToken = ref('')
const turnstileRef = ref<InstanceType<typeof TurnstileWidget>>()
const submitting = ref(false)
const submitError = ref('')
const submitted = ref(false)
const successMessage = ref('')

const FIELD_LABELS: Record<string, string> = {
  name: 'Name', email: 'Email', phone: 'Phone', message: 'Message', company: 'Company',
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    form.value = await $api<PublicWebForm>(`/v1/public/lead-form/${formId}`)
    for (const field of form.value.fields)
      values[field] = ''
    for (const field of form.value.custom_fields)
      values[field.name] = ''
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'This form is not available.')
  }
  finally {
    loading.value = false
  }
}

async function submit() {
  if (!form.value)
    return
  submitError.value = ''
  const missingRequired = form.value.custom_fields.find(f => f.required && !values[f.name]?.trim())
  if (!values.name?.trim()) {
    submitError.value = 'Name is required.'
    return
  }
  if (missingRequired) {
    submitError.value = `${missingRequired.name} is required.`
    return
  }
  submitting.value = true
  try {
    const result = await $api<{ message: string }>(`/v1/public/lead-form/${formId}/submit`, {
      method: 'POST',
      body: { values, turnstile_token: turnstileToken.value },
    })
    successMessage.value = result.message
    submitted.value = true
  }
  catch (error: any) {
    submitError.value = extractErrorMessage(error, 'Could not submit this form. Please try again.')
    turnstileRef.value?.reset()
  }
  finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="pa-4">
    <VProgressCircular v-if="loading" indeterminate color="primary" />

    <VAlert v-else-if="loadError" type="error" variant="tonal">
      {{ loadError }}
    </VAlert>

    <VAlert v-else-if="submitted" type="success" variant="tonal">
      {{ successMessage }}
    </VAlert>

    <div v-else-if="form">
      <h2 class="text-h6 mb-3">
        {{ form.name }}
      </h2>
      <VAlert v-if="submitError" type="error" variant="tonal" density="compact" class="mb-3">
        {{ submitError }}
      </VAlert>
      <VTextField
        v-for="field in form.fields" :key="field"
        v-model="values[field]" :label="FIELD_LABELS[field] || field" density="compact" class="mb-3"
      />
      <template v-for="field in form.custom_fields" :key="field.id">
        <VSelect
          v-if="field.field_type === 'dropdown'"
          v-model="values[field.name]" :label="field.name" :items="field.options" density="compact" class="mb-3"
        />
        <VTextField
          v-else
          v-model="values[field.name]" :label="field.name" :type="field.field_type === 'number' ? 'number' : field.field_type === 'date' ? 'date' : 'text'"
          density="compact" class="mb-3"
        />
      </template>
      <TurnstileWidget id="turnstile-lead-form" ref="turnstileRef" v-model="turnstileToken" class="mb-3" />
      <VBtn color="primary" block :loading="submitting" @click="submit">
        Submit
      </VBtn>
    </div>
  </div>
</template>
