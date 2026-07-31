<script setup lang="ts">
definePage({
  meta: {
    layout: 'blank',
    public: true,
  },
})
</script>

<template>
  <div class="legal-page">
    <LandingHeader />

    <VContainer class="py-12">
      <VRow justify="center">
        <VCol
          cols="12"
          md="8"
        >
          <h1 class="text-h3 font-weight-bold mb-2">
            Terms of Service
          </h1>
          <p class="text-medium-emphasis mb-8">
            Last updated: 31 July 2026
          </p>

          <p class="text-body-1 mb-6">
            These Terms of Service ("Terms") govern your access to and use of Textzi, a business
            messaging platform for WhatsApp and SMS, owned and operated by
            <strong>Paisape Techfin Private Limited</strong> ("Textzi", "the Company", "we",
            "us"). By creating an account or using our platform, you ("Customer", "you") agree to
            be bound by these Terms. If you do not agree, please do not use the platform.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            1. The Service
          </h2>
          <p class="text-body-1 mb-6">
            Textzi provides a dashboard and API for sending WhatsApp Business API messages and
            DLT-compliant bulk/transactional SMS in India, along with template management,
            contact/opt-out management, delivery reporting, wallet-based billing, and related
            tools. We may add, change, or discontinue features from time to time.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            2. Eligibility & Account Registration
          </h2>
          <p class="text-body-1 mb-6">
            You must be a registered business or an authorised representative of one to use
            Textzi for commercial messaging. You're responsible for the accuracy of the
            information you provide during registration and KYC, for keeping your login
            credentials confidential, and for all activity that occurs under your account. Notify
            us immediately if you suspect unauthorised access to your account.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            3. DLT / TRAI Compliance
          </h2>
          <p class="text-body-1 mb-2">
            Sending commercial SMS in India is regulated by TRAI's Telecom Commercial
            Communications Customer Preference Regulations (TCCCPR) and the Distributed Ledger
            Technology (DLT) framework. By using our SMS channel, you agree that:
          </p>
          <ul class="text-body-1 mb-6 legal-list">
            <li>You are solely responsible for registering a valid Principal Entity (PE) ID, sender header, and message templates on the DLT platform, whether self-registered or via our assisted registration service;</li>
            <li>Every message template you register and send must accurately reflect the content actually sent, with all variable placeholders matching the approved format;</li>
            <li>You will not send promotional messages to numbers registered on the National Customer Preference Register (NCPR/DND) except where explicit consent has been obtained and recorded;</li>
            <li>You are solely responsible for obtaining and retaining proof of consent from recipients before sending them any commercial communication; and</li>
            <li>Textzi may suspend delivery of any message or template that appears to violate TRAI regulations, without liability for resulting delays or losses.</li>
          </ul>

          <h2 class="text-h5 font-weight-bold mb-3">
            4. Acceptable Use
          </h2>
          <p class="text-body-1 mb-2">
            You agree not to use Textzi to send, and not to permit any third party to use your
            account to send:
          </p>
          <ul class="text-body-1 mb-6 legal-list">
            <li>Unsolicited messages to recipients who have not consented to receive them, or who have opted out;</li>
            <li>Content that is unlawful, fraudulent, defamatory, obscene, or that infringes any third party's rights;</li>
            <li>Phishing, malware, or messages impersonating another person, brand, or entity;</li>
            <li>Messages violating RBI, SEBI, IRDAI, or any other Indian regulator's guidelines applicable to your industry; or</li>
            <li>Content that violates WhatsApp's own Business Messaging Policy, where sent via our WhatsApp channel.</li>
          </ul>
          <p class="text-body-1 mb-6">
            We reserve the right to suspend or terminate any account found in violation of this
            section, immediately and without prior notice where the violation poses a legal,
            regulatory, or platform-integrity risk.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            5. Billing & Payment
          </h2>
          <ul class="text-body-1 mb-6 legal-list">
            <li>Textzi operates on a prepaid wallet model — you top up your SMS and/or WhatsApp wallet in advance, and each message sent debits credits from the relevant wallet at the rate applicable under your assigned rate card;</li>
            <li>All recharges are subject to GST at the prevailing rate, charged in addition to the recharge amount;</li>
            <li>An SMS that exceeds a single segment's character limit (160 characters for GSM-7 content, 70 for Unicode/regional-language content) is billed as multiple segments, consistent with standard telecom billing practice;</li>
            <li>DLT registration fees and channel subscription fees (where applicable) are billed separately from message credits and are described at the time of purchase; and</li>
            <li>All charges are recorded on invoices available from your dashboard, and are also synced to our accounting system for GST compliance.</li>
          </ul>
          <p class="text-body-1 mb-6">
            See our <RouterLink to="/refund-policy">Refund Policy</RouterLink> for the circumstances in which amounts paid may be refunded.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            6. Service Availability
          </h2>
          <p class="text-body-1 mb-6">
            We aim for high platform availability, but message delivery ultimately depends on
            third parties we don't control — telecom operators, the DLT registry, and WhatsApp/
            Meta. We do not guarantee delivery, delivery time, or read receipts for any individual
            message, and we are not liable for delays or failures caused by these third parties,
            network congestion, recipient handset issues, or force majeure events.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            7. Intellectual Property
          </h2>
          <p class="text-body-1 mb-6">
            The Textzi platform, including its software, design, and branding, is owned by
            Paisape Techfin Private Limited and protected by applicable intellectual property
            laws. We grant you a limited, non-exclusive, non-transferable licence to use the
            platform for your own business messaging during your subscription. You retain
            ownership of your own content, contact lists, and message templates.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            8. Confidentiality
          </h2>
          <p class="text-body-1 mb-6">
            Each party agrees to keep the other's confidential business information private and
            use it only to perform obligations under these Terms, except where disclosure is
            required by law or regulation.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            9. Limitation of Liability
          </h2>
          <p class="text-body-1 mb-6">
            To the maximum extent permitted by Indian law, Textzi's total liability arising out of
            or relating to these Terms or the platform is limited to the amount you paid us in the
            three (3) months preceding the claim. We are not liable for indirect, incidental,
            special, or consequential damages, including loss of profits, business, or data,
            arising from your use of the platform.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            10. Indemnification
          </h2>
          <p class="text-body-1 mb-6">
            You agree to indemnify and hold Textzi harmless from any claim, loss, or liability
            (including reasonable legal fees) arising from your use of the platform, your
            violation of these Terms, your violation of TRAI/DLT regulations or applicable law, or
            your infringement of any third party's rights, including any claim arising from
            messages sent through your account without proper consent.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            11. Suspension & Termination
          </h2>
          <p class="text-body-1 mb-6">
            We may suspend or terminate your account for violation of these Terms, non-payment,
            suspected fraud or abuse, or at the request of a telecom operator, DLT registry, or
            regulator. You may close your account at any time by contacting support; see our
            Refund Policy for how any remaining wallet balance is handled on closure.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            12. Governing Law & Jurisdiction
          </h2>
          <p class="text-body-1 mb-6">
            These Terms are governed by the laws of India. Any dispute arising out of or in
            connection with these Terms shall be subject to the exclusive jurisdiction of the
            courts at Mira Bhayandar, Maharashtra.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            13. Changes to These Terms
          </h2>
          <p class="text-body-1 mb-6">
            We may update these Terms from time to time. We'll post the revised Terms here with
            an updated "Last updated" date, and for material changes, we'll notify account holders
            by email. Continued use of the platform after a change takes effect constitutes
            acceptance of the revised Terms.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            14. Contact
          </h2>
          <p class="text-body-1 mb-6">
            Questions about these Terms can be sent to
            <a href="mailto:info@paisape.in">info@paisape.in</a> or 022-68833223.
          </p>

          <VBtn
            color="primary"
            to="/#contact"
            class="mt-4"
          >
            Contact Us
          </VBtn>
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

.legal-list {
  padding-inline-start: 1.25rem;

  li {
    margin-block-end: 0.5rem;
  }
}
</style>
