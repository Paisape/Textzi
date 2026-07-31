<script setup lang="ts">
defineProps<{
  modelValue: boolean
  code: string
  error: string
  submitting: boolean
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
    <VCard title="Confirm it's you">
      <VCardText>
        <p class="text-body-2 text-medium-emphasis mb-4">
          This is a sensitive settings area -- enter the current code from your authenticator app
          to continue.
        </p>
        <VAlert
          v-if="error"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ error }}
        </VAlert>
        <AppTextField
          :model-value="code"
          label="Authenticator code"
          placeholder="123456"
          maxlength="6"
          autofocus
          @update:model-value="(v: string) => emit('update:code', v)"
          @keyup.enter="emit('submit')"
        />
      </VCardText>
      <VCardText class="d-flex gap-3 justify-end">
        <VBtn
          variant="tonal"
          @click="emit('cancel')"
        >
          Cancel
        </VBtn>
        <VBtn
          :loading="submitting"
          @click="emit('submit')"
        >
          Verify
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>
</template>
