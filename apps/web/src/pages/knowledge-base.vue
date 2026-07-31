<script setup lang="ts">
definePage({
  meta: {
    layout: 'blank',
    public: true,
  },
})

type Faq = { q: string, a: string }
type Category = { key: string, title: string, icon: string, faqs: Faq[] }

const categories: Category[] = [
  {
    key: 'sms',
    title: 'SMS & DLT',
    icon: 'tabler-message-2',
    faqs: [
      {
        q: 'What is DLT registration and why do I need it?',
        a: 'DLT (Distributed Ledger Technology) is TRAI\'s mandatory registration framework for anyone sending commercial SMS in India. You need a registered Principal Entity (PE) ID, a Sender Header (the 6-character ID recipients see as the sender), and pre-approved message templates before you can send. Textzi handles the technical registration flow — you can self-register if you already have a PE ID, or ask us to register one for you.',
      },
      {
        q: 'How many characters can I send in one SMS segment?',
        a: 'A plain English (GSM-7) message is 160 characters for a single segment, or 153 characters per segment once a message needs to be split across multiple parts. A message containing emoji, most regional-language script (Hindi, Marathi, Tamil, etc.), or special Unicode characters switches to Unicode encoding, which is billed at 70 characters single-segment / 67 characters per segment.',
      },
      {
        q: 'What\'s the difference between transactional and promotional SMS?',
        a: 'Transactional messages (OTPs, order confirmations, alerts) can be sent to any number, any time, including DND-registered numbers, since they relate to a service the recipient already uses. Promotional messages (offers, marketing) can only be sent to numbers that have not opted into DND/NCPR, and only during TRAI-permitted hours. Your DLT template\'s category determines which rules apply — choose it carefully when registering a template.',
      },
      {
        q: 'Why did my message fail to deliver?',
        a: 'The most common reasons are: the DLT template didn\'t match the content sent (even a small wording change can cause a rejection), the recipient number is on DND and the message was promotional, the number is switched off/unreachable, or the sender header/PE ID mapping isn\'t fully approved yet. Check the delivery status code on the message in SMS Log & Report — each code maps to a specific reason.',
      },
      {
        q: 'How long does DLT approval take?',
        a: 'Self-service registration (if you already hold a PE ID with your operator) is usually instant in Textzi. A fresh PE ID/header/template registration through the telecom operator\'s DLT portal typically takes 1–3 business days, depending on the operator and how quickly documents are verified.',
      },
      {
        q: 'Can I send the same template with different variables to many recipients at once?',
        a: 'Yes — use Bulk Send (or the /v1/sms/send-bulk API) to send up to 100 recipients in one call, each with their own composed message text. Every recipient is billed and processed independently, so one invalid number in the batch doesn\'t affect the others.',
      },
    ],
  },
  {
    key: 'platform',
    title: 'Using Textzi',
    icon: 'tabler-settings',
    faqs: [
      {
        q: 'How do I get an API key?',
        a: 'Go to Channels > SMS > Settings > API Keys and click Generate Key. For security, generating, viewing, or revoking a key requires a one-time verification code sent to your registered mobile (or email if mobile isn\'t verified). The key is shown once — copy or download it immediately, since we only ever store a hash of it, not the key itself.',
      },
      {
        q: 'What\'s the difference between Send SMS in the dashboard and the API?',
        a: 'The dashboard\'s Compose tab lets you pick a template and fill in variables — Textzi renders the final text for you. The API is for your own systems: you send the complete, already-composed message text along with the DLT template ID it corresponds to, since your own application already knows what to send.',
      },
      {
        q: 'How do I get delivery reports for messages sent via the API?',
        a: 'Set a Delivery Report webhook URL under Channels > SMS > Settings. Whenever a message\'s final delivery status arrives from the carrier, Textzi calls your webhook with the result. You can also always check status directly via the dashboard\'s SMS Log & Report, or the /v1/sms/messages API.',
      },
      {
        q: 'Can I add teammates with limited access?',
        a: 'Yes — go to Team and invite a teammate with one of several roles (Sub User, Finance User, Marketing User, Read-only User), each with different permissions. Only the account owner can invite an Admin-tier role, and that\'s handled separately by Textzi\'s own platform team.',
      },
      {
        q: 'Is my message data encrypted?',
        a: 'You can turn on encryption-at-rest for a channel under Channel Settings — once enabled, new message bodies and recipient numbers are encrypted in our database. Even without it, only masked recipient numbers are ever shown in reports and admin views (only the last 4 digits are visible).',
      },
      {
        q: 'How do I enable two-factor authentication (2FA)?',
        a: 'Go to your account\'s Two-Factor Authentication settings, scan the QR code with an authenticator app (Google Authenticator, Authy, etc.), and confirm with a code. Once enabled, sensitive actions (like generating an API key or changing billing settings) will occasionally ask you to re-verify with a fresh code.',
      },
      {
        q: 'I forgot my password — what do I do?',
        a: 'Use Forgot Password on the login page and enter your registered email. We\'ll send a one-time reset code. For security, this option isn\'t available for suspended accounts — contact support in that case.',
      },
    ],
  },
  {
    key: 'billing',
    title: 'Billing & Wallet',
    icon: 'tabler-receipt-rupee',
    faqs: [
      {
        q: 'How does billing work?',
        a: 'Textzi is prepaid — you recharge your SMS (or WhatsApp) wallet, and every message you send debits credits from that wallet based on your rate card. There\'s no monthly subscription or lock-in for the core sending features.',
      },
      {
        q: 'What is a "segment" and how does it affect my bill?',
        a: 'Carriers bill SMS in fixed-length segments, not whole messages. A message longer than one segment\'s limit is split and billed as multiple segments — see the SMS & DLT section above for the exact character limits. Your Textzi wallet is debited per segment actually used, matching what the carrier itself charges for.',
      },
      {
        q: 'How do I add credits to my wallet?',
        a: 'Go to Wallet & Billing > Add Credits, enter an amount, and it\'s converted to credits at the rate for your assigned plan — larger recharges typically unlock a lower per-SMS rate. GST is added on top of the recharge amount.',
      },
      {
        q: 'Is GST applicable?',
        a: 'Yes, GST is charged at the prevailing rate on wallet recharges, DLT registration fees, and channel subscription fees. Every charge is reflected on a downloadable GST invoice available from the Invoices page.',
      },
      {
        q: 'Can I get a refund?',
        a: 'Credits already used to send messages aren\'t refundable, since the underlying carrier cost has already been incurred. Genuine issues — duplicate payments, a payment debited but not credited, or a fee charged for a service we failed to deliver — are eligible. See our full Refund Policy for details.',
      },
      {
        q: 'Where can I find my invoices?',
        a: 'Every recharge, fee, and admin credit generates an invoice, visible under Accounts > Invoices, with View and Download options for each one.',
      },
      {
        q: 'Do unused wallet credits expire?',
        a: 'No — credits you\'ve purchased remain in your wallet until you use them. They\'re only forfeited if you choose to close your account without requesting a refund of the remaining balance.',
      },
    ],
  },
]

const openPanels = ref<Record<string, string[]>>({ sms: [], platform: [], billing: [] })
</script>

<template>
  <div class="legal-page">
    <LandingHeader />

    <VContainer class="py-12">
      <VRow justify="center">
        <VCol
          cols="12"
          md="9"
        >
          <div class="text-center mb-10">
            <VChip
              color="primary"
              variant="tonal"
              size="small"
              class="mb-3"
            >
              Knowledge Base
            </VChip>
            <h1 class="text-h3 font-weight-bold mb-3">
              How can we help?
            </h1>
            <p class="text-medium-emphasis">
              Answers to the questions we hear most often about SMS/DLT, using the platform, and billing.
              Can't find what you need? <RouterLink to="/#contact">
                Contact us
              </RouterLink> and we'll get back to you within 48 hours.
            </p>
          </div>

          <div
            v-for="category in categories"
            :key="category.key"
            class="mb-8"
          >
            <div class="d-flex align-center gap-2 mb-3">
              <VAvatar
                color="primary"
                variant="tonal"
                size="36"
              >
                <VIcon :icon="category.icon" size="20" />
              </VAvatar>
              <h2 class="text-h5 font-weight-bold">
                {{ category.title }}
              </h2>
            </div>

            <VExpansionPanels
              v-model="openPanels[category.key]"
              multiple
              variant="accordion"
            >
              <VExpansionPanel
                v-for="faq in category.faqs"
                :key="faq.q"
                :title="faq.q"
                :text="faq.a"
              />
            </VExpansionPanels>
          </div>

          <div class="text-center mt-10">
            <VBtn
              color="primary"
              to="/#contact"
            >
              Contact Us
            </VBtn>
          </div>
        </VCol>
      </VRow>
    </VContainer>

    <LandingFooter />
  </div>
</template>

<style scoped lang="scss">
.legal-page {
  min-block-size: 100vh;
  background: rgb(var(--v-theme-background));
}
</style>
