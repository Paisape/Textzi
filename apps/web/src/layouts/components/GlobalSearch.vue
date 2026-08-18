<script setup lang="ts">
import { getRecentlyViewed, recentlyViewedIcon, recentlyViewedPath, type RecentlyViewedEntry } from '@/composables/useRecentlyViewed'

type SearchRow = { id: string, label: string, sublabel: string | null }
type SearchResults = { leads: SearchRow[], deals: SearchRow[], contacts: SearchRow[], companies: SearchRow[] }

const GROUPS: { key: keyof SearchResults, label: string, path: string, icon: string }[] = [
  { key: 'leads', label: 'Leads', path: '/crm-leads', icon: 'tabler-target-arrow' },
  { key: 'deals', label: 'Deals', path: '/crm-deals', icon: 'tabler-briefcase' },
  { key: 'contacts', label: 'Contacts', path: '/crm-contacts', icon: 'tabler-user' },
  { key: 'companies', label: 'Companies', path: '/crm-companies', icon: 'tabler-building' },
]

const router = useRouter()
const query = ref('')
const results = ref<SearchResults | null>(null)
const open = ref(false)
const loading = ref(false)
const recent = ref<RecentlyViewedEntry[]>([])

const hasResults = computed(() => Boolean(results.value && GROUPS.some(g => results.value![g.key].length)))

let searchTimer: ReturnType<typeof setTimeout> | undefined
watch(query, (value) => {
  clearTimeout(searchTimer)
  if (value.trim().length < 2) {
    results.value = null
    recent.value = getRecentlyViewed()
    open.value = recent.value.length > 0
    return
  }
  searchTimer = setTimeout(async () => {
    loading.value = true
    try {
      results.value = await $api<SearchResults>('/v1/crm/search', { params: { q: value.trim() } })
      open.value = true
    }
    catch {
      results.value = null
    }
    finally {
      loading.value = false
    }
  }, 250)
})

// The activator slot's own props already toggle `open` on click (that's what v-bind="menuProps"
// is for) -- reacting to `open` becoming true, rather than trying to also set it from a focus
// handler, avoids racing that click-driven toggle (focus fires before click, so setting `open`
// from @focus was getting immediately flipped back off by the click's own toggle right after).
watch(open, (isOpen) => {
  if (isOpen && !query.value.trim())
    recent.value = getRecentlyViewed()
})

function select(groupPath: string, id: string) {
  open.value = false
  query.value = ''
  results.value = null
  router.push(`${groupPath}/${id}`)
}

function selectRecent(entry: RecentlyViewedEntry) {
  open.value = false
  query.value = ''
  router.push(recentlyViewedPath(entry))
}
</script>

<template>
  <VMenu v-model="open" :close-on-content-click="false" location="bottom start" min-width="320">
    <template #activator="{ props: menuProps }">
      <VTextField
        v-bind="menuProps"
        v-model="query"
        placeholder="Search leads, deals, contacts..."
        prepend-inner-icon="tabler-search"
        density="compact" hide-details variant="outlined" clearable
        style="max-width: 280px;"
      />
    </template>
    <VCard max-width="360" max-height="420" class="overflow-y-auto">
      <VProgressLinear v-if="loading" indeterminate />
      <template v-if="!query.trim() && recent.length">
        <VList density="compact">
          <VListSubheader>Recently viewed</VListSubheader>
          <VListItem v-for="entry in recent" :key="`${entry.type}-${entry.id}`" @click="selectRecent(entry)">
            <template #prepend>
              <VIcon :icon="recentlyViewedIcon(entry)" size="16" />
            </template>
            <VListItemTitle>{{ entry.label }}</VListItemTitle>
            <VListItemSubtitle v-if="entry.sublabel">
              {{ entry.sublabel }}
            </VListItemSubtitle>
          </VListItem>
        </VList>
      </template>
      <template v-else-if="results">
        <template v-for="group in GROUPS" :key="group.key">
          <VList v-if="results[group.key].length" density="compact">
            <VListSubheader>{{ group.label }}</VListSubheader>
            <VListItem v-for="row in results[group.key]" :key="row.id" @click="select(group.path, row.id)">
              <template #prepend>
                <VIcon :icon="group.icon" size="16" />
              </template>
              <VListItemTitle>{{ row.label }}</VListItemTitle>
              <VListItemSubtitle v-if="row.sublabel">
                {{ row.sublabel }}
              </VListItemSubtitle>
            </VListItem>
          </VList>
        </template>
        <p v-if="!hasResults && !loading" class="text-medium-emphasis text-center pa-4 mb-0">
          No results.
        </p>
      </template>
    </VCard>
  </VMenu>
</template>
