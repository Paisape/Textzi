// Client-side "recently viewed" tracking for CRM record detail pages -- Zoho/SF both surface this
// in the nav so a rep can jump back to the last few records they touched. No backend needed: this
// is inherently a per-browser convenience, not data anyone else needs to see, so localStorage is
// the right amount of infrastructure for it.
export type RecentlyViewedType = 'lead' | 'deal' | 'contact' | 'company' | 'customer'
export type RecentlyViewedEntry = { type: RecentlyViewedType, id: string, label: string, sublabel?: string | null }

const STORAGE_KEY = 'textzi:recently-viewed'
const MAX_ENTRIES = 8

const GROUP_PATH: Record<RecentlyViewedType, string> = {
  lead: '/crm-leads',
  deal: '/crm-deals',
  contact: '/crm-contacts',
  company: '/crm-companies',
  customer: '/crm-customers',
}

const GROUP_ICON: Record<RecentlyViewedType, string> = {
  lead: 'tabler-target-arrow',
  deal: 'tabler-briefcase',
  contact: 'tabler-user',
  company: 'tabler-building',
  customer: 'tabler-user-check',
}

export function getRecentlyViewed(): RecentlyViewedEntry[] {
  if (typeof window === 'undefined')
    return []
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  }
  catch {
    return []
  }
}

export function addRecentlyViewed(entry: RecentlyViewedEntry) {
  if (typeof window === 'undefined')
    return
  const rest = getRecentlyViewed().filter(e => !(e.type === entry.type && e.id === entry.id))
  const updated = [entry, ...rest].slice(0, MAX_ENTRIES)
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(updated))
}

export function recentlyViewedPath(entry: RecentlyViewedEntry) {
  return `${GROUP_PATH[entry.type]}/${entry.id}`
}

export function recentlyViewedIcon(entry: RecentlyViewedEntry) {
  return GROUP_ICON[entry.type]
}
