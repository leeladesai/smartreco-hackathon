  let MODELS = [
    {id:'MDL-0201', name:'GPT-4o mini', provider:'OpenAI', mod:'LLM', color:'var(--cyan)', s1:'Context', v1:'128K', s2:'Price', v2:'$0.15/1M tok'},
    {id:'MDL-0188', name:'Claude Haiku 4.5', provider:'Anthropic', mod:'LLM', color:'var(--cyan)', s1:'Context', v1:'200K', s2:'Price', v2:'$0.25/1M tok'},
    {id:'MDL-0165', name:'Gemini 1.5 Flash', provider:'Google', mod:'LLM', color:'var(--cyan)', s1:'Context', v1:'1M', s2:'Price', v2:'$0.075/1M tok'},
    {id:'MDL-0142', name:'ElevenLabs Turbo v2.5', provider:'ElevenLabs', mod:'Voice', color:'var(--amber)', s1:'Latency', v1:'~275ms', s2:'Price', v2:'$0.0002/char'},
    {id:'MDL-0176', name:'Deepgram Aura', provider:'Deepgram', mod:'Voice', color:'var(--amber)', s1:'Latency', v1:'~200ms', s2:'Price', v2:'$0.0135/1K char'},
    {id:'MDL-0198', name:'Cartesia Sonic', provider:'Cartesia', mod:'Voice', color:'var(--amber)', s1:'Latency', v1:'~135ms', s2:'Price', v2:'$0.00015/char'},
    {id:'MDL-0119', name:'Flux.1 Pro', provider:'Black Forest Labs', mod:'Image', color:'var(--violet)', s1:'Resolution', v1:'2048px', s2:'Price', v2:'$0.05/image', sync:'indexing'},
    {id:'MDL-0103', name:'Stable Diffusion 3.5', provider:'Stability', mod:'Image', color:'var(--violet)', s1:'Resolution', v1:'1536px', s2:'Price', v2:'$0.035/image'},
    {id:'MDL-0087', name:'Runway Gen-3', provider:'Runway', mod:'Video', color:'var(--rose)', s1:'Max length', v1:'10s', s2:'Price', v2:'$0.10/sec'},
    {id:'MDL-0071', name:'Voyage-3', provider:'Voyage AI', mod:'Embedding', color:'var(--teal)', s1:'Dimensions', v1:'1024', s2:'Price', v2:'$0.02/1M tok'},
  ];
  const API_BASE = '';
  const FALLBACK_MODELS = MODELS.map(model => ({...model}));
  let userSession = false;
  let adminSession = false;
  let selectedModelId = null;
  let compareSelection = []; // model ids the user has explicitly added to compare — never pre-filled
  const COMPARE_STORAGE_KEY = 'trailmind.compareSelection';
  let watchlist = []; // model ids the user has starred — client-side only, no backend list
  const WATCHLIST_STORAGE_KEY = 'trailmind.watchlist';
  try { watchlist = JSON.parse(localStorage.getItem(WATCHLIST_STORAGE_KEY) || '[]'); } catch (error) { watchlist = []; }
  const eventQueue = [];
  const EVENT_BATCH_SIZE = 8;
  const EVENT_FLUSH_MS = 4000;
  let eventFlushTimer = null;

  // Judge demo mode: an admin-controlled, server-side global switch (GET/PUT
  // /api/settings/demo-mode) that shows a live "what just got tracked" overlay in the model
  // drawer/detail page. Off by default and meant only for live pipeline demos — see the
  // conversation this was added from for why it's not a permanent end-user feature.
  let demoModeEnabled = false;
  const demoEventLog = []; // {ref, label, status:'queued'|'sent'} — ref lets flushEvents() find and update the matching entry
  const DEMO_LOG_MAX = 6;

  async function loadDemoMode(){
    try {
      const response = await fetch(`${API_BASE}/api/settings/demo-mode`);
      if (!response.ok) return;
      const data = await response.json();
      demoModeEnabled = !!data.enabled;
      const toggle = document.getElementById('demo-mode-toggle');
      if (toggle) toggle.classList.toggle('active', demoModeEnabled);
      refreshTrackingPanels();
    } catch (error) {
      // Overlay just stays off if settings can't be reached.
    }
  }

  async function toggleDemoMode(){
    const next = !demoModeEnabled;
    try {
      const response = await fetch(`${API_BASE}/api/admin/settings/demo-mode`, {
        method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({enabled:next})
      });
      if (!response.ok) return;
      demoModeEnabled = next;
      const toggle = document.getElementById('demo-mode-toggle');
      if (toggle) toggle.classList.toggle('active', demoModeEnabled);
      refreshTrackingPanels();
    } catch (error) {
      // Leave state unchanged if the request failed.
    }
  }

  function refreshTrackingPanels(){
    renderTrackingPanel('drawer-');
    renderTrackingPanel('detail-');
  }

  function renderTrackingPanel(prefix){
    const wrap = document.getElementById(`${prefix}tracking`);
    if (!wrap) return;
    if (!demoModeEnabled) {
      wrap.style.display = 'none';
      wrap.innerHTML = '';
      return;
    }
    wrap.style.display = '';
    const rows = demoEventLog.slice(-5).reverse().map(entry => `
      <div class="tracking-row">
        <span class="dot" style="background:${entry.status === 'sent' ? 'var(--cyan)' : 'var(--amber)'};"></span>
        <span class="tracking-label">${escapeHtml(entry.label)}</span>
        <span class="tracking-status">${entry.status}</span>
      </div>`).join('');
    // model_view only fires on exit (dwell_seconds needs a real end time) — but a curator
    // watching this overlay live sees the *current* model missing from "Tracked just now"
    // otherwise, which reads as broken tracking rather than a timer in progress. Surface it
    // as its own row, styled/worded like a real tracked entry, not a vague status line.
    const currentModel = dwellModelId ? MODELS.find(m => String(m.id) === String(dwellModelId)) : null;
    const dwellRow = currentModel && String(dwellModelId) === String(selectedModelId)
      ? `<div class="tracking-row muted"><span class="dot hollow"></span><span class="tracking-label">model_view · ${escapeHtml(currentModel.name)}</span><span class="tracking-status">watching</span></div>`
      : '';
    // Newest-first throughout: the in-progress "watching" row is the most recent activity
    // of all, so it belongs above the already-queued/sent history, not below it.
    wrap.innerHTML = `<p class="eyebrow" style="margin:0 0 8px;">Tracked just now</p>`
      + (rows || dwellRow ? dwellRow + rows : '<p class="note">No events tracked yet for this view.</p>');
  }

  function togglePasswordVisibility(button){
    const input = button.closest('.password-field').querySelector('input');
    const showing = input.type === 'text';
    input.type = showing ? 'password' : 'text';
    button.classList.toggle('showing', !showing);
    button.setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
  }

  function escapeHtml(value){
    return String(value ?? '').replace(/[&<>'"]/g, character => ({
      '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;'
    }[character]));
  }

  function setSessionRole(role){
    userSession = role === 'user';
    adminSession = role === 'admin';
    const pill = document.getElementById('persona-pill');
    if (!pill || (!userSession && !adminSession)) return;
    // A role label ("AI engineer") is a fine placeholder while the real profile loads,
    // but the persistent label should be the actual account — otherwise every real
    // user of the app sees an identical, meaningless "AI engineer" pill.
    pill.textContent = adminSession ? 'signed in as: admin' : 'signed in as: …';
    fetch(`${API_BASE}/api/auth/me`)
      .then(response => response.ok ? response.json() : null)
      .then(data => {
        if (data && data.email) {
          pill.textContent = adminSession ? `signed in as: ${data.email} (admin)` : `signed in as: ${data.email}`;
        }
      })
      .catch(() => {});
  }

  const grid = document.getElementById('catalog-grid');
  const adminTable = document.getElementById('admin-model-table');
  const modelForm = document.getElementById('model-form');
  const modelFormStatus = document.getElementById('model-form-status');
  const modelModal = document.getElementById('model-modal');
  const modalityColors = {
    LLM: 'var(--cyan)', Voice: 'var(--amber)', Image: 'var(--violet)',
    Video: 'var(--rose)', Embedding: 'var(--teal)', Multimodal: 'var(--cyan)'
  };

  function modelColor(model){ return modalityColors[model.mod] || 'var(--muted)'; }

  // A display-only identifier derived from provider+name (e.g. "cartesia/sonic") — the
  // Model table has no slug column, so this is computed client-side, purely for the copy
  // action; it is never sent to or validated against the server.
  function modelSlug(model){
    const slugify = value => String(value || '').toLowerCase().trim()
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    const providerSlug = slugify(model.provider);
    const nameSlug = slugify(model.name);
    return providerSlug ? `${providerSlug}/${nameSlug}` : nameSlug;
  }

  const COPY_ICON = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';

  function slugRowHtml(model){
    const slug = modelSlug(model);
    return `<div class="slug-row" onclick="copyModelSlug(event, '${model.id}', '${escapeHtml(slug)}')" title="Copy identifier">
      <code>${escapeHtml(slug)}</code>${COPY_ICON}
    </div>`;
  }

  function copyModelSlug(event, modelId, slug){
    event.stopPropagation();
    const row = event.currentTarget;
    const codeEl = row.querySelector('code');
    const original = codeEl.textContent;
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(slug).catch(() => {});
    }
    trackEvent('model_copy', modelId, {slug});
    row.classList.add('copied');
    codeEl.textContent = 'Copied!';
    setTimeout(() => { row.classList.remove('copied'); codeEl.textContent = original; }, 1200);
  }

  // Client-side only (no backend list) — mirrors the compare-tray pattern. Adding fires a
  // tracked event so a deliberate "star" counts as interest signal for the recommendation
  // engine (see app/services/recommendation.py); removing does not, same rationale as compare.
  function toggleWatchlist(event, modelId){
    event.stopPropagation();
    const index = watchlist.indexOf(modelId);
    const adding = index === -1;
    if (adding) watchlist.push(modelId); else watchlist.splice(index, 1);
    localStorage.setItem(WATCHLIST_STORAGE_KEY, JSON.stringify(watchlist));
    trackEvent('model_watchlist', modelId, {action: adding ? 'add' : 'remove'});
    renderCatalog();
  }

  function watchlistButtonHtml(model){
    const on = watchlist.includes(model.id);
    const label = on ? 'Remove from watchlist' : 'Add to watchlist';
    return `<div class="btn icon ${on ? 'on' : ''}" onclick="toggleWatchlist(event, '${model.id}')" title="${label}" aria-label="${label}">${on ? '★' : '☆'}</div>`;
  }

  // Explicit feedback loop: a thumbs up/down on a dashboard recommendation card is
  // tracked as its own event (recommendation_feedback) — no new endpoint, it rides the
  // same batched /api/events/batch path as everything else. The backend's rerank_
  // candidates node (app/services/agent_graph.py) reads it back on the next pipeline
  // run, so a downvote genuinely stops that model from reappearing rather than just
  // recording an opinion nobody acts on. In-memory only (resets on reload) — good
  // enough to show the click registered without a new API to fetch prior state.
  const recommendationFeedback = {};

  function recordRecommendationFeedback(event, modelId, rating){
    event.stopPropagation();
    recommendationFeedback[modelId] = rating;
    trackEvent('recommendation_feedback', modelId, {rating, recommendation_id: dashboardRecId});
    flushEvents(); // deliberate feedback should land promptly, not wait for the batch timer
    const card = event.currentTarget.closest('.card');
    if (card) {
      card.querySelectorAll('.feedback-btn').forEach(btn => btn.classList.remove('active'));
      event.currentTarget.classList.add('active');
    }
  }

  function feedbackButtonsHtml(model){
    const rating = recommendationFeedback[model.id];
    return `
      <div class="btn icon feedback-btn up ${rating === 'up' ? 'active' : ''}" onclick="recordRecommendationFeedback(event, '${model.id}', 'up')" title="Good recommendation" aria-label="Good recommendation">👍</div>
      <div class="btn icon feedback-btn down ${rating === 'down' ? 'active' : ''}" onclick="recordRecommendationFeedback(event, '${model.id}', 'down')" title="Not relevant" aria-label="Not relevant">👎</div>
    `;
  }

  function fromApiModel(model){
    const isVoice = model.modality === 'Voice';
    return {
      id:String(model.id), name:model.title, provider:model.provider, mod:model.modality,
      color:modelColor({mod:model.modality}), s1:isVoice ? 'Latency' : 'Context',
      v1:isVoice && model.latency_ms ? `~${model.latency_ms}ms` : (model.context_window || 'n/a'),
      s2:'Price', v2:model.price, sync:model.vector_synced ? 'synced' : 'indexing', api:true,
      latency:model.latency_ms || '', context:model.context_window || '',
      tags:(model.use_case_tags || []).join(', '), description:model.description || '', story:model.story || '',
      source:model.source_url || '', whyThis:model.why_this || ''
    };
  }

  async function loadModels(){
    try {
      const response = await fetch(`${API_BASE}/api/models`);
      if (!response.ok) return;
      const models = await response.json();
      if (models.length) MODELS = models.map(fromApiModel);
      if (!selectedModelId && MODELS.length) selectedModelId = MODELS[0].id;
      renderCatalog();
      renderAdminTable();
      if (window.location.pathname === '/compare') renderCompare();
    } catch (error) {
      // The local mock catalog remains available when the API is not running.
    }
  }

  let selectedProviderFilter = null;

  function activeModalityFilters(){
    return Array.from(document.querySelectorAll('#modality-filters .chip.active[data-modality]')).map(c => c.dataset.modality);
  }

  function renderCatalog(){
    if (!grid) return; // catalog grid only exists on the catalog page now
    const activeModalities = activeModalityFilters();
    const latencyChip = document.querySelector('#modality-filters .chip.active[data-latency-max]');
    const maxLatency = latencyChip ? Number(latencyChip.dataset.latencyMax) : null;
    const watchlistOnly = document.querySelector('#modality-filters .chip.active[data-watchlist-only]');
    let visible = activeModalities.length ? MODELS.filter(m => activeModalities.includes(m.mod)) : MODELS;
    if (selectedProviderFilter) visible = visible.filter(m => m.provider === selectedProviderFilter);
    if (maxLatency != null) visible = visible.filter(m => m.latency !== '' && m.latency != null && Number(m.latency) < maxLatency);
    if (watchlistOnly) visible = visible.filter(m => watchlist.includes(m.id));
    grid.innerHTML = visible.map(m => `
      <div class="card" onclick="openModel('${m.id}')">
        <div class="stripe" style="background:${modelColor(m)}"></div>
        <div class="card-body">
          <div class="card-top">
            <span class="modality-tag" style="background:color-mix(in srgb, ${modelColor(m)} 22%, transparent); color:${modelColor(m)};">${escapeHtml(m.mod)}</span>
          </div>
          <h3>${escapeHtml(m.name)}</h3>
          <p class="provider">${escapeHtml(m.provider)}</p>
          ${slugRowHtml(m)}
          <div class="spec-row"><span>${escapeHtml(m.s1)}</span><b>${escapeHtml(m.v1)}</b></div>
          <div class="spec-row"><span>${escapeHtml(m.s2)}</span><b>${escapeHtml(m.v2)}</b></div>
          <div class="card-actions">
            ${watchlistButtonHtml(m)}
            <div class="btn ${compareSelection.includes(m.id) ? 'on' : ''}" onclick="event.stopPropagation(); toggleCompareModel('${m.id}');">${compareSelection.includes(m.id) ? '✓ Comparing' : '+ Compare'}</div>
            <div class="btn primary" onclick="event.stopPropagation(); openModel('${m.id}');">View</div>
          </div>
        </div>
      </div>
    `).join('');
  }

  function renderAdminTable(){
    if (!adminTable) return; // admin table only exists on the admin page now
    adminTable.innerHTML = MODELS.map(m => `
      <tr>
        <td>${escapeHtml(m.name)}</td><td>${escapeHtml(m.provider)}</td><td>${escapeHtml(m.mod)}</td><td>${escapeHtml(m.v2)}</td>
        <td class="${m.sync === 'indexing' ? 'sync-pending' : 'sync-ok'}">${m.sync === 'indexing' ? '⋯ indexing' : '✓ synced'}</td>
        <td class="admin-actions">
          <button type="button" onclick="editModel('${m.id}')">Edit</button>
          <button type="button" class="delete" onclick="deleteModel('${m.id}')">Delete</button>
        </td>
      </tr>
    `).join('');
  }

  // Admin users list: read-only view of who's actually registered (app/main.py
  // GET /api/admin/users) — accounts themselves are created via self-registration
  // (submitAuth) or the seed script, never from this page.
  async function loadUsers(){
    if (!adminSession) return;
    const tbody = document.getElementById('admin-users-table');
    const empty = document.getElementById('admin-users-empty');
    if (!tbody) return; // only present on the admin users page
    try {
      const response = await fetch(`${API_BASE}/api/admin/users`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const users = await response.json();
      empty.style.display = users.length ? 'none' : 'block';
      tbody.innerHTML = users.map(user => {
        const joined = new Date(user.created_at).toLocaleDateString([], {day:'numeric', month:'short', year:'numeric'});
        const roleClass = user.role === 'admin' ? 'sync-ok' : '';
        return `
          <tr>
            <td>${escapeHtml(user.email)}</td>
            <td class="${roleClass}">${escapeHtml(user.role)}</td>
            <td>${joined}</td>
            <td class="admin-actions">
              <button type="button" class="delete" onclick="deleteUser(${user.id}, '${escapeHtml(user.email)}')">Delete</button>
            </td>
          </tr>
        `;
      }).join('');
    } catch (error) {
      tbody.innerHTML = '';
      empty.style.display = 'block';
      empty.textContent = 'Could not load users. Try refreshing.';
    }
  }

  async function deleteUser(id, email){
    if (!window.confirm(`Delete ${email}? This also removes their tracked activity and recommendation history.`)) return;
    try {
      const response = await fetch(`${API_BASE}/api/admin/users/${id}`, {method:'DELETE'});
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        window.alert((body && body.detail) || 'Could not delete this user.');
        return;
      }
      await loadUsers();
    } catch (error) {
      window.alert('Could not delete this user. Check your connection and try again.');
    }
  }

  // Cost/latency rollup (bonus, efficiency polish): aggregated straight from our own
  // DB (Recommendation.mesh_* columns, captured in app/services/mesh.py at generation
  // time) — deliberately not another LangSmith call, so this works even without
  // tracing configured and demonstrates the "efficiency" story with real numbers.
  async function loadCostRollup(){
    if (!adminSession) return;
    const wrap = document.getElementById('cost-rollup');
    if (!wrap) return; // only present on the observability page
    try {
      const response = await fetch(`${API_BASE}/api/admin/observability/costs`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const latency = data.avg_latency_ms != null ? `${Math.round(data.avg_latency_ms)}<small>ms</small>` : '—';
      const totalTokens = data.total_prompt_tokens + data.total_completion_tokens;
      const cost = data.total_cost_usd != null ? `$${data.total_cost_usd.toFixed(4)}` : '<small>unknown</small>';
      wrap.innerHTML = `
        <div class="stat-tile"><span class="k">Mesh calls</span><span class="v">${data.call_count}</span></div>
        <div class="stat-tile"><span class="k">Avg latency</span><span class="v">${latency}</span></div>
        <div class="stat-tile"><span class="k">Total tokens</span><span class="v">${totalTokens.toLocaleString()}</span></div>
        <div class="stat-tile"><span class="k">Total cost</span><span class="v">${cost}</span></div>
      `;
    } catch (error) {
      wrap.innerHTML = '';
    }
  }

  async function loadObservability(){
    if (!adminSession) return;
    const unavailableBox = document.getElementById('observability-unavailable');
    const tableWrap = document.getElementById('observability-table-wrap');
    const tbody = document.getElementById('observability-run-table');
    if (!tbody) return; // only present on the observability page
    try {
      const response = await fetch(`${API_BASE}/api/admin/observability/runs`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data.available) {
        tableWrap.style.display = 'none';
        unavailableBox.style.display = 'block';
        unavailableBox.textContent = data.message || 'LangSmith observability is not available.';
        return;
      }
      unavailableBox.style.display = 'none';
      tableWrap.style.display = '';
      if (!data.runs.length) {
        tbody.innerHTML = '<tr><td colspan="5">No pipeline runs yet — browse the catalog and compare a couple of models to trigger one.</td></tr>';
        return;
      }
      tbody.innerHTML = data.runs.map(run => {
        const ok = run.status !== 'error' && !run.error;
        const started = run.start_time ? new Date(run.start_time).toLocaleString() : '—';
        const latency = run.latency_ms != null ? `${Math.round(run.latency_ms)}ms` : '—';
        return `
          <tr class="clickable" onclick="openTraceDrawer('${run.id}')" title="View step-by-step trace">
            <td class="${ok ? 'sync-ok' : 'sync-error'}">${ok ? '✓ ' + escapeHtml(run.status) : '✕ ' + escapeHtml(run.status)}</td>
            <td>${escapeHtml(run.name)}</td>
            <td>${escapeHtml(started)}</td>
            <td>${latency}</td>
            <td>${run.error ? escapeHtml(run.error) : '—'}</td>
          </tr>
        `;
      }).join('');
    } catch (error) {
      tableWrap.style.display = 'none';
      unavailableBox.style.display = 'block';
      unavailableBox.textContent = 'Could not load observability data — check the server logs.';
    }
  }

  // Brings a single run's step-by-step trace into the admin portal itself (rather than
  // only linking out to LangSmith) — one call to GET .../runs/{id}, which already
  // filters LangGraph's internal plumbing spans down to our own named pipeline steps
  // (see app/services/observability.py:KNOWN_STEP_NAMES). Uses the same drawer/sidecar
  // pattern as the model detail drawer (base.html) rather than a centered modal — more
  // room for the JSON payloads without feeling like a popup interruption.
  function openTraceDrawer(runId){
    const backdrop = document.getElementById('trace-drawer-backdrop');
    const body = document.getElementById('trace-drawer-body');
    const link = document.getElementById('trace-drawer-link');
    if (!backdrop) return;
    document.getElementById('trace-drawer-sub').textContent = '';
    link.style.display = 'none';
    body.innerHTML = '<p class="note">Loading trace…</p>';
    backdrop.classList.add('show');
    document.addEventListener('keydown', traceDrawerEscHandler);
    loadTraceDetail(runId);
  }

  function traceDrawerEscHandler(event){
    if (event.key === 'Escape') closeTraceDrawer();
  }

  function closeTraceDrawer(){
    const backdrop = document.getElementById('trace-drawer-backdrop');
    if (backdrop) backdrop.classList.remove('show');
    document.removeEventListener('keydown', traceDrawerEscHandler);
  }

  async function loadTraceDetail(runId){
    const body = document.getElementById('trace-drawer-body');
    const sub = document.getElementById('trace-drawer-sub');
    const link = document.getElementById('trace-drawer-link');
    try {
      const response = await fetch(`${API_BASE}/api/admin/observability/runs/${encodeURIComponent(runId)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data.available || !data.run) {
        body.innerHTML = `<p class="note">${escapeHtml(data.message || 'Could not load this trace.')}</p>`;
        return;
      }
      const run = data.run;
      const started = run.start_time ? new Date(run.start_time).toLocaleString() : '—';
      const latency = run.latency_ms != null ? `${Math.round(run.latency_ms)}ms` : '—';
      sub.textContent = `${run.name} · ${started} · ${latency}`;
      if (run.url) {
        link.href = run.url;
        link.style.display = '';
      }
      body.innerHTML = run.steps.length
        ? run.steps.map(renderTraceStep).join('')
        : '<p class="note">No named pipeline steps recorded for this run.</p>';
    } catch (error) {
      body.innerHTML = '<p class="note">Could not load this trace — check the server logs.</p>';
    }
  }

  function renderTraceStep(step){
    const ok = step.status !== 'error' && !step.error;
    const latency = step.latency_ms != null ? `${Math.round(step.latency_ms)}ms` : '—';
    const indent = Math.min(step.depth, 3) * 18;
    const io = (label, value) => (value && Object.keys(value).length)
      ? `<details class="trace-io"><summary>${label}</summary><pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre></details>`
      : '';
    return `
      <div class="trace-step" style="margin-left:${indent}px;">
        <div class="trace-step-head">
          <span class="${ok ? 'sync-ok' : 'sync-error'}">${ok ? '✓' : '✕'}</span>
          <span class="trace-step-name">${escapeHtml(step.name)}</span>
          <span class="trace-step-type">${escapeHtml(step.run_type)}</span>
          <span class="trace-step-latency">${latency}</span>
        </div>
        ${step.error ? `<div class="trace-step-error">${escapeHtml(step.error)}</div>` : ''}
        ${io('Input', step.inputs)}
        ${io('Output', step.outputs)}
      </div>
    `;
  }

  function renderDetail(modelId, prefix='detail-'){
    const model = MODELS.find(item => String(item.id) === String(modelId));
    if (!model) return;
    selectedModelId = model.id;
    const color = modelColor(model);
    const modality = document.getElementById(`${prefix}modality`);
    modality.textContent = model.mod;
    modality.style.background = `color-mix(in srgb, ${color} 22%, transparent)`;
    modality.style.color = color;
    document.getElementById(`${prefix}title`).textContent = model.name;
    document.getElementById(`${prefix}provider`).textContent = model.provider;
    const slugEl = document.getElementById(`${prefix}slug`);
    if (slugEl) slugEl.innerHTML = slugRowHtml(model);
    const watchlistEl = document.getElementById(`${prefix}watchlist-btn`);
    if (watchlistEl) watchlistEl.outerHTML = watchlistButtonHtml(model).replace('class="btn icon', `id="${prefix}watchlist-btn" class="btn icon`);
    document.getElementById(`${prefix}description`).textContent = model.description || `${model.name} from ${model.provider}.`;
    document.getElementById(`${prefix}specs`).innerHTML = [
      [model.s1, model.v1], ['Price', model.v2],
      ['Context window', model.context || 'n/a'],
      ['Source', model.source || 'Catalog record']
    ].map(([label, value]) => `<tr><td>${escapeHtml(label)}</td><td>${escapeHtml(value)}</td></tr>`).join('');
    document.getElementById(`${prefix}tags`).innerHTML = (model.tags || '').split(',').map(tag => tag.trim()).filter(Boolean)
      .map(tag => `<span class="use-tag">${escapeHtml(tag)}</span>`).join('');
    document.getElementById(`${prefix}related`).innerHTML = '<p class="note">Finding similar models…</p>';
    loadRelatedModels(model.id, prefix);
    // Accurate regardless of dwell state: the view event only actually ships once you leave
    // this model (dwell_seconds needs a real end time — see finalizeDwell), so claiming it's
    // already "recorded" the instant the drawer opens was misleading.
    document.getElementById(`${prefix}note`).textContent = userSession
      ? 'This view is being tracked and will be recorded once you move on.'
      : 'Sign in to record model views and shape your recommendation.';
    updateCompareButton(`${prefix}compare-btn`, model.id);
  }

  // Content-based, not activity-based: queries the same vector store the recommendation
  // pipeline uses, but keyed on this model's own embedding text rather than the user's
  // behavior — genuinely similar catalog entries, independent of the personalized
  // Dashboard recommendation. See GET /api/models/{id}/related in app/main.py.
  async function loadRelatedModels(modelId, prefix){
    const container = document.getElementById(`${prefix}related`);
    if (!container) return;
    try {
      const response = await fetch(`${API_BASE}/api/models/${modelId}/related`);
      if (!response.ok) throw new Error('related fetch failed');
      const items = await response.json();
      if (String(selectedModelId) !== String(modelId)) return; // user already moved on
      if (!items.length) {
        container.innerHTML = '<p class="note">No close catalog matches yet.</p>';
        return;
      }
      container.innerHTML = items.map(item => `
        <div class="related-item" style="cursor:pointer;" onclick="openModel('${item.id}')">
          <div class="related-item-top"><span>${escapeHtml(item.title)}</span><span class="rlt">${escapeHtml(item.price)}</span></div>
          <p class="related-why">${escapeHtml(item.why_this || '')}</p>
        </div>`).join('');
    } catch (error) {
      if (String(selectedModelId) === String(modelId)) {
        container.innerHTML = '<p class="note">Could not load related models.</p>';
      }
    }
  }

  function updateCompareButton(buttonId, modelId){
    const button = document.getElementById(buttonId);
    if (!button) return;
    const comparing = compareSelection.includes(modelId);
    button.classList.toggle('on', comparing);
    button.textContent = comparing ? '✓ Added to compare' : '+ Add to compare';
  }

  async function searchModels(query){
    try {
      const response = await fetch(`${API_BASE}/api/models?q=${encodeURIComponent(query)}`);
      if (!response.ok) return;
      const results = await response.json();
      MODELS = results.length || query ? results.map(fromApiModel) : FALLBACK_MODELS.map(model => ({...model}));
      renderCatalog();
      renderAdminTable();
    } catch (error) {
      // Keep the current catalog visible if the API is unavailable.
    }
  }

  function openModel(modelId){
    // The drawer markup lives in base.html, so it's present on every screen. Where it exists,
    // open in place; the standalone /models/{id} page itself has no drawer trigger, so go()
    // is only ever reached from a direct URL load or a non-JS fallback.
    const backdrop = document.getElementById('model-drawer-backdrop');
    if (backdrop) {
      openModelDrawer(modelId);
    } else {
      selectedModelId = String(modelId);
      go('detail');
    }
  }

  function drawerEscHandler(event){
    if (event.key === 'Escape') closeModelDrawer();
  }

  function openModelDrawer(modelId){
    const backdrop = document.getElementById('model-drawer-backdrop');
    if (!backdrop) return;
    const alreadyOpen = backdrop.classList.contains('show');
    finalizeDwell(); // close out any dwell from a previously open drawer model
    selectedModelId = String(modelId);
    renderDetail(selectedModelId, 'drawer-');
    startDwell(selectedModelId);
    refreshTrackingPanels();
    backdrop.classList.add('show');
    document.addEventListener('keydown', drawerEscHandler);
    // Switching models while already open replaces the current history entry rather than
    // stacking one per click, so back/forward still lands on "before the drawer" in one step.
    const url = `/models/${selectedModelId}`;
    if (alreadyOpen) history.replaceState({drawerModel: selectedModelId}, '', url);
    else history.pushState({drawerModel: selectedModelId}, '', url);
  }

  function closeModelDrawer(fromPopstate=false){
    const backdrop = document.getElementById('model-drawer-backdrop');
    if (!backdrop || !backdrop.classList.contains('show')) return;
    backdrop.classList.remove('show');
    finalizeDwell();
    flushEvents();
    document.removeEventListener('keydown', drawerEscHandler);
    if (!fromPopstate) history.back();
  }

  window.addEventListener('popstate', () => closeModelDrawer(true));

  let dashboardRecId = null;
  let dashboardPollTimer = null;
  const DASHBOARD_POLL_MS = 15000;

  const STEPPER_STEPS = ['analyze', 'retrieve', 'grade', 'generate', 'deliver'];
  const STEPPER_NOTES = {
    none: 'Waiting on your first tracked actions — browse or search the catalog to start the pipeline.',
    no_candidates: 'Retrieval ran but found no close catalog match for your activity yet — keep browsing to sharpen the signal.',
    retrieval_ready: 'Delivered from retrieval only — generation was skipped because no narrative generator (Mesh) is configured.',
    ready: 'Delivered with a generated narrative — the full pipeline ran end to end.',
  };

  function renderStepper(recommendation){
    const stepper = document.getElementById('dashboard-stepper');
    const note = document.getElementById('stepper-note');
    if (!stepper) return;
    const status = recommendation.status;
    const hasEvents = status !== 'pending' || recommendation.trigger_reason != null;
    let states, noteKey;
    if (status === 'pending' && !hasEvents) {
      states = ['now', 'pending', 'pending', 'pending', 'pending'];
      noteKey = 'none';
    } else if (status === 'pending') {
      states = ['done', 'now', 'pending', 'pending', 'pending'];
      noteKey = 'no_candidates';
    } else if (status === 'ready') {
      states = ['done', 'done', 'done', 'done', 'done'];
      noteKey = 'ready';
    } else {
      states = ['done', 'done', 'done', 'skipped', 'done'];
      noteKey = 'retrieval_ready';
    }
    STEPPER_STEPS.forEach((key, i) => {
      const el = document.getElementById(`step-${key}`);
      if (!el) return;
      el.classList.remove('done', 'now', 'skipped');
      const state = states[i];
      const numEl = el.querySelector('.n');
      if (state === 'done') { el.classList.add('done'); numEl.textContent = '✓'; }
      else if (state === 'now') { el.classList.add('now'); numEl.textContent = el.dataset.n; }
      else if (state === 'skipped') { el.classList.add('skipped'); numEl.textContent = '–'; }
      else { numEl.textContent = el.dataset.n; }
    });
    if (note) note.textContent = STEPPER_NOTES[noteKey] || '';
  }

  function timeAgo(isoString){
    const seconds = Math.max(0, Math.round((Date.now() - new Date(isoString).getTime()) / 1000));
    if (seconds < 60) return 'just now';
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return new Date(isoString).toLocaleDateString([], {day:'numeric', month:'short'});
  }

  // Mesh's narrative is stored as a JSON-encoded {understanding, points} pair (see
  // app/services/narrative.py) so the two are rendered as separate labeled sections rather
  // than one running paragraph. Anything that isn't that shape — old plain-text narratives,
  // placeholder copy, a bare fallback string — falls back to the previous rendering.
  function renderNarrative(text){
    const el = document.getElementById('dashboard-narrative');
    let parsed = null;
    try { parsed = JSON.parse(text); } catch (error) { parsed = null; }
    if (parsed && typeof parsed === 'object' && (parsed.understanding || (parsed.points || []).length)) {
      const points = (parsed.points || []).filter(Boolean);
      el.innerHTML = [
        parsed.understanding ? `<div class="narrative-section">
          <p class="narrative-label">Understanding your activity</p>
          <p class="narrative-para">${escapeHtml(parsed.understanding)}</p>
        </div>` : '',
        points.length ? `<div class="narrative-section">
          <p class="narrative-label">Why these recommendations</p>
          <ul class="narrative-list">${points.map(point => `<li>${escapeHtml(point)}</li>`).join('')}</ul>
        </div>` : ''
      ].join('');
      return;
    }
    const lines = String(text || '').split('\n').map(line => line.replace(/^[-•\s]+/, '').trim()).filter(Boolean);
    if (lines.length > 1) {
      el.innerHTML = `<ul class="narrative-list">${lines.map(line => `<li>${escapeHtml(line)}</li>`).join('')}</ul>`;
    } else {
      el.textContent = lines[0] || text || '';
    }
  }

  function renderDashboardEvidence(evidence){
    const row = document.getElementById('dashboard-evidence');
    const count = document.getElementById('evidence-count');
    if (!row) return;
    count.textContent = evidence.length ? `(${evidence.length} this session)` : '';
    row.innerHTML = evidence.length
      ? evidence.map(item => `
        <div class="evidence-chip">
          <p class="label">${escapeHtml(item.label)}</p>
          <p class="sub">${escapeHtml(item.action)} · ${timeAgo(item.created_at)}</p>
        </div>`).join('')
      : '<div class="evidence-chip"><p class="sub">Nothing tracked yet this session — browse a model to get started.</p></div>';
  }

  async function loadDashboard(){
    if (!userSession) return;
    try {
      const response = await fetch(`${API_BASE}/api/recommendations/me`);
      if (!response.ok) return;
      const recommendation = await response.json();
      dashboardRecId = recommendation.id ?? null;
      renderStepper(recommendation);
      renderDashboardEvidence(recommendation.evidence || []);
      if (recommendation.status === 'pending' || !recommendation.models?.length) {
        document.getElementById('dashboard-tags').innerHTML = '<span class="badge reason">status: learning</span><span class="badge conf">recommendation pending</span>';
        renderNarrative('Your activity is being collected. Once enough signal is available, your grounded recommendation will appear here.');
        document.getElementById('recommendation-grid').innerHTML = '<p class="note">Browse and compare models to give the recommendation engine something real to work with.</p>';
      } else {
        const candidates = recommendation.models.map(fromApiModel);
        const hasNarrative = Boolean(recommendation.narrative);
        document.getElementById('dashboard-tags').innerHTML = hasNarrative
          ? '<span class="badge reason">status: generated</span><span class="badge conf">grounded candidates</span>'
          : '<span class="badge reason">status: retrieval ready</span><span class="badge conf">grounded candidates</span>';
        renderNarrative(recommendation.narrative || 'These candidates were retrieved from the catalog using your recent activity. A generated explanation will appear when Mesh is configured.');
        document.getElementById('recommendation-grid').innerHTML = candidates.map((model, index) => `
          <div class="card" onclick="openModel('${model.id}')">
            <div class="stripe" style="background:${modelColor(model)}"></div>
            <div class="card-body">
              <div class="card-top"><span class="part-id">Match ${index + 1}</span><span class="modality-tag" style="background:color-mix(in srgb, ${modelColor(model)} 22%, transparent); color:${modelColor(model)};">${escapeHtml(model.mod)}</span></div>
              <h3>${escapeHtml(model.name)}</h3><p class="provider">${escapeHtml(model.provider)}</p>
              ${slugRowHtml(model)}
              ${model.whyThis ? `<p class="why-tag">${escapeHtml(model.whyThis)}</p>` : ''}
              <div class="spec-row"><span>${escapeHtml(model.s1)}</span><b>${escapeHtml(model.v1)}</b></div>
              <div class="spec-row"><span>${escapeHtml(model.s2)}</span><b>${escapeHtml(model.v2)}</b></div>
              <div class="card-actions">${watchlistButtonHtml(model)}${feedbackButtonsHtml(model)}</div>
            </div>
          </div>`).join('');
      }
    } catch (error) {
      // Keep the honest pending state when the recommendation API is unavailable.
    }
  }

  // DLV-2: while the dashboard is open, periodically check whether a newer agent run has
  // landed (e.g. from events flushed in another tab) and re-render so it's never stale.
  async function pollDashboard(){
    if (!userSession) return;
    try {
      const response = await fetch(`${API_BASE}/api/recommendations/me`);
      if (!response.ok) return;
      const recommendation = await response.json();
      if ((recommendation.id ?? null) !== dashboardRecId) loadDashboard();
    } catch (error) {
      // Silently skip this tick; the next poll (or a manual re-nav) will retry.
    }
  }

  function startDashboardPolling(){
    stopDashboardPolling();
    dashboardPollTimer = setInterval(pollDashboard, DASHBOARD_POLL_MS);
  }

  function stopDashboardPolling(){
    if (dashboardPollTimer) clearInterval(dashboardPollTimer);
    dashboardPollTimer = null;
  }

  let activityEvents = [];
  let activityPage = 1;
  const ACTIVITY_PAGE_SIZE = 10;

  async function loadActivity(){
    const log = document.getElementById('activity-log');
    if (!userSession) {
      log.innerHTML = '<p class="note">Sign in and browse the catalog to see your persisted activity here.</p>';
      return;
    }
    try {
      const response = await fetch(`${API_BASE}/api/activity/me`);
      if (!response.ok) return;
      const payload = await response.json();
      activityEvents = payload.events;
      renderActivityLog();
      renderActivityPipeline(payload.pipeline);
    } catch (error) {
      log.innerHTML = '<p class="note">Activity is temporarily unavailable.</p>';
    }
  }

  const PIPELINE_TRIGGER_LABELS = {
    event_threshold: 'Enough new activity was tracked',
    activity_retrieval: 'Live preview from your recent activity',
    no_retrieval_candidates: 'No strong catalog match yet',
  };

  function renderActivityPipeline(pipeline){
    const flow = document.getElementById('activity-pipeline');
    const note = document.getElementById('activity-pipeline-note');
    if (!flow) return;
    if (!pipeline || !pipeline.behavior_summary) {
      flow.innerHTML = '<p class="pipeline-summary muted">Nothing generated yet — browse or search the catalog to give the agent something to read.</p>';
      if (note) note.textContent = 'Your persisted event stream will appear here once the recommendation pipeline is connected.';
      return;
    }
    const created = new Date(pipeline.created_at);
    const timestamp = `${created.toLocaleDateString([], {day:'numeric', month:'short', year:'numeric'})}, ${created.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'})}`;
    const triggerLabel = PIPELINE_TRIGGER_LABELS[pipeline.trigger_reason] || pipeline.trigger_reason || 'n/a';
    flow.innerHTML = `
      <p class="pipeline-summary">${escapeHtml(pipeline.behavior_summary)}</p>
      <div class="pipeline-meta">
        <span class="pipeline-meta-item"><span class="k">Why now</span><b>${escapeHtml(triggerLabel)}</b></span>
        <span class="pipeline-meta-item"><span class="k">Generated</span><b>${escapeHtml(timestamp)}</b></span>
      </div>
    `;
    if (note) note.textContent = 'This is the exact behavior snapshot the agent read for your current recommendation — check the Dashboard to see what it produced.';
  }

  function describeFilterChange(metadata){
    const parts = [];
    if (metadata?.modalities?.length) parts.push(metadata.modalities.join(', '));
    if (metadata?.provider) parts.push(`provider: ${metadata.provider}`);
    if (metadata?.latency_max != null) parts.push(`latency < ${metadata.latency_max}ms`);
    return parts.length ? `Filtered by ${parts.join(' · ')}` : 'Filters cleared';
  }

  function renderActivityRow(event){
    const model = MODELS.find(item => String(item.id) === String(event.model_id));
    const detail = event.type === 'catalog_filter' ? describeFilterChange(event.metadata)
      : event.type === 'model_watchlist' ? `${event.metadata?.action === 'remove' ? 'Removed from' : 'Added to'} watchlist: ${model ? model.name : 'model'}`
      : event.type === 'model_copy' ? `Copied identifier: ${event.metadata?.slug || (model ? model.name : '')}`
      : model ? model.name : event.metadata?.query || 'Catalog activity';
    const dwell = event.metadata?.dwell_seconds != null ? ` <span>· dwell ${escapeHtml(event.metadata.dwell_seconds)}s</span>` : '';
    const created = new Date(event.created_at);
    const dateStr = created.toLocaleDateString([], {day:'numeric', month:'short', year:'numeric'});
    const timeStr = created.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
    return `<div class="log-row"><div class="log-time">${escapeHtml(dateStr)}, ${escapeHtml(timeStr)}</div><div class="log-type" style="background:var(--amber-dim); color:var(--amber);">${escapeHtml(event.type)}</div><div class="log-detail">${escapeHtml(detail)}${dwell}</div></div>`;
  }

  function renderActivityLog(){
    const log = document.getElementById('activity-log');
    const note = document.getElementById('activity-note');
    const pagination = document.getElementById('activity-pagination');
    if (!log) return;
    if (!activityEvents.length) {
      log.innerHTML = '<p class="note">No activity recorded yet. Start by searching or opening a model.</p>';
      if (note) note.textContent = '';
      if (pagination) pagination.style.display = 'none';
      return;
    }
    const activeTypes = Array.from(document.querySelectorAll('#activity-type-filters .chip.active[data-event-type]')).map(c => c.dataset.eventType);
    const query = (document.getElementById('activity-search')?.value || '').trim().toLowerCase();
    const filtered = activityEvents.filter(event => {
      if (activeTypes.length && !activeTypes.includes(event.type)) return false;
      if (query) {
        const model = MODELS.find(item => String(item.id) === String(event.model_id));
        const detailText = (event.type === 'catalog_filter' ? describeFilterChange(event.metadata)
          : model ? model.name : event.metadata?.query || '').toLowerCase();
        if (!detailText.includes(query)) return false;
      }
      return true;
    });

    const totalPages = Math.max(1, Math.ceil(filtered.length / ACTIVITY_PAGE_SIZE));
    activityPage = Math.min(Math.max(activityPage, 1), totalPages);
    const start = (activityPage - 1) * ACTIVITY_PAGE_SIZE;
    const pageItems = filtered.slice(start, start + ACTIVITY_PAGE_SIZE);

    log.innerHTML = pageItems.length ? pageItems.map(renderActivityRow).join('')
      : '<p class="note">No activity matches this filter.</p>';

    if (note) {
      if (!filtered.length) {
        note.textContent = '';
      } else {
        const rangeStart = start + 1;
        const rangeEnd = Math.min(start + ACTIVITY_PAGE_SIZE, filtered.length);
        const scope = filtered.length === activityEvents.length
          ? `${activityEvents.length} persisted event${activityEvents.length === 1 ? '' : 's'}`
          : `${filtered.length} of ${activityEvents.length} persisted events`;
        note.textContent = `Showing ${rangeStart}–${rangeEnd} of ${scope} · event ingestion is active.`;
      }
    }

    if (pagination) {
      pagination.style.display = filtered.length > ACTIVITY_PAGE_SIZE ? 'flex' : 'none';
      const label = document.getElementById('activity-page-label');
      const prevBtn = document.getElementById('activity-prev');
      const nextBtn = document.getElementById('activity-next');
      if (label) label.textContent = `Page ${activityPage} of ${totalPages}`;
      if (prevBtn) prevBtn.disabled = activityPage <= 1;
      if (nextBtn) nextBtn.disabled = activityPage >= totalPages;
    }
  }

  function setActivityPage(page){
    activityPage = page;
    renderActivityLog();
  }

  // ---- login-page "live comparison" widget — always computed from the real catalog,
  // never hardcoded numbers, so it can't drift from what's actually in the DB.
  function parseTokenCount(text){
    if (!text) return null;
    const match = String(text).match(/([\d,.]+)\s*([kKmM]?)/);
    if (!match) return null;
    let value = parseFloat(match[1].replace(/,/g, ''));
    if (Number.isNaN(value)) return null;
    const unit = match[2].toLowerCase();
    if (unit === 'k') value *= 1000;
    if (unit === 'm') value *= 1000000;
    return value;
  }

  function parsePriceValue(text){
    if (!text) return null;
    const match = String(text).match(/\$([\d.]+)/);
    return match ? parseFloat(match[1]) : null;
  }

  async function loadLoginPitch(){
    const liveCompare = document.getElementById('live-compare');
    const pillsEl = document.getElementById('category-pills');
    const footnoteEl = document.getElementById('catalog-footnote');
    if (!liveCompare || !pillsEl || !footnoteEl) return;

    try {
      const response = await fetch(`${API_BASE}/api/models`);
      const models = response.ok ? await response.json() : [];
      if (!Array.isArray(models) || !models.length) {
        liveCompare.style.display = 'none';
        footnoteEl.textContent = 'Catalog is empty right now — check back soon.';
        return;
      }

      const countsByModality = {};
      models.forEach(model => { countsByModality[model.modality] = (countsByModality[model.modality] || 0) + 1; });
      const modalityOrder = ['LLM', 'Voice', 'Image', 'Video', 'Embedding'];
      pillsEl.innerHTML = modalityOrder.filter(modality => countsByModality[modality]).map(modality =>
        `<span class="pill"><span class="dot" style="background:${modalityColors[modality] || 'var(--muted)'}"></span>${escapeHtml(modality)} · ${countsByModality[modality]}</span>`
      ).join('');

      const categoryCount = Object.keys(countsByModality).length;
      footnoteEl.textContent = `${models.length} model${models.length === 1 ? '' : 's'} tracked across ${categoryCount} categor${categoryCount === 1 ? 'y' : 'ies'} · live catalog`;

      let pair = null;
      for (const modality of modalityOrder) {
        const group = models.filter(model => model.modality === modality);
        if (group.length >= 2) { pair = group.slice(0, 2); break; }
      }
      if (!pair) { liveCompare.style.display = 'none'; return; }

      const [a, b] = pair;
      document.getElementById('live-compare-pair').innerHTML =
        `<span style="color:var(--cyan)">${escapeHtml(a.title)}</span> vs <span style="color:var(--amber)">${escapeHtml(b.title)}</span>`;

      const rows = [];
      const contextA = parseTokenCount(a.context_window), contextB = parseTokenCount(b.context_window);
      if (contextA != null && contextB != null) {
        rows.push({label: 'Context window', textA: a.context_window, textB: b.context_window, valueA: contextA, valueB: contextB});
      }
      const priceA = parsePriceValue(a.price), priceB = parsePriceValue(b.price);
      if (priceA != null && priceB != null) {
        rows.push({label: 'Price', textA: a.price, textB: b.price, valueA: priceA, valueB: priceB});
      }
      if (a.latency_ms != null && b.latency_ms != null) {
        rows.push({label: 'Avg latency', textA: `${a.latency_ms}ms`, textB: `${b.latency_ms}ms`, valueA: a.latency_ms, valueB: b.latency_ms});
      }

      if (!rows.length) { liveCompare.style.display = 'none'; return; }

      liveCompare.style.display = '';
      document.getElementById('live-compare-rows').innerHTML = rows.map(row => {
        const max = Math.max(row.valueA, row.valueB) || 1;
        const widthA = Math.max(8, Math.round(row.valueA / max * 100));
        const widthB = Math.max(8, Math.round(row.valueB / max * 100));
        return `
          <div class="compare-row">
            <div class="compare-label">${escapeHtml(row.label)}</div>
            <div class="compare-cols">
              <div><span class="compare-value">${escapeHtml(row.textA)}</span><div class="compare-bar"><div class="compare-bar-fill cyan" style="width:${widthA}%"></div></div></div>
              <div><span class="compare-value">${escapeHtml(row.textB)}</span><div class="compare-bar"><div class="compare-bar-fill amber" style="width:${widthB}%"></div></div></div>
            </div>
          </div>`;
      }).join('');
    } catch (error) {
      liveCompare.style.display = 'none';
    }
  }

  function setFormStatus(message, kind=''){
    modelFormStatus.textContent = message;
    modelFormStatus.className = `form-status ${kind}`;
  }

  function scheduleEventFlush(){
    if (eventFlushTimer || !eventQueue.length) return;
    eventFlushTimer = setTimeout(() => {
      eventFlushTimer = null;
      flushEvents();
    }, EVENT_FLUSH_MS);
  }

  function markDemoLogSent(events){
    if (!demoModeEnabled) return;
    let changed = false;
    events.forEach(sentEvent => {
      const entry = demoEventLog.find(item => item.ref === sentEvent);
      if (entry && entry.status !== 'sent') { entry.status = 'sent'; changed = true; }
    });
    if (changed) refreshTrackingPanels();
  }

  async function flushEvents(useBeacon=false){
    if (!eventQueue.length) return;
    const events = eventQueue.splice(0, EVENT_BATCH_SIZE);
    const body = JSON.stringify({events});
    if (useBeacon && navigator.sendBeacon){
      const accepted = navigator.sendBeacon(
        `${API_BASE}/api/events/batch`,
        new Blob([body], {type:'application/json'})
      );
      if (!accepted) eventQueue.unshift(...events);
      else markDemoLogSent(events);
      if (eventQueue.length) scheduleEventFlush();
      return;
    }
    if (!userSession) return;
    try {
      const response = await fetch(`${API_BASE}/api/events/batch`, {
        method:'POST', headers:{'Content-Type':'application/json'}, body,
        keepalive:true
      });
      if (!response.ok) eventQueue.unshift(...events);
      else markDemoLogSent(events);
    } catch (error) {
      eventQueue.unshift(...events);
    }
    if (eventQueue.length) scheduleEventFlush();
  }

  function trackEvent(eventType, modelId=null, metadata={}){
    if (!userSession) return;
    const event = {event_type:eventType, metadata};
    // Number(null) is 0, not NaN — without the explicit null check, every model-less event
    // (search, catalog_filter) would silently ship as model_id: 0 instead of omitting it.
    if (modelId != null) {
      const numericModelId = Number(modelId);
      if (Number.isInteger(numericModelId)) event.model_id = numericModelId;
    }
    eventQueue.push(event);
    if (demoModeEnabled) {
      const model = modelId != null ? MODELS.find(m => String(m.id) === String(modelId)) : null;
      demoEventLog.push({ref:event, label: model ? `${eventType} · ${model.name}` : eventType, status:'queued'});
      if (demoEventLog.length > DEMO_LOG_MAX) demoEventLog.shift();
      refreshTrackingPanels();
    }
    if (eventQueue.length >= EVENT_BATCH_SIZE){
      flushEvents();
    } else {
      scheduleEventFlush();
    }
  }

  function trackCompare(modelId){ trackEvent('model_compare', modelId, {explicit:true}); }

  // Dwell is only meaningful once the user leaves the page — a model_view fired on open
  // can't know how long they stayed. Start a timer on entry, finalize (and fire the event)
  // whenever the user navigates elsewhere, switches to a different model's detail, or the
  // tab is hidden/closed.
  let dwellModelId = null;
  let dwellStartedAt = null;

  function startDwell(modelId){
    dwellModelId = modelId ? String(modelId) : null;
    dwellStartedAt = dwellModelId ? Date.now() : null;
  }

  function finalizeDwell(){
    if (!dwellModelId || !dwellStartedAt) return;
    // The drawer opens/closes far faster than a full page navigation ever did, so a sub-second
    // glance is common and still real evaluation signal — it must still be captured, just with
    // an honest (possibly 0) dwell_seconds rather than being dropped on the floor.
    const seconds = Math.max(0, Math.round((Date.now() - dwellStartedAt) / 1000));
    trackEvent('model_view', dwellModelId, {dwell_seconds: seconds});
    dwellModelId = null;
    dwellStartedAt = null;
  }

  // The tray only ever contains what the user explicitly added here — never seeded with
  // placeholder models. Adding is the only thing that fires the model_compare event; removing
  // does not (removing isn't evaluation signal, it's undoing a click).
  function toggleCompareModel(modelId){
    if (!modelId) return;
    const index = compareSelection.indexOf(modelId);
    if (index !== -1) {
      compareSelection.splice(index, 1);
    } else {
      if (compareSelection.length >= 3) return; // tray holds at most 3
      compareSelection.push(modelId);
      trackCompare(modelId);
    }
    renderCatalog();
    localStorage.setItem(COMPARE_STORAGE_KEY, JSON.stringify(compareSelection));
    if (selectedModelId) {
      updateCompareButton('detail-compare-btn', selectedModelId);
      updateCompareButton('drawer-compare-btn', selectedModelId);
    }
    renderTray();
  }

  function renderTray(){
    const slotsEl = document.getElementById('tray-slots');
    const countEl = document.getElementById('tray-count');
    const compareBtn = document.getElementById('tray-compare-btn');
    const chosen = compareSelection.map(id => MODELS.find(m => m.id === id)).filter(Boolean);
    countEl.textContent = chosen.length;
    let html = chosen.map(m => `
      <div class="tray-slot">${escapeHtml(m.name)}
        <span onclick="event.stopPropagation(); toggleCompareModel('${m.id}');" style="cursor:pointer;">×</span>
      </div>`).join('');
    if (chosen.length < 3) html += `<div class="tray-slot empty">+ add one more</div>`;
    slotsEl.innerHTML = html;
    const ready = chosen.length >= 2;
    compareBtn.classList.toggle('primary', ready);
    compareBtn.style.opacity = ready ? '1' : '.5';
    compareBtn.style.cursor = ready ? 'pointer' : 'default';
    updateTrayVisibility();
  }

  function restoreCompareFromUrl(){
    const ids = new URLSearchParams(window.location.search).get('ids');
    const stored = localStorage.getItem(COMPARE_STORAGE_KEY);
    let source = ids || stored;
    if (!ids && stored) {
      try { source = JSON.parse(stored); } catch (error) { source = ''; }
    }
    if (!source) return;
    compareSelection = source.toString().split(',').map(id => id.trim()).filter((id, index, all) =>
      id && index < 3 && all.indexOf(id) === index
    );
    localStorage.setItem(COMPARE_STORAGE_KEY, JSON.stringify(compareSelection));
    renderTray();
    renderCompare();
  }

  function renderCompare(){
    const chosen = compareSelection.map(id => MODELS.find(m => m.id === id)).filter(Boolean);
    document.getElementById('compare-title').textContent = chosen.length
      ? chosen.map(m => m.name).join(' vs ')
      : 'Nothing to compare yet';
    if (chosen.length < 2) {
      document.getElementById('compare-table').innerHTML =
        '<tr><td class="note" style="border:none;">Add 2–3 models from the catalog first.</td></tr>';
      return;
    }
    const rows = [
      ['Provider', m => m.provider],
      ['Modality', m => m.mod],
      // Always pulled from the model's own latency/context fields rather than the previous
      // s1/v1 pair — that borrowed its row *label* from chosen[0] but its row *value* from
      // every column, so comparing e.g. a Voice model against an LLM mislabeled the LLM's
      // context-window value as "Latency".
      ['Latency', m => m.latency ? `~${m.latency}ms` : '—'],
      ['Context window', m => m.context || '—'],
      ['Price', m => m.v2],
      ['Use cases', m => m.tags || '—'],
      ['Description', m => m.description || '—']
    ];
    const head = `<tr><th>Spec</th>${chosen.map(m => `<th>${escapeHtml(m.name)}</th>`).join('')}</tr>`;
    const body = rows.map(([label, get]) =>
      `<tr><td class="metric">${escapeHtml(label)}</td>${chosen.map(m => `<td>${escapeHtml(get(m))}</td>`).join('')}</tr>`
    ).join('');
    document.getElementById('compare-table').innerHTML = head + body;
  }

  function updateTrayVisibility(){
    const activePage = document.querySelector('.page.active');
    const pageId = activePage ? activePage.id.replace('page-', '') : '';
    document.getElementById('tray').classList.toggle('show', TRAY_PAGES.includes(pageId) && compareSelection.length > 0);
  }

  // Bulk catalog upload: admin-only, CSV/JSON -> POST /api/admin/models/bulk-upload
  // (app/services/catalog_import.py). No mock-mode fallback here, unlike saveModel —
  // there is nothing meaningful to fake for a multi-row import against the in-memory
  // demo catalog, so it's real-admin-only.
  function openBulkUploadModal(){
    document.getElementById('bulk-upload-form').reset();
    document.getElementById('bulk-upload-status').textContent = '';
    document.getElementById('bulk-upload-results').innerHTML = '';
    document.getElementById('bulk-upload-modal').classList.add('show');
  }

  function closeBulkUploadModal(event){
    const modal = document.getElementById('bulk-upload-modal');
    if (event && event.target !== modal) return;
    modal.classList.remove('show');
  }

  async function submitBulkUpload(event){
    event.preventDefault();
    const statusEl = document.getElementById('bulk-upload-status');
    const resultsEl = document.getElementById('bulk-upload-results');
    resultsEl.innerHTML = '';
    if (!adminSession) {
      statusEl.textContent = 'Sign in as admin to upload a catalog file.';
      return;
    }
    const fileInput = document.getElementById('bulk-upload-file');
    const file = fileInput.files[0];
    if (!file) {
      statusEl.textContent = 'Choose a CSV or JSON file first.';
      return;
    }
    statusEl.textContent = 'Uploading and processing…';
    const formData = new FormData();
    formData.append('file', file);
    try {
      const response = await fetch(`${API_BASE}/api/admin/models/bulk-upload`, {method:'POST', body:formData});
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        statusEl.textContent = (data && data.detail) || 'Upload failed. Check the file and try again.';
        return;
      }
      statusEl.textContent = `${data.inserted} added, ${data.skipped_duplicate} duplicate${data.skipped_duplicate === 1 ? '' : 's'} skipped, ${data.invalid} invalid.`;
      const problems = data.rows.filter(row => row.status !== 'inserted');
      if (problems.length) {
        resultsEl.innerHTML = '<ul class="bulk-upload-issues">' + problems.map(row => {
          const label = `Row ${row.row}${row.title ? ` (${escapeHtml(row.title)})` : ''}`;
          const detail = row.status === 'skipped_duplicate' ? 'already in catalog' : escapeHtml(row.errors.join('; '));
          return `<li><strong>${label}:</strong> ${detail}</li>`;
        }).join('') + '</ul>';
      }
      if (data.inserted > 0) await loadModels();
    } catch (error) {
      statusEl.textContent = 'Upload failed. Check your connection and try again.';
    }
  }

  function openModelModal(){
    resetModelForm();
    modelModal.classList.add('show');
    requestAnimationFrame(() => document.getElementById('model-title').focus());
  }

  function closeModelModal(event){
    if (event && event.target !== modelModal) return;
    modelModal.classList.remove('show');
    resetModelForm();
  }

  function resetModelForm(){
    modelForm.reset();
    document.getElementById('model-edit-id').value = '';
    document.getElementById('model-form-title').textContent = 'Add model';
    setFormStatus('');
  }

  function editModel(id){
    const model = MODELS.find(item => item.id === id);
    if (!model) return;
    document.getElementById('model-edit-id').value = model.id;
    document.getElementById('model-title').value = model.name;
    document.getElementById('model-provider').value = model.provider;
    document.getElementById('model-modality').value = model.mod;
    document.getElementById('model-price').value = model.v2;
    document.getElementById('model-latency').value = model.latency || '';
    document.getElementById('model-context').value = model.context || '';
    document.getElementById('model-tags').value = model.tags || '';
    document.getElementById('model-description').value = model.description || '';
    document.getElementById('model-story').value = model.story || '';
    document.getElementById('model-source').value = model.source || '';
    document.getElementById('model-form-title').textContent = `Edit ${model.name}`;
    setFormStatus(`Editing ${model.id}. Save to re-index this model.`);
    modelModal.classList.add('show');
    requestAnimationFrame(() => document.getElementById('model-title').focus());
  }

  async function deleteModel(id){
    const model = MODELS.find(item => item.id === id);
    if (!model || !window.confirm(`Delete ${model.name} from the catalog?`)) return;
    if (adminSession && model.api) {
      const response = await fetch(`${API_BASE}/api/admin/models/${model.id}`, {method:'DELETE'});
      if (!response.ok) {
        setFormStatus('The model could not be deleted. Try again.', 'error');
        return;
      }
      await loadModels();
      return;
    }
    MODELS.splice(MODELS.indexOf(model), 1);
    renderAdminTable();
    renderCatalog();
    closeModelModal();
    setFormStatus(`${model.name} deleted from the mock catalog.`, 'success');
  }

  async function saveModel(event){
    event.preventDefault();
    const editId = document.getElementById('model-edit-id').value;
    const model = editId ? MODELS.find(item => item.id === editId) : null;
    const name = document.getElementById('model-title').value.trim();
    const provider = document.getElementById('model-provider').value.trim();
    const mod = document.getElementById('model-modality').value;
    const price = document.getElementById('model-price').value.trim();
    if (!name || !provider || !price) {
      setFormStatus('Title, provider, and price are required.', 'error');
      return;
    }
    const payload = {
      title:name, provider, modality:mod, price,
      latency_ms:Number(document.getElementById('model-latency').value) || null,
      context_window:document.getElementById('model-context').value.trim() || null,
      use_case_tags:document.getElementById('model-tags').value.split(',').map(tag => tag.trim()).filter(Boolean),
      description:document.getElementById('model-description').value.trim() || `${name} from ${provider}.`,
      story:document.getElementById('model-story').value.trim() || null,
      source_url:document.getElementById('model-source').value.trim() || null
    };
    if (adminSession && (editId || !model)) {
      const response = await fetch(`${API_BASE}/api/admin/models${editId ? `/${editId}` : ''}`, {
        method:editId ? 'PUT' : 'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)
      });
      if (!response.ok) {
        setFormStatus('The model could not be saved. Check the fields and try again.', 'error');
        return;
      }
      await loadModels();
      modelModal.classList.remove('show');
      resetModelForm();
      return;
    }
    const next = model || {id:`MDL-${String(200 + MODELS.length + 1).padStart(4, '0')}`};
    Object.assign(next, {
      name, provider, mod, color:modelColor({mod}), s1: mod === 'Voice' ? 'Latency' : 'Context',
      v1: document.getElementById('model-latency').value.trim() || 'n/a', s2:'Price', v2:price,
      latency:document.getElementById('model-latency').value.trim(),
      context:document.getElementById('model-context').value.trim(), tags:document.getElementById('model-tags').value.trim(),
      description:document.getElementById('model-description').value.trim(),
      story:document.getElementById('model-story').value.trim(),
      source:document.getElementById('model-source').value.trim(), sync:'indexing'
    });
    if (!model) MODELS.push(next);
    renderAdminTable();
    renderCatalog();
    setFormStatus(`${name} saved. Vector index is updating…`, 'success');
    setTimeout(() => {
      next.sync = 'synced';
      renderAdminTable();
      if (modelModal.classList.contains('show')) setFormStatus(`${name} saved and marked as synced.`, 'success');
    }, 900);
    modelModal.classList.remove('show');
    resetModelForm();
  }

  document.addEventListener('keydown', event => {
    if (modelModal && event.key === 'Escape' && modelModal.classList.contains('show')) closeModelModal();
  });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      finalizeDwell();
      flushEvents(true);
    }
  });
  window.addEventListener('pagehide', () => {
    finalizeDwell();
    flushEvents(true);
  });

  loadModels();
  loadLoginPitch();

  renderCatalog();
  renderAdminTable();

  // Real app-flow navigation: each screen only exposes the destinations a user could actually
  // reach from it. Auth state (none / AI engineer / admin) drives which nav links exist at all —
  // there is no single tab bar exposing every screen as an equal peer.
  const BUILDER_PAGES = ['catalog', 'detail', 'compare', 'dashboard', 'activity'];
  const TRAY_PAGES = ['catalog', 'detail', 'compare'];

  function navStateFor(page){
    if (page === 'admin' || page === 'observability' || page === 'admin-users') return 'admin';
    if (BUILDER_PAGES.includes(page)) return 'engineer';
    return 'none'; // auth, admin-auth — logged-out screens get no app chrome
  }

  function routeFor(page){
    if (page === 'auth') return '/login';
    if (page === 'admin-auth') return '/admin/login';
    if (page === 'catalog') return '/catalog';
    if (page === 'detail') return selectedModelId ? `/models/${selectedModelId}` : '/catalog';
    if (page === 'compare') return `/compare?ids=${encodeURIComponent(compareSelection.join(','))}`;
    if (page === 'dashboard') return '/dashboard';
    if (page === 'activity') return '/activity';
    if (page === 'admin') return '/admin';
    if (page === 'observability') return '/admin/observability';
    if (page === 'admin-users') return '/admin/users';
    return '/catalog';
  }

  // Each route now serves only its own screen's markup (per-template split), so cross-page
  // navigation is a real browser navigation, not a client-side DOM toggle — the browser's
  // native history/back-forward handles what a manual popstate listener used to. `pagehide`
  // (registered further down) already finalizes dwell tracking and flushes queued events on
  // any real navigation, so go() doesn't need to do that itself.
  function go(page){
    window.location.href = routeFor(page);
  }

  // Runs once per real page load (called from the inline script at the bottom of base.html)
  // to wire up the single screen that was actually server-rendered — this replaces the part
  // of the old go() that used to also handle in-DOM page switching.
  async function initPage(page){
    await loadModels(); // ensures MODELS is populated before any page that reads it below —
                         // needed now that a direct load of e.g. /models/42 can't rely on the
                         // catalog page having already warmed MODELS earlier in the session
    loadDemoMode();
    const state = navStateFor(page);
    document.getElementById('app-nav').dataset.state = state;
    document.querySelectorAll('.nav-link').forEach(l => l.classList.toggle('active', l.dataset.page === page));
    updateTrayVisibility();
    if (page === 'detail') {
      const modelId = window.INITIAL_MODEL_ID != null ? String(window.INITIAL_MODEL_ID) : selectedModelId;
      selectedModelId = modelId;
      renderDetail(modelId);
      startDwell(modelId);
      refreshTrackingPanels();
    }
    if (page === 'compare') restoreCompareFromUrl();
    if (page === 'dashboard') { loadDashboard(); startDashboardPolling(); }
    if (page === 'activity') loadActivity();
    if (page === 'observability') { loadObservability(); loadCostRollup(); }
    if (page === 'admin-users') loadUsers();
    window.scrollTo({top:0, behavior:'instant'});
  }

  async function logout(){
    const wasAdmin = document.getElementById('app-nav').dataset.state === 'admin';
    try { await fetch(`${API_BASE}/api/auth/logout`, {method:'POST'}); } catch (error) {
      // Navigate away regardless — worst case the cookie outlives this tab, not a hang.
    }
    go(wasAdmin ? 'admin-auth' : 'auth');
  }

  renderTray();

  // Filter chips only ever mutated the DOM/grid, never the tracked event stream — which model
  // relaxes/tightens a filter to is real evaluation signal, same as a search query is. Debounced
  // so a quick run of clicks (e.g. toggling three modality chips in a row) logs one event, not one
  // per click.
  let filterTrackTimer;
  function trackFilterChange(){
    clearTimeout(filterTrackTimer);
    filterTrackTimer = setTimeout(() => {
      const latencyChip = document.querySelector('#modality-filters .chip.active[data-latency-max]');
      trackEvent('catalog_filter', null, {
        modalities: activeModalityFilters(),
        provider: selectedProviderFilter,
        latency_max: latencyChip ? Number(latencyChip.dataset.latencyMax) : null
      });
    }, 400);
  }

  document.querySelectorAll('#modality-filters .chip[data-modality], #modality-filters .chip[data-latency-max]').forEach(c => c.addEventListener('click', () => {
    c.classList.toggle('active');
    renderCatalog();
    trackFilterChange();
  }));

  // Watchlist-only is a personal view toggle, not a search/evaluation filter — the underlying
  // add/remove actions are already tracked individually via toggleWatchlist, so this doesn't
  // also fire a catalog_filter event.
  document.querySelectorAll('#modality-filters .chip[data-watchlist-only]').forEach(c => c.addEventListener('click', () => {
    c.classList.toggle('active');
    renderCatalog();
  }));

  function renderProviderDropdown(){
    const panel = document.getElementById('provider-dropdown-panel');
    if (!panel) return;
    const providers = Array.from(new Set(MODELS.map(m => m.provider))).sort();
    panel.innerHTML = [`<div class="dropdown-item ${!selectedProviderFilter ? 'active' : ''}" onclick="selectProviderFilter(null)">All providers</div>`]
      .concat(providers.map(p => `<div class="dropdown-item ${selectedProviderFilter === p ? 'active' : ''}" onclick="selectProviderFilter('${escapeHtml(p)}')">${escapeHtml(p)}</div>`))
      .join('');
  }

  function toggleProviderDropdown(event){
    event.stopPropagation();
    const panel = document.getElementById('provider-dropdown-panel');
    if (!panel) return;
    renderProviderDropdown();
    panel.classList.toggle('show');
  }

  function selectProviderFilter(provider){
    selectedProviderFilter = provider;
    document.querySelector('#provider-filter .chip').classList.toggle('active', Boolean(provider));
    document.getElementById('provider-filter-label').textContent = provider ? `: ${provider}` : '';
    document.getElementById('provider-dropdown-panel').classList.remove('show');
    renderCatalog();
    trackFilterChange();
  }

  document.addEventListener('click', event => {
    const panel = document.getElementById('provider-dropdown-panel');
    if (panel && panel.classList.contains('show') && !event.target.closest('#provider-filter')) {
      panel.classList.remove('show');
    }
  });

  document.querySelectorAll('#activity-type-filters .chip[data-event-type]').forEach(c => c.addEventListener('click', () => {
    c.classList.toggle('active');
    activityPage = 1; // a changed filter invalidates whatever page you were on
    renderActivityLog();
  }));
  const activitySearchInput = document.getElementById('activity-search'); // activity page only
  if (activitySearchInput) {
    let activitySearchTimer;
    activitySearchInput.addEventListener('input', () => {
      clearTimeout(activitySearchTimer);
      activitySearchTimer = setTimeout(() => {
        activityPage = 1;
        renderActivityLog();
      }, 150);
    });
  }
  const searchInput = document.querySelector('.searchbar input'); // catalog page only
  if (searchInput) {
    let searchTimer;
    searchInput.addEventListener('input', event => {
      const query = event.target.value.trim();
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        searchModels(query);
        trackEvent('search', null, {query});
      }, 220);
    });
  }

  // ---- auth (AI engineer) ----
  const AUTH_BUTTON_LABEL = {login: 'Sign in →', register: 'Create account →'};
  const AUTH_SWITCH_HTML = {
    login: 'New here? <span onclick="setAuthMode(\'register\')">Create an account</span>',
    register: 'Already have an account? <span onclick="setAuthMode(\'login\')">Sign in</span>',
  };

  function setAuthMode(mode){
    const registering = mode === 'register';
    document.querySelectorAll('#auth-toggle .opt').forEach(x => x.classList.toggle('active', x.dataset.mode === mode));
    document.querySelectorAll('.auth-copy').forEach(el => el.classList.toggle('active', el.dataset.copy === mode));
    document.getElementById('auth-form').classList.toggle('register-mode', registering);
    document.getElementById('auth-submit-btn').textContent = AUTH_BUTTON_LABEL[mode];
    document.getElementById('auth-switch').innerHTML = AUTH_SWITCH_HTML[mode];
    document.getElementById('auth-error').classList.remove('show');
    document.querySelector('#auth-form .only-register input').tabIndex = registering ? 0 : -1;
    document.getElementById('auth-forgot').tabIndex = registering ? -1 : 0;
    // Fresh credentials per mode: never let the pre-filled demo login email leak into
    // a real signup, and never leave a typed password sitting in the DOM after a switch.
    const fields = document.querySelectorAll('#auth-form input');
    fields[1].value = '';
    if (fields[2]) fields[2].value = '';
    if (registering) fields[0].value = '';
  }

  function authErrorMessage(body, fallback){
    const detail = body && body.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail[0] && typeof detail[0].msg === 'string') return detail[0].msg;
    return fallback;
  }

  const authForgot = document.getElementById('auth-forgot'); // login page only
  if (authForgot) {
    authForgot.addEventListener('click', () => {
      const note = document.getElementById('auth-error');
      note.textContent = "Password reset isn't available in this build yet — contact your curator to have your account reset.";
      note.classList.add('show');
    });
  }

  document.querySelectorAll('#auth-toggle .opt').forEach(o => o.addEventListener('click', () => setAuthMode(o.dataset.mode)));

  async function submitAuth(event){
    if (event) event.preventDefault();
    const errorEl = document.getElementById('auth-error');
    errorEl.classList.remove('show');
    const fields = document.querySelectorAll('#auth-form input');
    const registering = document.getElementById('auth-form').classList.contains('register-mode');
    const email = fields[0].value.trim();
    const password = fields[1].value;

    if (registering) {
      // Client-side checks catch the common mistakes (typo'd confirm, too-short
      // password) before a round-trip — the backend (app/schemas.py AuthCredentials,
      // min_length=8) still enforces the real rule, this is purely a faster no.
      if (password.length < 8) {
        errorEl.textContent = 'Password must be at least 8 characters.';
        errorEl.classList.add('show');
        return;
      }
      const confirmPassword = fields[2] ? fields[2].value : password;
      if (password !== confirmPassword) {
        errorEl.textContent = "Passwords don't match.";
        errorEl.classList.add('show');
        return;
      }
    }

    const credentials = {email, password};
    try {
      let response = await fetch(`${API_BASE}/api/auth/${registering ? 'register' : 'login'}`, {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(credentials)
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        const fallback = registering
          ? 'Could not create your account. Try again.'
          : "Wrong email or password. Try again, or check you're on the right tab above.";
        errorEl.textContent = authErrorMessage(body, fallback);
        errorEl.classList.add('show');
        return;
      }
      if (registering) {
        response = await fetch(`${API_BASE}/api/auth/login`, {
          method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(credentials)
        });
        if (!response.ok) {
          setAuthMode('login');
          errorEl.textContent = 'Account created — sign in below to continue.';
          errorEl.classList.add('show');
          return;
        }
      }
    } catch (error) {
      errorEl.textContent = 'Something went wrong. Check your connection and try again.';
      errorEl.classList.add('show');
      return;
    }
    // The session cookie is now set — go('catalog') is a real navigation, so the next page
    // load picks up the authenticated session_role server-side rather than relying on any
    // client-side state set here (which would be discarded on unload anyway).
    go('catalog');
  }

  // ---- auth (admin) ----
  async function submitAdminAuth(event){
    if (event) event.preventDefault();
    document.getElementById('admin-auth-error').classList.remove('show');
    const fields = document.querySelectorAll('#admin-auth-form input');
    try {
      const response = await fetch(`${API_BASE}/api/admin/login`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({email:fields[0].value, password:fields[1].value})
      });
      if (!response.ok) throw new Error('login failed');
    } catch (error) {
      document.getElementById('admin-auth-error').classList.add('show');
      return;
    }
    go('admin');
  }
