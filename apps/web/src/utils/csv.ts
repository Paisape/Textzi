/** Client-side CSV export -- the data driving these exports (customers, invoices, usage) is
 * already fetched into the page as JSON, so there's no reason to round-trip to a new backend
 * endpoint just to reformat what's already in memory. */
function csvEscape(value: unknown): string {
  const text = value === null || value === undefined ? '' : String(value)
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

export function downloadCsv(filename: string, columns: { key: string, label: string }[], rows: Record<string, unknown>[]): void {
  const header = columns.map(c => csvEscape(c.label)).join(',')
  const body = rows.map(row => columns.map(c => csvEscape(row[c.key])).join(',')).join('\n')
  const blob = new Blob([`${header}\n${body}`], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
