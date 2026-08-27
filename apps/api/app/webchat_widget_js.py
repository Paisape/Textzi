"""The embeddable widget script itself, as a plain Python string constant -- deliberately not a
built asset (no Vite/webpack step) so there's nothing to build/deploy separately from the API
container, and deliberately framework-free (no Vue/React) since it has to run inside an arbitrary
third-party page and stay small. Phase 1: bubble + panel, visitor_id persistence, the /visit and
/message calls, and a live WebSocket connection for the agent's replies. Phase 2: when /visit
reports is_online=false (business-hours check, see services.is_outside_business_hours), the
composer is replaced with a name/email capture form instead of a live text input -- the backend
side of this (send_visitor_message accepting name/email, creating the same Contact/Conversation
either way) was already built in Phase 1, this is the missing widget-side UI state. Proactive-
trigger UI remains a stub wired to the already-built backend fields, not yet implemented here."""

WIDGET_JS = r"""
(function () {
  var script = document.currentScript;
  var widgetKey = script.getAttribute('data-widget-key');
  if (!widgetKey) { return; }

  var apiOrigin = new URL(script.src).origin;
  var storageKey = 'textzi_webchat_visitor_id';
  var visitorId = null;
  try {
    visitorId = localStorage.getItem(storageKey);
    if (!visitorId) {
      visitorId = 'v-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
      localStorage.setItem(storageKey, visitorId);
    }
  } catch (e) {
    visitorId = 'v-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
  }

  var state = { open: false, online: true, greeting: 'Hi! How can we help?', color: '#F1600D', offlineMessage: '', offlineCaptured: false };
  var ws = null;

  function post(path, body) {
    return fetch(apiOrigin + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(function (r) { return r.json(); });
  }

  // Turnstile -- send_visitor_message on the backend requires a token whenever a platform secret
  // is configured (fails closed outside development, same posture as every other public form in
  // this codebase). Invisible mode (no visible checkbox) since the widget has no spare UI real
  // estate for one. Rendered once with execution:'execute' (token generated only when explicitly
  // triggered, not automatically on render) and one stable callback set at render time -- Cloudflare's
  // per-widget callback is fixed at render(), so a fresh token per send comes from calling
  // turnstile.execute(widgetId) again (implicitly resetting) and awaiting that same callback,
  // tracked via a module-scoped pending-resolver rather than passing a new callback each time.
  var turnstileWidgetId = null;
  var turnstileSetupPromise = null;
  var turnstilePendingResolve = null;

  function loadTurnstileScript() {
    if (window.turnstile) { return Promise.resolve(); }
    if (window.__textziTurnstileLoading) { return window.__textziTurnstileLoading; }
    window.__textziTurnstileLoading = new Promise(function (resolve) {
      var el = document.createElement('script');
      el.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
      el.async = true;
      el.onload = function () { resolve(); };
      el.onerror = function () { resolve(); };
      document.head.appendChild(el);
    });
    return window.__textziTurnstileLoading;
  }

  function resolveTurnstilePending(token) {
    if (turnstilePendingResolve) {
      var resolve = turnstilePendingResolve;
      turnstilePendingResolve = null;
      resolve(token || '');
    }
  }

  function setupTurnstile() {
    if (turnstileSetupPromise) { return turnstileSetupPromise; }
    turnstileSetupPromise = fetch(apiOrigin + '/v1/public/webchat/turnstile-config').then(function (r) { return r.json(); })
      .then(function (config) {
        if (!config || !config.site_key) { return null; }
        return loadTurnstileScript().then(function () {
          if (!window.turnstile) { return null; }
          var container = document.createElement('div');
          container.style.display = 'none';
          document.body.appendChild(container);
          turnstileWidgetId = window.turnstile.render(container, {
            sitekey: config.site_key, size: 'invisible', execution: 'execute',
            callback: function (token) { resolveTurnstilePending(token); },
            'error-callback': function () { resolveTurnstilePending(''); },
            'expired-callback': function () { resolveTurnstilePending(''); },
          });
          return turnstileWidgetId;
        });
      })
      .catch(function () { return null; });
    return turnstileSetupPromise;
  }

  // Resolves to a fresh token for one send, or '' if Turnstile isn't configured/failed to load --
  // an empty token still reaches the backend, which then fails closed exactly as if this fix had
  // never shipped (no worse than before, just correctly gated instead of silently broken).
  function getTurnstileToken() {
    return setupTurnstile().then(function (widgetId) {
      if (!widgetId || !window.turnstile) { return ''; }
      return new Promise(function (resolve) {
        turnstilePendingResolve = resolve;
        try {
          window.turnstile.execute(widgetId);
        } catch (e) { resolveTurnstilePending(''); return; }
        setTimeout(function () { resolveTurnstilePending(''); }, 8000);
      });
    });
  }

  function connectSocket() {
    var wsScheme = apiOrigin.indexOf('https') === 0 ? 'wss' : 'ws';
    var wsUrl = wsScheme + '://' + apiOrigin.replace(/^https?:\/\//, '') + '/v1/public/webchat/' + widgetKey + '/ws?visitor_id=' + encodeURIComponent(visitorId);
    try {
      ws = new WebSocket(wsUrl);
      ws.onmessage = function (event) {
        try {
          var data = JSON.parse(event.data);
          if (data.type === 'message' && data.message && data.message.direction === 'outbound') {
            if (data.message.message_type && data.message.message_type !== 'text' && data.message.media_url) {
              appendMedia(data.message.id, data.message.message_type, 'agent');
            } else {
              appendRichMessage(data.message.body, 'agent');
            }
          } else if (data.type === 'csat_request') {
            appendCsatPrompt();
          }
        } catch (e) {}
      };
      ws.onclose = function () { setTimeout(connectSocket, 3000); };
    } catch (e) {}
  }

  var root = document.createElement('div');
  root.style.position = 'fixed';
  root.style.bottom = '20px';
  root.style.right = '20px';
  root.style.zIndex = '999999';
  root.style.fontFamily = 'system-ui, -apple-system, sans-serif';
  document.body.appendChild(root);

  var bubble = document.createElement('button');
  bubble.id = 'textzi-widget-bubble';
  bubble.textContent = 'Chat';
  bubble.style.cssText = 'border:0;border-radius:999px;padding:14px 20px;color:#fff;font-size:15px;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.2);';
  root.appendChild(bubble);

  var panel = document.createElement('div');
  panel.style.cssText = 'display:none;position:fixed;bottom:80px;right:20px;width:340px;max-width:90vw;height:460px;max-height:70vh;background:#fff;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.25);flex-direction:column;overflow:hidden;';
  root.appendChild(panel);

  var header = document.createElement('div');
  header.style.cssText = 'padding:14px 16px;color:#fff;font-size:14px;';
  panel.appendChild(header);

  var thread = document.createElement('div');
  thread.style.cssText = 'flex:1;overflow-y:auto;padding:12px;font-size:14px;';
  panel.appendChild(thread);

  // Live composer (online) -----------------------------------------------------------------
  // A small contenteditable + toolbar rather than a full editor library, to keep the widget
  // tiny/framework-free -- output is real HTML (bold/italic/link/list), sanitized server-side
  // (services.sanitize_rich_text) before storage, since this is untrusted visitor input.
  var composerWrap = document.createElement('div');
  composerWrap.style.cssText = 'border-top:1px solid #eee;padding:8px;';

  var toolbar = document.createElement('div');
  toolbar.style.cssText = 'display:flex;gap:4px;margin-bottom:6px;';
  function makeToolbarBtn(label, title, command, value) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = label;
    btn.title = title;
    btn.style.cssText = 'border:1px solid #ddd;background:#fff;border-radius:4px;width:26px;height:26px;cursor:pointer;font-size:12px;';
    btn.addEventListener('mousedown', function (e) {
      e.preventDefault(); // keep focus/selection in the editable div
      document.execCommand(command, false, value || null);
      input.focus();
    });
    return btn;
  }
  var boldBtn = makeToolbarBtn('B', 'Bold', 'bold');
  boldBtn.style.fontWeight = 'bold';
  var italicBtn = makeToolbarBtn('I', 'Italic', 'italic');
  italicBtn.style.fontStyle = 'italic';
  var listBtn = makeToolbarBtn('•', 'Bullet list', 'insertUnorderedList');
  var linkBtn = makeToolbarBtn('🔗', 'Link', '');
  linkBtn.addEventListener('mousedown', function (e) {
    e.preventDefault();
    var url = window.prompt('Link URL:');
    if (url) { document.execCommand('createLink', false, url); }
    input.focus();
  });
  toolbar.appendChild(boldBtn);
  toolbar.appendChild(italicBtn);
  toolbar.appendChild(listBtn);
  toolbar.appendChild(linkBtn);
  composerWrap.appendChild(toolbar);

  var composer = document.createElement('div');
  composer.style.cssText = 'display:flex;';
  var attachBtn = document.createElement('button');
  attachBtn.type = 'button';
  attachBtn.textContent = '📎';
  attachBtn.title = 'Attach a file';
  attachBtn.style.cssText = 'border:1px solid #ddd;background:#fff;border-radius:6px;width:34px;cursor:pointer;font-size:15px;margin-right:6px;';
  var fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.style.display = 'none';
  fileInput.accept = 'image/jpeg,image/png,image/webp,application/pdf,.doc,.docx,.xls,.xlsx,.txt';
  var input = document.createElement('div');
  input.contentEditable = 'true';
  input.setAttribute('data-placeholder', 'Type a message...');
  input.style.cssText = 'flex:1;border:1px solid #ddd;border-radius:6px;padding:8px;font-size:14px;min-height:20px;max-height:80px;overflow-y:auto;outline:none;';
  var sendBtn = document.createElement('button');
  sendBtn.textContent = 'Send';
  sendBtn.style.cssText = 'margin-left:8px;border:0;border-radius:6px;padding:8px 14px;color:#fff;cursor:pointer;align-self:flex-end;';
  composer.appendChild(attachBtn);
  composer.appendChild(fileInput);
  composer.appendChild(input);
  composer.appendChild(sendBtn);
  composerWrap.appendChild(composer);
  panel.appendChild(composerWrap);

  // Lightweight placeholder emulation for the contenteditable div (no :placeholder-shown reliance
  // across older browsers -- just toggle a CSS class based on actual content).
  function updatePlaceholderState() {
    if (input.textContent.trim() === '') { input.classList.add('textzi-empty'); } else { input.classList.remove('textzi-empty'); }
  }
  var placeholderStyle = document.createElement('style');
  placeholderStyle.textContent = '.textzi-empty:before{content:attr(data-placeholder);color:#999;pointer-events:none;}';
  document.head.appendChild(placeholderStyle);
  input.addEventListener('input', updatePlaceholderState);
  updatePlaceholderState();

  // Offline capture form (shown instead of the composer when is_online is false) -----------
  var offlineForm = document.createElement('div');
  offlineForm.style.cssText = 'display:none;border-top:1px solid #eee;padding:10px;';
  var offlineNote = document.createElement('p');
  offlineNote.style.cssText = 'margin:0 0 8px;font-size:13px;color:#555;';
  var offlineNameInput = document.createElement('input');
  offlineNameInput.type = 'text';
  offlineNameInput.placeholder = 'Your name';
  offlineNameInput.style.cssText = 'width:100%;box-sizing:border-box;border:1px solid #ddd;border-radius:6px;padding:8px;font-size:14px;margin-bottom:6px;';
  var offlineEmailInput = document.createElement('input');
  offlineEmailInput.type = 'email';
  offlineEmailInput.placeholder = 'Your email';
  offlineEmailInput.style.cssText = 'width:100%;box-sizing:border-box;border:1px solid #ddd;border-radius:6px;padding:8px;font-size:14px;margin-bottom:6px;';
  var offlineMessageInput = document.createElement('textarea');
  offlineMessageInput.placeholder = 'How can we help?';
  offlineMessageInput.rows = 2;
  offlineMessageInput.style.cssText = 'width:100%;box-sizing:border-box;border:1px solid #ddd;border-radius:6px;padding:8px;font-size:14px;margin-bottom:6px;resize:none;';
  var offlineSendBtn = document.createElement('button');
  offlineSendBtn.textContent = 'Leave a message';
  offlineSendBtn.style.cssText = 'width:100%;border:0;border-radius:6px;padding:9px 14px;color:#fff;cursor:pointer;font-size:14px;';
  offlineForm.appendChild(offlineNote);
  offlineForm.appendChild(offlineNameInput);
  offlineForm.appendChild(offlineEmailInput);
  offlineForm.appendChild(offlineMessageInput);
  offlineForm.appendChild(offlineSendBtn);
  panel.appendChild(offlineForm);

  // Plain-text system strings only (greeting/offline/proactive copy from admin settings, local
  // confirmation text) -- always textContent, never innerHTML, so nothing here is ever
  // interpreted as markup.
  function appendMessage(body, who) {
    var row = document.createElement('div');
    row.style.cssText = 'margin-bottom:8px;display:flex;' + (who === 'visitor' ? 'justify-content:flex-end;' : '');
    var bubbleEl = document.createElement('div');
    bubbleEl.textContent = body;
    bubbleEl.style.cssText = 'max-width:75%;padding:8px 12px;border-radius:10px;font-size:14px;' +
      (who === 'visitor' ? 'background:' + state.color + ';color:#fff;' : 'background:#f1f1f1;color:#222;');
    row.appendChild(bubbleEl);
    thread.appendChild(row);
    thread.scrollTop = thread.scrollHeight;
  }

  // Real chat message bodies -- innerHTML, since these carry real formatting (bold/italic/link/
  // list). Safe on both sides: the visitor's own just-typed content here is their own browser
  // (nothing to protect against), and an agent's reply has already been through
  // services.sanitize_rich_text server-side by the time it round-trips back if it originated from
  // a visitor -- an agent's OWN composed HTML is trusted the same way crm-email.vue's outbound
  // v-html already is elsewhere in this codebase.
  function appendRichMessage(html, who) {
    var row = document.createElement('div');
    row.style.cssText = 'margin-bottom:8px;display:flex;' + (who === 'visitor' ? 'justify-content:flex-end;' : '');
    var bubbleEl = document.createElement('div');
    bubbleEl.innerHTML = html;
    bubbleEl.style.cssText = 'max-width:75%;padding:8px 12px;border-radius:10px;font-size:14px;word-break:break-word;' +
      (who === 'visitor' ? 'background:' + state.color + ';color:#fff;' : 'background:#f1f1f1;color:#222;');
    row.appendChild(bubbleEl);
    thread.appendChild(row);
    thread.scrollTop = thread.scrollHeight;
  }

  function appendMedia(messageId, messageType, who) {
    var mediaUrl = apiOrigin + '/v1/public/webchat/' + widgetKey + '/media/' + messageId;
    var row = document.createElement('div');
    row.style.cssText = 'margin-bottom:8px;display:flex;' + (who === 'visitor' ? 'justify-content:flex-end;' : '');
    var wrap = document.createElement('div');
    wrap.style.cssText = 'max-width:75%;border-radius:10px;overflow:hidden;' +
      (who === 'visitor' ? 'border:2px solid ' + state.color + ';' : 'border:1px solid #eee;');
    if (messageType === 'image') {
      var img = document.createElement('img');
      img.src = mediaUrl;
      img.style.cssText = 'display:block;max-width:100%;cursor:pointer;';
      img.addEventListener('click', function () { window.open(mediaUrl, '_blank'); });
      wrap.appendChild(img);
    } else {
      var link = document.createElement('a');
      link.href = mediaUrl;
      link.target = '_blank';
      link.textContent = 'Download file';
      link.style.cssText = 'display:block;padding:10px 14px;font-size:13px;background:#fff;color:#222;text-decoration:none;';
      wrap.appendChild(link);
    }
    row.appendChild(wrap);
    thread.appendChild(row);
    thread.scrollTop = thread.scrollHeight;
  }

  function applyColor() {
    bubble.style.background = state.color;
    header.style.background = state.color;
    sendBtn.style.background = state.color;
    offlineSendBtn.style.background = state.color;
  }

  function appendCsatPrompt() {
    var row = document.createElement('div');
    row.style.cssText = 'margin:10px 0;padding:10px;border:1px solid #eee;border-radius:8px;text-align:center;';
    var label = document.createElement('p');
    label.textContent = 'How was this conversation?';
    label.style.cssText = 'margin:0 0 8px;font-size:13px;color:#555;';
    row.appendChild(label);
    var starsRow = document.createElement('div');
    starsRow.style.cssText = 'display:flex;justify-content:center;gap:4px;';
    for (var n = 1; n <= 5; n++) {
      (function (rating) {
        var starBtn = document.createElement('button');
        starBtn.textContent = String(rating);
        starBtn.style.cssText = 'border:1px solid #ddd;background:#fff;border-radius:6px;width:32px;height:32px;cursor:pointer;font-size:14px;';
        starBtn.addEventListener('click', function () {
          post('/v1/public/webchat/' + widgetKey + '/csat', { visitor_id: visitorId, rating: rating }).then(function () {
            row.innerHTML = '';
            var thanks = document.createElement('p');
            thanks.textContent = 'Thanks for the feedback!';
            thanks.style.cssText = 'margin:0;font-size:13px;color:#555;';
            row.appendChild(thanks);
          });
        });
        starsRow.appendChild(starBtn);
      })(n);
    }
    row.appendChild(starsRow);
    thread.appendChild(row);
    thread.scrollTop = thread.scrollHeight;
  }

  function renderMode() {
    if (state.online || state.offlineCaptured) {
      composer.style.display = 'flex';
      offlineForm.style.display = 'none';
    } else {
      composer.style.display = 'none';
      offlineForm.style.display = 'block';
      offlineNote.textContent = state.offlineMessage || "We're offline right now -- leave your details and we'll get back to you.";
    }
  }

  function send() {
    var body = input.innerHTML.trim();
    if (!input.textContent.trim()) { return; }
    appendRichMessage(body, 'visitor');
    input.innerHTML = '';
    updatePlaceholderState();
    getTurnstileToken().then(function (token) {
      return post('/v1/public/webchat/' + widgetKey + '/message', { visitor_id: visitorId, body: body, turnstile_token: token || null });
    }).then(function () {
      if (!ws) { connectSocket(); }
    });
  }

  function sendFile(file) {
    var formData = new FormData();
    formData.append('visitor_id', visitorId);
    formData.append('file', file);
    attachBtn.disabled = true;
    fetch(apiOrigin + '/v1/public/webchat/' + widgetKey + '/media', { method: 'POST', body: formData })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.message_id) {
          appendMedia(data.message_id, file.type && file.type.indexOf('image/') === 0 ? 'image' : 'document', 'visitor');
          if (!ws) { connectSocket(); }
        }
      })
      .finally(function () { attachBtn.disabled = false; fileInput.value = ''; });
  }

  function sendOffline() {
    var body = offlineMessageInput.value.trim();
    var name = offlineNameInput.value.trim();
    var email = offlineEmailInput.value.trim();
    if (!body || !email) { return; }
    offlineSendBtn.disabled = true;
    getTurnstileToken().then(function (token) {
      return post('/v1/public/webchat/' + widgetKey + '/message', { visitor_id: visitorId, body: body, name: name || null, email: email, turnstile_token: token || null });
    }).then(function () {
      state.offlineCaptured = true;
      thread.innerHTML = '';
      appendMessage(body, 'visitor');
      appendMessage("Thanks -- we've got your message and will reply by email or here as soon as we're back online.", 'agent');
      renderMode();
    }).finally(function () { offlineSendBtn.disabled = false; });
  }

  sendBtn.addEventListener('click', send);
  input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { send(); } });
  attachBtn.addEventListener('click', function () { fileInput.click(); });
  fileInput.addEventListener('change', function () {
    if (fileInput.files && fileInput.files[0]) { sendFile(fileInput.files[0]); }
  });
  offlineSendBtn.addEventListener('click', sendOffline);
  bubble.addEventListener('click', function () {
    state.open = !state.open;
    panel.style.display = state.open ? 'flex' : 'none';
  });

  function openPanel() {
    if (state.open) { return; }
    state.open = true;
    panel.style.display = 'flex';
  }

  post('/v1/public/webchat/' + widgetKey + '/visit', {
    visitor_id: visitorId, current_url: window.location.href, referrer: document.referrer || null,
  }).then(function (data) {
    if (!data || data.detail) { return; }
    state.online = !!data.is_online;
    state.greeting = data.greeting_message || state.greeting;
    state.color = data.bubble_color || state.color;
    state.offlineMessage = data.offline_message || '';
    header.textContent = state.online ? state.greeting : 'We are offline';
    if (state.online && !thread.childNodes.length) {
      appendMessage(state.greeting, 'agent');
    }
    applyColor();
    renderMode();

    // Proactive trigger -- only makes sense while online (an offline proactive nudge would just
    // dump someone into the email-capture form unprompted, not a good first impression), and only
    // on pages matching proactive_url_pattern if one is configured (substring match against the
    // current URL -- e.g. "/pricing" only fires on pricing pages, empty/null means every page).
    var urlMatches = !data.proactive_url_pattern || window.location.href.indexOf(data.proactive_url_pattern) !== -1;
    if (data.proactive_trigger_enabled && state.online && data.proactive_trigger_message && urlMatches) {
      var fireProactive = function () {
        if (state.open) { return; }
        appendMessage(data.proactive_trigger_message, 'agent');
        openPanel();
      };
      if (data.proactive_trigger_type === 'exit_intent') {
        // Fires the first time the cursor crosses above the top of the viewport -- the standard
        // "about to close the tab / switch away" signal every proactive-chat product uses.
        var exitIntentHandler = function (e) {
          if (e.clientY <= 0) {
            fireProactive();
            document.removeEventListener('mouseleave', exitIntentHandler);
          }
        };
        document.addEventListener('mouseleave', exitIntentHandler);
      } else {
        setTimeout(fireProactive, Math.max(1, data.proactive_trigger_delay_seconds || 30) * 1000);
      }
    }
  });

  connectSocket();
})();
"""
