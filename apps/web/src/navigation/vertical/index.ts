// Nav items for each channel's own workspace -- shared between customerNav's nested groups
// (shown when browsing the general dashboard) and channelFocusedNav's flattened list (shown once
// inside that channel's own focused workspace at /waba or /crm), so the two never drift apart.
export const WABA_NAV_ITEMS = [
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
]

export const CRM_NAV_ITEMS = [
  {
    title: 'Helpdesk',
    icon: { icon: 'tabler-headset' },
    children: [
      {
        title: 'Tickets',
        to: { name: 'tickets' },
        icon: { icon: 'tabler-ticket' },
      },
    ],
  },
  {
    title: 'Email',
    to: { name: 'crm-email' },
    icon: { icon: 'tabler-mail' },
  },
  {
    title: 'Leads',
    to: { name: 'crm-leads' },
    icon: { icon: 'tabler-target-arrow' },
  },
  {
    title: 'Contacts',
    to: { name: 'crm-contacts' },
    icon: { icon: 'tabler-address-book' },
  },
  {
    title: 'Deals',
    to: { name: 'crm-deals' },
    icon: { icon: 'tabler-briefcase' },
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
    title: 'Report Builder',
    to: { name: 'crm-report-builder' },
    icon: { icon: 'tabler-chart-dots' },
  },
  {
    title: 'Manage',
    to: { name: 'channels-crm' },
    icon: { icon: 'tabler-settings' },
  },
]

export const SMS_NAV_ITEMS = [
  {
    title: 'Send SMS',
    to: { name: 'sms' },
    icon: { icon: 'tabler-message-2' },
  },
  {
    title: 'Manage',
    to: { name: 'channels-sms' },
    icon: { icon: 'tabler-settings' },
  },
]

// The focused workspace shown at /waba or /crm once a channel tile is opened -- flattens that
// channel's own nav (no longer nested under a "WhatsApp"/"CRM" parent, since the whole workspace
// already is that channel) and prepends a way back to the general dashboard, hidden entirely for
// a teammate whose channel_scope locks them to this one channel permanently.
//
// pageScope (team.vue, set at invite time alongside channel_scope) narrows further to just a few
// pages within that channel -- null shows everything, matching today's default. A group with
// children (Helpdesk) keeps only the children whose route is in scope, and disappears entirely
// if none are.
function filterByPageScope(items: any[], pageScope: string[] | null): any[] {
  if (!pageScope)
    return items
  return items
    .map((item) => {
      if (item.children) {
        const children = filterByPageScope(item.children, pageScope)
        return children.length ? { ...item, children } : null
      }
      return item.to && pageScope.includes(item.to.name) ? item : null
    })
    .filter(item => item !== null)
}

export function channelFocusedNav(channel: 'sms' | 'waba' | 'crm', canSwitch: boolean, pageScope: string[] | null = null) {
  const items = channel === 'waba' ? WABA_NAV_ITEMS : channel === 'crm' ? CRM_NAV_ITEMS : SMS_NAV_ITEMS
  return [
    ...(canSwitch
      ? [{
          title: 'Dashboard',
          to: { name: 'dashboard' },
          icon: { icon: 'tabler-arrow-back-up' },
        }]
      : []),
    ...filterByPageScope(items, pageScope),
  ]
}

// WhatsApp and CRM are shown as dedicated menu groups only once that channel is actually active
// (WhatsApp: a connected WABA number; CRM: channel_active(db, entity_id, "crm") -- currently
// free/always-on until CRM pricing exists). Before that, the Channels marketplace page is still
// how a tenant discovers and activates either one -- always visible, never gated. SMS has no such
// gating since every tenant has it by default; kept as the first channel group per the requested
// SMS -> WhatsApp -> CRM ordering.
//
// `minimal` -- used only on the Dashboard page itself, which already has its own "Channels" tile
// section with Open/Manage actions per channel. Showing WhatsApp/CRM's full ~12-item submenu
// there too is pure clutter, so on Dashboard they collapse to a single link straight into that
// channel's focused workspace (/waba, /crm) instead of an expandable group. Every other page
// (including every page inside a channel) keeps the full expandable submenu unchanged.
export function customerNav(status: { wabaActive: boolean, crmActive: boolean }, opts: { minimal?: boolean } = {}) {
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
      ? [opts.minimal
        ? {
            title: 'WhatsApp',
            to: { name: 'waba' },
            icon: { icon: 'tabler-brand-whatsapp' },
          }
        : {
            title: 'WhatsApp',
            icon: { icon: 'tabler-brand-whatsapp' },
            children: WABA_NAV_ITEMS,
          }]
      : []),
    ...(status.crmActive
      ? [opts.minimal
        ? {
            title: 'CRM',
            to: { name: 'crm' },
            icon: { icon: 'tabler-address-book' },
          }
        : {
            title: 'CRM',
            icon: { icon: 'tabler-address-book' },
            children: CRM_NAV_ITEMS,
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
    title: 'Textzi Mailboxes',
    to: { name: 'admin-mailboxes' },
    icon: { icon: 'tabler-mailbox' },
  },
  {
    title: 'Mail Log',
    to: { name: 'admin-mail-log' },
    icon: { icon: 'tabler-mail-opened' },
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
    title: 'WhatsApp API Log',
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
        title: 'Razorpay Setting',
        to: { name: 'platform-razorpay-settings' },
        icon: { icon: 'tabler-credit-card' },
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
        title: 'Stalwart Setting',
        to: { name: 'platform-stalwart-settings' },
        icon: { icon: 'tabler-server-cog' },
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
