// Title-cases a snake_case/plain enum value for display, except for a small set of known
// acronyms/proper nouns that plain CSS text-transform:capitalize always gets wrong ("Kyc" instead
// of "KYC", "Csv Import" instead of "CSV Import", "Whatsapp" instead of "WhatsApp").
const KNOWN_WORDS: Record<string, string> = {
  kyc: 'KYC',
  csv: 'CSV',
  whatsapp: 'WhatsApp',
  sms: 'SMS',
  gst: 'GST',
  hsn: 'HSN',
  crm: 'CRM',
  sla: 'SLA',
  id: 'ID',
  pdf: 'PDF',
  api: 'API',
}

export function formatLabel(value: string | null | undefined): string {
  if (!value)
    return ''
  return value
    .split(/[_\s]+/)
    .map(word => KNOWN_WORDS[word.toLowerCase()] || (word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()))
    .join(' ')
}
