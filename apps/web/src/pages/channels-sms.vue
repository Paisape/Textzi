<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type TemplateSummary = {
  id: string
  pe_id: string
  header_id: string
  alias: string
  dlt_template_id: string
  body: string
  category: string
}

type ChannelStatus = {
  subscription_price: number
  subscription_paid: boolean
  dlt_status: 'not_started' | 'pending_review' | 'approved'
  channel_active: boolean
}

type PeIdRow = { id: string, value: string, operator: string, status: string }
type HeaderRow = { id: string, pe_id: string, header_id: string, value: string, status: string }

const activeTab = ref('sender-id')
const stepUp = useStepUpAuth()

// ---- Templates tab ----
const templates = ref<TemplateSummary[]>([])
const templatesError = ref('')
const templatesLoading = ref(false)

async function loadTemplates() {
  templatesLoading.value = true
  templatesError.value = ''
  try {
    templates.value = await $api<TemplateSummary[]>('/v1/sms/templates')
  }
  catch (error: any) {
    templatesError.value = extractErrorMessage(error, 'Could not load templates.')
  }
  finally {
    templatesLoading.value = false
  }
}

const peIdsForTemplate = ref<PeIdRow[]>([])
const headersForTemplate = ref<HeaderRow[]>([])
const newTemplatePeId = ref<string | null>(null)
const newTemplateHeaderId = ref<string | null>(null)
const headersForSelectedPe = computed(() => headersForTemplate.value.filter(h => h.pe_id === newTemplatePeId.value))
watch(newTemplatePeId, () => { newTemplateHeaderId.value = null })
const newTemplateAlias = ref('')
const newTemplateDltId = ref('')
const newTemplateBody = ref('')
const newTemplateCategory = ref('transactional')
const templateSubmitting = ref(false)
const templateSubmitError = ref('')

const CATEGORY_OPTIONS = [
  { value: 'transactional', title: 'Transactional' },
  { value: 'otp', title: 'OTP' },
  { value: 'service_explicit', title: 'Service — Explicit' },
  { value: 'service_implicit', title: 'Service — Implicit' },
  { value: 'promotional', title: 'Promotional' },
]

// ---- Test a template ----
const testDialogOpen = ref(false)
const testTemplate = ref<TemplateSummary | null>(null)
const testMobile = ref('')
const testSubmitting = ref(false)
const testError = ref('')
const testResult = ref<{ status: string, route: string } | null>(null)

function onOpenTestDialog(template: TemplateSummary) {
  testTemplate.value = template
  testMobile.value = ''
  testError.value = ''
  testResult.value = null
  testDialogOpen.value = true
}

function dummyVariablesFor(body: string): Record<string, string> {
  const matches = body.matchAll(/\{\{\s*(\w+)\s*\}\}/g)
  const variables: Record<string, string> = {}
  for (const match of new Set([...matches].map(m => m[1])))
    variables[match] = 'Test'
  return variables
}

async function onSubmitTest() {
  testError.value = ''
  testResult.value = null
  if (!testTemplate.value)
    return
  const mobile = testMobile.value.trim()
  if (!/^[1-9][0-9]{9}$/.test(mobile)) {
    testError.value = 'Enter a valid 10-digit mobile number.'
    return
  }
  testSubmitting.value = true
  try {
    const result = await $api<{ status: string, route: string }>('/v1/sms/compose', {
      method: 'POST',
      body: {
        template: testTemplate.value.alias,
        mobile: `91${mobile}`,
        variables: dummyVariablesFor(testTemplate.value.body),
      },
    })
    testResult.value = { status: result.status, route: result.route }
  }
  catch (error: any) {
    testError.value = extractErrorMessage(error, 'Could not send the test message.')
  }
  finally {
    testSubmitting.value = false
  }
}

async function onAddTemplate() {
  templateSubmitError.value = ''
  if (!newTemplatePeId.value || !newTemplateHeaderId.value || !newTemplateAlias.value.trim() || !newTemplateDltId.value.trim() || !newTemplateBody.value.trim()) {
    templateSubmitError.value = 'Fill in every field.'
    return
  }
  templateSubmitting.value = true
  try {
    const form = new FormData()
    form.set('pe_id', newTemplatePeId.value)
    form.set('header_id', newTemplateHeaderId.value)
    form.set('alias', newTemplateAlias.value.trim())
    form.set('dlt_template_id', newTemplateDltId.value.trim())
    form.set('body', newTemplateBody.value.trim())
    form.set('category', newTemplateCategory.value)
    await $api('/v1/channels/sms/templates', { method: 'POST', body: form })
    newTemplateAlias.value = ''; newTemplateDltId.value = ''; newTemplateBody.value = ''
    await loadTemplates()
  }
  catch (error: any) {
    templateSubmitError.value = extractErrorMessage(error, 'Could not register this template.')
  }
  finally {
    templateSubmitting.value = false
  }
}

// ---- Edit a template ----
const editDialogOpen = ref(false)
const editTemplateId = ref<string | null>(null)
const editTemplatePeId = ref<string | null>(null)
const editTemplateHeaderId = ref<string | null>(null)
const editTemplateAlias = ref('')
const editTemplateDltId = ref('')
const editTemplateBody = ref('')
const editTemplateCategory = ref('transactional')
const editHeadersForSelectedPe = computed(() => headersForTemplate.value.filter(h => h.pe_id === editTemplatePeId.value))
function onEditPeIdChange() {
  // Only reset the header when the admin actually picks a different PE ID in the dropdown --
  // not when onOpenEditDialog programmatically sets both fields together while pre-filling.
  editTemplateHeaderId.value = null
}
const editSubmitting = ref(false)
const editError = ref('')

function onOpenEditDialog(template: TemplateSummary) {
  editTemplateId.value = template.id
  editTemplatePeId.value = template.pe_id
  editTemplateHeaderId.value = template.header_id
  editTemplateAlias.value = template.alias
  editTemplateDltId.value = template.dlt_template_id
  editTemplateBody.value = template.body
  editTemplateCategory.value = template.category
  editError.value = ''
  editDialogOpen.value = true
}

async function onSubmitEdit() {
  editError.value = ''
  if (!editTemplateId.value || !editTemplatePeId.value || !editTemplateHeaderId.value || !editTemplateAlias.value.trim() || !editTemplateDltId.value.trim() || !editTemplateBody.value.trim()) {
    editError.value = 'Fill in every field.'
    return
  }
  editSubmitting.value = true
  try {
    const form = new FormData()
    form.set('pe_id', editTemplatePeId.value)
    form.set('header_id', editTemplateHeaderId.value)
    form.set('alias', editTemplateAlias.value.trim())
    form.set('dlt_template_id', editTemplateDltId.value.trim())
    form.set('body', editTemplateBody.value.trim())
    form.set('category', editTemplateCategory.value)
    await $api(`/v1/channels/sms/templates/${editTemplateId.value}`, { method: 'PUT', body: form })
    editDialogOpen.value = false
    await loadTemplates()
  }
  catch (error: any) {
    editError.value = extractErrorMessage(error, 'Could not save these changes.')
  }
  finally {
    editSubmitting.value = false
  }
}

const deleteTemplateTarget = ref<TemplateSummary | null>(null)
const deletingTemplate = ref(false)
const deleteTemplateError = ref('')

function onOpenDeleteTemplateDialog(template: TemplateSummary) {
  deleteTemplateTarget.value = template
  deleteTemplateError.value = ''
}

function closeDeleteTemplateDialog() {
  deleteTemplateTarget.value = null
  deleteTemplateError.value = ''
}

async function onConfirmDeleteTemplate() {
  if (!deleteTemplateTarget.value)
    return
  deleteTemplateError.value = ''
  deletingTemplate.value = true
  try {
    await $api(`/v1/channels/sms/templates/${deleteTemplateTarget.value.id}`, { method: 'DELETE' })
    closeDeleteTemplateDialog()
    await loadTemplates()
  }
  catch (error: any) {
    deleteTemplateError.value = extractErrorMessage(error, 'Could not delete this template.')
  }
  finally {
    deletingTemplate.value = false
  }
}

// ---- Sender ID tab: channel status ----
const status = ref<ChannelStatus | null>(null)
const statusError = ref('')
const statusLoading = ref(true)

async function loadStatus() {
  statusLoading.value = true
  statusError.value = ''
  try {
    status.value = await $api<ChannelStatus>('/v1/channels/sms/status')
  }
  catch (error: any) {
    statusError.value = extractErrorMessage(error, 'Could not load channel status.')
  }
  finally {
    statusLoading.value = false
  }
}

const myPeIds = ref<PeIdRow[]>([])
async function loadMyPeIds() {
  try {
    const [pes, headers] = await Promise.all([
      $api<PeIdRow[]>('/v1/channels/sms/pe-ids'),
      $api<HeaderRow[]>('/v1/channels/sms/headers'),
    ])
    myPeIds.value = pes
    peIdsForTemplate.value = pes
    headersForTemplate.value = headers
    myHeaders.value = headers
  }
  catch {
    myPeIds.value = []
  }
}

async function refreshAll() {
  await loadStatus()
  if (status.value?.channel_active)
    await loadMyPeIds()
}

// Subscription payment (only shown if a future channel has a real price)
const subscriptionPaying = ref(false)
const subscriptionError = ref('')
async function onPaySubscription() {
  subscriptionError.value = ''
  subscriptionPaying.value = true
  try {
    await $api('/v1/channels/sms/subscription/recharge', { method: 'POST' })
    await refreshAll()
  }
  catch (error: any) {
    subscriptionError.value = extractErrorMessage(error, 'Could not activate the channel subscription.')
  }
  finally {
    subscriptionPaying.value = false
  }
}

// DLT: already-registered self-service path
const dltMode = ref<'self-service' | 'request'>('self-service')
const ssValue = ref('')
const ssOperator = ref('')
const ssHeaderId = ref('')
const ssHeaderValue = ref('')
const ssCertificate = ref<File | File[] | null>(null)
const ssPeTmMapping = ref<File | File[] | null>(null)
const ssSubmitting = ref(false)
const ssError = ref('')

function firstFile(value: File | File[] | null): File | null {
  if (Array.isArray(value))
    return value[0] ?? null
  return value
}

async function onSubmitSelfService() {
  ssError.value = ''
  const certificate = firstFile(ssCertificate.value)
  const peTmMapping = firstFile(ssPeTmMapping.value)
  if (!ssValue.value.trim() || !ssOperator.value.trim() || !ssHeaderId.value.trim() || !ssHeaderValue.value.trim() || !certificate) {
    ssError.value = 'Fill in every field and upload your PE certificate.'
    return
  }
  if (!peTmMapping) {
    ssError.value = 'Upload the PE-TM chain mapping confirmation.'
    return
  }
  ssSubmitting.value = true
  try {
    const form = new FormData()
    form.set('pe_value', ssValue.value.trim())
    form.set('operator', ssOperator.value.trim())
    form.set('header_id', ssHeaderId.value.trim())
    form.set('header_value', ssHeaderValue.value.trim())
    form.set('certificate', certificate)
    form.set('pe_tm_mapping', peTmMapping)
    await $api('/v1/channels/sms/dlt/self-service', { method: 'POST', body: form })
    ssValue.value = ''; ssOperator.value = ''; ssHeaderId.value = ''; ssHeaderValue.value = ''; ssCertificate.value = null; ssPeTmMapping.value = null
    await refreshAll()
  }
  catch (error: any) {
    ssError.value = extractErrorMessage(error, 'Could not submit your DLT registration.')
  }
  finally {
    ssSubmitting.value = false
  }
}

// DLT: request-help path
type DltQuote = { combined_fee: number, gst_amount: number, total_amount: number, telemarketer_name: string, telemarketer_id: string }
const dltQuote = ref<DltQuote | null>(null)
const requestCompanyName = ref('')
const requestCompanyPan = ref('')
const requestCompanyGst = ref('')
const requestSignatoryName = ref('')
const requestContactNumber = ref('')
const requestContactEmail = ref('')
const requestAadhar = ref('')
const requestNotes = ref('')
const requestPanDoc = ref<File | File[] | null>(null)
const requestGstDoc = ref<File | File[] | null>(null)
const requestAadharDoc = ref<File | File[] | null>(null)
const requestIncorporationCert = ref<File | File[] | null>(null)
const requestAddressProof = ref<File | File[] | null>(null)
const requestDirectorList = ref<File | File[] | null>(null)
const requestOtherDocs = ref<File | File[] | null>(null)
const requestAuthLetter = ref<File | File[] | null>(null)
const requestSubmitting = ref(false)
const requestError = ref('')
const sampleDownloading = ref(false)

function asFileArray(value: File | File[] | null): File[] {
  if (!value)
    return []
  return Array.isArray(value) ? value : [value]
}

async function loadDltQuote() {
  try {
    dltQuote.value = await $api<DltQuote>('/v1/channels/sms/dlt/quote')
  }
  catch {
    dltQuote.value = null
  }
}

const tmIdCopied = ref(false)
async function onCopyTelemarketerId() {
  if (!dltQuote.value)
    return
  try {
    await navigator.clipboard.writeText(dltQuote.value.telemarketer_id)
    tmIdCopied.value = true
    setTimeout(() => { tmIdCopied.value = false }, 2000)
  }
  catch {
    // Clipboard access can be denied by the browser -- the ID is already shown on screen to
    // copy manually, so there's nothing more useful to do here.
  }
}

async function onDownloadAuthorizationLetterSample() {
  sampleDownloading.value = true
  try {
    const blob = await $api<Blob, 'blob'>('/v1/channels/sms/dlt/authorization-letter-sample', { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'Textzi-Authorization-Letter-Sample.docx'
    link.click()
    URL.revokeObjectURL(url)
  }
  catch (error: any) {
    requestError.value = extractErrorMessage(error, 'Could not download the sample format.')
  }
  finally {
    sampleDownloading.value = false
  }
}

async function onSubmitRequest() {
  requestError.value = ''
  const panDoc = firstFile(requestPanDoc.value)
  const gstDoc = firstFile(requestGstDoc.value)
  const aadharDoc = firstFile(requestAadharDoc.value)
  const incorporationCert = firstFile(requestIncorporationCert.value)
  const addressProof = firstFile(requestAddressProof.value)
  const directorList = firstFile(requestDirectorList.value)
  const otherFiles = asFileArray(requestOtherDocs.value)
  const letter = firstFile(requestAuthLetter.value)
  if (!requestCompanyName.value.trim() || !requestCompanyPan.value.trim() || !requestCompanyGst.value.trim() || !requestSignatoryName.value.trim()
    || !requestContactNumber.value.trim() || !requestContactEmail.value.trim() || !requestAadhar.value.trim()) {
    requestError.value = 'Fill in every required field.'
    return
  }
  const requiredDocs: [File | null, string][] = [
    [panDoc, 'the PAN card copy'],
    [gstDoc, 'the GST certificate copy'],
    [aadharDoc, 'the Aadhar card copy'],
    [incorporationCert, 'the company incorporation certificate'],
    [addressProof, 'the address proof in the company name'],
    [directorList, 'the director list (as per MCA)'],
    [letter, 'the signed authorization letter'],
  ]
  const missing = requiredDocs.find(([file]) => !file)
  if (missing) {
    requestError.value = `Upload ${missing[1]}.`
    return
  }
  requestSubmitting.value = true
  try {
    const form = new FormData()
    form.set('company_name', requestCompanyName.value.trim())
    form.set('company_pan', requestCompanyPan.value.trim().toUpperCase())
    form.set('company_gst', requestCompanyGst.value.trim().toUpperCase())
    form.set('authorized_signatory_name', requestSignatoryName.value.trim())
    form.set('contact_number', requestContactNumber.value.trim())
    form.set('contact_email', requestContactEmail.value.trim())
    form.set('authorized_person_aadhar', requestAadhar.value.trim())
    if (requestNotes.value.trim())
      form.set('notes', requestNotes.value.trim())
    form.set('pan_document', panDoc as File)
    form.set('gst_document', gstDoc as File)
    form.set('aadhar_document', aadharDoc as File)
    form.set('incorporation_certificate', incorporationCert as File)
    form.set('address_proof', addressProof as File)
    form.set('director_list', directorList as File)
    form.set('authorization_letter', letter as File)
    for (const file of otherFiles)
      form.append('other_documents', file)
    const created = await $api<{ id: string }>('/v1/channels/sms/dlt/request', { method: 'POST', body: form })
    await $api(`/v1/channels/sms/dlt/request/${created.id}/recharge`, { method: 'POST' })
    requestCompanyName.value = ''; requestCompanyPan.value = ''; requestCompanyGst.value = ''
    requestSignatoryName.value = ''; requestContactNumber.value = ''; requestContactEmail.value = ''; requestAadhar.value = ''
    requestNotes.value = ''
    requestPanDoc.value = null; requestGstDoc.value = null; requestAadharDoc.value = null
    requestIncorporationCert.value = null; requestAddressProof.value = null; requestDirectorList.value = null
    requestOtherDocs.value = null; requestAuthLetter.value = null
    await refreshAll()
  }
  catch (error: any) {
    requestError.value = extractErrorMessage(error, 'Could not submit your DLT registration request.')
  }
  finally {
    requestSubmitting.value = false
  }
}

// Add another PE ID once active
const newPeValue = ref('')
const newPeOperator = ref('')
const peSubmitting = ref(false)
const peError = ref('')
async function onAddPeId() {
  peError.value = ''
  if (!newPeValue.value.trim() || !newPeOperator.value.trim()) {
    peError.value = 'Enter both the PE ID value and operator.'
    return
  }
  peSubmitting.value = true
  try {
    const form = new FormData()
    form.set('value', newPeValue.value.trim())
    form.set('operator', newPeOperator.value.trim())
    await $api('/v1/channels/sms/pe-ids', { method: 'POST', body: form })
    newPeValue.value = ''; newPeOperator.value = ''
    await loadMyPeIds()
  }
  catch (error: any) {
    peError.value = extractErrorMessage(error, 'Could not register this PE ID.')
  }
  finally {
    peSubmitting.value = false
  }
}

// Add a header for an existing PE ID
const myHeaders = ref<HeaderRow[]>([])
const newHeaderPeId = ref<string | null>(null)
const newHeaderId = ref('')
const newHeaderValue = ref('')
const headerSubmitting = ref(false)
const headerError = ref('')
async function onAddHeader() {
  headerError.value = ''
  if (!newHeaderPeId.value || !newHeaderId.value.trim() || !newHeaderValue.value.trim()) {
    headerError.value = 'Select a PE ID and fill in the header id and sender header.'
    return
  }
  headerSubmitting.value = true
  try {
    const form = new FormData()
    form.set('header_id', newHeaderId.value.trim())
    form.set('value', newHeaderValue.value.trim())
    await $api(`/v1/channels/sms/pe-ids/${newHeaderPeId.value}/headers`, { method: 'POST', body: form })
    newHeaderId.value = ''; newHeaderValue.value = ''
    await loadMyPeIds()
  }
  catch (error: any) {
    headerError.value = extractErrorMessage(error, 'Could not register this header.')
  }
  finally {
    headerSubmitting.value = false
  }
}

// ---- Logs tab ----
type MessageRow = { id: string, recipient: string, rendered_body: string, status: string, route: string | null, created_at: string }
const messages = ref<MessageRow[]>([])
const logsError = ref('')
const logsLoading = ref(false)
async function loadLogs() {
  logsLoading.value = true
  logsError.value = ''
  try {
    messages.value = await $api<MessageRow[]>('/v1/sms/messages')
  }
  catch (error: any) {
    logsError.value = extractErrorMessage(error, 'Could not load message logs.')
  }
  finally {
    logsLoading.value = false
  }
}
function statusColor(status: string): string {
  if (status === 'submitted')
    return 'success'
  if (status === 'failed')
    return 'error'
  return 'warning'
}

// ---- Reports tab ----
type ReportsSummary = { total: number, submitted: number, failed: number, accepted: number }
const reports = ref<ReportsSummary | null>(null)
const reportsError = ref('')
async function loadReports() {
  reportsError.value = ''
  try {
    reports.value = await $api<ReportsSummary>('/v1/channels/sms/reports/summary')
  }
  catch (error: any) {
    reportsError.value = extractErrorMessage(error, 'Could not load reports.')
  }
}

// ---- Settings tab: encryption ----
const encryptionEnabled = ref(false)
const encryptionLoading = ref(false)
const encryptionSaving = ref(false)
const encryptionError = ref('')

// ---- Settings tab: delivery-report webhook ----
// Tata never calls this URL directly -- Textzi is always the one receiving the delivery report
// and relaying it here, if set.
const drWebhookUrl = ref('')
const drWebhookSaving = ref(false)
const drWebhookError = ref('')
const drWebhookSaved = ref(false)

async function loadEncryptionSettings() {
  encryptionError.value = ''
  encryptionLoading.value = true
  try {
    const result = await stepUp.withStepUp(() => $api<{ encryption_enabled: boolean, dr_webhook_url: string | null }>('/v1/channels/sms/settings'))
    encryptionEnabled.value = result.encryption_enabled
    drWebhookUrl.value = result.dr_webhook_url || ''
  }
  catch (error: any) {
    encryptionError.value = extractErrorMessage(error, 'Could not load encryption settings.')
  }
  finally {
    encryptionLoading.value = false
  }
}

async function onToggleEncryption(value: boolean | null) {
  const nextValue = Boolean(value)
  encryptionError.value = ''
  encryptionSaving.value = true
  try {
    const result = await stepUp.withStepUp(() => $api<{ encryption_enabled: boolean }>('/v1/channels/sms/settings', { method: 'PUT', body: { encryption_enabled: nextValue, dr_webhook_url: drWebhookUrl.value || null } }))
    encryptionEnabled.value = result.encryption_enabled
  }
  catch (error: any) {
    encryptionEnabled.value = !nextValue
    encryptionError.value = extractErrorMessage(error, 'Could not update encryption setting.')
  }
  finally {
    encryptionSaving.value = false
  }
}

async function onSaveDrWebhook() {
  drWebhookError.value = ''
  drWebhookSaved.value = false
  drWebhookSaving.value = true
  try {
    await stepUp.withStepUp(() => $api('/v1/channels/sms/settings', { method: 'PUT', body: { encryption_enabled: encryptionEnabled.value, dr_webhook_url: drWebhookUrl.value.trim() || null } }))
    drWebhookSaved.value = true
  }
  catch (error: any) {
    drWebhookError.value = extractErrorMessage(error, 'Could not save this webhook URL.')
  }
  finally {
    drWebhookSaving.value = false
  }
}

// ---- Settings tab: API keys ----
type ApiKeyRow = { id: string, active: boolean, allowed_ips: string[] }
const apiKeys = ref<ApiKeyRow[]>([])
const apiKeysError = ref('')
const apiKeyCreating = ref(false)
const revealedApiKey = ref('')
const revealedKeyCopied = ref(false)
const revealedKeyDialogOpen = ref(false)
const revealedKeyCountdown = ref(30)
const ipWhitelistDrafts = ref<Record<string, string>>({})
const savingIpWhitelistId = ref<string | null>(null)
const revokingKeyId = ref<string | null>(null)

let revealedKeyCloseTimer: ReturnType<typeof setInterval> | undefined

function startRevealedKeyAutoClose() {
  clearInterval(revealedKeyCloseTimer)
  revealedKeyCountdown.value = 30
  revealedKeyCloseTimer = setInterval(() => {
    revealedKeyCountdown.value -= 1
    if (revealedKeyCountdown.value <= 0)
      closeRevealedKeyDialog()
  }, 1000)
}

function closeRevealedKeyDialog() {
  clearInterval(revealedKeyCloseTimer)
  revealedKeyDialogOpen.value = false
  revealedApiKey.value = ''
}

onUnmounted(() => clearInterval(revealedKeyCloseTimer))

function copyRevealedKey() {
  navigator.clipboard?.writeText(revealedApiKey.value)
  revealedKeyCopied.value = true
  setTimeout(() => { revealedKeyCopied.value = false }, 1500)
}

function downloadRevealedKey() {
  const blob = new Blob([revealedApiKey.value], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'textzi-api-key.txt'
  a.click()
  URL.revokeObjectURL(url)
}

async function loadApiKeys() {
  apiKeysError.value = ''
  try {
    apiKeys.value = await stepUp.withStepUp(() => $api<ApiKeyRow[]>('/v1/channels/sms/api-keys'))
    for (const key of apiKeys.value)
      ipWhitelistDrafts.value[key.id] = key.allowed_ips.join(', ')
  }
  catch (error: any) {
    apiKeysError.value = extractErrorMessage(error, 'Could not load API keys.')
  }
}

// Both actions below require a fresh one-time code (sent to the account's verified mobile if
// it has one, else email) before they're allowed to proceed -- independent of TOTP 2FA, which
// only kicks in if the account has that configured. Generating a key and changing its IP
// allow-list are both sensitive enough to gate unconditionally.
type PendingOtpAction = { type: 'generate_key' } | { type: 'update_ip_whitelist', keyId: string } | { type: 'revoke_key', keyId: string }

const otpDialogOpen = ref(false)
const otpSentVia = ref<'mobile' | 'email' | null>(null)
const otpMaskedDestination = ref('')
const otpCode = ref('')
const otpError = ref('')
const otpSubmitting = ref(false)
const otpRequesting = ref(false)
const pendingOtpAction = ref<PendingOtpAction | null>(null)

async function requestApiKeyOtp(action: 'generate_key' | 'update_ip_whitelist' | 'revoke_key') {
  apiKeysError.value = ''
  otpError.value = ''
  otpCode.value = ''
  otpRequesting.value = true
  try {
    const result = await stepUp.withStepUp(() => $api<{ sent_via: 'mobile' | 'email', masked_destination: string, dev_otp_code: string | null }>(
      '/v1/channels/sms/api-keys/request-otp', { method: 'POST', body: { action } },
    ))
    otpSentVia.value = result.sent_via
    otpMaskedDestination.value = result.masked_destination
    if (result.dev_otp_code)
      otpCode.value = result.dev_otp_code
    otpDialogOpen.value = true
  }
  catch (error: any) {
    apiKeysError.value = extractErrorMessage(error, 'Could not send a verification code.')
  }
  finally {
    otpRequesting.value = false
  }
}

async function onRequestGenerateKey() {
  pendingOtpAction.value = { type: 'generate_key' }
  await requestApiKeyOtp('generate_key')
}

async function onRequestSaveIpWhitelist(keyId: string) {
  pendingOtpAction.value = { type: 'update_ip_whitelist', keyId }
  await requestApiKeyOtp('update_ip_whitelist')
}

async function onRequestRevokeKey(keyId: string) {
  pendingOtpAction.value = { type: 'revoke_key', keyId }
  await requestApiKeyOtp('revoke_key')
}

async function onSubmitOtp() {
  if (!pendingOtpAction.value)
    return
  otpError.value = ''
  otpSubmitting.value = true
  const action = pendingOtpAction.value
  try {
    if (action.type === 'generate_key') {
      apiKeyCreating.value = true
      revealedApiKey.value = ''
      const result = await $api<{ api_key: string }>('/v1/channels/sms/api-keys', { method: 'POST', body: { otp_code: otpCode.value } })
      revealedApiKey.value = result.api_key
      revealedKeyDialogOpen.value = true
      startRevealedKeyAutoClose()
      await loadApiKeys()
    }
    else if (action.type === 'update_ip_whitelist') {
      savingIpWhitelistId.value = action.keyId
      const allowedIps = (ipWhitelistDrafts.value[action.keyId] || '').split(',').map(ip => ip.trim()).filter(Boolean)
      await $api(`/v1/channels/sms/api-keys/${action.keyId}/ip-whitelist`, { method: 'PUT', body: { allowed_ips: allowedIps, otp_code: otpCode.value } })
      await loadApiKeys()
    }
    else {
      revokingKeyId.value = action.keyId
      await $api(`/v1/channels/sms/api-keys/${action.keyId}/revoke`, { method: 'POST', body: { otp_code: otpCode.value } })
      await loadApiKeys()
    }
    otpDialogOpen.value = false
    pendingOtpAction.value = null
  }
  catch (error: any) {
    otpError.value = extractErrorMessage(error, 'Incorrect or expired code.')
  }
  finally {
    otpSubmitting.value = false
    apiKeyCreating.value = false
    savingIpWhitelistId.value = null
    revokingKeyId.value = null
  }
}

watch(dltMode, () => {
  if (!dltQuote.value)
    loadDltQuote()
}, { immediate: true })

// ---- API Docs tab ----
const apiBaseUrl = ref('https://api.textzi.in')
const apiDocsLoaded = ref(false)

async function loadApiDocsInfo() {
  try {
    const result = await $api<{ api_base_url: string }>('/v1/public/api-base-url')
    apiBaseUrl.value = result.api_base_url || window.location.origin
  }
  catch {
    apiBaseUrl.value = window.location.origin
  }
  finally {
    apiDocsLoaded.value = true
  }
}

const copiedKey = ref('')
function copyToClipboard(text: string, key: string) {
  navigator.clipboard?.writeText(text)
  copiedKey.value = key
  setTimeout(() => { if (copiedKey.value === key) copiedKey.value = '' }, 1500)
}

const sendCurlExample = computed(() => `curl -X POST "${apiBaseUrl.value}/v1/sms/send" \\
  -H "X-Api-Key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: order-1001-confirmation" \\
  -d '{
    "template_id": "1707123456789012345",
    "mobile": "919876543210",
    "message": "Your order 1001 has been confirmed and will ship to Pune."
  }'`)

const sendResponseExample = `{
  "status": "submitted",
  "message_id": "8d7734f6-99e6-41a3-bfdd-35c52bd5ea15",
  "route": "default-route",
  "balance": 4321.5,
  "credits_charged": 1
}`

const simpleUrlExample = computed(() => `${apiBaseUrl.value}/v1/sms/send-url?api_key=YOUR_API_KEY&mobile=919876543210&template_id=1707123456789012345&message=Your+order+1001+has+been+confirmed+and+will+ship+to+Pune.`)

const bulkCurlExample = computed(() => `curl -X POST "${apiBaseUrl.value}/v1/sms/send-bulk" \\
  -H "X-Api-Key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "template_id": "1707123456789012345",
    "recipients": [
      { "mobile": "919876543210", "message": "Your order 1001 has been confirmed and will ship to Pune." },
      { "mobile": "919876543211", "message": "Your order 1002 has been confirmed and will ship to Mumbai." }
    ]
  }'`)

const bulkResponseExample = `{
  "accepted": 2,
  "rejected": 0,
  "balance": 4319.5,
  "results": [
    { "mobile": "919876543210", "status": "submitted", "message_id": "...", "credits_charged": 1, "error": null },
    { "mobile": "919876543211", "status": "submitted", "message_id": "...", "credits_charged": 1, "error": null }
  ]
}`

const webhookPayloadExample = `{
  "message_id": "8d7734f6-99e6-41a3-bfdd-35c52bd5ea15",
  "recipient": "919876543210",
  "status": "delivered",
  "delivery_status_code": 2,
  "delivered_at": "2026-07-30T10:21:57+00:00"
}`

const bulkRecipientShapeExample = '{ mobile, message }'

const errorCodesReference = [
  { code: 401, meaning: 'Invalid or missing X-Api-Key.' },
  { code: 403, meaning: 'This entity/channel is not active.' },
  { code: 422, meaning: 'Validation failure -- unknown/unapproved template_id, recipient on your opt-out list, or a malformed request body.' },
  { code: 429, meaning: 'Rate limit exceeded for this account. See Rate Limits below.' },
  { code: 409, meaning: 'Duplicate Idempotency-Key reused with a different request.' },
]

function buildPostmanCollection(baseUrl: string) {
  return {
    info: {
      name: 'Textzi SMS API',
      description: 'Send SMS, bulk SMS, and manage opt-outs through the Textzi platform.',
      schema: 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
    },
    variable: [
      { key: 'base_url', value: baseUrl },
      { key: 'api_key', value: 'YOUR_API_KEY' },
    ],
    item: [
      {
        name: 'Send SMS',
        request: {
          method: 'POST',
          header: [
            { key: 'X-Api-Key', value: '{{api_key}}' },
            { key: 'Content-Type', value: 'application/json' },
            { key: 'Idempotency-Key', value: 'order-1001-confirmation', disabled: true },
          ],
          body: {
            mode: 'raw',
            raw: JSON.stringify({ template_id: '1707123456789012345', mobile: '919876543210', message: 'Your order 1001 has been confirmed and will ship to Pune.' }, null, 2),
            options: { raw: { language: 'json' } },
          },
          url: { raw: '{{base_url}}/v1/sms/send', host: ['{{base_url}}'], path: ['v1', 'sms', 'send'] },
        },
      },
      {
        name: 'Send Bulk SMS',
        request: {
          method: 'POST',
          header: [
            { key: 'X-Api-Key', value: '{{api_key}}' },
            { key: 'Content-Type', value: 'application/json' },
          ],
          body: {
            mode: 'raw',
            raw: JSON.stringify({
              template_id: '1707123456789012345',
              recipients: [
                { mobile: '919876543210', message: 'Your order 1001 has been confirmed and will ship to Pune.' },
                { mobile: '919876543211', message: 'Your order 1002 has been confirmed and will ship to Mumbai.' },
              ],
            }, null, 2),
            options: { raw: { language: 'json' } },
          },
          url: { raw: '{{base_url}}/v1/sms/send-bulk', host: ['{{base_url}}'], path: ['v1', 'sms', 'send-bulk'] },
        },
      },
    ],
  }
}

function downloadPostmanCollection() {
  const collection = buildPostmanCollection(apiBaseUrl.value)
  const blob = new Blob([JSON.stringify(collection, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'Textzi-SMS-API.postman_collection.json'
  a.click()
  URL.revokeObjectURL(url)
}

watch(activeTab, tab => {
  if (tab === 'templates' && !templates.value.length && !templatesError.value)
    loadTemplates()
  if (tab === 'logs' && !messages.value.length && !logsError.value)
    loadLogs()
  if (tab === 'reports' && !reports.value && !reportsError.value)
    loadReports()
  if (tab === 'settings' && !apiKeys.value.length && !apiKeysError.value)
    loadApiKeys()
  if (tab === 'settings' && !encryptionLoading.value)
    loadEncryptionSettings()
  if (tab === 'api-docs' && !apiDocsLoaded.value)
    loadApiDocsInfo()
})

onMounted(async () => {
  await refreshAll()
  if (activeTab.value === 'templates')
    loadTemplates()
})
</script>

<template>
  <div class="d-flex align-center gap-2 text-body-2 text-medium-emphasis mb-1">
    <RouterLink to="/channels">
      Channels
    </RouterLink>
    <span>/</span>
    <span>SMS</span>
  </div>
  <h1 class="text-h4 mb-6">
    SMS
  </h1>

  <VCard>
    <VTabs v-model="activeTab">
      <VTab value="sender-id">
        Sender ID
      </VTab>
      <VTab value="templates">
        Templates
      </VTab>
      <VTab value="logs">
        Logs
      </VTab>
      <VTab value="reports">
        Reports
      </VTab>
      <VTab value="uploaded-reports">
        Uploaded Reports
      </VTab>
      <VTab value="settings">
        Settings
      </VTab>
      <VTab value="api-docs">
        API Docs
      </VTab>
    </VTabs>
    <VDivider />
    <VWindow v-model="activeTab">
      <!-- Sender ID -->
      <VWindowItem value="sender-id">
        <VCardText>
          <VAlert
            v-if="statusError"
            type="error"
            variant="tonal"
          >
            {{ statusError }}
          </VAlert>

          <VProgressLinear
            v-else-if="statusLoading"
            indeterminate
            color="primary"
          />

          <template v-else-if="status">
            <!-- Active: show real PE ID list -->
            <template v-if="status.channel_active">
              <VAlert
                v-if="peError"
                type="error"
                variant="tonal"
                density="compact"
                class="mb-4"
              >
                {{ peError }}
              </VAlert>
              <VForm
                class="mb-6"
                @submit.prevent="onAddPeId"
              >
                <VRow>
                  <VCol
                    cols="12"
                    sm="4"
                  >
                    <AppTextField
                      v-model="newPeValue"
                      label="PE ID"
                      placeholder="1701234567890123456"
                    />
                  </VCol>
                  <VCol
                    cols="12"
                    sm="4"
                  >
                    <AppTextField
                      v-model="newPeOperator"
                      label="Operator"
                      placeholder="Jio / Airtel / Vi"
                    />
                  </VCol>
                  <VCol
                    cols="12"
                    sm="4"
                    class="d-flex align-end"
                  >
                    <VBtn
                      type="submit"
                      :loading="peSubmitting"
                    >
                      Add PE ID
                    </VBtn>
                  </VCol>
                </VRow>
              </VForm>
              <VTable class="mb-6">
                <thead>
                  <tr>
                    <th>PE ID</th>
                    <th>Operator</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="pe in myPeIds"
                    :key="pe.id"
                  >
                    <td>{{ pe.value }}</td>
                    <td>{{ pe.operator }}</td>
                    <td class="text-capitalize">
                      {{ pe.status }}
                    </td>
                  </tr>
                  <tr v-if="!myPeIds.length">
                    <td
                      colspan="3"
                      class="text-center text-medium-emphasis"
                    >
                      No PE IDs yet.
                    </td>
                  </tr>
                </tbody>
              </VTable>

              <VDivider class="mb-6" />

              <h6 class="text-h6 mb-4">
                Sender Headers
              </h6>
              <VAlert
                v-if="headerError"
                type="error"
                variant="tonal"
                density="compact"
                class="mb-4"
              >
                {{ headerError }}
              </VAlert>
              <VForm
                class="mb-6"
                @submit.prevent="onAddHeader"
              >
                <VRow>
                  <VCol
                    cols="12"
                    sm="3"
                  >
                    <VSelect
                      v-model="newHeaderPeId"
                      :items="myPeIds"
                      item-value="id"
                      :item-title="(pe: PeIdRow) => `${pe.value} (${pe.operator})`"
                      label="PE ID"
                      :disabled="!myPeIds.length"
                    />
                  </VCol>
                  <VCol
                    cols="12"
                    sm="3"
                  >
                    <AppTextField
                      v-model="newHeaderId"
                      label="DLT header id"
                      placeholder="HDR1701234567890123"
                    />
                  </VCol>
                  <VCol
                    cols="12"
                    sm="3"
                  >
                    <AppTextField
                      v-model="newHeaderValue"
                      label="Sender header"
                      placeholder="TEXTZI"
                    />
                  </VCol>
                  <VCol
                    cols="12"
                    sm="3"
                    class="d-flex align-end"
                  >
                    <VBtn
                      type="submit"
                      :loading="headerSubmitting"
                    >
                      Add Header
                    </VBtn>
                  </VCol>
                </VRow>
              </VForm>
              <VTable>
                <thead>
                  <tr>
                    <th>Sender header</th>
                    <th>DLT header id</th>
                    <th>PE ID</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="header in myHeaders"
                    :key="header.id"
                  >
                    <td class="font-weight-medium">
                      {{ header.value }}
                    </td>
                    <td>{{ header.header_id }}</td>
                    <td>{{ myPeIds.find(p => p.id === header.pe_id)?.value ?? header.pe_id }}</td>
                    <td class="text-capitalize">
                      {{ header.status }}
                    </td>
                  </tr>
                  <tr v-if="!myHeaders.length">
                    <td
                      colspan="4"
                      class="text-center text-medium-emphasis"
                    >
                      No sender headers yet.
                    </td>
                  </tr>
                </tbody>
              </VTable>
            </template>

            <!-- Not active: activation wizard -->
            <template v-else>
              <VCard
                v-if="status.subscription_price > 0 && !status.subscription_paid"
                variant="outlined"
                class="mb-6"
              >
                <VCardText>
                  <h6 class="text-h6 mb-2">
                    Step 1: Activate SMS Channel — ₹{{ status.subscription_price.toLocaleString('en-IN') }}
                  </h6>
                  <VAlert
                    v-if="subscriptionError"
                    type="error"
                    variant="tonal"
                    density="compact"
                    class="mb-4"
                  >
                    {{ subscriptionError }}
                  </VAlert>
                  <VBtn
                    :loading="subscriptionPaying"
                    @click="onPaySubscription"
                  >
                    Pay & Activate
                  </VBtn>
                </VCardText>
              </VCard>

              <VCard
                v-if="status.dlt_status === 'pending_review'"
                variant="outlined"
              >
                <VCardText>
                  <VAlert
                    type="info"
                    variant="tonal"
                  >
                    Your DLT registration request has been submitted and is pending review by our team. We'll activate your channel once it's approved.
                  </VAlert>
                </VCardText>
              </VCard>

              <VCard
                v-else-if="!(status.subscription_price > 0 && !status.subscription_paid)"
                variant="outlined"
              >
                <VCardText>
                  <h6 class="text-h6 mb-4">
                    DLT Registration
                  </h6>
                  <VRadioGroup
                    v-model="dltMode"
                    class="mb-4"
                    inline
                  >
                    <VRadio
                      label="I already have DLT registration"
                      value="self-service"
                    />
                    <VRadio
                      label="I need help registering"
                      value="request"
                      class="ms-6"
                    />
                  </VRadioGroup>

                  <template v-if="dltMode === 'self-service'">
                    <VAlert
                      v-if="ssError"
                      type="error"
                      variant="tonal"
                      density="compact"
                      class="mb-4"
                    >
                      {{ ssError }}
                    </VAlert>

                    <VAlert
                      type="warning"
                      variant="tonal"
                      density="compact"
                      class="mb-4"
                    >
                      <div class="mb-2">
                        Since you're bringing your own DLT registration, please send a <strong>PE-TM chain mapping</strong> request from your own DLT operator login (Airtel/Jio/Vi), selecting the following as your Telemarketer:
                      </div>
                      <div
                        v-if="dltQuote"
                        class="d-flex flex-wrap align-center gap-4"
                      >
                        <div>
                          <div class="text-caption text-medium-emphasis">
                            Telemarketer Name
                          </div>
                          <div class="font-weight-medium">
                            {{ dltQuote.telemarketer_name }}
                          </div>
                        </div>
                        <div>
                          <div class="text-caption text-medium-emphasis">
                            Telemarketer ID
                          </div>
                          <div class="d-flex align-center gap-1">
                            <span class="font-weight-medium">{{ dltQuote.telemarketer_id }}</span>
                            <VBtn
                              icon
                              variant="text"
                              size="x-small"
                              @click="onCopyTelemarketerId"
                            >
                              <VIcon :icon="tmIdCopied ? 'tabler-check' : 'tabler-copy'" />
                            </VBtn>
                          </div>
                        </div>
                      </div>
                    </VAlert>

                    <VForm @submit.prevent="onSubmitSelfService">
                      <VRow>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <AppTextField
                            v-model="ssValue"
                            label="PE ID"
                            placeholder="1701234567890123456"
                          />
                        </VCol>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <AppTextField
                            v-model="ssOperator"
                            label="Operator"
                            placeholder="Jio / Airtel / Vi / BSNL"
                          />
                        </VCol>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <AppTextField
                            v-model="ssHeaderId"
                            label="DLT header id"
                            placeholder="HDR1701234567890123"
                          />
                        </VCol>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <AppTextField
                            v-model="ssHeaderValue"
                            label="Sender header"
                            placeholder="TEXTZI"
                          />
                        </VCol>
                        <VCol cols="12">
                          <VFileInput
                            v-model="ssCertificate"
                            label="PE certificate (PDF/JPG/PNG)"
                            accept=".pdf,.jpg,.jpeg,.png"
                            prepend-icon="tabler-file-certificate"
                          />
                        </VCol>
                        <VCol cols="12">
                          <VFileInput
                            v-model="ssPeTmMapping"
                            label="PE-TM chain mapping confirmation"
                            accept=".pdf,.jpg,.jpeg,.png"
                            prepend-icon="tabler-link"
                          />
                        </VCol>
                        <VCol cols="12">
                          <VBtn
                            type="submit"
                            :loading="ssSubmitting"
                          >
                            Submit — activates immediately
                          </VBtn>
                        </VCol>
                      </VRow>
                    </VForm>
                  </template>

                  <template v-else>
                    <VAlert
                      v-if="requestError"
                      type="error"
                      variant="tonal"
                      density="compact"
                      class="mb-4"
                    >
                      {{ requestError }}
                    </VAlert>
                    <div
                      v-if="dltQuote"
                      class="mb-4"
                    >
                      <div class="d-flex justify-space-between mb-1">
                        <span class="text-medium-emphasis">DLT registration fee</span>
                        <span>₹{{ dltQuote.combined_fee.toLocaleString('en-IN') }}</span>
                      </div>
                      <div class="d-flex justify-space-between mb-1">
                        <span class="text-medium-emphasis">GST (18%)</span>
                        <span>₹{{ dltQuote.gst_amount.toLocaleString('en-IN') }}</span>
                      </div>
                      <VDivider class="my-2" />
                      <div class="d-flex justify-space-between font-weight-medium">
                        <span>Total</span>
                        <span>₹{{ dltQuote.total_amount.toLocaleString('en-IN') }}</span>
                      </div>
                    </div>
                    <VAlert
                      type="info"
                      variant="tonal"
                      density="compact"
                      class="mb-4"
                    >
                      Please note that during this activity you would need OTP, hence the authorized person must be available to share OTP.
                    </VAlert>

                    <VForm @submit.prevent="onSubmitRequest">
                      <VRow>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <AppTextField
                            v-model="requestCompanyName"
                            label="Name of Company"
                            placeholder="Enter name"
                          />
                        </VCol>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <AppTextField
                            v-model="requestCompanyPan"
                            label="Company PAN"
                            placeholder="AAAAA9999A"
                            maxlength="10"
                            style="text-transform: uppercase;"
                          />
                        </VCol>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <AppTextField
                            v-model="requestCompanyGst"
                            label="Company GST"
                            placeholder="15-character GSTIN"
                            maxlength="15"
                            style="text-transform: uppercase;"
                          />
                        </VCol>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <AppTextField
                            v-model="requestSignatoryName"
                            label="Authorized Signatory Name"
                            placeholder="As per company records"
                          />
                        </VCol>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <AppTextField
                            v-model="requestContactNumber"
                            label="Contact Number"
                            placeholder="10-digit mobile number"
                            maxlength="10"
                          />
                        </VCol>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <AppTextField
                            v-model="requestContactEmail"
                            label="Email"
                            type="email"
                            placeholder="name@company.com"
                          />
                        </VCol>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <AppTextField
                            v-model="requestAadhar"
                            label="Authorized Person Aadhar"
                            placeholder="12-digit Aadhar number"
                            maxlength="12"
                            hint="Stored encrypted; never shown to anyone in full."
                            persistent-hint
                          />
                        </VCol>
                      </VRow>

                      <AppTextarea
                        v-model="requestNotes"
                        label="Notes (optional)"
                        placeholder="Anything our team should know about your business"
                        rows="2"
                        class="mb-4 mt-4"
                      />

                      <p class="text-body-2 text-medium-emphasis mb-2">
                        Please upload colour copies only.
                      </p>
                      <VRow>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <VFileInput
                            v-model="requestPanDoc"
                            label="PAN card copy"
                            accept=".pdf,.jpg,.jpeg,.png"
                            prepend-icon="tabler-id-badge-2"
                          />
                        </VCol>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <VFileInput
                            v-model="requestAadharDoc"
                            label="Aadhar card copy"
                            accept=".pdf,.jpg,.jpeg,.png"
                            prepend-icon="tabler-id-badge-2"
                          />
                        </VCol>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <VFileInput
                            v-model="requestGstDoc"
                            label="GST certificate copy"
                            accept=".pdf,.jpg,.jpeg,.png"
                            prepend-icon="tabler-id-badge-2"
                          />
                        </VCol>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <VFileInput
                            v-model="requestIncorporationCert"
                            label="Company incorporation certificate"
                            accept=".pdf,.jpg,.jpeg,.png"
                            prepend-icon="tabler-certificate"
                          />
                        </VCol>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <VFileInput
                            v-model="requestAddressProof"
                            label="Address proof (in company name)"
                            accept=".pdf,.jpg,.jpeg,.png"
                            prepend-icon="tabler-home"
                          />
                        </VCol>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <VFileInput
                            v-model="requestDirectorList"
                            label="Director list (as per MCA)"
                            accept=".pdf,.jpg,.jpeg,.png"
                            prepend-icon="tabler-users"
                          />
                        </VCol>
                        <VCol
                          cols="12"
                          sm="6"
                        >
                          <VFileInput
                            v-model="requestOtherDocs"
                            label="Other supporting documents (optional)"
                            accept=".pdf,.jpg,.jpeg,.png"
                            multiple
                            prepend-icon="tabler-files"
                          />
                        </VCol>
                      </VRow>

                      <div class="d-flex align-center justify-space-between mb-1 mt-4">
                        <span class="text-body-2 font-weight-medium">Authorization letter</span>
                        <VBtn
                          variant="text"
                          size="small"
                          prepend-icon="tabler-download"
                          :loading="sampleDownloading"
                          @click="onDownloadAuthorizationLetterSample"
                        >
                          Download sample format
                        </VBtn>
                      </div>
                      <VFileInput
                        v-model="requestAuthLetter"
                        label="Signed authorization letter (colour copy)"
                        accept=".pdf,.jpg,.jpeg,.png"
                        prepend-icon="tabler-file-signature"
                        class="mb-4"
                      />

                      <VBtn
                        type="submit"
                        :loading="requestSubmitting"
                      >
                        Pay & Submit Request
                      </VBtn>
                    </VForm>
                  </template>
                </VCardText>
              </VCard>
            </template>
          </template>
        </VCardText>
      </VWindowItem>

      <!-- Templates -->
      <VWindowItem value="templates">
        <VCardText>
          <VAlert
            v-if="templatesError"
            type="error"
            variant="tonal"
            class="mb-4"
          >
            {{ templatesError }}
          </VAlert>

          <template v-if="status?.channel_active">
            <VAlert
              v-if="templateSubmitError"
              type="error"
              variant="tonal"
              density="compact"
              class="mb-4"
            >
              {{ templateSubmitError }}
            </VAlert>
            <VForm
              class="mb-6"
              @submit.prevent="onAddTemplate"
            >
              <VRow>
                <VCol
                  cols="12"
                  sm="3"
                >
                  <VSelect
                    v-model="newTemplatePeId"
                    :items="peIdsForTemplate"
                    item-value="id"
                    :item-title="(pe: PeIdRow) => `${pe.value} (${pe.operator})`"
                    label="PE ID"
                  />
                </VCol>
                <VCol
                  cols="12"
                  sm="3"
                >
                  <VSelect
                    v-model="newTemplateHeaderId"
                    :items="headersForSelectedPe"
                    item-value="id"
                    :item-title="(h: HeaderRow) => `${h.header_id} — ${h.value}`"
                    label="Header"
                    :disabled="!newTemplatePeId"
                  />
                </VCol>
                <VCol
                  cols="12"
                  sm="3"
                >
                  <AppTextField
                    v-model="newTemplateAlias"
                    label="Template Name"
                    placeholder="e.g. your DLT template name, OTP NEW"
                    hint="Saved exactly as entered -- this is what you'll pick the template by when sending"
                    persistent-hint
                  />
                </VCol>
                <VCol
                  cols="12"
                  sm="3"
                >
                  <AppTextField
                    v-model="newTemplateDltId"
                    label="DLT template id"
                    placeholder="1707123456789012345"
                  />
                </VCol>
                <VCol
                  cols="12"
                  sm="4"
                >
                  <VSelect
                    v-model="newTemplateCategory"
                    :items="CATEGORY_OPTIONS"
                    item-title="title"
                    item-value="value"
                    label="Category"
                  />
                </VCol>
                <VCol cols="12">
                  <AppTextarea
                    v-model="newTemplateBody"
                    label="Approved message body"
                    placeholder="Your order {{ '{{order_id}}' }} has been confirmed."
                    rows="2"
                  />
                </VCol>
                <VCol cols="12">
                  <VBtn
                    type="submit"
                    :loading="templateSubmitting"
                  >
                    Register template
                  </VBtn>
                </VCol>
              </VRow>
            </VForm>
          </template>

          <VTable v-if="!templatesError">
            <thead>
              <tr>
                <th>Template Name</th>
                <th>DLT template id</th>
                <th>Category</th>
                <th>Wording</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="template in templates"
                :key="template.id"
              >
                <td class="font-weight-medium">
                  {{ template.alias }}
                </td>
                <td>{{ template.dlt_template_id }}</td>
                <td class="text-capitalize">
                  {{ template.category.replaceAll('_', ' ') }}
                </td>
                <td>{{ template.body }}</td>
                <td>
                  <div class="d-flex gap-2">
                    <VBtn
                      size="small"
                      variant="outlined"
                      :disabled="!status?.channel_active"
                      @click="onOpenTestDialog(template)"
                    >
                      Test
                    </VBtn>
                    <VBtn
                      size="small"
                      variant="outlined"
                      @click="onOpenEditDialog(template)"
                    >
                      Edit
                    </VBtn>
                    <VBtn
                      size="small"
                      variant="text"
                      color="error"
                      @click="onOpenDeleteTemplateDialog(template)"
                    >
                      Delete
                    </VBtn>
                  </div>
                </td>
              </tr>
              <tr v-if="!templatesLoading && !templates.length">
                <td
                  colspan="5"
                  class="text-center text-medium-emphasis"
                >
                  No templates yet. {{ status?.channel_active ? 'Register one above.' : 'Activate the SMS channel first.' }}
                </td>
              </tr>
            </tbody>
          </VTable>
        </VCardText>
      </VWindowItem>

      <VDialog
        v-model="testDialogOpen"
        max-width="480"
      >
        <VCard>
          <VCardText>
            <h5 class="text-h5 mb-6">
              Test {{ testTemplate?.alias }}
            </h5>

            <VAlert
              v-if="testError"
              type="error"
              variant="tonal"
              density="compact"
              class="mb-4"
            >
              {{ testError }}
            </VAlert>

            <VAlert
              v-if="testResult"
              :type="testResult.status === 'failed' ? 'error' : 'success'"
              variant="tonal"
              density="compact"
              class="mb-4"
            >
              Message {{ testResult.status }} via route "{{ testResult.route }}". Check the
              <a
                href="#"
                class="font-weight-medium"
                @click.prevent="testDialogOpen = false; activeTab = 'logs'"
              >
                Logs tab
              </a>
              for the delivery status.
            </VAlert>

            <VTextField
              v-model="testMobile"
              label="Mobile number"
              placeholder="9876500000"
              maxlength="10"
              :disabled="testSubmitting"
            >
              <template #prepend-inner>
                <span class="text-medium-emphasis">+91</span>
              </template>
            </VTextField>
          </VCardText>

          <VCardText class="d-flex justify-end gap-3">
            <VBtn
              variant="outlined"
              @click="testDialogOpen = false"
            >
              Cancel
            </VBtn>
            <VBtn
              :loading="testSubmitting"
              @click="onSubmitTest"
            >
              Test
            </VBtn>
          </VCardText>
        </VCard>
      </VDialog>

      <VDialog
        v-model="editDialogOpen"
        max-width="720"
      >
        <VCard>
          <VCardTitle>
            Edit template
          </VCardTitle>
          <VCardText>
            <VAlert
              v-if="editError"
              type="error"
              variant="tonal"
              density="compact"
              class="mb-4"
            >
              {{ editError }}
            </VAlert>
            <VForm @submit.prevent="onSubmitEdit">
              <VRow>
                <VCol cols="12" sm="6">
                  <VSelect
                    v-model="editTemplatePeId"
                    :items="peIdsForTemplate"
                    item-value="id"
                    :item-title="(pe: PeIdRow) => `${pe.value} (${pe.operator})`"
                    label="PE ID"
                    @update:model-value="onEditPeIdChange"
                  />
                </VCol>
                <VCol cols="12" sm="6">
                  <VSelect
                    v-model="editTemplateHeaderId"
                    :items="editHeadersForSelectedPe"
                    item-value="id"
                    :item-title="(h: HeaderRow) => `${h.header_id} — ${h.value}`"
                    label="Header"
                    :disabled="!editTemplatePeId"
                  />
                </VCol>
                <VCol cols="12" sm="6">
                  <AppTextField
                    v-model="editTemplateAlias"
                    label="Template Name"
                    hint="Saved exactly as entered -- this is what you'll pick the template by when sending"
                    persistent-hint
                  />
                </VCol>
                <VCol cols="12" sm="6">
                  <AppTextField
                    v-model="editTemplateDltId"
                    label="DLT template id"
                  />
                </VCol>
                <VCol cols="12" sm="6">
                  <VSelect
                    v-model="editTemplateCategory"
                    :items="CATEGORY_OPTIONS"
                    item-title="title"
                    item-value="value"
                    label="Category"
                  />
                </VCol>
                <VCol cols="12">
                  <AppTextarea
                    v-model="editTemplateBody"
                    label="Approved message body"
                    rows="2"
                  />
                </VCol>
              </VRow>
            </VForm>
          </VCardText>
          <VCardActions>
            <VSpacer />
            <VBtn variant="tonal" @click="editDialogOpen = false">
              Cancel
            </VBtn>
            <VBtn
              :loading="editSubmitting"
              @click="onSubmitEdit"
            >
              Save Changes
            </VBtn>
          </VCardActions>
        </VCard>
      </VDialog>

      <VDialog
        :model-value="!!deleteTemplateTarget"
        max-width="480"
        @update:model-value="value => { if (!value) closeDeleteTemplateDialog() }"
      >
        <VCard v-if="deleteTemplateTarget">
          <VCardTitle class="text-error">
            Delete this template permanently
          </VCardTitle>
          <VCardText>
            <VAlert type="error" variant="tonal" density="compact" class="mb-4">
              This permanently deletes <strong>{{ deleteTemplateTarget.alias }}</strong>. There is no undo.
              Only allowed while this template has never been used to send a message -- if it
              has, the delete is blocked to keep that message history intact.
            </VAlert>
            <VAlert v-if="deleteTemplateError" type="error" variant="tonal" density="compact">
              {{ deleteTemplateError }}
            </VAlert>
          </VCardText>
          <VCardActions>
            <VSpacer />
            <VBtn variant="tonal" @click="closeDeleteTemplateDialog">
              Cancel
            </VBtn>
            <VBtn
              color="error"
              :loading="deletingTemplate"
              @click="onConfirmDeleteTemplate"
            >
              Delete Permanently
            </VBtn>
          </VCardActions>
        </VCard>
      </VDialog>

      <!-- Logs -->
      <VWindowItem value="logs">
        <VCardText>
          <VAlert
            v-if="logsError"
            type="error"
            variant="tonal"
          >
            {{ logsError }}
          </VAlert>
          <VTable v-else>
            <thead>
              <tr>
                <th>Sent time</th>
                <th>Mobile number</th>
                <th>Message</th>
                <th>Route</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="message in messages"
                :key="message.id"
              >
                <td>{{ new Date(message.created_at).toLocaleString('en-IN') }}</td>
                <td>{{ message.recipient }}</td>
                <td style="max-inline-size: 320px;">
                  {{ message.rendered_body }}
                </td>
                <td>{{ message.route ?? '—' }}</td>
                <td>
                  <VChip
                    :color="statusColor(message.status)"
                    size="small"
                    class="text-capitalize"
                  >
                    {{ message.status }}
                  </VChip>
                </td>
              </tr>
              <tr v-if="!logsLoading && !messages.length">
                <td
                  colspan="5"
                  class="text-center text-medium-emphasis"
                >
                  No messages sent yet.
                </td>
              </tr>
            </tbody>
          </VTable>
        </VCardText>
      </VWindowItem>

      <!-- Reports -->
      <VWindowItem value="reports">
        <VCardText>
          <VAlert
            v-if="reportsError"
            type="error"
            variant="tonal"
          >
            {{ reportsError }}
          </VAlert>
          <VRow v-else-if="reports">
            <VCol
              cols="6"
              sm="3"
            >
              <VCard variant="outlined">
                <VCardText>
                  <p class="text-body-2 text-medium-emphasis mb-1">
                    Total sent
                  </p>
                  <h4 class="text-h4 font-weight-bold">
                    {{ reports.total }}
                  </h4>
                </VCardText>
              </VCard>
            </VCol>
            <VCol
              cols="6"
              sm="3"
            >
              <VCard variant="outlined">
                <VCardText>
                  <p class="text-body-2 text-medium-emphasis mb-1">
                    Submitted
                  </p>
                  <h4 class="text-h4 font-weight-bold text-success">
                    {{ reports.submitted }}
                  </h4>
                </VCardText>
              </VCard>
            </VCol>
            <VCol
              cols="6"
              sm="3"
            >
              <VCard variant="outlined">
                <VCardText>
                  <p class="text-body-2 text-medium-emphasis mb-1">
                    Failed
                  </p>
                  <h4 class="text-h4 font-weight-bold text-error">
                    {{ reports.failed }}
                  </h4>
                </VCardText>
              </VCard>
            </VCol>
            <VCol
              cols="6"
              sm="3"
            >
              <VCard variant="outlined">
                <VCardText>
                  <p class="text-body-2 text-medium-emphasis mb-1">
                    Accepted (pending)
                  </p>
                  <h4 class="text-h4 font-weight-bold text-warning">
                    {{ reports.accepted }}
                  </h4>
                </VCardText>
              </VCard>
            </VCol>
          </VRow>
        </VCardText>
      </VWindowItem>

      <!-- Uploaded Reports -->
      <VWindowItem value="uploaded-reports">
        <VCardText>
          <VAlert
            type="info"
            variant="tonal"
          >
            Coming soon.
          </VAlert>
        </VCardText>
      </VWindowItem>

      <!-- Settings -->
      <VWindowItem value="settings">
        <VCardText>
          <VAlert
            v-if="apiKeysError"
            type="error"
            variant="tonal"
            class="mb-4"
          >
            {{ apiKeysError }}
          </VAlert>

          <VAlert
            v-if="encryptionError"
            type="error"
            variant="tonal"
            class="mb-4"
          >
            {{ encryptionError }}
          </VAlert>

          <h6 class="text-h6 mb-2">
            Encryption
          </h6>
          <VSwitch
            v-model="encryptionEnabled"
            :loading="encryptionLoading || encryptionSaving"
            :disabled="encryptionLoading || encryptionSaving"
            :label="encryptionEnabled ? 'Encryption is ON' : 'Encryption is OFF'"
            color="success"
            class="mb-2"
            @update:model-value="onToggleEncryption"
          />
          <p class="text-body-2 text-medium-emphasis mb-6" style="max-inline-size: 640px;">
            When on, this SMS channel's Logs and Reports will never show the actual message
            text — it is stored encrypted and displayed as "[Encrypted]". Mobile numbers are
            masked to only the last 4 digits. This applies only to the SMS channel; other
            channels have their own independent setting.
          </p>

          <h6 class="text-h6 mb-2">
            Delivery Report Webhook
          </h6>
          <p class="text-body-2 text-medium-emphasis mb-4" style="max-inline-size: 640px;">
            When set, Textzi POSTs a delivery status update to this URL once a message's final
            delivery report arrives from the carrier — must be https, and can't point at a
            private or local address.
          </p>
          <VAlert
            v-if="drWebhookError"
            type="error"
            variant="tonal"
            density="compact"
            class="mb-4"
            style="max-inline-size: 640px;"
          >
            {{ drWebhookError }}
          </VAlert>
          <VAlert
            v-if="drWebhookSaved"
            type="success"
            variant="tonal"
            density="compact"
            class="mb-4"
            style="max-inline-size: 640px;"
          >
            Webhook URL saved.
          </VAlert>
          <div class="d-flex gap-3 align-center mb-6" style="max-inline-size: 640px;">
            <AppTextField
              v-model="drWebhookUrl"
              label="Webhook URL"
              placeholder="https://your-app.example.com/webhooks/textzi-dr"
              class="flex-grow-1"
              @update:model-value="drWebhookSaved = false"
            />
            <VBtn
              :loading="drWebhookSaving"
              @click="onSaveDrWebhook"
            >
              Save
            </VBtn>
          </div>

          <h6 class="text-h6 mb-4">
            API Keys
          </h6>
          <p class="text-body-2 text-medium-emphasis mb-4" style="max-inline-size: 640px;">
            Generating a key, changing its IP allow-list, and revoking a key all require a
            one-time code sent to your registered mobile (or email, if no verified mobile is on
            file). A revoked key stops working immediately and can't be un-revoked.
          </p>
          <VBtn
            class="mb-6"
            :loading="otpRequesting || apiKeyCreating"
            :disabled="!status?.channel_active"
            @click="onRequestGenerateKey"
          >
            Generate new API key
          </VBtn>

          <VTable>
            <thead>
              <tr>
                <th>Key id</th>
                <th>Status</th>
                <th>IP allow-list (comma separated, blank = no restriction)</th>
                <th />
                <th />
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="key in apiKeys"
                :key="key.id"
              >
                <td>
                  <code>{{ key.id }}</code>
                </td>
                <td>
                  <VChip
                    :color="key.active ? 'success' : 'error'"
                    size="small"
                  >
                    {{ key.active ? 'Active' : 'Revoked' }}
                  </VChip>
                </td>
                <td style="min-inline-size: 260px;">
                  <AppTextField
                    v-model="ipWhitelistDrafts[key.id]"
                    density="compact"
                    placeholder="203.0.113.5, 198.51.100.20"
                    hide-details
                  />
                </td>
                <td>
                  <VBtn
                    size="small"
                    :loading="otpRequesting || savingIpWhitelistId === key.id"
                    @click="onRequestSaveIpWhitelist(key.id)"
                  >
                    Save
                  </VBtn>
                </td>
                <td>
                  <VBtn
                    v-if="key.active"
                    size="small"
                    variant="text"
                    color="error"
                    :loading="otpRequesting || revokingKeyId === key.id"
                    @click="onRequestRevokeKey(key.id)"
                  >
                    Revoke
                  </VBtn>
                </td>
              </tr>
              <tr v-if="!apiKeys.length">
                <td
                  colspan="5"
                  class="text-center text-medium-emphasis"
                >
                  No API keys yet.
                </td>
              </tr>
            </tbody>
          </VTable>
        </VCardText>
      </VWindowItem>

      <VWindowItem value="api-docs">
        <VCardText>
          <div class="d-flex align-center justify-space-between flex-wrap gap-4 mb-6">
            <div>
              <h6 class="text-h6 mb-1">
                SMS API Reference
              </h6>
              <p class="text-body-2 text-medium-emphasis mb-0" style="max-inline-size: 640px;">
                Everything below reflects the actual, currently-deployed API. Generate a key from
                the Settings tab, then swap <code>YOUR_API_KEY</code> in any example for the real
                thing.
              </p>
            </div>
            <VBtn prepend-icon="tabler-download" variant="tonal" @click="downloadPostmanCollection">
              Download Postman Collection
            </VBtn>
          </div>

          <VCard variant="outlined" class="mb-6">
            <VCardText>
              <h6 class="text-subtitle-1 font-weight-bold mb-2">
                Base URL & Authentication
              </h6>
              <div class="d-flex align-center gap-2 mb-3">
                <code class="api-docs-inline-code">{{ apiBaseUrl }}</code>
                <VBtn
                  size="x-small"
                  variant="text"
                  icon
                  @click="copyToClipboard(apiBaseUrl, 'base-url')"
                >
                  <VIcon :icon="copiedKey === 'base-url' ? 'tabler-check' : 'tabler-copy'" size="18" />
                </VBtn>
              </div>
              <p class="text-body-2 text-medium-emphasis mb-0">
                Every request needs an <code>X-Api-Key</code> header (generate one under
                Settings — the plaintext is only ever shown once, right after creation).
              </p>
            </VCardText>
          </VCard>

          <!-- POST /v1/sms/send -->
          <VCard variant="outlined" class="mb-6">
            <VCardText>
              <div class="d-flex align-center gap-2 mb-2">
                <VChip color="success" size="small" class="font-weight-bold">
                  POST
                </VChip>
                <code class="api-docs-inline-code">/v1/sms/send</code>
              </div>
              <p class="text-body-2 mb-4">
                Sends one message to one recipient, dispatched inline (the response reflects the
                real delivery attempt, not just acceptance).
              </p>

              <h6 class="text-caption font-weight-bold text-uppercase mb-2">
                Headers
              </h6>
              <VTable density="compact" class="mb-4">
                <thead>
                  <tr>
                    <th>Header</th>
                    <th>Required</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td><code>X-Api-Key</code></td>
                    <td>Yes</td>
                    <td>Your account's API key.</td>
                  </tr>
                  <tr>
                    <td><code>Idempotency-Key</code></td>
                    <td>No</td>
                    <td>Replaying the same key returns the original result instead of sending twice. Max 120 characters.</td>
                  </tr>
                  <tr>
                    <td><code>X-User-Id</code></td>
                    <td>No</td>
                    <td>
                      Route a send through a per-user route policy set up for someone in your own
                      organization. Ignored if the id doesn't belong to your organization. Find a
                      teammate's id (and copy it) on the
                      <RouterLink to="/team">Team</RouterLink> page.
                    </td>
                  </tr>
                </tbody>
              </VTable>

              <h6 class="text-caption font-weight-bold text-uppercase mb-2">
                Body
              </h6>
              <VTable density="compact" class="mb-4">
                <thead>
                  <tr>
                    <th>Field</th>
                    <th>Type</th>
                    <th>Required</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td><code>template_id</code></td>
                    <td>string</td>
                    <td>Yes</td>
                    <td>Your DLT-registered template id (not Textzi's alias) — the same id shown against the template under Templates above.</td>
                  </tr>
                  <tr>
                    <td><code>mobile</code></td>
                    <td>string</td>
                    <td>Yes</td>
                    <td>Recipient's number with country code, e.g. <code>919876543210</code>.</td>
                  </tr>
                  <tr>
                    <td><code>message</code></td>
                    <td>string</td>
                    <td>Yes</td>
                    <td>The complete message text, exactly as it should be sent — your own system fills in the template's variables before calling this API. Textzi does no interpolation here; max 1600 characters.</td>
                  </tr>
                </tbody>
              </VTable>

              <div class="d-flex align-center justify-space-between mb-2">
                <h6 class="text-caption font-weight-bold text-uppercase mb-0">
                  Example request
                </h6>
                <VBtn size="x-small" variant="text" icon @click="copyToClipboard(sendCurlExample, 'send-curl')">
                  <VIcon :icon="copiedKey === 'send-curl' ? 'tabler-check' : 'tabler-copy'" size="16" />
                </VBtn>
              </div>
              <pre class="api-docs-code mb-4">{{ sendCurlExample }}</pre>

              <div class="d-flex align-center justify-space-between mb-2">
                <h6 class="text-caption font-weight-bold text-uppercase mb-0">
                  Example response <span class="text-medium-emphasis">200 OK</span>
                </h6>
                <VBtn size="x-small" variant="text" icon @click="copyToClipboard(sendResponseExample, 'send-response')">
                  <VIcon :icon="copiedKey === 'send-response' ? 'tabler-check' : 'tabler-copy'" size="16" />
                </VBtn>
              </div>
              <pre class="api-docs-code">{{ sendResponseExample }}</pre>
            </VCardText>
          </VCard>

          <!-- GET /v1/sms/send-url -->
          <VCard variant="outlined" class="mb-6">
            <VCardText>
              <div class="d-flex align-center gap-2 mb-2">
                <VChip color="info" size="small" class="font-weight-bold">
                  GET
                </VChip>
                <code class="api-docs-inline-code">/v1/sms/send-url</code>
              </div>
              <p class="text-body-2 mb-4">
                Same send, as a single plain URL instead of a header + JSON body — for systems
                that can only fire a GET request (no custom headers, no JSON support), e.g.
                migrating off a raw carrier gateway URL. Everything else about the send (rate
                limits, opt-out checks, wallet debit) behaves identically to
                <code>POST /v1/sms/send</code> above.
              </p>
              <VAlert type="warning" variant="tonal" density="compact" class="mb-4">
                Putting your API key in a URL is less safe than a header — it can end up in
                server/proxy logs or browser history along the way. Prefer
                <code>POST /v1/sms/send</code> unless your integration genuinely can't send a
                header or JSON body.
              </VAlert>

              <h6 class="text-caption font-weight-bold text-uppercase mb-2">
                Query parameters
              </h6>
              <VTable density="compact" class="mb-4">
                <thead>
                  <tr>
                    <th>Parameter</th>
                    <th>Required</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td><code>api_key</code></td>
                    <td>Yes</td>
                    <td>Your account's API key.</td>
                  </tr>
                  <tr>
                    <td><code>mobile</code></td>
                    <td>Yes</td>
                    <td>Recipient's number with country code, e.g. <code>919876543210</code>.</td>
                  </tr>
                  <tr>
                    <td><code>template_id</code></td>
                    <td>Yes</td>
                    <td>Your DLT-registered template id (not Textzi's Template Name) — the same id shown against the template under Templates above.</td>
                  </tr>
                  <tr>
                    <td><code>message</code></td>
                    <td>Yes</td>
                    <td>The complete message text, exactly as it should be sent, URL-encoded. Max 1600 characters.</td>
                  </tr>
                  <tr>
                    <td><code>idempotency_key</code></td>
                    <td>No</td>
                    <td>Same behavior as the <code>Idempotency-Key</code> header on <code>POST /v1/sms/send</code>.</td>
                  </tr>
                </tbody>
              </VTable>

              <div class="d-flex align-center justify-space-between mb-2">
                <h6 class="text-caption font-weight-bold text-uppercase mb-0">
                  Example request
                </h6>
                <VBtn size="x-small" variant="text" icon @click="copyToClipboard(simpleUrlExample, 'send-url')">
                  <VIcon :icon="copiedKey === 'send-url' ? 'tabler-check' : 'tabler-copy'" size="16" />
                </VBtn>
              </div>
              <pre class="api-docs-code mb-4">{{ simpleUrlExample }}</pre>

              <div class="d-flex align-center justify-space-between mb-2">
                <h6 class="text-caption font-weight-bold text-uppercase mb-0">
                  Example response <span class="text-medium-emphasis">200 OK</span>
                </h6>
                <VBtn size="x-small" variant="text" icon @click="copyToClipboard(sendResponseExample, 'send-url-response')">
                  <VIcon :icon="copiedKey === 'send-url-response' ? 'tabler-check' : 'tabler-copy'" size="16" />
                </VBtn>
              </div>
              <pre class="api-docs-code">{{ sendResponseExample }}</pre>
            </VCardText>
          </VCard>

          <!-- POST /v1/sms/send-bulk -->
          <VCard variant="outlined" class="mb-6">
            <VCardText>
              <div class="d-flex align-center gap-2 mb-2">
                <VChip color="success" size="small" class="font-weight-bold">
                  POST
                </VChip>
                <code class="api-docs-inline-code">/v1/sms/send-bulk</code>
              </div>
              <p class="text-body-2 mb-4">
                One template, up to 100 recipients per call, each with their own complete message
                text. One bad or opted-out number doesn't fail the rest of the batch — check each
                entry's own <code>status</code> in the response.
              </p>

              <h6 class="text-caption font-weight-bold text-uppercase mb-2">
                Body
              </h6>
              <VTable density="compact" class="mb-4">
                <thead>
                  <tr>
                    <th>Field</th>
                    <th>Type</th>
                    <th>Required</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td><code>template_id</code></td>
                    <td>string</td>
                    <td>Yes</td>
                    <td>Same as Send SMS above — one DLT template id for the whole batch.</td>
                  </tr>
                  <tr>
                    <td><code>recipients</code></td>
                    <td>array (1–100)</td>
                    <td>Yes</td>
                    <td>Each item: <code>{{ bulkRecipientShapeExample }}</code>, same rules as a single send.</td>
                  </tr>
                </tbody>
              </VTable>

              <div class="d-flex align-center justify-space-between mb-2">
                <h6 class="text-caption font-weight-bold text-uppercase mb-0">
                  Example request
                </h6>
                <VBtn size="x-small" variant="text" icon @click="copyToClipboard(bulkCurlExample, 'bulk-curl')">
                  <VIcon :icon="copiedKey === 'bulk-curl' ? 'tabler-check' : 'tabler-copy'" size="16" />
                </VBtn>
              </div>
              <pre class="api-docs-code mb-4">{{ bulkCurlExample }}</pre>

              <div class="d-flex align-center justify-space-between mb-2">
                <h6 class="text-caption font-weight-bold text-uppercase mb-0">
                  Example response <span class="text-medium-emphasis">200 OK</span>
                </h6>
                <VBtn size="x-small" variant="text" icon @click="copyToClipboard(bulkResponseExample, 'bulk-response')">
                  <VIcon :icon="copiedKey === 'bulk-response' ? 'tabler-check' : 'tabler-copy'" size="16" />
                </VBtn>
              </div>
              <pre class="api-docs-code">{{ bulkResponseExample }}</pre>
            </VCardText>
          </VCard>

          <VRow>
            <VCol cols="12" md="6">
              <VCard variant="outlined" class="mb-6" height="100%">
                <VCardText>
                  <h6 class="text-subtitle-1 font-weight-bold mb-2">
                    Billing
                  </h6>
                  <p class="text-body-2 mb-0">
                    1 credit per 160 characters of the final, rendered message — rounded up.
                    160 chars = 1 credit, 161–320 = 2, 321–480 = 3, and so on. If every route
                    fails to deliver, the exact amount charged is refunded automatically.
                  </p>
                </VCardText>
              </VCard>
            </VCol>
            <VCol cols="12" md="6">
              <VCard variant="outlined" class="mb-6" height="100%">
                <VCardText>
                  <h6 class="text-subtitle-1 font-weight-bold mb-2">
                    Rate Limits
                  </h6>
                  <p class="text-body-2 mb-0">
                    Requests are throttled per account across both <code>/v1/sms/send</code> and
                    <code>/v1/sms/send-bulk</code>. Exceeding the limit returns
                    <code>429</code> with a <code>Rate limit exceeded</code> message — back off
                    and retry after the window resets.
                  </p>
                </VCardText>
              </VCard>
            </VCol>
          </VRow>

          <VCard variant="outlined" class="mb-6">
            <VCardText>
              <h6 class="text-subtitle-1 font-weight-bold mb-2">
                Delivery Report Webhook
              </h6>
              <p class="text-body-2 mb-4">
                Not set via the API — configure your webhook URL from the
                <button type="button" class="text-primary api-docs-link-button" @click="activeTab = 'settings'">
                  Settings tab
                </button>
                above (must be https). Once set, Textzi POSTs the following to it every time a
                message reaches its final delivery status:
              </p>
              <div class="d-flex align-center justify-space-between mb-2">
                <h6 class="text-caption font-weight-bold text-uppercase mb-0">
                  Webhook payload
                </h6>
                <VBtn size="x-small" variant="text" icon @click="copyToClipboard(webhookPayloadExample, 'webhook-payload')">
                  <VIcon :icon="copiedKey === 'webhook-payload' ? 'tabler-check' : 'tabler-copy'" size="16" />
                </VBtn>
              </div>
              <pre class="api-docs-code">{{ webhookPayloadExample }}</pre>
            </VCardText>
          </VCard>

          <VCard variant="outlined">
            <VCardText>
              <h6 class="text-subtitle-1 font-weight-bold mb-4">
                Error codes
              </h6>
              <VTable density="compact">
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Meaning</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="err in errorCodesReference" :key="err.code">
                    <td>
                      <VChip size="small" color="error" variant="tonal">
                        {{ err.code }}
                      </VChip>
                    </td>
                    <td>{{ err.meaning }}</td>
                  </tr>
                </tbody>
              </VTable>
            </VCardText>
          </VCard>
        </VCardText>
      </VWindowItem>
    </VWindow>
  </VCard>

  <StepUpDialog
    v-model="stepUp.dialogOpen.value"
    :code="stepUp.code.value"
    :error="stepUp.error.value"
    :submitting="stepUp.submitting.value"
    @update:code="v => stepUp.code.value = v"
    @submit="stepUp.submit"
    @cancel="stepUp.cancel"
  />

  <VDialog v-model="otpDialogOpen" max-width="420" persistent>
    <VCard>
      <VCardTitle>Enter verification code</VCardTitle>
      <VCardText>
        <p class="text-body-2 text-medium-emphasis mb-4">
          We sent a 6-digit code to your {{ otpSentVia === 'mobile' ? 'mobile number' : 'email' }}
          ending in <strong>{{ otpMaskedDestination }}</strong>. It expires in 10 minutes.
        </p>
        <VAlert v-if="otpError" type="error" variant="tonal" density="compact" class="mb-4">
          {{ otpError }}
        </VAlert>
        <VForm @submit.prevent="onSubmitOtp">
          <AppTextField
            v-model="otpCode"
            label="Verification code"
            placeholder="123456"
            maxlength="8"
            autofocus
            class="mb-4"
          />
          <div class="d-flex gap-3">
            <VBtn type="submit" :loading="otpSubmitting">
              Verify
            </VBtn>
            <VBtn
              variant="text"
              :disabled="otpSubmitting"
              @click="otpDialogOpen = false; pendingOtpAction = null"
            >
              Cancel
            </VBtn>
          </div>
        </VForm>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="revealedKeyDialogOpen" max-width="480" persistent>
    <VCard>
      <VCardTitle class="d-flex align-center justify-space-between">
        <span>New API key</span>
        <span class="text-caption text-medium-emphasis">Closes in {{ revealedKeyCountdown }}s</span>
      </VCardTitle>
      <VCardText>
        <p class="text-body-2 mb-3">
          Copy or download it now — it will not be shown again.
        </p>
        <code class="d-block mb-4 api-docs-inline-code" style="word-break: break-all;">{{ revealedApiKey }}</code>
        <div class="d-flex gap-3">
          <VBtn size="small" variant="tonal" :prepend-icon="revealedKeyCopied ? 'tabler-check' : 'tabler-copy'" @click="copyRevealedKey">
            {{ revealedKeyCopied ? 'Copied' : 'Copy' }}
          </VBtn>
          <VBtn size="small" variant="tonal" prepend-icon="tabler-download" @click="downloadRevealedKey">
            Download
          </VBtn>
          <VSpacer />
          <VBtn size="small" variant="text" @click="closeRevealedKeyDialog">
            Close
          </VBtn>
        </div>
      </VCardText>
    </VCard>
  </VDialog>
</template>

<style scoped>
.api-docs-code {
  background: rgba(var(--v-theme-on-surface), 0.05);
  border-radius: 6px;
  padding: 12px;
  font-family: monospace;
  font-size: 0.8125rem;
  white-space: pre-wrap;
  word-break: break-word;
}

.api-docs-inline-code {
  background: rgba(var(--v-theme-on-surface), 0.05);
  border-radius: 4px;
  padding: 2px 8px;
  font-family: monospace;
  font-size: 0.875rem;
}

.api-docs-link-button {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  cursor: pointer;
  text-decoration: underline;
}
</style>
