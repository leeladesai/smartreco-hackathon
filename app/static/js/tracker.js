/*!
 * TrailMind tracker SDK (TRK-1..7, docs/design/09-Platform-Pivot-Decision.md).
 *
 * Embed on a tenant's own page:
 *   <script src="https://<this-host>/static/js/tracker.js" data-widget-key="wk_live_..."></script>
 *
 * The host page calls window.TrailMind.track(eventType, catalogItemId, metadata) to record
 * behavioral signal (item views, searches, an explicit "compare" action, etc.) — this
 * file has no opinion about the host page's own catalog UI, it only batches and ships
 * events to POST /api/track/events. Anonymous by design: the only identity is a
 * client-generated visitor_id (TRK-7 — no PII is ever collected, regardless of what's
 * present on the host page).
 */
(function () {
  'use strict';

  var CURRENT_SCRIPT = document.currentScript;
  var WIDGET_KEY = CURRENT_SCRIPT ? CURRENT_SCRIPT.getAttribute('data-widget-key') : null;
  if (!WIDGET_KEY) {
    console.error('[TrailMind] tracker.js loaded without a data-widget-key attribute — not tracking.');
    return;
  }

  // API_BASE defaults to this script's own origin, so the snippet works unmodified
  // regardless of which TrailMind-hosted domain a tenant embeds it from.
  var API_BASE = CURRENT_SCRIPT.src ? new URL(CURRENT_SCRIPT.src).origin : '';
  var TRACK_URL = API_BASE + '/api/track/events';

  var VISITOR_STORAGE_KEY = 'trailmind.visitor_id';
  var EVENT_BATCH_SIZE = 8;
  var EVENT_FLUSH_MS = 4000;

  function generateVisitorId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return 'v_' + window.crypto.randomUUID();
    }
    // Fallback for browsers without crypto.randomUUID — not cryptographically
    // strong, but this is an anonymous, low-stakes identifier, not a security token.
    return 'v_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2);
  }

  // In-memory fallback if localStorage is blocked (private browsing, cookies
  // disabled, etc.) — tracking still works for the current page load, it just won't
  // persist the same visitor_id across page views.
  var memoryVisitorId = null;

  function getVisitorId() {
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
  var eventQueue = [];
  var flushTimer = null;

  function scheduleFlush() {
    if (flushTimer || !eventQueue.length) return;
    flushTimer = setTimeout(function () {
      flushTimer = null;
      flushEvents();
    }, EVENT_FLUSH_MS);
  }

  function flushEvents(useBeacon) {
    if (!eventQueue.length) return;
    var events = eventQueue.splice(0, EVENT_BATCH_SIZE);
    var body = JSON.stringify({
      widget_key: WIDGET_KEY,
      visitor_id: visitorId,
      events: events
    });
    if (useBeacon && navigator.sendBeacon) {
      var accepted = navigator.sendBeacon(TRACK_URL, new Blob([body], { type: 'application/json' }));
      if (!accepted) eventQueue.unshift.apply(eventQueue, events);
      if (eventQueue.length) scheduleFlush();
      return;
    }
    fetch(TRACK_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body,
      keepalive: true
    }).then(function (response) {
      if (!response.ok) eventQueue.unshift.apply(eventQueue, events);
    }).catch(function () {
      eventQueue.unshift.apply(eventQueue, events);
    }).finally(function () {
      if (eventQueue.length) scheduleFlush();
    });
  }

  function track(eventType, catalogItemId, metadata) {
    var event = { event_type: eventType, metadata: metadata || {} };
    // Number(null) is 0, not NaN — the explicit null/undefined check avoids ever
    // shipping catalog_item_id: 0 for an item-less event (search, catalog_filter, etc.).
    if (catalogItemId !== null && catalogItemId !== undefined) {
      var numericCatalogItemId = Number(catalogItemId);
      if (Number.isInteger(numericCatalogItemId)) event.catalog_item_id = numericCatalogItemId;
    }
    eventQueue.push(event);
    if (eventQueue.length >= EVENT_BATCH_SIZE) {
      flushEvents();
    } else {
      scheduleFlush();
    }
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') flushEvents(true);
  });
  window.addEventListener('pagehide', function () {
    flushEvents(true);
  });

  window.TrailMind = window.TrailMind || {};
  window.TrailMind.track = track;
  window.TrailMind.visitorId = visitorId;
})();
