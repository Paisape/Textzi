"""The embeddable widget script itself, as a plain Python string constant -- deliberately not a
built asset (no Vite/webpack step) so there's nothing to build/deploy separately from the API
container, and deliberately framework-free (no Vue/React) since it has to run inside an arbitrary
third-party page and stay small. Phase 1 scope only: bubble + panel, visitor_id persistence, the
/visit and /message calls, and a live WebSocket connection for the agent's replies. Typing-
indicator sending and the offline/proactive-trigger UI states are Phase 1-adjacent stubs wired to
already-built backend fields (is_online/offline_message/proactive_trigger_*) but kept minimal here
-- polish is expected to iterate once this is live, not a reason to hold back the working core."""

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

  var state = { open: false, online: true, greeting: 'Hi! How can we help?', color: '#F1600D', offlineMessage: '' };
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

  sendBtn.addEventListener('click', send);
  input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { send(); } });
  bubble.addEventListener('click', function () {
    state.open = !state.open;
    panel.style.display = state.open ? 'flex' : 'none';
  });

  post('/v1/public/webchat/' + widgetKey + '/visit', {
    visitor_id: visitorId, current_url: window.location.href, referrer: document.referrer || null,
  }).then(function (data) {
    if (!data || data.detail) { return; }
    state.online = !!data.is_online;
    state.greeting = data.greeting_message || state.greeting;
    state.color = data.bubble_color || state.color;
    state.offlineMessage = data.offline_message || '';
    header.textContent = state.online ? state.greeting : 'We are offline';
    if (!state.online && state.offlineMessage) {
      appendMessage(state.offlineMessage, 'agent');
    }
    applyColor();
  });

  connectSocket();
})();
"""
