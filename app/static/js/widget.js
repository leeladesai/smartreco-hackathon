/*!
 * TrailMind chat-bot widget (DLV-1..4/DLV-6, docs/design/09-Platform-Pivot-Decision.md).
 *
 * Embed on a tenant's own page, alongside (or instead of) tracker.js — reads the same
 * tenant key/visitor id:
 *   <script src="https://<this-host>/static/js/widget.js" data-tenant-key="tk_live_..."></script>
 *
 * Shape: a launcher bubble that opens proactively (DLV-1) when a real-time push
 * arrives over GET /api/widget/stream (DLV-2, SSE) — the push itself only carries
 * ids/distances, so on receipt this re-fetches the fully-shaped payload from
 * GET /api/recommendations/latest (title/price/why_this per model, already built for
 * that endpoint) rather than duplicating that shaping here. A visitor can then ask a
 * follow-up question (DLV-4, POST /api/widget/ask) or expand "why am I seeing this"
 * (DLV-6, GET /api/widget/activity). Rendered inside a Shadow DOM root so the widget's
 * own styles can never leak into, or be broken by, the host page's CSS.
 *
 * TEN-8: the backend itself refuses every /api/widget/* call with 403 while
 * `tenant.status != 'active'` — this file doesn't duplicate that check, it just
 * treats a 403 on stream-open as "stay dark," per DLV-1's stay-dormant requirement.
 */
(function () {
  'use strict';

  var CURRENT_SCRIPT = document.currentScript;
  var TENANT_KEY = CURRENT_SCRIPT ? CURRENT_SCRIPT.getAttribute('data-tenant-key') : null;
  if (!TENANT_KEY) {
    console.error('[TrailMind] widget.js loaded without a data-tenant-key attribute — not rendering.');
    return;
  }

  var API_BASE = CURRENT_SCRIPT.src ? new URL(CURRENT_SCRIPT.src).origin : '';
  var VISITOR_STORAGE_KEY = 'trailmind.visitor_id';

  function generateVisitorId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return 'v_' + window.crypto.randomUUID();
    }
    return 'v_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2);
  }

  var memoryVisitorId = null;

  function getVisitorId() {
    // Shares tracker.js's own storage key so the same visitor_id is used whichever
    // script initializes it first, regardless of load order — the widget's push
    // stream and the tracker's ingested events must resolve to one identity.
    if (window.TrailMind && window.TrailMind.visitorId) {
      return window.TrailMind.visitorId;
    }
    try {
      var stored = window.localStorage.getItem(VISITOR_STORAGE_KEY);
      if (stored) return stored;
      var fresh = generateVisitorId();
      window.localStorage.setItem(VISITOR_STORAGE_KEY, fresh);
      return fresh;
    } catch (error) {
      if (!memoryVisitorId) memoryVisitorId = generateVisitorId();
      return memoryVisitorId;
    }
  }

  var visitorId = getVisitorId();
  var qs = function (params) {
    return Object.keys(params)
      .map(function (key) {
        return encodeURIComponent(key) + '=' + encodeURIComponent(params[key]);
      })
      .join('&');
  };

  // ---- Shadow-DOM shell -----------------------------------------------------

  var host = document.createElement('div');
  host.id = 'trailmind-widget-host';
  var shadow = host.attachShadow({ mode: 'open' });

  var style = document.createElement('style');
  style.textContent =
    ':host{all:initial}' +
    '.tm-launcher{position:fixed;right:20px;bottom:20px;width:56px;height:56px;' +
    'border-radius:50%;background:#1f2937;color:#fff;display:flex;align-items:center;' +
    'justify-content:center;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.25);' +
    'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;' +
    'font-size:24px;z-index:2147483000;transition:transform .15s ease}' +
    '.tm-launcher:hover{transform:scale(1.06)}' +
    '.tm-badge{position:absolute;top:-2px;right:-2px;width:14px;height:14px;' +
    'border-radius:50%;background:#ef4444;border:2px solid #fff;display:none}' +
    '.tm-badge.tm-show{display:block}' +
    '.tm-panel{position:fixed;right:20px;bottom:88px;width:340px;max-height:70vh;' +
    'background:#fff;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.2);' +
    'display:none;flex-direction:column;overflow:hidden;' +
    'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;' +
    'font-size:14px;color:#111827;z-index:2147483000}' +
    '.tm-panel.tm-open{display:flex}' +
    '.tm-header{padding:12px 14px;background:#1f2937;color:#fff;display:flex;' +
    'justify-content:space-between;align-items:center;font-weight:600}' +
    '.tm-close{cursor:pointer;opacity:.8;font-size:16px;line-height:1}' +
    '.tm-close:hover{opacity:1}' +
    '.tm-body{padding:12px 14px;overflow-y:auto;flex:1}' +
    '.tm-empty{color:#6b7280;font-size:13px}' +
    '.tm-understanding{margin:0 0 8px;color:#374151}' +
    '.tm-points{margin:0 0 12px;padding-left:18px}' +
    '.tm-points li{margin-bottom:4px}' +
    '.tm-card{border:1px solid #e5e7eb;border-radius:8px;padding:8px 10px;margin-bottom:8px}' +
    '.tm-card-title{font-weight:600;margin-bottom:2px}' +
    '.tm-card-meta{color:#6b7280;font-size:12px}' +
    '.tm-why{color:#6b7280;font-size:12px;margin-top:14px;cursor:pointer;text-decoration:underline}' +
    '.tm-activity li{margin-bottom:4px;font-size:12px;color:#374151}' +
    '.tm-thread{margin-top:12px;border-top:1px solid #e5e7eb;padding-top:10px}' +
    '.tm-q{font-weight:600;margin-top:8px}' +
    '.tm-a{color:#374151;margin-top:2px}' +
    '.tm-ask{display:flex;border-top:1px solid #e5e7eb;padding:8px}' +
    '.tm-ask input{flex:1;border:1px solid #d1d5db;border-radius:6px;padding:6px 8px;' +
    'font-size:13px;font-family:inherit}' +
    '.tm-ask button{margin-left:6px;border:none;background:#1f2937;color:#fff;' +
    'border-radius:6px;padding:6px 12px;cursor:pointer;font-size:13px}' +
    '.tm-ask button:disabled{opacity:.5;cursor:default}';
  shadow.appendChild(style);

  var launcher = document.createElement('div');
  launcher.className = 'tm-launcher';
  launcher.setAttribute('role', 'button');
  launcher.setAttribute('aria-label', 'Open recommendations');
  launcher.textContent = '💬';
  var badge = document.createElement('div');
  badge.className = 'tm-badge';
  launcher.appendChild(badge);
  shadow.appendChild(launcher);

  var panel = document.createElement('div');
  panel.className = 'tm-panel';
  panel.innerHTML =
    '<div class="tm-header"><span>Recommendations</span><span class="tm-close" aria-label="Close">✕</span></div>' +
    '<div class="tm-body"><div class="tm-empty">Nothing yet — browse around and we’ll have a suggestion for you.</div></div>' +
    '<div class="tm-ask"><input type="text" placeholder="Ask a question…" maxlength="500" />' +
    '<button type="button">Ask</button></div>';
  shadow.appendChild(panel);

  var bodyEl = panel.querySelector('.tm-body');
  var askInput = panel.querySelector('.tm-ask input');
  var askButton = panel.querySelector('.tm-ask button');
  var closeButton = panel.querySelector('.tm-close');

  var latestModelsById = {};
  var opened = false;

  function openPanel() {
    opened = true;
    panel.classList.add('tm-open');
    badge.classList.remove('tm-show');
  }

  function closePanel() {
    opened = false;
    panel.classList.remove('tm-open');
  }

  launcher.addEventListener('click', function () {
    if (panel.classList.contains('tm-open')) {
      closePanel();
    } else {
      openPanel();
    }
  });
  closeButton.addEventListener('click', closePanel);

  function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
  }

  function renderRecommendation(data) {
    latestModelsById = {};
    (data.models || []).forEach(function (model) {
      latestModelsById[model.id] = model;
    });

    if (!data.narrative && (!data.models || !data.models.length)) {
      bodyEl.innerHTML =
        '<div class="tm-empty">Nothing yet — browse around and we’ll have a suggestion for you.</div>';
      return;
    }

    var html = '';
    var understanding = null;
    var points = [];
    if (data.narrative) {
      try {
        var parsed = JSON.parse(data.narrative);
        understanding = parsed.understanding;
        points = parsed.points || [];
      } catch (error) {
        understanding = data.narrative;
      }
    }
    if (understanding) {
      html += '<p class="tm-understanding">' + escapeHtml(understanding) + '</p>';
    }
    if (points.length) {
      html += '<ul class="tm-points">' + points.map(function (point) {
        return '<li>' + escapeHtml(point) + '</li>';
      }).join('') + '</ul>';
    }
    (data.models || []).forEach(function (model) {
      html += '<div class="tm-card"><div class="tm-card-title">' + escapeHtml(model.title) + '</div>' +
        '<div class="tm-card-meta">' + escapeHtml(model.provider) + ' · ' + escapeHtml(model.price) + '</div>';
      if (model.why_this) {
        html += '<div class="tm-card-meta">' + escapeHtml(model.why_this) + '</div>';
      }
      html += '</div>';
    });
    html += '<div class="tm-why" data-action="activity">Why am I seeing this?</div>';
    bodyEl.innerHTML = html;

    var whyEl = bodyEl.querySelector('[data-action="activity"]');
    if (whyEl) whyEl.addEventListener('click', showActivity);
  }

  function fetchLatest() {
    return fetch(
      API_BASE + '/api/recommendations/latest?' + qs({ tenant_key: TENANT_KEY, visitor_id: visitorId })
    )
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .catch(function () {
        return null;
      });
  }

  function showActivity() {
    fetch(API_BASE + '/api/widget/activity?' + qs({ tenant_key: TENANT_KEY, visitor_id: visitorId }))
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (!data) return;
        var html = '<div class="tm-activity"><strong>Recent activity</strong><ul>';
        (data.events || []).slice(-8).forEach(function (event) {
          html += '<li>' + escapeHtml(event.type) + '</li>';
        });
        html += '</ul></div>';
        bodyEl.insertAdjacentHTML('beforeend', html);
      })
      .catch(function () {});
  }

  function appendQA(question, answer) {
    var thread = bodyEl.querySelector('.tm-thread');
    if (!thread) {
      thread = document.createElement('div');
      thread.className = 'tm-thread';
      bodyEl.appendChild(thread);
    }
    thread.insertAdjacentHTML(
      'beforeend',
      '<div class="tm-q">' + escapeHtml(question) + '</div><div class="tm-a">' + escapeHtml(answer) + '</div>'
    );
    bodyEl.scrollTop = bodyEl.scrollHeight;
  }

  function askQuestion() {
    var question = askInput.value.trim();
    if (!question) return;
    askInput.value = '';
    askButton.disabled = true;
    fetch(API_BASE + '/api/widget/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tenant_key: TENANT_KEY, visitor_id: visitorId, question: question })
    })
      .then(function (response) {
        return response.ok ? response.json() : { answer: 'Something went wrong — please try again.' };
      })
      .then(function (data) {
        appendQA(question, data.answer);
        openPanel();
      })
      .catch(function () {
        appendQA(question, 'Something went wrong — please try again.');
      })
      .finally(function () {
        askButton.disabled = false;
      });
  }

  askButton.addEventListener('click', askQuestion);
  askInput.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') askQuestion();
  });

  // ---- Real-time push (DLV-2) -----------------------------------------------

  function connectStream() {
    if (typeof window.EventSource !== 'function') return;
    var url = API_BASE + '/api/widget/stream?' + qs({ tenant_key: TENANT_KEY, visitor_id: visitorId });
    var source = new EventSource(url);
    source.addEventListener('recommendation', function () {
      fetchLatest().then(function (data) {
        if (!data) return;
        renderRecommendation(data);
        if (!opened) badge.classList.add('tm-show');
      });
    });
    source.onerror = function () {
      // A 403 (tenant not yet 'active', TEN-8) or any other failure closes the
      // connection natively — EventSource retries on a plain network error by
      // itself; there is nothing extra to reconnect here, and no error should ever
      // surface to the visitor.
    };
  }

  function init() {
    document.body.appendChild(host);
    fetchLatest().then(function (data) {
      if (data && (data.narrative || (data.models && data.models.length))) {
        renderRecommendation(data);
      }
    });
    connectStream();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.TrailMindWidget = { visitorId: visitorId };
})();
