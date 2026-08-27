import { createHead } from '@unhead/vue/client'
import type { App } from 'vue'

export default function (app: App) {
  app.use(createHead())
}
