<script setup lang="ts">
import { Image } from '@tiptap/extension-image'
import { Placeholder } from '@tiptap/extension-placeholder'
import { TextAlign } from '@tiptap/extension-text-align'
import { Underline } from '@tiptap/extension-underline'
import { StarterKit } from '@tiptap/starter-kit'
import { EditorContent, useEditor } from '@tiptap/vue-3'

const props = defineProps<{
  modelValue: string
  placeholder?: string
  allowImage?: boolean
  // A single-row, small icon-only toolbar matching the WhatsApp inbox composer's compact style
  // (inbox.vue's bold/italic/strikethrough row) instead of this component's own boxed two-row
  // toolbar -- visual only, same rich-text/HTML editing underneath. Opt-in so the email composer
  // (crm-email.vue), which also uses this component, keeps its current look unchanged.
  compact?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const editorRef = ref()
const imageInput = ref<HTMLInputElement>()

const editor = useEditor({
  content: props.modelValue,
  extensions: [
    StarterKit,
    TextAlign.configure({
      types: ['heading', 'paragraph'],
    }),
    Placeholder.configure({
      placeholder: props.placeholder ?? 'Write something here...',
    }),
    Underline,
    ...(props.allowImage ? [Image] : []),
  ],
  onUpdate() {
    if (!editor.value)
      return

    emit('update:modelValue', editor.value.getHTML())
  },
})

function pickImage() {
  imageInput.value?.click()
}

function onImageSelected(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file || !editor.value)
    return
  const reader = new FileReader()
  reader.onload = () => {
    editor.value?.chain().focus().setImage({ src: reader.result as string }).run()
  }
  reader.readAsDataURL(file)
  ;(event.target as HTMLInputElement).value = ''
}

watch(() => props.modelValue, () => {
  const isSame = editor.value?.getHTML() === props.modelValue

  if (isSame)
    return

  editor.value?.commands.setContent(props.modelValue)
})
</script>

<template>
  <div>
    <!-- Compact toolbar (webchat-inbox.vue): a single row of small text-variant icon buttons,
    matching the WhatsApp inbox composer's own bold/italic/strikethrough row (inbox.vue) --
    formatting-only, no alignment/image controls, since a chat reply has no use for either. -->
    <div
      v-if="editor && compact"
      class="d-flex align-center ga-1 mb-1"
    >
      <VBtn
        size="x-small"
        variant="text"
        icon="tabler-bold"
        :color="editor.isActive('bold') ? 'primary' : 'default'"
        @click="editor.chain().focus().toggleBold().run()"
      />
      <VBtn
        size="x-small"
        variant="text"
        icon="tabler-italic"
        :color="editor.isActive('italic') ? 'primary' : 'default'"
        @click="editor.chain().focus().toggleItalic().run()"
      />
      <VBtn
        size="x-small"
        variant="text"
        icon="tabler-strikethrough"
        :color="editor.isActive('strike') ? 'primary' : 'default'"
        @click="editor.chain().focus().toggleStrike().run()"
      />
    </div>

    <div
      v-else-if="editor"
      class="d-flex gap-2 py-2 px-6 flex-wrap align-center editor"
    >
      <IconBtn
        size="small"
        rounded
        :variant="editor.isActive('bold') ? 'tonal' : 'text'"
        :color="editor.isActive('bold') ? 'primary' : 'default'"
        @click="editor.chain().focus().toggleBold().run()"
      >
        <VIcon icon="tabler-bold" />
      </IconBtn>

      <IconBtn
        size="small"
        rounded
        :variant="editor.isActive('underline') ? 'tonal' : 'text'"
        :color="editor.isActive('underline') ? 'primary' : 'default'"
        @click="editor.commands.toggleUnderline()"
      >
        <VIcon icon="tabler-underline" />
      </IconBtn>

      <IconBtn
        size="small"
        rounded
        :variant="editor.isActive('italic') ? 'tonal' : 'text'"
        :color="editor.isActive('italic') ? 'primary' : 'default'"
        @click="editor.chain().focus().toggleItalic().run()"
      >
        <VIcon
          icon="tabler-italic"
          class="font-weight-medium"
        />
      </IconBtn>

      <IconBtn
        size="small"
        rounded
        :variant="editor.isActive('strike') ? 'tonal' : 'text'"
        :color="editor.isActive('strike') ? 'primary' : 'default'"
        @click="editor.chain().focus().toggleStrike().run()"
      >
        <VIcon icon="tabler-strikethrough" />
      </IconBtn>

      <IconBtn
        size="small"
        rounded
        :variant="editor.isActive({ textAlign: 'left' }) ? 'tonal' : 'text'"
        :color="editor.isActive({ textAlign: 'left' }) ? 'primary' : 'default'"
        @click="editor.chain().focus().setTextAlign('left').run()"
      >
        <VIcon icon="tabler-align-left" />
      </IconBtn>

      <IconBtn
        size="small"
        rounded
        :color="editor.isActive({ textAlign: 'center' }) ? 'primary' : 'default'"
        :variant="editor.isActive({ textAlign: 'center' }) ? 'tonal' : 'text'"
        @click="editor.chain().focus().setTextAlign('center').run()"
      >
        <VIcon icon="tabler-align-center" />
      </IconBtn>

      <IconBtn
        size="small"
        rounded
        :variant="editor.isActive({ textAlign: 'right' }) ? 'tonal' : 'text'"
        :color="editor.isActive({ textAlign: 'right' }) ? 'primary' : 'default'"
        @click="editor.chain().focus().setTextAlign('right').run()"
      >
        <VIcon icon="tabler-align-right" />
      </IconBtn>

      <IconBtn
        size="small"
        rounded
        :variant="editor.isActive({ textAlign: 'justify' }) ? 'tonal' : 'text'"
        :color="editor.isActive({ textAlign: 'justify' }) ? 'primary' : 'default'"
        @click="editor.chain().focus().setTextAlign('justify').run()"
      >
        <VIcon icon="tabler-align-justified" />
      </IconBtn>

      <template v-if="allowImage">
        <IconBtn size="small" rounded @click="pickImage">
          <VIcon icon="tabler-photo" />
        </IconBtn>
        <input ref="imageInput" type="file" accept="image/*" class="d-none" @change="onImageSelected">
      </template>
    </div>

    <VDivider v-if="!compact" />

    <EditorContent
      ref="editorRef"
      :editor="editor"
      :class="{ 'compact-editor': compact }"
    />
  </div>
</template>

<style lang="scss">
.ProseMirror {
  padding: 0.5rem;
  min-block-size: 15vh;
  outline: none;

  img {
    max-inline-size: 100%;
    block-size: auto;
  }

  p {
    margin-block-end: 0;
  }

  p.is-editor-empty:first-child::before {
    block-size: 0;
    color: #adb5bd;
    content: attr(data-placeholder);
    float: inline-start;
    pointer-events: none;
  }
}

// Compact variant (webchat-inbox.vue) -- a chat reply box, not a document editor, so it starts
// at roughly the same height as inbox.vue's own `rows="2"` textarea instead of 15vh.
.compact-editor .ProseMirror {
  min-block-size: 3rem;
  padding: 0.375rem 0.75rem;
}
</style>
