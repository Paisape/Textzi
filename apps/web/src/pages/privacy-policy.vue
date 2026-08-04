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
            Privacy Policy
          </h1>
          <p class="text-medium-emphasis mb-8">
            Last updated: 31 July 2026
          </p>

          <p class="text-body-1 mb-6">
            Textzi ("Textzi", "we", "us", "our") is a business messaging platform for WhatsApp
            and SMS, owned and operated by <strong>Paisape Techfin Private Limited</strong>
            ("the Company"), a company incorporated in India. This Privacy Policy explains what
            personal data we collect through textzi.in and the Textzi platform, why we collect
            it, how we use and protect it, and the choices and rights available to you. By using
            our website or platform, you agree to the practices described here.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            1. Information We Collect
          </h2>
          <p class="text-body-1 mb-2">
            <strong>Account and business information:</strong> name, email address, mobile
            number, password (stored as a salted hash, never in plain text), company name, GSTIN
            and business address, and KYC/onboarding details you provide.
          </p>
          <p class="text-body-1 mb-2">
            <strong>DLT and messaging identity data:</strong> Principal Entity (PE) IDs, DLT
            header/sender IDs, and message template content you register — this data is also
            shared with the DLT registry and telecom operators, since that registration is a
            regulatory requirement for sending commercial messages in India.
          </p>
          <p class="text-body-1 mb-2">
            <strong>Message and recipient data:</strong> the mobile numbers you send to, and the
            content of messages sent through the platform. If you enable message encryption for
            a channel, message content and recipient numbers are encrypted at rest; without it,
            they're stored in plain text so you can review your own send history.
          </p>
          <p class="text-body-1 mb-2">
            <strong>Billing and payment information:</strong> wallet recharge amounts, invoices,
            GST details, and payment references from our payment gateway. We do not store your
            full card or UPI credentials — those are handled directly by our payment processor.
          </p>
          <p class="text-body-1 mb-2">
            <strong>Usage and technical data:</strong> login timestamps, IP address, browser/device
            information, API request logs, and delivery reports from telecom operators, collected
            to operate, secure, and troubleshoot the platform.
          </p>
          <p class="text-body-1 mb-2">
            <strong>Website visit data:</strong> when you browse our public marketing site
            (whether or not you have an account), we record which pages you view, how you got
            there (referring page), your approximate country (from your IP address — never a
            precise location), and your browser/operating system/device type. This is grouped
            into an anonymous browsing session using an identifier stored in your browser — we do
            not know who you are unless you separately register or log in. We never collect your
            name, email, or mobile number this way, and we never access your browsing activity on
            any other website.
          </p>
          <p class="text-body-1 mb-6">
            <strong>Contact form and support data:</strong> anything you submit via our Contact
            form or to our support team (name, email, phone, company, message).
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            2. How We Use Your Information
          </h2>
          <p class="text-body-1 mb-2">
            We use the information we collect to:
          </p>
          <ul class="text-body-1 mb-6 legal-list">
            <li>Create and manage your account, and authenticate you when you sign in;</li>
            <li>Register and maintain your DLT entity/header/template mappings with the DLT registry and telecom operators, as legally required to send commercial SMS in India;</li>
            <li>Deliver the WhatsApp/SMS messages you send through the platform, and report delivery status back to you;</li>
            <li>Process wallet recharges, generate invoices, and comply with GST and other tax obligations;</li>
            <li>Send you transactional communications — OTPs, account verification, invoices, service notifications, and responses to support requests;</li>
            <li>Detect, investigate, and prevent fraud, abuse, and violations of our Terms of Service;</li>
            <li>Improve and secure the platform, and comply with applicable law.</li>
          </ul>

          <h2 class="text-h5 font-weight-bold mb-3">
            3. How We Share Your Information
          </h2>
          <p class="text-body-1 mb-2">
            We do not sell your personal data. We share it only where necessary to operate the
            service, and only with:
          </p>
          <ul class="text-body-1 mb-6 legal-list">
            <li><strong>Telecom operators and the DLT registry</strong> — to register your sender identity/templates and route your messages;</li>
            <li><strong>WhatsApp/Meta</strong> — where you use our WhatsApp Business API channel, subject to Meta's own data handling terms;</li>
            <li><strong>Payment gateway providers</strong> — to process wallet recharges securely;</li>
            <li><strong>Our accounting system (ERPNext)</strong> — to generate and record invoices for GST/accounting compliance;</li>
            <li><strong>Service providers who support our infrastructure</strong> (hosting, email delivery), bound by confidentiality obligations; and</li>
            <li><strong>Law enforcement or regulators</strong>, where required by Indian law or a valid legal process.</li>
          </ul>

          <h2 class="text-h5 font-weight-bold mb-3">
            4. Data Retention
          </h2>
          <p class="text-body-1 mb-6">
            We retain account, billing, and invoice data for as long as your account is active
            and thereafter for as long as required to meet our accounting, tax, and legal
            obligations under Indian law (typically at least 8 years for financial records).
            Message content and recipient data are retained for as long as reasonably needed for
            delivery reporting, dispute resolution, and fraud prevention, after which they may be
            deleted or anonymised.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            5. Data Security
          </h2>
          <p class="text-body-1 mb-6">
            We use industry-standard safeguards to protect your data, including encrypted
            connections (HTTPS/TLS) for all traffic, salted password hashing, optional
            encryption-at-rest for message content and recipient numbers, two-factor
            authentication for account access, and role-based access controls that limit who on
            our team can view sensitive data. No method of transmission or storage is 100%
            secure, but we work to protect your information using these commercially reasonable
            measures.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            6. Your Rights
          </h2>
          <p class="text-body-1 mb-2">
            Subject to applicable law, including the Digital Personal Data Protection Act, 2023,
            you have the right to:
          </p>
          <ul class="text-body-1 mb-6 legal-list">
            <li>Access the personal data we hold about you;</li>
            <li>Request correction of inaccurate or incomplete data;</li>
            <li>Request deletion of your personal data, subject to our legal/regulatory retention obligations (e.g. financial records, DLT registration data);</li>
            <li>Withdraw consent for optional communications at any time; and</li>
            <li>Lodge a grievance with our Grievance Officer (below) if you believe your data has been misused.</li>
          </ul>
          <p class="text-body-1 mb-6">
            To exercise any of these rights, contact us using the details in Section 9 below.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            7. Cookies
          </h2>
          <p class="text-body-1 mb-6">
            Our website and dashboard use essential cookies/local storage to keep you signed in
            and remember your preferences (such as theme), and a first-party identifier (also
            local storage, not a cookie) to group your page views on our marketing site into one
            anonymous session, as described in Section 1. We do not use third-party advertising or
            tracking cookies, and this identifier is never shared with anyone outside Textzi.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            8. Children's Privacy
          </h2>
          <p class="text-body-1 mb-6">
            Textzi is a business-to-business platform and is not directed at, or intended for use
            by, individuals under the age of 18. We do not knowingly collect personal data from
            children.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            9. Grievance Officer & Contact
          </h2>
          <p class="text-body-1 mb-2">
            In accordance with the Information Technology Act, 2000 and rules made thereunder,
            the Grievance Officer for Textzi is:
          </p>
          <p class="text-body-1 mb-6">
            Paisape Techfin Private Limited<br>
            Office No. 409, 4th Floor, Fortune Emporio, Opposite Thakur Mall,
            Western Express Hwy, Mira Road East, Mira Bhayandar, Maharashtra 401107<br>
            Phone: 022-68833223<br>
            Email: <a href="mailto:info@paisape.in">info@paisape.in</a>
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            10. Changes to This Policy
          </h2>
          <p class="text-body-1 mb-6">
            We may update this Privacy Policy from time to time to reflect changes in our
            practices or legal requirements. We'll post the revised policy here with an updated
            "Last updated" date, and for material changes, we'll notify account holders by email.
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
