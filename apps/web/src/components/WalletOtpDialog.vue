<script setup lang="ts">
defineProps<{
  modelValue: boolean
  code: string
  error: string
  submitting: boolean
  sentVia: 'mobile' | 'email' | null
  maskedDestination: string
}>()

const emit = defineEmits<{
  'update:modelValue': [boolean]
  'update:code': [string]
  submit: []
  cancel: []
}>()
</script>

<template>
  <VDialog
    :model-value="modelValue"
    max-width="420"
    persistent
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
  >
    <VCard title="Confirm this payment">
      <VCardText>
        <p class="text-body-2 text-medium-emphasis mb-4">
          We sent a 6-digit code to your {{ sentVia === 'mobile' ? 'mobile number' : 'email' }}
          ending in <strong>{{ maskedDestination }}</strong>. It expires in 10 minutes.
        </p>
        <VAlert v-if="error" type="error" variant="tonal" density="compact" class="mb-4">
          {{ error }}
        </VAlert>
        <VForm @submit.prevent="emit('submit')">
          <AppTextField
            :model-value="code"
            label="Verification code"
            placeholder="123456"
            maxlength="8"
            autofocus
            class="mb-4"
            @update:model-value="(v: string) => emit('update:code', v)"
          />
          <div class="d-flex gap-3">
            <VBtn type="submit" :loading="submitting">
              Confirm
            </VBtn>
            <VBtn variant="text" :disabled="submitting" @click="emit('cancel')">
              Cancel
            </VBtn>
          </div>
        </VForm>
      </VCardText>
    </VCard>
  </VDialog>
</template>
