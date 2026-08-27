<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

type CrmSettings = {
  pipeline_stages: string[]
  notify_email: boolean
  notify_sms: boolean
  notify_whatsapp: boolean
  logo_url: string | null
  brand_color: string | null
  quote_approval_threshold: number | null
  quote_approver_user_ids: string[]
}

const route = useRoute()
const activeTab = ref<'notifications' | 'branding' | 'company' | 'fields' | 'scoring' | 'territories' | 'targets' | 'team' | 'webform' | 'billing' | 'channels' | 'helpdesk' | 'approvals' | 'products' | 'documents'>(
  route.query.tab === 'helpdesk' ? 'helpdesk' : 'notifications',
)

const settings = ref<CrmSettings | null>(null)
const loading = ref(false)
const loadError = ref('')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    settings.value = await $api<CrmSettings>('/v1/crm/settings')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load CRM settings.')
  }
  finally {
    loading.value = false
  }
}

// --- Notifications ---

const notifyForm = ref({ notify_email: false, notify_sms: false, notify_whatsapp: false, brand_color: '' })
const notifySaving = ref(false)
const notifyError = ref('')
const notifySaved = ref(false)

watch(settings, value => {
  if (value)
    notifyForm.value = { notify_email: value.notify_email, notify_sms: value.notify_sms, notify_whatsapp: value.notify_whatsapp, brand_color: value.brand_color || '' }
}, { immediate: true })

async function saveNotifications() {
  notifySaving.value = true
  notifyError.value = ''
  notifySaved.value = false
  try {
    settings.value = await $api<CrmSettings>('/v1/crm/settings', {
      method: 'PUT',
      body: { notify_email: notifyForm.value.notify_email, notify_sms: notifyForm.value.notify_sms, notify_whatsapp: notifyForm.value.notify_whatsapp, brand_color: settings.value?.brand_color || null },
    })
    notifySaved.value = true
  }
  catch (error: any) {
    notifyError.value = extractErrorMessage(error, 'Could not save notification settings.')
  }
  finally {
    notifySaving.value = false
  }
}

// --- Branding ---

const brandColorForm = ref('')
const brandSaving = ref(false)
const brandError = ref('')
const brandSaved = ref(false)
const logoUploading = ref(false)
const logoError = ref('')

watch(settings, value => {
  if (value)
    brandColorForm.value = value.brand_color || ''
}, { immediate: true })

async function saveBrandColor() {
  brandSaving.value = true
  brandError.value = ''
  brandSaved.value = false
  try {
    settings.value = await $api<CrmSettings>('/v1/crm/settings', {
      method: 'PUT',
      body: {
        notify_email: settings.value?.notify_email || false,
        notify_sms: settings.value?.notify_sms || false,
        notify_whatsapp: settings.value?.notify_whatsapp || false,
        brand_color: brandColorForm.value || null,
      },
    })
    brandSaved.value = true
  }
  catch (error: any) {
    brandError.value = extractErrorMessage(error, 'Could not save brand color.')
  }
  finally {
    brandSaving.value = false
  }
}

async function uploadLogo(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file)
    return
  logoUploading.value = true
  logoError.value = ''
  try {
    const formData = new FormData()
    formData.append('logo', file)
    settings.value = await $api<CrmSettings>('/v1/crm/settings/logo', { method: 'POST', body: formData })
  }
  catch (error: any) {
    logoError.value = extractErrorMessage(error, 'Could not upload this logo.')
  }
  finally {
    logoUploading.value = false
  }
}

// --- Quote approvals ---

const approvalsForm = ref({ quote_approval_threshold: null as number | null, quote_approver_user_ids: [] as string[] })
const approvalsSaving = ref(false)
const approvalsError = ref('')
const approvalsSaved = ref(false)

watch(settings, value => {
  if (value)
    approvalsForm.value = { quote_approval_threshold: value.quote_approval_threshold, quote_approver_user_ids: [...value.quote_approver_user_ids] }
}, { immediate: true })

async function saveApprovals() {
  approvalsSaving.value = true
  approvalsError.value = ''
  approvalsSaved.value = false
  try {
    settings.value = await $api<CrmSettings>('/v1/crm/settings', {
      method: 'PUT',
      body: {
        notify_email: settings.value?.notify_email || false,
        notify_sms: settings.value?.notify_sms || false,
        notify_whatsapp: settings.value?.notify_whatsapp || false,
        brand_color: settings.value?.brand_color || null,
        quote_approval_threshold: approvalsForm.value.quote_approval_threshold,
        quote_approver_user_ids: approvalsForm.value.quote_approver_user_ids,
      },
    })
    approvalsSaved.value = true
  }
  catch (error: any) {
    approvalsError.value = extractErrorMessage(error, 'Could not save quote approval settings.')
  }
  finally {
    approvalsSaving.value = false
  }
}

// --- Products (CPQ price list) ---

type Product = { id: string, name: string, sku: string | null, hsn_code: string, unit_price: number, description: string | null, active: boolean }

const products = ref<Product[]>([])
const productDialog = ref(false)
const productForm = reactive({ name: '', sku: '', hsn_code: '', unit_price: 0, description: '' })
const productSaving = ref(false)
const productError = ref('')
const editingProductId = ref<string | null>(null)

async function loadProducts() {
  try {
    products.value = await $api<Product[]>('/v1/crm/quotes/products')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load products.')
  }
}

function openProductDialog() {
  editingProductId.value = null
  productForm.name = ''
  productForm.sku = ''
  productForm.hsn_code = ''
  productForm.unit_price = 0
  productForm.description = ''
  productError.value = ''
  productDialog.value = true
}

function openEditProductDialog(product: Product) {
  editingProductId.value = product.id
  productForm.name = product.name
  productForm.sku = product.sku || ''
  productForm.hsn_code = product.hsn_code
  productForm.unit_price = product.unit_price
  productForm.description = product.description || ''
  productError.value = ''
  productDialog.value = true
}

async function saveProduct() {
  if (!productForm.name.trim())
    return
  productSaving.value = true
  productError.value = ''
  try {
    const body = {
      name: productForm.name.trim(), sku: productForm.sku.trim() || null, hsn_code: productForm.hsn_code.trim(),
      unit_price: productForm.unit_price, description: productForm.description.trim() || null,
    }
    if (editingProductId.value) {
      const updated = await $api<Product>(`/v1/crm/quotes/products/${editingProductId.value}`, { method: 'PATCH', body })
      const index = products.value.findIndex(p => p.id === editingProductId.value)
      if (index !== -1)
        products.value[index] = updated
    }
    else {
      products.value.push(await $api<Product>('/v1/crm/quotes/products', { method: 'POST', body }))
    }
    productDialog.value = false
  }
  catch (error: any) {
    productError.value = extractErrorMessage(error, 'Could not save this product.')
  }
  finally {
    productSaving.value = false
  }
}

const togglingProductId = ref<string | null>(null)

async function toggleProductActive(product: Product) {
  togglingProductId.value = product.id
  try {
    const updated = await $api<Product>(`/v1/crm/quotes/products/${product.id}`, { method: 'PATCH', body: { active: !product.active } })
    product.active = updated.active
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this product.')
  }
  finally {
    togglingProductId.value = null
  }
}

const deletingProductId = ref<string | null>(null)

async function deleteProduct(product: Product) {
  deletingProductId.value = product.id
  try {
    await $api(`/v1/crm/quotes/products/${product.id}`, { method: 'DELETE' })
    products.value = products.value.filter(p => p.id !== product.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this product.')
  }
  finally {
    deletingProductId.value = null
  }
}

// --- Document templates ---

type DocumentTemplate = { id: string, name: string, applies_to: string, body: string }

const documentTemplates = ref<DocumentTemplate[]>([])
const documentDialog = ref(false)
const documentForm = reactive({ name: '', applies_to: 'proposal', body: '' })
const documentSaving = ref(false)
const documentError = ref('')
const editingDocumentId = ref<string | null>(null)

async function loadDocumentTemplates() {
  try {
    documentTemplates.value = await $api<DocumentTemplate[]>('/v1/crm/document-templates')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load document templates.')
  }
}

function openDocumentDialog() {
  editingDocumentId.value = null
  documentForm.name = ''
  documentForm.applies_to = 'proposal'
  documentForm.body = ''
  documentError.value = ''
  documentDialog.value = true
}

function openEditDocumentDialog(template: DocumentTemplate) {
  editingDocumentId.value = template.id
  documentForm.name = template.name
  documentForm.applies_to = template.applies_to
  documentForm.body = template.body
  documentError.value = ''
  documentDialog.value = true
}

async function saveDocumentTemplate() {
  if (!documentForm.name.trim() || !documentForm.body.trim())
    return
  documentSaving.value = true
  documentError.value = ''
  try {
    const body = { name: documentForm.name.trim(), applies_to: documentForm.applies_to, body: documentForm.body }
    if (editingDocumentId.value) {
      const updated = await $api<DocumentTemplate>(`/v1/crm/document-templates/${editingDocumentId.value}`, { method: 'PATCH', body })
      const index = documentTemplates.value.findIndex(t => t.id === editingDocumentId.value)
      if (index !== -1)
        documentTemplates.value[index] = updated
    }
    else {
      documentTemplates.value.push(await $api<DocumentTemplate>('/v1/crm/document-templates', { method: 'POST', body }))
    }
    documentDialog.value = false
  }
  catch (error: any) {
    documentError.value = extractErrorMessage(error, 'Could not save this document template.')
  }
  finally {
    documentSaving.value = false
  }
}

const deletingDocumentTemplateId = ref<string | null>(null)

async function deleteDocumentTemplate(template: DocumentTemplate) {
  deletingDocumentTemplateId.value = template.id
  try {
    await $api(`/v1/crm/document-templates/${template.id}`, { method: 'DELETE' })
    documentTemplates.value = documentTemplates.value.filter(t => t.id !== template.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this document template.')
  }
  finally {
    deletingDocumentTemplateId.value = null
  }
}

// --- Channels (Email BYO-SMTP/IMAP; SMS/WhatsApp shown as Textzi-operated status cards) ---

type EmailAccount = {
  connected: boolean
  from_name: string | null
  from_email: string | null
  smtp_host: string | null
  smtp_port: number | null
  smtp_username: string | null
  smtp_use_tls: boolean
  imap_host: string | null
  imap_port: number | null
  imap_username: string | null
  imap_use_ssl: boolean
  status: string | null
  last_error: string | null
  last_synced_at: string | null
}

const emailAccount = ref<EmailAccount | null>(null)
const emailForm = reactive({
  from_name: '', from_email: '', smtp_host: '', smtp_port: 587, smtp_username: '', smtp_password: '', smtp_use_tls: true,
  imap_host: '', imap_port: 993, imap_username: '', imap_password: '', imap_use_ssl: true,
})
const emailSaving = ref(false)
const emailTesting = ref(false)
const emailError = ref('')
const emailTestResult = ref<{ ok: boolean, error: string | null } | null>(null)

async function loadEmailAccount() {
  try {
    emailAccount.value = await $api<EmailAccount>('/v1/crm/email/account')
    if (emailAccount.value.connected) {
      emailForm.from_name = emailAccount.value.from_name || ''
      emailForm.from_email = emailAccount.value.from_email || ''
      emailForm.smtp_host = emailAccount.value.smtp_host || ''
      emailForm.smtp_port = emailAccount.value.smtp_port || 587
      emailForm.smtp_username = emailAccount.value.smtp_username || ''
      emailForm.smtp_use_tls = emailAccount.value.smtp_use_tls
      emailForm.imap_host = emailAccount.value.imap_host || ''
      emailForm.imap_port = emailAccount.value.imap_port || 993
      emailForm.imap_username = emailAccount.value.imap_username || ''
      emailForm.imap_use_ssl = emailAccount.value.imap_use_ssl
    }
  }
  catch (error: any) {
    emailError.value = extractErrorMessage(error, 'Could not load the email account.')
  }
}

async function saveEmailAccount() {
  emailSaving.value = true
  emailError.value = ''
  emailTestResult.value = null
  try {
    emailAccount.value = await $api<EmailAccount>('/v1/crm/email/account', { method: 'PUT', body: { ...emailForm } })
  }
  catch (error: any) {
    emailError.value = extractErrorMessage(error, 'Could not save this email account.')
  }
  finally {
    emailSaving.value = false
  }
}

async function testEmailAccount() {
  emailTesting.value = true
  emailTestResult.value = null
  try {
    emailTestResult.value = await $api<{ ok: boolean, error: string | null }>('/v1/crm/email/account/test', { method: 'POST' })
    if (emailAccount.value)
      emailAccount.value.status = emailTestResult.value.ok ? 'connected' : 'error'
  }
  catch (error: any) {
    emailTestResult.value = { ok: false, error: extractErrorMessage(error, 'Could not test this connection.') }
  }
  finally {
    emailTesting.value = false
  }
}

const disconnecting = ref(false)
const disconnectError = ref('')

async function disconnectEmailAccount() {
  disconnecting.value = true
  disconnectError.value = ''
  try {
    await $api('/v1/crm/email/account', { method: 'DELETE' })
    emailAccount.value = null
  }
  catch (error: any) {
    disconnectError.value = extractErrorMessage(error, 'Could not disconnect this mailbox.')
  }
  finally {
    disconnecting.value = false
  }
}

// --- Helpdesk: ticket groups (SLA/CSAT/Macros settings live in the shared Waba*Panel components,
// rendered below; Canned Responses management is inline, moved here from channels-whatsapp.vue
// since tickets -- and the composer that uses canned responses -- now span WhatsApp and Email) ---

type TicketGroup = { id: string, name: string, member_user_ids: string[] }

const ticketGroups = ref<TicketGroup[]>([])
const groupDialog = ref(false)
const groupForm = reactive({ name: '', member_user_ids: [] as string[] })
const groupSaving = ref(false)
const groupError = ref('')

function openGroupDialog() {
  groupForm.name = ''
  groupForm.member_user_ids = []
  groupError.value = ''
  groupDialog.value = true
}

async function saveGroup() {
  if (!groupForm.name.trim())
    return
  groupSaving.value = true
  groupError.value = ''
  try {
    const created = await $api<TicketGroup>('/v1/waba/ticket-groups', { method: 'POST', body: { name: groupForm.name.trim(), member_user_ids: groupForm.member_user_ids } })
    ticketGroups.value.push(created)
    groupDialog.value = false
  }
  catch (error: any) {
    groupError.value = extractErrorMessage(error, 'Could not create this group.')
  }
  finally {
    groupSaving.value = false
  }
}

const deletingGroupId = ref<string | null>(null)

async function deleteGroup(group: TicketGroup) {
  deletingGroupId.value = group.id
  try {
    await $api(`/v1/waba/ticket-groups/${group.id}`, { method: 'DELETE' })
    ticketGroups.value = ticketGroups.value.filter(g => g.id !== group.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this group.')
  }
  finally {
    deletingGroupId.value = null
  }
}

type CannedResponse = { id: string, shortcut: string, body: string }

const cannedResponses = ref<CannedResponse[]>([])
const cannedLoading = ref(false)
const cannedError = ref('')

async function loadCannedResponses() {
  cannedLoading.value = true
  cannedError.value = ''
  try {
    cannedResponses.value = await $api<CannedResponse[]>('/v1/waba/canned-responses')
  }
  catch (error: any) {
    cannedError.value = extractErrorMessage(error, 'Could not load canned responses.')
  }
  finally {
    cannedLoading.value = false
  }
}

const cannedDialog = ref(false)
const cannedForm = ref({ id: '', shortcut: '', body: '' })
const cannedSaving = ref(false)
const cannedFormError = ref('')

function openCannedDialog(item?: CannedResponse) {
  cannedForm.value = item ? { id: item.id, shortcut: item.shortcut, body: item.body } : { id: '', shortcut: '', body: '' }
  cannedFormError.value = ''
  cannedDialog.value = true
}

async function saveCanned() {
  if (!cannedForm.value.shortcut.trim() || !cannedForm.value.body.trim())
    return
  cannedSaving.value = true
  cannedFormError.value = ''
  try {
    const body = { shortcut: cannedForm.value.shortcut.trim(), body: cannedForm.value.body.trim() }
    if (cannedForm.value.id) {
      const updated = await $api<CannedResponse>(`/v1/waba/canned-responses/${cannedForm.value.id}`, { method: 'PUT', body })
      const i = cannedResponses.value.findIndex(c => c.id === updated.id)
      if (i !== -1)
        cannedResponses.value[i] = updated
    }
    else {
      cannedResponses.value.push(await $api<CannedResponse>('/v1/waba/canned-responses', { method: 'POST', body }))
    }
    cannedDialog.value = false
  }
  catch (error: any) {
    cannedFormError.value = extractErrorMessage(error, 'Could not save this canned response.')
  }
  finally {
    cannedSaving.value = false
  }
}

const deletingCannedId = ref<string | null>(null)

async function deleteCanned(item: CannedResponse) {
  deletingCannedId.value = item.id
  try {
    await $api(`/v1/waba/canned-responses/${item.id}`, { method: 'DELETE' })
    cannedResponses.value = cannedResponses.value.filter(c => c.id !== item.id)
  }
  catch (error: any) {
    cannedError.value = extractErrorMessage(error, 'Could not delete this canned response.')
  }
  finally {
    deletingCannedId.value = null
  }
}

// --- Custom fields ---

type CustomField = { id: string, applies_to: 'lead' | 'deal' | 'crm_contact' | 'customer' | 'ticket', name: string, field_type: 'text' | 'number' | 'date' | 'dropdown', options: string[], required: boolean, position: number }

const APPLIES_TO_OPTIONS = [
  { title: 'Lead', value: 'lead' },
  { title: 'Deal', value: 'deal' },
  { title: 'Contact', value: 'crm_contact' },
  { title: 'Customer', value: 'customer' },
  { title: 'Ticket', value: 'ticket' },
]
const FIELD_TYPE_OPTIONS = [
  { title: 'Text', value: 'text' },
  { title: 'Number', value: 'number' },
  { title: 'Date', value: 'date' },
  { title: 'Dropdown', value: 'dropdown' },
]

const customFields = ref<CustomField[]>([])
const fieldsDialog = ref(false)
const fieldsForm = reactive({ applies_to: 'lead' as CustomField['applies_to'], name: '', field_type: 'text' as CustomField['field_type'], optionsText: '', required: false })
const fieldsSaving = ref(false)
const fieldsError = ref('')

function appliesToLabel(value: string) {
  return APPLIES_TO_OPTIONS.find(o => o.value === value)?.title || value
}

function openFieldsDialog() {
  fieldsForm.applies_to = 'lead'
  fieldsForm.name = ''
  fieldsForm.field_type = 'text'
  fieldsForm.optionsText = ''
  fieldsForm.required = false
  fieldsError.value = ''
  fieldsDialog.value = true
}

async function saveCustomField() {
  if (!fieldsForm.name.trim())
    return
  fieldsSaving.value = true
  fieldsError.value = ''
  try {
    const created = await $api<CustomField>('/v1/crm/custom-fields', {
      method: 'POST',
      body: {
        applies_to: fieldsForm.applies_to,
        name: fieldsForm.name.trim(),
        field_type: fieldsForm.field_type,
        options: fieldsForm.field_type === 'dropdown' ? fieldsForm.optionsText.split(',').map(o => o.trim()).filter(Boolean) : [],
        required: fieldsForm.required,
      },
    })
    customFields.value.push(created)
    fieldsDialog.value = false
  }
  catch (error: any) {
    fieldsError.value = extractErrorMessage(error, 'Could not create this field.')
  }
  finally {
    fieldsSaving.value = false
  }
}

const deletingFieldId = ref<string | null>(null)

async function deleteCustomField(field: CustomField) {
  deletingFieldId.value = field.id
  try {
    await $api(`/v1/crm/custom-fields/${field.id}`, { method: 'DELETE' })
    customFields.value = customFields.value.filter(f => f.id !== field.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this field.')
  }
  finally {
    deletingFieldId.value = null
  }
}

// --- Scoring rules ---

type ScoringRule = { id: string, name: string, condition_type: 'has_label' | 'custom_field_set' | 'source', condition_value: string, points: number, active: boolean }

const scoringRules = ref<ScoringRule[]>([])
const scoringDialog = ref(false)
const scoringForm = reactive({ name: '', condition_type: 'source' as ScoringRule['condition_type'], condition_value: '', points: 10 })
const scoringSaving = ref(false)
const scoringError = ref('')

function openScoringDialog() {
  scoringForm.name = ''
  scoringForm.condition_type = 'source'
  scoringForm.condition_value = ''
  scoringForm.points = 10
  scoringError.value = ''
  scoringDialog.value = true
}

async function saveScoringRule() {
  if (!scoringForm.name.trim() || !scoringForm.condition_value.trim())
    return
  scoringSaving.value = true
  scoringError.value = ''
  try {
    const created = await $api<ScoringRule>('/v1/crm/scoring-rules', { method: 'POST', body: { ...scoringForm, name: scoringForm.name.trim(), active: true } })
    scoringRules.value.push(created)
    scoringDialog.value = false
  }
  catch (error: any) {
    scoringError.value = extractErrorMessage(error, 'Could not create this scoring rule.')
  }
  finally {
    scoringSaving.value = false
  }
}

const busyScoringRuleId = ref<string | null>(null)

async function toggleScoringRuleActive(rule: ScoringRule) {
  busyScoringRuleId.value = rule.id
  try {
    const updated = await $api<ScoringRule>(`/v1/crm/scoring-rules/${rule.id}`, { method: 'PATCH', body: { active: !rule.active } })
    rule.active = updated.active
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this scoring rule.')
  }
  finally {
    busyScoringRuleId.value = null
  }
}

async function deleteScoringRule(rule: ScoringRule) {
  busyScoringRuleId.value = rule.id
  try {
    await $api(`/v1/crm/scoring-rules/${rule.id}`, { method: 'DELETE' })
    scoringRules.value = scoringRules.value.filter(r => r.id !== rule.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this scoring rule.')
  }
  finally {
    busyScoringRuleId.value = null
  }
}

// --- Territories ---

type AssignableUser = { id: string, full_name: string, email: string }
type Territory = { id: string, name: string, pincodes: string[], owner_user_id: string | null, parent_territory_id: string | null }

const territories = ref<Territory[]>([])
const assignableUsers = ref<AssignableUser[]>([])
const territoryDialog = ref(false)
const territoryForm = reactive({ name: '', pincodesText: '', owner_user_id: null as string | null, parent_territory_id: null as string | null })
const territorySaving = ref(false)
const territoryError = ref('')
const editingTerritoryId = ref<string | null>(null)

function territoryLabel(id: string | null) {
  return territories.value.find(t => t.id === id)?.name || '—'
}

function openTerritoryDialog() {
  editingTerritoryId.value = null
  territoryForm.name = ''
  territoryForm.pincodesText = ''
  territoryForm.owner_user_id = null
  territoryForm.parent_territory_id = null
  territoryError.value = ''
  territoryDialog.value = true
}

function openEditTerritoryDialog(territory: Territory) {
  editingTerritoryId.value = territory.id
  territoryForm.name = territory.name
  territoryForm.pincodesText = territory.pincodes.join(', ')
  territoryForm.owner_user_id = territory.owner_user_id
  territoryForm.parent_territory_id = territory.parent_territory_id
  territoryError.value = ''
  territoryDialog.value = true
}

async function saveTerritory() {
  const pincodes = territoryForm.pincodesText.split(',').map(p => p.trim()).filter(Boolean)
  if (!territoryForm.name.trim() || !pincodes.length)
    return
  territorySaving.value = true
  territoryError.value = ''
  try {
    const body = { name: territoryForm.name.trim(), pincodes, owner_user_id: territoryForm.owner_user_id, parent_territory_id: territoryForm.parent_territory_id }
    if (editingTerritoryId.value) {
      const updated = await $api<Territory>(`/v1/crm/territories/${editingTerritoryId.value}`, { method: 'PATCH', body })
      const index = territories.value.findIndex(t => t.id === editingTerritoryId.value)
      if (index !== -1)
        territories.value[index] = updated
    }
    else {
      const created = await $api<Territory>('/v1/crm/territories', { method: 'POST', body })
      territories.value.push(created)
    }
    territoryDialog.value = false
  }
  catch (error: any) {
    territoryError.value = extractErrorMessage(error, 'Could not save this territory.')
  }
  finally {
    territorySaving.value = false
  }
}

const deletingTerritoryId = ref<string | null>(null)

async function deleteTerritory(territory: Territory) {
  deletingTerritoryId.value = territory.id
  try {
    await $api(`/v1/crm/territories/${territory.id}`, { method: 'DELETE' })
    territories.value = territories.value.filter(t => t.id !== territory.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this territory.')
  }
  finally {
    deletingTerritoryId.value = null
  }
}

function ownerName(id: string | null) {
  return assignableUsers.value.find(u => u.id === id)?.full_name || 'Unassigned'
}

// --- Sales targets ---

type SalesTarget = { id: string, user_id: string, period_start: string, period_end: string, target_value: number, actual_value: number }

const salesTargets = ref<SalesTarget[]>([])
const targetDialog = ref(false)
const targetForm = reactive({ user_id: '', period_start: '', period_end: '', target_value: 0 })
const targetSaving = ref(false)
const targetError = ref('')
const editingTargetId = ref<string | null>(null)

function openTargetDialog() {
  editingTargetId.value = null
  targetForm.user_id = ''
  targetForm.period_start = ''
  targetForm.period_end = ''
  targetForm.target_value = 0
  targetError.value = ''
  targetDialog.value = true
}

function openEditTargetDialog(target: SalesTarget) {
  editingTargetId.value = target.id
  targetForm.user_id = target.user_id
  targetForm.period_start = target.period_start.slice(0, 10)
  targetForm.period_end = target.period_end.slice(0, 10)
  targetForm.target_value = target.target_value
  targetError.value = ''
  targetDialog.value = true
}

async function saveTarget() {
  if (!targetForm.user_id || !targetForm.period_start || !targetForm.period_end || !targetForm.target_value)
    return
  targetSaving.value = true
  targetError.value = ''
  try {
    if (editingTargetId.value) {
      const updated = await $api<SalesTarget>(`/v1/crm/sales-targets/${editingTargetId.value}`, {
        method: 'PATCH',
        body: {
          period_start: new Date(targetForm.period_start).toISOString(),
          period_end: new Date(targetForm.period_end).toISOString(),
          target_value: targetForm.target_value,
        },
      })
      const index = salesTargets.value.findIndex(t => t.id === editingTargetId.value)
      if (index !== -1)
        salesTargets.value[index] = updated
    }
    else {
      const created = await $api<SalesTarget>('/v1/crm/sales-targets', {
        method: 'POST',
        body: {
          user_id: targetForm.user_id,
          period_start: new Date(targetForm.period_start).toISOString(),
          period_end: new Date(targetForm.period_end).toISOString(),
          target_value: targetForm.target_value,
        },
      })
      salesTargets.value.push(created)
    }
    targetDialog.value = false
  }
  catch (error: any) {
    targetError.value = extractErrorMessage(error, 'Could not save this sales target.')
  }
  finally {
    targetSaving.value = false
  }
}

function inr(value: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value)
}

const deletingTargetId = ref<string | null>(null)

async function deleteTarget(target: SalesTarget) {
  deletingTargetId.value = target.id
  try {
    await $api(`/v1/crm/sales-targets/${target.id}`, { method: 'DELETE' })
    salesTargets.value = salesTargets.value.filter(t => t.id !== target.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this sales target.')
  }
  finally {
    deletingTargetId.value = null
  }
}

// --- Team / manager hierarchy ---

type TeamMember = { id: string, email: string, full_name: string, role: string, status: string, manager_id: string | null }

const teamMembers = ref<TeamMember[]>([])
const managerSaving = ref<string | null>(null)

async function setManager(member: TeamMember, managerId: string | null) {
  managerSaving.value = member.id
  try {
    await $api(`/v1/crm/users/${member.id}/manager`, { method: 'PUT', body: { manager_id: managerId } })
    member.manager_id = managerId
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this teammate\'s manager.')
  }
  finally {
    managerSaving.value = null
  }
}

async function loadExtras() {
  try {
    const [scoringResult, territoryResult, userResult, targetResult, teamResult, fieldsResult, groupResult] = await Promise.all([
      $api<ScoringRule[]>('/v1/crm/scoring-rules'),
      $api<Territory[]>('/v1/crm/territories'),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
      $api<SalesTarget[]>('/v1/crm/sales-targets'),
      $api<TeamMember[]>('/v1/team/members'),
      $api<CustomField[]>('/v1/crm/custom-fields'),
      $api<TicketGroup[]>('/v1/waba/ticket-groups'),
    ])
    scoringRules.value = scoringResult
    territories.value = territoryResult
    assignableUsers.value = userResult
    salesTargets.value = targetResult
    teamMembers.value = teamResult
    customFields.value = fieldsResult
    ticketGroups.value = groupResult
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load some CRM settings.')
  }
  loadEmailAccount()
  loadCannedResponses()
  loadProducts()
  loadDocumentTemplates()
}

// --- Web lead-capture form ---

type Pipeline = { id: string, name: string }
type WebForm = { enabled: boolean, fields: string[], success_message: string, target_pipeline_id: string | null, embed_snippet: string }

const AVAILABLE_FIELDS = ['name', 'email', 'phone', 'message']
const pipelines = ref<Pipeline[]>([])
const webForm = ref<WebForm | null>(null)
const webFormSaving = ref(false)
const webFormError = ref('')
const webFormSaved = ref(false)
const webFormCopied = ref(false)

async function loadWebForm() {
  try {
    const [formResult, pipelineResult] = await Promise.all([
      $api<WebForm>('/v1/crm/web-form'),
      $api<Pipeline[]>('/v1/crm/pipelines'),
    ])
    webForm.value = formResult
    pipelines.value = pipelineResult
  }
  catch (error: any) {
    webFormError.value = extractErrorMessage(error, 'Could not load the web form settings.')
  }
}

function toggleField(field: string) {
  if (!webForm.value)
    return
  if (webForm.value.fields.includes(field))
    webForm.value.fields = webForm.value.fields.filter(f => f !== field)
  else
    webForm.value.fields = [...webForm.value.fields, field]
}

async function saveWebForm() {
  if (!webForm.value)
    return
  webFormSaving.value = true
  webFormError.value = ''
  webFormSaved.value = false
  try {
    webForm.value = await $api<WebForm>('/v1/crm/web-form', {
      method: 'PUT',
      body: {
        enabled: webForm.value.enabled,
        fields: webForm.value.fields,
        success_message: webForm.value.success_message,
        target_pipeline_id: webForm.value.target_pipeline_id,
      },
    })
    webFormSaved.value = true
  }
  catch (error: any) {
    webFormError.value = extractErrorMessage(error, 'Could not save the web form settings.')
  }
  finally {
    webFormSaving.value = false
  }
}

async function copyEmbedSnippet() {
  if (!webForm.value)
    return
  await navigator.clipboard.writeText(webForm.value.embed_snippet)
  webFormCopied.value = true
  setTimeout(() => { webFormCopied.value = false }, 2000)
}

// --- Booking link ---

type DayHours = { open: string, close: string }
type BusinessHours = { enabled: boolean, timezone: string, schedule: Record<string, DayHours>, outside_hours_message: string | null }
type BookingLink = { id: string, slug: string, duration_minutes: number, active: boolean }

const DAYS = [
  { key: 'mon', label: 'Monday' }, { key: 'tue', label: 'Tuesday' }, { key: 'wed', label: 'Wednesday' },
  { key: 'thu', label: 'Thursday' }, { key: 'fri', label: 'Friday' }, { key: 'sat', label: 'Saturday' }, { key: 'sun', label: 'Sunday' },
]

const businessHours = ref<BusinessHours | null>(null)
const bookingLink = ref<BookingLink | null>(null)
const bookingLoading = ref(false)
const bookingError = ref('')
const bookingSaving = ref(false)
const bookingSaved = ref(false)
const bookingLinkCopied = ref(false)
const bookingSlug = ref('')
const bookingDuration = ref(30)
const bookingActive = ref(true)

function dayEnabled(key: string) {
  return !!businessHours.value?.schedule[key]
}

function toggleDay(key: string) {
  if (!businessHours.value)
    return
  const schedule = { ...businessHours.value.schedule }
  if (schedule[key])
    delete schedule[key]
  else
    schedule[key] = { open: '09:00', close: '18:00' }
  businessHours.value.schedule = schedule
}

async function loadBooking() {
  bookingLoading.value = true
  bookingError.value = ''
  try {
    const [hoursResult, linkResult] = await Promise.all([
      $api<BusinessHours>('/v1/waba/business-hours'),
      $api<BookingLink | null>('/v1/crm/settings/booking-link'),
    ])
    businessHours.value = hoursResult
    bookingLink.value = linkResult
    bookingSlug.value = linkResult?.slug || ''
    bookingDuration.value = linkResult?.duration_minutes || 30
    bookingActive.value = linkResult?.active ?? true
  }
  catch (error: any) {
    bookingError.value = extractErrorMessage(error, 'Could not load booking link settings.')
  }
  finally {
    bookingLoading.value = false
  }
}

async function saveBusinessHours() {
  if (!businessHours.value)
    return
  bookingSaving.value = true
  bookingError.value = ''
  bookingSaved.value = false
  try {
    businessHours.value = await $api<BusinessHours>('/v1/waba/business-hours', {
      method: 'PUT',
      body: {
        enabled: businessHours.value.enabled, timezone: businessHours.value.timezone,
        schedule: businessHours.value.schedule, outside_hours_message: businessHours.value.outside_hours_message,
      },
    })
    bookingSaved.value = true
  }
  catch (error: any) {
    bookingError.value = extractErrorMessage(error, 'Could not save your hours.')
  }
  finally {
    bookingSaving.value = false
  }
}

async function saveBookingLink() {
  if (!bookingSlug.value.trim())
    return
  bookingSaving.value = true
  bookingError.value = ''
  bookingSaved.value = false
  try {
    bookingLink.value = await $api<BookingLink>('/v1/crm/settings/booking-link', {
      method: 'PUT',
      body: { slug: bookingSlug.value.trim(), duration_minutes: bookingDuration.value, active: bookingActive.value },
    })
    bookingSaved.value = true
  }
  catch (error: any) {
    bookingError.value = extractErrorMessage(error, 'Could not save the booking link.')
  }
  finally {
    bookingSaving.value = false
  }
}

const bookingUrl = computed(() => bookingLink.value ? `${window.location.origin}/public-booking/${bookingLink.value.slug}` : '')

async function copyBookingUrl() {
  if (!bookingUrl.value)
    return
  await navigator.clipboard.writeText(bookingUrl.value)
  bookingLinkCopied.value = true
  setTimeout(() => { bookingLinkCopied.value = false }, 2000)
}

onMounted(() => {
  load()
  loadExtras()
  loadWebForm()
  loadBooking()
})
</script>

<template>
  <h1 class="text-h4 mb-1">
    Manage CRM
  </h1>
  <p class="text-medium-emphasis mb-6">
    Settings for how your CRM works -- notification channels and branding. Tickets, Leads, and
    Customers themselves live in the CRM section of the main menu, and pipeline stages are managed
    from <RouterLink :to="{ name: 'crm-pipelines' }">
      Pipelines
    </RouterLink>.
  </p>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>

  <VTabs v-model="activeTab" class="mb-6">
    <VTab value="notifications">
      Notifications
    </VTab>
    <VTab value="branding">
      Branding
    </VTab>
    <VTab value="company">
      Company
    </VTab>
    <VTab value="channels">
      Channels
    </VTab>
    <VTab value="helpdesk">
      Helpdesk
    </VTab>
    <VTab value="fields">
      Custom Fields
    </VTab>
    <VTab value="scoring">
      Lead Scoring
    </VTab>
    <VTab value="territories">
      Territories
    </VTab>
    <VTab value="targets">
      Sales Targets
    </VTab>
    <VTab value="team">
      Team
    </VTab>
    <VTab value="webform">
      Web Form
    </VTab>
    <VTab value="booking">
      Booking Link
    </VTab>
    <VTab value="billing">
      Billing
    </VTab>
    <VTab value="approvals">
      Quote Approvals
    </VTab>
    <VTab value="products">
      Products
    </VTab>
    <VTab value="documents">
      Document Templates
    </VTab>
  </VTabs>

  <VWindow v-model="activeTab">
    <VWindowItem value="notifications">
      <VCard max-width="560">
        <VCardText>
          <h2 class="text-h6 mb-1">
            Notifications
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Lead/deal assignment, deal won/lost, task assignment, and quote approval events always
            show up in the bell icon in the top bar. Turn this on to also email the owner.
          </p>
          <VAlert v-if="notifyError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ notifyError }}
          </VAlert>
          <VAlert v-if="notifySaved" type="success" variant="tonal" density="compact" class="mb-3">
            Saved.
          </VAlert>
          <VSwitch v-model="notifyForm.notify_email" label="Also email the owner" density="compact" class="mb-4" />
          <div>
            <VBtn :loading="notifySaving" @click="saveNotifications">
              Save
            </VBtn>
          </div>
        </VCardText>
      </VCard>
    </VWindowItem>

    <VWindowItem value="branding">
      <VCard max-width="560">
        <VCardText>
          <h2 class="text-h6 mb-1">
            Branding
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Your logo and brand color, used on CRM-facing customer communications.
          </p>
          <VAlert v-if="logoError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ logoError }}
          </VAlert>
          <p class="text-body-2 mb-2">
            Logo: <strong>{{ settings?.logo_url ? 'Uploaded' : 'Not uploaded' }}</strong>
          </p>
          <VBtn size="small" variant="tonal" :loading="logoUploading" prepend-icon="tabler-upload" class="mb-4">
            {{ settings?.logo_url ? 'Replace logo' : 'Upload logo' }}
            <input type="file" accept="image/png,image/jpeg" class="file-input-overlay" @change="uploadLogo">
          </VBtn>

          <VAlert v-if="brandError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ brandError }}
          </VAlert>
          <VAlert v-if="brandSaved" type="success" variant="tonal" density="compact" class="mb-3">
            Saved.
          </VAlert>
          <AppTextField v-model="brandColorForm" label="Brand color (hex)" placeholder="#FF5722" class="mb-4" />
          <div>
            <VBtn :loading="brandSaving" @click="saveBrandColor">
              Save
            </VBtn>
          </div>
        </VCardText>
      </VCard>
    </VWindowItem>

    <VWindowItem value="company">
      <VCard max-width="560">
        <VCardText>
          <h2 class="text-h6 mb-1">
            Company details
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Your organization's GST, PAN, and address are managed from your account profile, not
            here, so there's one place they're ever edited.
          </p>
          <VBtn :to="{ name: 'profile' }" variant="tonal" prepend-icon="tabler-building">
            Go to company profile
          </VBtn>
        </VCardText>
      </VCard>
    </VWindowItem>

    <VWindowItem value="channels">
      <VRow>
        <VCol cols="12" md="7">
          <VCard>
            <VCardText>
              <h2 class="text-h6 mb-1">
                Email
              </h2>
              <p class="text-body-2 text-medium-emphasis mb-4">
                Connect your own mailbox -- any SMTP/IMAP provider works. This is a CRM-plan
                capability, not a metered channel.
              </p>
              <VAlert v-if="emailError" type="error" variant="tonal" density="compact" class="mb-3">
                {{ emailError }}
              </VAlert>
              <VAlert v-if="disconnectError" type="error" variant="tonal" density="compact" class="mb-3">
                {{ disconnectError }}
              </VAlert>
              <VAlert v-if="emailTestResult" :type="emailTestResult.ok ? 'success' : 'error'" variant="tonal" density="compact" class="mb-3">
                {{ emailTestResult.ok ? 'Connected successfully.' : emailTestResult.error }}
              </VAlert>
              <VChip v-if="emailAccount?.connected" size="small" class="mb-4" :color="emailAccount.status === 'connected' ? 'success' : emailAccount.status === 'error' ? 'error' : undefined">
                {{ emailAccount.status === 'connected' ? 'Connected' : emailAccount.status === 'error' ? 'Error' : 'Unverified' }}
              </VChip>

              <VRow>
                <VCol cols="12" sm="6">
                  <VTextField v-model="emailForm.from_name" label="From name" density="compact" class="mb-3" />
                </VCol>
                <VCol cols="12" sm="6">
                  <VTextField v-model="emailForm.from_email" label="From email" type="email" density="compact" class="mb-3" />
                </VCol>
              </VRow>
              <p class="text-subtitle-2 mb-2">
                Outgoing (SMTP)
              </p>
              <VRow>
                <VCol cols="12" sm="8">
                  <VTextField v-model="emailForm.smtp_host" label="SMTP host" density="compact" class="mb-3" />
                </VCol>
                <VCol cols="12" sm="4">
                  <VTextField v-model.number="emailForm.smtp_port" label="Port" type="number" density="compact" class="mb-3" />
                </VCol>
              </VRow>
              <VTextField v-model="emailForm.smtp_username" label="SMTP username" density="compact" class="mb-3" />
              <VTextField v-model="emailForm.smtp_password" label="SMTP password" type="password" density="compact" class="mb-3" />
              <VSwitch v-model="emailForm.smtp_use_tls" label="Use TLS" density="compact" class="mb-3" />
              <p class="text-subtitle-2 mb-2">
                Incoming (IMAP)
              </p>
              <VRow>
                <VCol cols="12" sm="8">
                  <VTextField v-model="emailForm.imap_host" label="IMAP host" density="compact" class="mb-3" />
                </VCol>
                <VCol cols="12" sm="4">
                  <VTextField v-model.number="emailForm.imap_port" label="Port" type="number" density="compact" class="mb-3" />
                </VCol>
              </VRow>
              <VTextField v-model="emailForm.imap_username" label="IMAP username" density="compact" class="mb-3" />
              <VTextField v-model="emailForm.imap_password" label="IMAP password" type="password" density="compact" class="mb-3" />
              <VSwitch v-model="emailForm.imap_use_ssl" label="Use SSL" density="compact" class="mb-4" />
              <div class="d-flex ga-3">
                <VBtn :loading="emailSaving" @click="saveEmailAccount">
                  {{ emailAccount?.connected ? 'Save' : 'Connect' }}
                </VBtn>
                <VBtn v-if="emailAccount?.connected" variant="tonal" :loading="emailTesting" @click="testEmailAccount">
                  Test connection
                </VBtn>
                <VBtn v-if="emailAccount?.connected" variant="text" color="error" :loading="disconnecting" @click="disconnectEmailAccount">
                  Disconnect
                </VBtn>
              </div>
            </VCardText>
          </VCard>
        </VCol>
        <VCol cols="12" md="5">
          <VCard class="mb-4">
            <VCardText>
              <div class="d-flex align-center justify-space-between mb-1">
                <h2 class="text-h6 mb-0">
                  SMS
                </h2>
                <VChip size="small" color="success">
                  Powered by Textzi
                </VChip>
              </div>
              <p class="text-body-2 text-medium-emphasis mb-4">
                Textzi's own SMS infrastructure -- already active on your account.
              </p>
              <VBtn variant="tonal" prepend-icon="tabler-settings" :to="{ name: 'channels-sms' }">
                Manage
              </VBtn>
            </VCardText>
          </VCard>
          <VCard>
            <VCardText>
              <div class="d-flex align-center justify-space-between mb-1">
                <h2 class="text-h6 mb-0">
                  WhatsApp
                </h2>
                <VChip size="small" color="success">
                  Powered by Textzi
                </VChip>
              </div>
              <p class="text-body-2 text-medium-emphasis mb-4">
                Connected via Meta's own Embedded Signup -- managed on the WhatsApp channel's own
                settings page, not here.
              </p>
              <VBtn variant="tonal" prepend-icon="tabler-settings" :to="{ name: 'channels-whatsapp' }">
                Manage
              </VBtn>
            </VCardText>
          </VCard>
        </VCol>
      </VRow>
    </VWindowItem>

    <VWindowItem value="helpdesk">
      <p class="text-body-2 text-medium-emphasis mb-4">
        Tickets can now come from WhatsApp or Email -- SLA, CSAT, macros, canned responses, and
        groups all apply across both.
      </p>
      <WabaHoursSlaPanel class="mb-6" />
      <WabaMacrosPanel class="mb-6" />
      <WabaCsatPanel class="mb-6" />

      <div class="d-flex align-center justify-space-between mb-3">
        <h2 class="text-h6 mb-0">
          Groups
        </h2>
        <VBtn size="small" prepend-icon="tabler-plus" @click="openGroupDialog">
          New group
        </VBtn>
      </div>
      <VAlert v-if="groupError" type="error" variant="tonal" class="mb-4">
        {{ groupError }}
      </VAlert>
      <VCard class="mb-6">
        <VTable>
          <thead>
            <tr>
              <th>Name</th>
              <th>Members</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="group in ticketGroups" :key="group.id">
              <td>{{ group.name }}</td>
              <td>{{ group.member_user_ids.length }}</td>
              <td class="text-end">
                <VBtn icon="tabler-trash" size="small" variant="text" :loading="deletingGroupId === group.id" :disabled="deletingGroupId === group.id" @click="deleteGroup(group)" />
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!ticketGroups.length" class="text-medium-emphasis text-center pa-6">
          No groups yet.
        </p>
      </VCard>

      <div class="d-flex align-center justify-space-between mb-3">
        <h2 class="text-h6 mb-0">
          Canned Responses
        </h2>
        <VBtn size="small" prepend-icon="tabler-plus" @click="openCannedDialog()">
          New canned response
        </VBtn>
      </div>
      <VAlert v-if="cannedError" type="error" variant="tonal" class="mb-4">
        {{ cannedError }}
      </VAlert>
      <VCard>
        <VTable>
          <thead>
            <tr>
              <th>Shortcut</th>
              <th>Body</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in cannedResponses" :key="item.id">
              <td>/{{ item.shortcut }}</td>
              <td class="text-truncate" style="max-width: 400px;">
                {{ item.body }}
              </td>
              <td class="text-end">
                <VBtn size="small" variant="text" icon="tabler-pencil" :disabled="deletingCannedId === item.id" @click="openCannedDialog(item)" />
                <VBtn size="small" variant="text" icon="tabler-trash" :loading="deletingCannedId === item.id" :disabled="deletingCannedId === item.id" @click="deleteCanned(item)" />
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!cannedLoading && !cannedResponses.length" class="text-medium-emphasis text-center pa-6">
          No canned responses yet.
        </p>
      </VCard>
    </VWindowItem>

    <VWindowItem value="fields">
      <p class="text-body-2 text-medium-emphasis mb-4">
        Extra fields for your business (e.g. "Product") -- once added, they show up automatically
        on the New Lead/Deal/Contact/Customer forms.
      </p>
      <div class="d-flex justify-end mb-3">
        <VBtn color="primary" prepend-icon="tabler-plus" @click="openFieldsDialog">
          New field
        </VBtn>
      </div>
      <VCard>
        <VTable>
          <thead>
            <tr>
              <th>Name</th>
              <th>Applies to</th>
              <th>Type</th>
              <th>Required</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="field in customFields" :key="field.id">
              <td>{{ field.name }}</td>
              <td>{{ appliesToLabel(field.applies_to) }}</td>
              <td class="text-capitalize">
                {{ field.field_type }}
                <span v-if="field.field_type === 'dropdown'" class="text-medium-emphasis">({{ field.options.join(', ') }})</span>
              </td>
              <td>{{ field.required ? 'Yes' : 'No' }}</td>
              <td class="text-end">
                <VBtn icon="tabler-trash" size="small" variant="text" :loading="deletingFieldId === field.id" :disabled="deletingFieldId === field.id" @click="deleteCustomField(field)" />
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!customFields.length" class="text-medium-emphasis text-center pa-6">
          No custom fields yet.
        </p>
      </VCard>
    </VWindowItem>

    <VWindowItem value="scoring">
      <div class="d-flex justify-end mb-3">
        <VBtn color="primary" prepend-icon="tabler-plus" @click="openScoringDialog">
          New rule
        </VBtn>
      </div>
      <VCard>
        <VTable>
          <thead>
            <tr>
              <th>Name</th>
              <th>Condition</th>
              <th>Points</th>
              <th>Active</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="rule in scoringRules" :key="rule.id">
              <td>{{ rule.name }}</td>
              <td>{{ rule.condition_type }} = {{ rule.condition_value }}</td>
              <td>{{ rule.points }}</td>
              <td>
                <VSwitch :model-value="rule.active" density="compact" hide-details :disabled="busyScoringRuleId === rule.id" @update:model-value="toggleScoringRuleActive(rule)" />
              </td>
              <td class="text-end">
                <VBtn icon="tabler-trash" size="small" variant="text" :loading="busyScoringRuleId === rule.id" :disabled="busyScoringRuleId === rule.id" @click="deleteScoringRule(rule)" />
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!scoringRules.length" class="text-medium-emphasis text-center pa-6">
          No scoring rules yet — every lead scores 0.
        </p>
      </VCard>
    </VWindowItem>

    <VWindowItem value="territories">
      <div class="d-flex justify-end mb-3">
        <VBtn color="primary" prepend-icon="tabler-plus" @click="openTerritoryDialog">
          New territory
        </VBtn>
      </div>
      <VCard>
        <VTable>
          <thead>
            <tr>
              <th>Name</th>
              <th>Part of</th>
              <th>Pincodes</th>
              <th>Owner</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="territory in territories" :key="territory.id">
              <td>{{ territory.name }}</td>
              <td>{{ territoryLabel(territory.parent_territory_id) }}</td>
              <td>{{ territory.pincodes.join(', ') }}</td>
              <td>{{ ownerName(territory.owner_user_id) }}</td>
              <td class="text-end">
                <VBtn icon="tabler-pencil" size="small" variant="text" :disabled="deletingTerritoryId === territory.id" @click="openEditTerritoryDialog(territory)" />
                <VBtn icon="tabler-trash" size="small" variant="text" :loading="deletingTerritoryId === territory.id" :disabled="deletingTerritoryId === territory.id" @click="deleteTerritory(territory)" />
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!territories.length" class="text-medium-emphasis text-center pa-6">
          No territories yet.
        </p>
      </VCard>
    </VWindowItem>

    <VWindowItem value="targets">
      <div class="d-flex justify-end mb-3">
        <VBtn color="primary" prepend-icon="tabler-plus" @click="openTargetDialog">
          New target
        </VBtn>
      </div>
      <VCard>
        <VTable>
          <thead>
            <tr>
              <th>User</th>
              <th>Period</th>
              <th>Target</th>
              <th>Actual</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="target in salesTargets" :key="target.id">
              <td>{{ ownerName(target.user_id) }}</td>
              <td>{{ new Date(target.period_start).toLocaleDateString() }} – {{ new Date(target.period_end).toLocaleDateString() }}</td>
              <td>{{ inr(target.target_value) }}</td>
              <td :class="target.actual_value >= target.target_value ? 'text-success' : ''">
                {{ inr(target.actual_value) }}
              </td>
              <td class="text-end">
                <VBtn icon="tabler-pencil" size="small" variant="text" :disabled="deletingTargetId === target.id" @click="openEditTargetDialog(target)" />
                <VBtn icon="tabler-trash" size="small" variant="text" :loading="deletingTargetId === target.id" :disabled="deletingTargetId === target.id" @click="deleteTarget(target)" />
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!salesTargets.length" class="text-medium-emphasis text-center pa-6">
          No sales targets yet.
        </p>
      </VCard>
    </VWindowItem>

    <VWindowItem value="team">
      <VCard>
        <VCardText>
          <h2 class="text-h6 mb-1">
            Manager hierarchy
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Who each teammate reports to — used for sales-target roll-ups. One level only.
          </p>
        </VCardText>
        <VTable>
          <thead>
            <tr>
              <th>Name</th>
              <th>Role</th>
              <th>Manager</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="member in teamMembers" :key="member.id">
              <td>{{ member.full_name }}</td>
              <td>{{ member.role }}</td>
              <td>
                <VSelect
                  :model-value="member.manager_id"
                  :items="[{ title: 'None', value: null }, ...teamMembers.filter(m => m.id !== member.id).map(m => ({ title: m.full_name, value: m.id }))]"
                  density="compact" hide-details variant="plain" style="max-width: 200px;"
                  :loading="managerSaving === member.id"
                  @update:model-value="(v: string | null) => setManager(member, v)"
                />
              </td>
            </tr>
          </tbody>
        </VTable>
      </VCard>
    </VWindowItem>

    <VWindowItem value="webform">
      <VCard max-width="640">
        <VCardText>
          <h2 class="text-h6 mb-1">
            Web lead-capture form
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            An embeddable form for your website — submissions become leads here automatically.
          </p>
          <VAlert v-if="webFormError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ webFormError }}
          </VAlert>
          <VAlert v-if="webFormSaved" type="success" variant="tonal" density="compact" class="mb-3">
            Saved.
          </VAlert>
          <template v-if="webForm">
            <VSwitch v-model="webForm.enabled" label="Enabled" density="compact" class="mb-2" />
            <p class="text-body-2 mb-2">
              Fields to collect
            </p>
            <div class="d-flex flex-wrap ga-2 mb-4">
              <VChip
                v-for="field in AVAILABLE_FIELDS" :key="field" size="small"
                :variant="webForm.fields.includes(field) ? 'flat' : 'outlined'"
                :color="webForm.fields.includes(field) ? 'primary' : undefined"
                class="text-capitalize" @click="toggleField(field)"
              >
                {{ field }}
              </VChip>
            </div>
            <VTextarea v-model="webForm.success_message" label="Success message" rows="2" density="compact" class="mb-4" />
            <VSelect
              v-model="webForm.target_pipeline_id" label="Target pipeline" density="compact" clearable class="mb-4"
              :items="pipelines.map(p => ({ title: p.name, value: p.id }))"
              placeholder="Default pipeline"
            />
            <div class="mb-4">
              <VBtn :loading="webFormSaving" @click="saveWebForm">
                Save
              </VBtn>
            </div>
            <p class="text-body-2 mb-2">
              Embed snippet
            </p>
            <VTextarea :model-value="webForm.embed_snippet" readonly rows="2" density="compact" class="mb-2" />
            <VBtn size="small" variant="tonal" prepend-icon="tabler-copy" @click="copyEmbedSnippet">
              {{ webFormCopied ? 'Copied' : 'Copy snippet' }}
            </VBtn>
          </template>
        </VCardText>
      </VCard>
    </VWindowItem>

    <VWindowItem value="booking">
      <VCard max-width="640">
        <VCardText>
          <h2 class="text-h6 mb-1">
            Meeting booking link
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Share one link so a lead or customer can pick their own open slot — it books directly onto your calendar (Tasks → meeting).
          </p>
          <VAlert v-if="bookingError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ bookingError }}
          </VAlert>
          <VAlert v-if="bookingSaved" type="success" variant="tonal" density="compact" class="mb-3">
            Saved.
          </VAlert>

          <template v-if="businessHours">
            <p class="text-body-2 font-weight-medium mb-2">
              Weekly hours
            </p>
            <VSwitch v-model="businessHours.enabled" label="Enable business hours" density="compact" class="mb-2" />
            <template v-if="businessHours.enabled">
              <div v-for="day in DAYS" :key="day.key" class="d-flex align-center ga-3 mb-2">
                <VCheckbox :model-value="dayEnabled(day.key)" density="compact" hide-details @update:model-value="toggleDay(day.key)" />
                <span style="min-inline-size: 100px;">{{ day.label }}</span>
                <template v-if="businessHours.schedule[day.key]">
                  <VTextField v-model="businessHours.schedule[day.key].open" type="time" density="compact" hide-details style="max-inline-size: 130px;" />
                  <span>to</span>
                  <VTextField v-model="businessHours.schedule[day.key].close" type="time" density="compact" hide-details style="max-inline-size: 130px;" />
                </template>
              </div>
            </template>
            <div class="mb-6">
              <VBtn size="small" :loading="bookingSaving" @click="saveBusinessHours">
                Save hours
              </VBtn>
            </div>
          </template>

          <VDivider class="mb-4" />

          <p class="text-body-2 font-weight-medium mb-2">
            Your booking link
          </p>
          <div class="d-flex align-center ga-2 mb-3">
            <span class="text-body-2 text-medium-emphasis">{{ `${window.location.origin}/public-booking/` }}</span>
            <VTextField v-model="bookingSlug" density="compact" hide-details style="max-inline-size: 200px;" />
          </div>
          <VTextField v-model.number="bookingDuration" type="number" label="Meeting length (minutes)" density="compact" class="mb-3" style="max-inline-size: 220px;" />
          <VSwitch v-model="bookingActive" label="Active" density="compact" class="mb-3" />
          <div class="d-flex ga-2 align-center">
            <VBtn :loading="bookingSaving" @click="saveBookingLink">
              Save link
            </VBtn>
            <VBtn v-if="bookingLink" size="small" variant="tonal" prepend-icon="tabler-copy" @click="copyBookingUrl">
              {{ bookingLinkCopied ? 'Copied' : 'Copy link' }}
            </VBtn>
          </div>
        </VCardText>
      </VCard>
    </VWindowItem>

    <VWindowItem value="billing">
      <ChannelBillingPanel channel="crm" />
    </VWindowItem>

    <VWindowItem value="approvals">
      <VCard max-width="560">
        <VCardText>
          <h2 class="text-h6 mb-1">
            Quote approval chain
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Quotes over this amount need sign-off from every approver listed below before they can
            be sent. Leave the approver list empty to let anyone on the team approve; leave the
            threshold blank to require no approval at all.
          </p>
          <VAlert v-if="approvalsError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ approvalsError }}
          </VAlert>
          <VAlert v-if="approvalsSaved" type="success" variant="tonal" density="compact" class="mb-3">
            Saved.
          </VAlert>
          <VTextField
            v-model.number="approvalsForm.quote_approval_threshold" label="Approval required above (INR)"
            type="number" min="0" density="compact" clearable class="mb-4"
          />
          <VSelect
            v-model="approvalsForm.quote_approver_user_ids" label="Approvers (in order)" multiple chips closable-chips
            :items="assignableUsers.map(u => ({ title: u.full_name, value: u.id }))" density="compact" class="mb-4"
          />
          <div>
            <VBtn :loading="approvalsSaving" @click="saveApprovals">
              Save
            </VBtn>
          </div>
        </VCardText>
      </VCard>
    </VWindowItem>

    <VWindowItem value="products">
      <div class="d-flex justify-end mb-3">
        <VBtn color="primary" prepend-icon="tabler-plus" @click="openProductDialog">
          New product
        </VBtn>
      </div>
      <VCard>
        <VTable>
          <thead>
            <tr>
              <th>Name</th>
              <th>SKU</th>
              <th>HSN</th>
              <th>Price (INR)</th>
              <th>Active</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="product in products" :key="product.id">
              <td>{{ product.name }}</td>
              <td>{{ product.sku || '—' }}</td>
              <td>{{ product.hsn_code || '—' }}</td>
              <td>{{ inr(product.unit_price) }}</td>
              <td>
                <VSwitch :model-value="product.active" density="compact" hide-details :disabled="togglingProductId === product.id" @update:model-value="toggleProductActive(product)" />
              </td>
              <td class="text-end">
                <VBtn icon="tabler-pencil" size="small" variant="text" :disabled="deletingProductId === product.id" @click="openEditProductDialog(product)" />
                <VBtn icon="tabler-trash" size="small" variant="text" :loading="deletingProductId === product.id" :disabled="deletingProductId === product.id" @click="deleteProduct(product)" />
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!products.length" class="text-medium-emphasis text-center pa-6">
          No products yet — add one to pick it directly on a quote.
        </p>
      </VCard>
    </VWindowItem>

    <VWindowItem value="documents">
      <div class="d-flex justify-end mb-3">
        <VBtn color="primary" prepend-icon="tabler-plus" @click="openDocumentDialog">
          New template
        </VBtn>
      </div>
      <VCard>
        <VTable>
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="template in documentTemplates" :key="template.id">
              <td>{{ template.name }}</td>
              <td class="text-capitalize">
                {{ template.applies_to }}
              </td>
              <td class="text-end">
                <VBtn icon="tabler-pencil" size="small" variant="text" :disabled="deletingDocumentTemplateId === template.id" @click="openEditDocumentDialog(template)" />
                <VBtn icon="tabler-trash" size="small" variant="text" :loading="deletingDocumentTemplateId === template.id" :disabled="deletingDocumentTemplateId === template.id" @click="deleteDocumentTemplate(template)" />
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!documentTemplates.length" class="text-medium-emphasis text-center pa-6">
          No document templates yet — build one with merge fields like contact.name or deal.value (wrapped in double curly braces), then generate it from a deal.
        </p>
      </VCard>
    </VWindowItem>
  </VWindow>

  <VDialog v-model="fieldsDialog" max-width="420" persistent>
    <VCard title="New custom field">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="fieldsDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="fieldsError" type="error" variant="tonal" density="compact">
          {{ fieldsError }}
        </VAlert>
        <VSelect v-model="fieldsForm.applies_to" label="Applies to" density="compact" :items="APPLIES_TO_OPTIONS" />
        <VTextField v-model="fieldsForm.name" label="Field name" density="compact" autofocus />
        <VSelect v-model="fieldsForm.field_type" label="Field type" density="compact" :items="FIELD_TYPE_OPTIONS" />
        <VTextField
          v-if="fieldsForm.field_type === 'dropdown'" v-model="fieldsForm.optionsText"
          label="Options (comma-separated)" placeholder="POS, QR, BBPS, AEPS, Soundbox" density="compact"
        />
        <VSwitch v-model="fieldsForm.required" label="Required" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="fieldsDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="fieldsSaving" :disabled="!fieldsForm.name.trim()" @click="saveCustomField">
          Create
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="scoringDialog" max-width="420" persistent>
    <VCard title="New scoring rule">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="scoringDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="scoringError" type="error" variant="tonal" density="compact">
          {{ scoringError }}
        </VAlert>
        <VTextField v-model="scoringForm.name" label="Rule name" density="compact" />
        <VSelect
          v-model="scoringForm.condition_type" label="Condition" density="compact"
          :items="[{ title: 'Has label', value: 'has_label' }, { title: 'Custom field set', value: 'custom_field_set' }, { title: 'Source', value: 'source' }]"
        />
        <VTextField v-model="scoringForm.condition_value" label="Value (label name / field key / source)" density="compact" />
        <VTextField v-model.number="scoringForm.points" type="number" label="Points" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="scoringDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="scoringSaving" :disabled="!scoringForm.name.trim() || !scoringForm.condition_value.trim()" @click="saveScoringRule">
          Create
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="territoryDialog" max-width="420" persistent>
    <VCard :title="editingTerritoryId ? 'Edit territory' : 'New territory'">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="territoryDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="territoryError" type="error" variant="tonal" density="compact">
          {{ territoryError }}
        </VAlert>
        <VTextField v-model="territoryForm.name" label="Territory name" density="compact" />
        <VTextField v-model="territoryForm.pincodesText" label="Pincodes (comma-separated)" density="compact" />
        <VSelect
          v-model="territoryForm.owner_user_id" label="Owner" density="compact" clearable
          :items="assignableUsers.map(u => ({ title: u.full_name, value: u.id }))"
        />
        <VSelect
          v-model="territoryForm.parent_territory_id" label="Part of (optional)" density="compact" clearable
          :items="territories.filter(t => t.id !== editingTerritoryId).map(t => ({ title: t.name, value: t.id }))"
        />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="territoryDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="territorySaving" :disabled="!territoryForm.name.trim() || !territoryForm.pincodesText.trim()" @click="saveTerritory">
          {{ editingTerritoryId ? 'Save' : 'Create' }}
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="targetDialog" max-width="420" persistent>
    <VCard :title="editingTargetId ? 'Edit sales target' : 'New sales target'">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="targetDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="targetError" type="error" variant="tonal" density="compact">
          {{ targetError }}
        </VAlert>
        <VSelect
          v-model="targetForm.user_id" label="User" density="compact" :disabled="!!editingTargetId"
          :items="assignableUsers.map(u => ({ title: u.full_name, value: u.id }))"
        />
        <VTextField v-model="targetForm.period_start" label="Period start" type="date" density="compact" />
        <VTextField v-model="targetForm.period_end" label="Period end" type="date" density="compact" />
        <VTextField v-model.number="targetForm.target_value" label="Target value (INR)" type="number" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="targetDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="targetSaving" :disabled="!targetForm.user_id || !targetForm.period_start || !targetForm.period_end || !targetForm.target_value" @click="saveTarget">
          {{ editingTargetId ? 'Save' : 'Create' }}
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="groupDialog" max-width="420" persistent>
    <VCard title="New group">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="groupDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="groupError" type="error" variant="tonal" density="compact">
          {{ groupError }}
        </VAlert>
        <VTextField v-model="groupForm.name" label="Group name" density="compact" autofocus />
        <VSelect
          v-model="groupForm.member_user_ids" label="Members" density="compact" multiple chips
          :items="assignableUsers.map(u => ({ title: u.full_name, value: u.id }))"
        />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="groupDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="groupSaving" :disabled="!groupForm.name.trim()" @click="saveGroup">
          Create
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="cannedDialog" max-width="480" persistent>
    <VCard :title="cannedForm.id ? 'Edit canned response' : 'New canned response'">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="cannedDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="cannedFormError" type="error" variant="tonal" density="compact">
          {{ cannedFormError }}
        </VAlert>
        <VTextField v-model="cannedForm.shortcut" label="Shortcut" placeholder="hours" :maxlength="25" />
        <VTextarea v-model="cannedForm.body" label="Body" placeholder="We're open Mon-Sat, 10am-7pm." rows="3" :maxlength="500" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="cannedDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="cannedSaving" @click="saveCanned">
          Save
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="productDialog" max-width="420" persistent>
    <VCard :title="editingProductId ? 'Edit product' : 'New product'">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="productDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="productError" type="error" variant="tonal" density="compact">
          {{ productError }}
        </VAlert>
        <VTextField v-model="productForm.name" label="Product name" density="compact" autofocus />
        <VTextField v-model="productForm.sku" label="SKU (optional)" density="compact" />
        <VTextField v-model="productForm.hsn_code" label="HSN code" density="compact" />
        <VTextField v-model.number="productForm.unit_price" label="Unit price (INR)" type="number" min="0" density="compact" />
        <VTextarea v-model="productForm.description" label="Description (optional)" rows="2" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="productDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="productSaving" :disabled="!productForm.name.trim()" @click="saveProduct">
          {{ editingProductId ? 'Save' : 'Create' }}
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="documentDialog" max-width="640" persistent>
    <VCard :title="editingDocumentId ? 'Edit document template' : 'New document template'">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="documentDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="documentError" type="error" variant="tonal" density="compact">
          {{ documentError }}
        </VAlert>
        <VTextField v-model="documentForm.name" label="Template name" density="compact" autofocus />
        <VSelect
          v-model="documentForm.applies_to" label="Type" density="compact"
          :items="[{ title: 'Proposal', value: 'proposal' }, { title: 'Contract', value: 'contract' }, { title: 'Other', value: 'other' }]"
        />
        <VTextarea
          v-model="documentForm.body" label="Body" rows="10" density="compact"
          hint="Available merge fields: {{contact.name}}, {{contact.phone}}, {{contact.email}}, {{company.name}}, {{deal.name}}, {{deal.value}}, {{deal.stage}}, {{organization.name}}, {{date.today}}"
          persistent-hint
        />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="documentDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="documentSaving" :disabled="!documentForm.name.trim() || !documentForm.body.trim()" @click="saveDocumentTemplate">
          {{ editingDocumentId ? 'Save' : 'Create' }}
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>

<style scoped>
.file-input-overlay {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}
</style>
