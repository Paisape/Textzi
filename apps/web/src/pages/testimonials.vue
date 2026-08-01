<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type MyTestimonial = { id: string, author_name: string, author_role: string, quote: string, status: string, created_at: string }

const STATUS_COLORS: Record<string, string> = { pending: 'warning', approved: 'success', rejected: 'error' }
const STATUS_LABELS: Record<string, string> = { pending: 'Pending review', approved: 'Published', rejected: 'Not published' }

const mine = ref<MyTestimonial[]>([])
const loadError = ref('')
const loading = ref(false)

const form = ref({ author_name: '', author_role: '', quote: '' })
const submitting = ref(false)
const submitError = ref('')
const submitSuccess = ref('')

async function load() {
  loadError.value = ''
  loading.value = true
  try {
    mine.value = await $api<MyTestimonial[]>('/v1/testimonials/mine')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load your testimonials.')
  }
  finally {
    loading.value = false
  }
}

async function onSubmit() {
  submitError.value = ''
  submitSuccess.value = ''
  submitting.value = true
  try {
    await $api('/v1/testimonials', { method: 'POST', body: form.value })
    submitSuccess.value = 'Thanks! Your testimonial is pending review and will appear on our site once approved.'
    form.value = { author_name: '', author_role: '', quote: '' }
    await load()
  }
  catch (error: any) {
    submitError.value = extractErrorMessage(error, 'Could not submit your testimonial.')
  }
  finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Share a Testimonial
  </h1>
  <p class="text-medium-emphasis mb-6">
    Tell other businesses about your experience with Textzi. Submissions are reviewed by our team
    before appearing on the public site.
  </p>

  <VRow>
    <VCol cols="12" md="6">
      <VCard title="Submit a testimonial">
        <VCardText>
          <VAlert v-if="submitError" type="error" variant="tonal" density="compact" class="mb-4" closable @click:close="submitError = ''">
            {{ submitError }}
          </VAlert>
          <VAlert v-if="submitSuccess" type="success" variant="tonal" density="compact" class="mb-4" closable @click:close="submitSuccess = ''">
            {{ submitSuccess }}
          </VAlert>

          <VForm @submit.prevent="onSubmit">
            <VRow>
              <VCol cols="12">
                <AppTextField
                  v-model="form.author_name"
                  label="Your name"
                  placeholder="Ananya Rao"
                />
              </VCol>
              <VCol cols="12">
                <AppTextField
                  v-model="form.author_role"
                  label="Role & company"
                  placeholder="Founder, UrbanCart"
                />
              </VCol>
              <VCol cols="12">
                <AppTextarea
                  v-model="form.quote"
                  label="Your testimonial"
                  placeholder="How has Textzi helped your business?"
                  rows="4"
                />
              </VCol>
              <VCol cols="12">
                <VBtn type="submit" :loading="submitting">
                  Submit for review
                </VBtn>
              </VCol>
            </VRow>
          </VForm>
        </VCardText>
      </VCard>
    </VCol>

    <VCol cols="12" md="6">
      <VCard title="Your submissions">
        <VCardText>
          <VAlert v-if="loadError" type="error" variant="tonal" density="compact">
            {{ loadError }}
          </VAlert>
          <p v-else-if="!loading && !mine.length" class="text-medium-emphasis">
            You haven't submitted a testimonial yet.
          </p>
          <VList v-else lines="three">
            <VListItem v-for="t in mine" :key="t.id">
              <template #append>
                <VChip size="small" :color="STATUS_COLORS[t.status] ?? 'default'">
                  {{ STATUS_LABELS[t.status] ?? t.status }}
                </VChip>
              </template>
              <VListItemTitle>{{ t.author_name }} — {{ t.author_role }}</VListItemTitle>
              <VListItemSubtitle class="text-wrap">
                "{{ t.quote }}"
              </VListItemSubtitle>
            </VListItem>
          </VList>
        </VCardText>
      </VCard>
    </VCol>
  </VRow>
</template>
