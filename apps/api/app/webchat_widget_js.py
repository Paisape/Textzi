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

  function connectSocket() {
    var wsScheme = apiOrigin.indexOf('https') === 0 ? 'wss' : 'ws';
    var wsUrl = wsScheme + '://' + apiOrigin.replace(/^https?:\/\//, '') + '/v1/public/webchat/' + widgetKey + '/ws?visitor_id=' + encodeURIComponent(visitorId);
    try {
      ws = new WebSocket(wsUrl);
      ws.onmessage = function (event) {
        try {
          var data = JSON.parse(event.data);
          if (data.type === 'message' && data.message && data.message.direction === 'outbound') {
            appendMessage(data.message.body, 'agent');
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
  var composer = document.createElement('div');
  composer.style.cssText = 'display:flex;border-top:1px solid #eee;padding:8px;';
  var input = document.createElement('input');
  input.type = 'text';
  input.placeholder = 'Type a message...';
  input.style.cssText = 'flex:1;border:1px solid #ddd;border-radius:6px;padding:8px;font-size:14px;';
  var sendBtn = document.createElement('button');
  sendBtn.textContent = 'Send';
  sendBtn.style.cssText = 'margin-left:8px;border:0;border-radius:6px;padding:8px 14px;color:#fff;cursor:pointer;';
  composer.appendChild(input);
  composer.appendChild(sendBtn);
  panel.appendChild(composer);

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
    var body = input.value.trim();
    if (!body) { return; }
    appendMessage(body, 'visitor');
    input.value = '';
    post('/v1/public/webchat/' + widgetKey + '/message', { visitor_id: visitorId, body: body }).then(function () {
      if (!ws) { connectSocket(); }
    });
  }

  function sendOffline() {
    var body = offlineMessageInput.value.trim();
    var name = offlineNameInput.value.trim();
    var email = offlineEmailInput.value.trim();
    if (!body || !email) { return; }
    offlineSendBtn.disabled = true;
    post('/v1/public/webchat/' + widgetKey + '/message', { visitor_id: visitorId, body: body, name: name || null, email: email }).then(function () {
      state.offlineCaptured = true;
      thread.innerHTML = '';
      appendMessage(body, 'visitor');
      appendMessage("Thanks -- we've got your message and will reply by email or here as soon as we're back online.", 'agent');
      renderMode();
    }).finally(function () { offlineSendBtn.disabled = false; });
  }

  sendBtn.addEventListener('click', send);
  input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { send(); } });
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

    // Proactive trigger -- auto-opens the bubble after the configured delay if the visitor
    // hasn't interacted yet (only makes sense while online -- an offline proactive nudge would
    // just dump someone into the email-capture form unprompted, not a good first impression).
    if (data.proactive_trigger_enabled && state.online && data.proactive_trigger_message) {
      setTimeout(function () {
        if (state.open) { return; }
        appendMessage(data.proactive_trigger_message, 'agent');
        openPanel();
      }, Math.max(1, data.proactive_trigger_delay_seconds || 30) * 1000);
    }
  });

  connectSocket();
})();
"""
