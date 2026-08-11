// WhatsApp and CRM are shown as dedicated menu groups only once that channel is actually active
// (WhatsApp: a connected WABA number; CRM: channel_active(db, entity_id, "crm") -- currently
// free/always-on until CRM pricing exists). Before that, the Channels marketplace page is still
// how a tenant discovers and activates either one -- always visible, never gated. SMS has no such
// gating since every tenant has it by default; kept as the first channel group per the requested
// SMS -> WhatsApp -> CRM ordering.
export function customerNav(status: { wabaActive: boolean, crmActive: boolean }) {
  return [
    {
      title: 'Home',
      to: { name: 'dashboard' },
      icon: { icon: 'tabler-smart-home' },
    },
    {
      title: 'Send SMS',
      to: { name: 'sms' },
      icon: { icon: 'tabler-message-2' },
    },
    ...(status.wabaActive
      ? [{
          title: 'WhatsApp',
          icon: { icon: 'tabler-brand-whatsapp' },
          children: [
            {
              title: 'Inbox',
              to: { name: 'inbox' },
              icon: { icon: 'tabler-messages' },
            },
            {
              title: 'Customers',
              to: { name: 'waba-customers' },
              icon: { icon: 'tabler-users' },
            },
            {
              title: 'Campaigns',
              to: { name: 'waba-campaigns' },
              icon: { icon: 'tabler-speakerphone' },
            },
            {
              title: 'Reports',
              to: { name: 'waba-reports' },
              icon: { icon: 'tabler-chart-bar' },
            },
            {
              title: 'Manage',
              to: { name: 'channels-whatsapp' },
              icon: { icon: 'tabler-settings' },
            },
          ],
        }]
      : []),
    ...(status.crmActive
      ? [{
          title: 'CRM',
          icon: { icon: 'tabler-address-book' },
          children: [
            {
              title: 'Tickets',
              to: { name: 'tickets' },
              icon: { icon: 'tabler-ticket' },
            },
            {
              title: 'Leads',
              to: { name: 'crm-leads' },
              icon: { icon: 'tabler-target-arrow' },
            },
            {
              title: 'Customers',
              to: { name: 'crm-customers' },
              icon: { icon: 'tabler-user-check' },
            },
            {
              title: 'Companies',
              to: { name: 'crm-companies' },
              icon: { icon: 'tabler-building' },
            },
            {
              title: 'Tasks',
              to: { name: 'crm-tasks' },
              icon: { icon: 'tabler-checklist' },
            },
            {
              title: 'Quotes',
              to: { name: 'crm-quotes' },
              icon: { icon: 'tabler-file-text' },
            },
            {
              title: 'Automation',
              to: { name: 'crm-automation' },
              icon: { icon: 'tabler-route' },
            },
            {
              title: 'Pipelines',
              to: { name: 'crm-pipelines' },
              icon: { icon: 'tabler-timeline' },
            },
            {
              title: 'Reports',
              to: { name: 'crm-reports' },
              icon: { icon: 'tabler-chart-bar' },
            },
            {
              title: 'Manage',
              to: { name: 'channels-crm' },
              icon: { icon: 'tabler-settings' },
            },
          ],
        }]
      : []),
    {
      title: 'Channels',
      to: { name: 'channels' },
      icon: { icon: 'tabler-apps' },
    },
    {
      title: 'Wallet & Billing',
      to: { name: 'wallet' },
      icon: { icon: 'tabler-wallet' },
    },
    {
      title: 'Accounts',
      icon: { icon: 'tabler-file-invoice' },
      children: [
        {
          title: 'Invoices',
          to: { name: 'invoices' },
          icon: { icon: 'tabler-receipt' },
        },
        {
          title: 'Team',
          to: { name: 'team' },
          icon: { icon: 'tabler-users-group' },
        },
        {
          title: 'Testimonials',
          to: { name: 'testimonials' },
          icon: { icon: 'tabler-message-star' },
        },
      ],
    },
    {
      title: 'Reports',
      icon: { icon: 'tabler-report-analytics' },
      children: [
        {
          title: 'Wallet Ledger',
          to: { name: 'reports-wallet-ledger' },
          icon: { icon: 'tabler-wallet' },
        },
        {
          title: 'Payment Ledger',
          to: { name: 'reports-payment-ledger' },
          icon: { icon: 'tabler-credit-card' },
        },
        {
          title: 'Purchase Ledger',
          to: { name: 'reports-purchase-ledger' },
          icon: { icon: 'tabler-shopping-cart' },
        },
        {
          title: 'Activity Log',
          to: { name: 'reports-activity-log' },
          icon: { icon: 'tabler-history' },
        },
        {
          title: 'API Log',
          to: { name: 'reports-api-log' },
          icon: { icon: 'tabler-terminal-2' },
        },
      ],
    },
  ]
}

export const adminNav = [
  {
    title: 'Home',
    to: { name: 'dashboard' },
    icon: { icon: 'tabler-smart-home' },
  },
  {
    title: 'DLT Hierarchy',
    to: { name: 'dlt' },
    icon: { icon: 'tabler-sitemap' },
  },
  {
    title: 'Settings',
    icon: { icon: 'tabler-settings' },
    children: [
      {
        title: 'Provider Routes',
        to: { name: 'provider-routes' },
        icon: { icon: 'tabler-route' },
      },
      {
        title: 'Channel Settings',
        to: { name: 'channel-settings' },
        icon: { icon: 'tabler-adjustments' },
      },
      {
        title: 'DLT Requests',
        to: { name: 'dlt-requests' },
        icon: { icon: 'tabler-file-certificate' },
      },
      {
        title: 'Profile Change Requests',
        to: { name: 'profile-change-requests' },
        icon: { icon: 'tabler-user-edit' },
      },
    ],
  },
  {
    title: 'Rate Cards',
    to: { name: 'rate-cards' },
    icon: { icon: 'tabler-receipt-rupee' },
  },
  {
    title: 'Billing Plans',
    to: { name: 'admin-billing-plans' },
    icon: { icon: 'tabler-credit-card' },
  },
  {
    title: 'Users',
    to: { name: 'users' },
    icon: { icon: 'tabler-users' },
  },
  {
    title: 'Customers',
    to: { name: 'customers' },
    icon: { icon: 'tabler-building-store' },
  },
  {
    title: 'Analytics',
    to: { name: 'admin-analytics' },
    icon: { icon: 'tabler-chart-line' },
  },
  {
    title: 'Audit Log',
    to: { name: 'admin-audit-log' },
    icon: { icon: 'tabler-history' },
  },
  {
    title: 'SMS Log & Report',
    to: { name: 'admin-messages' },
    icon: { icon: 'tabler-message-report' },
  },
  {
    title: 'API Log & Report',
    to: { name: 'admin-api-log' },
    icon: { icon: 'tabler-api' },
  },
  {
    title: 'WhatsApp Webhook Log',
    to: { name: 'admin-waba-webhook-log' },
    icon: { icon: 'tabler-brand-whatsapp' },
  },
  {
    title: 'Contact Us Submissions',
    to: { name: 'admin-contact-messages' },
    icon: { icon: 'tabler-mail-question' },
  },
  {
    title: 'Testimonials',
    to: { name: 'admin-testimonials' },
    icon: { icon: 'tabler-message-star' },
  },
  {
    title: 'Billing',
    icon: { icon: 'tabler-building-bank' },
    children: [
      {
        title: 'Wallet Credits',
        to: { name: 'admin-wallet-credits' },
        icon: { icon: 'tabler-coin' },
      },
      {
        title: 'Invoices',
        to: { name: 'admin-invoices' },
        icon: { icon: 'tabler-receipt' },
      },
      {
        title: 'Payment Reconciliation',
        to: { name: 'payment-reconciliation' },
        icon: { icon: 'tabler-refresh' },
      },
      {
        title: 'Wallet Top-up Report',
        to: { name: 'admin-wallet-topup-report' },
        icon: { icon: 'tabler-shield-check' },
      },
      {
        title: 'Usage',
        to: { name: 'admin-usage' },
        icon: { icon: 'tabler-chart-bar' },
      },
      {
        title: 'Delivery Status Rules',
        to: { name: 'delivery-status-rules' },
        icon: { icon: 'tabler-list-check' },
      },
    ],
  },
  {
    title: 'Platform Settings',
    icon: { icon: 'tabler-server-cog' },
    children: [
      {
        title: 'General Setting',
        to: { name: 'platform-general-settings' },
        icon: { icon: 'tabler-settings-cog' },
      },
      {
        title: 'SMS Setting',
        to: { name: 'platform-sms-settings' },
        icon: { icon: 'tabler-message-cog' },
      },
      {
        title: 'SMTP Setting',
        to: { name: 'platform-smtp-settings' },
        icon: { icon: 'tabler-mail-cog' },
      },
      {
        title: 'Zoho Books Integration',
        to: { name: 'platform-zoho-settings' },
        icon: { icon: 'tabler-building-bank' },
      },
      {
        title: 'Zoho Sync Log',
        to: { name: 'zoho-sync-log' },
        icon: { icon: 'tabler-list-details' },
      },
      {
        title: 'R2 Setting',
        to: { name: 'platform-r2-settings' },
        icon: { icon: 'tabler-cloud-cog' },
      },
      {
        title: 'Turnstile Setting',
        to: { name: 'platform-turnstile-settings' },
        icon: { icon: 'tabler-shield-check' },
      },
      {
        title: 'WhatsApp Setting',
        to: { name: 'platform-waba-settings' },
        icon: { icon: 'tabler-brand-whatsapp' },
      },
      {
        title: 'Archive Status',
        to: { name: 'archive-status' },
        icon: { icon: 'tabler-archive' },
      },
    ],
  },
]

// Scoped platform-staff roles (finance_team/sales_team/support_team) -- each sees only its own
// slice of the admin panel, enforced backend-side by admin.STAFF_AREA_ROLES; these arrays just
// decide what to show, not what's actually reachable.
export const financeNav = [
  {
    title: 'Home',
    to: { name: 'dashboard' },
    icon: { icon: 'tabler-smart-home' },
  },
  {
    title: 'Billing',
    icon: { icon: 'tabler-building-bank' },
    children: [
      {
        title: 'Wallet Credits',
        to: { name: 'admin-wallet-credits' },
        icon: { icon: 'tabler-coin' },
      },
      {
        title: 'Invoices',
        to: { name: 'admin-invoices' },
        icon: { icon: 'tabler-receipt' },
      },
      {
        title: 'Wallet Top-up Report',
        to: { name: 'admin-wallet-topup-report' },
        icon: { icon: 'tabler-shield-check' },
      },
      {
        title: 'Usage',
        to: { name: 'admin-usage' },
        icon: { icon: 'tabler-chart-bar' },
      },
    ],
  },
]

export const salesNav = [
  {
    title: 'Home',
    to: { name: 'dashboard' },
    icon: { icon: 'tabler-smart-home' },
  },
  {
    title: 'Customers',
    to: { name: 'customers' },
    icon: { icon: 'tabler-building-store' },
  },
  {
    title: 'Analytics',
    to: { name: 'admin-analytics' },
    icon: { icon: 'tabler-chart-line' },
  },
  {
    title: 'Rate Cards',
    to: { name: 'rate-cards' },
    icon: { icon: 'tabler-receipt-rupee' },
  },
]

export const supportNav = [
  {
    title: 'Home',
    to: { name: 'dashboard' },
    icon: { icon: 'tabler-smart-home' },
  },
  {
    title: 'Contact Us Submissions',
    to: { name: 'admin-contact-messages' },
    icon: { icon: 'tabler-mail-question' },
  },
  {
    title: 'Users',
    to: { name: 'users' },
    icon: { icon: 'tabler-users' },
  },
  {
    title: 'Audit Log',
    to: { name: 'admin-audit-log' },
    icon: { icon: 'tabler-history' },
  },
]
