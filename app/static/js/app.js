  // Admin/platform console only. The AI-engineer self-service catalog/dashboard/activity
  // surface (browsing, event tracking, watchlist, compare tray, model drawer, login/
  // register) was removed as part of the platform pivot to a multi-tenant, embeddable
  // widget product (docs/design/09-Platform-Pivot-Decision.md) — it returns with the
  // tracker SDK phase, built on anonymous visitor identity rather than a cookie-session
  // `user` role. Everything below serves only the admin console (overview/catalog/users/
  // observability) and the admin login screen.

  let MODELS = [
    {id:'MDL-0201', name:'GPT-4o mini', provider:'OpenAI', mod:'LLM', s1:'Context', v1:'128K', s2:'Price', v2:'$0.15/1M tok'},
    {id:'MDL-0188', name:'Claude Haiku 4.5', provider:'Anthropic', mod:'LLM', s1:'Context', v1:'200K', s2:'Price', v2:'$0.25/1M tok'},
    {id:'MDL-0165', name:'Gemini 1.5 Flash', provider:'Google', mod:'LLM', s1:'Context', v1:'1M', s2:'Price', v2:'$0.075/1M tok'},
    {id:'MDL-0142', name:'ElevenLabs Turbo v2.5', provider:'ElevenLabs', mod:'Voice', s1:'Latency', v1:'~275ms', s2:'Price', v2:'$0.0002/char'},
    {id:'MDL-0176', name:'Deepgram Aura', provider:'Deepgram', mod:'Voice', s1:'Latency', v1:'~200ms', s2:'Price', v2:'$0.0135/1K char'},
    {id:'MDL-0198', name:'Cartesia Sonic', provider:'Cartesia', mod:'Voice', s1:'Latency', v1:'~135ms', s2:'Price', v2:'$0.00015/char'},
    {id:'MDL-0119', name:'Flux.1 Pro', provider:'Black Forest Labs', mod:'Image', s1:'Resolution', v1:'2048px', s2:'Price', v2:'$0.05/image', sync:'indexing'},
    {id:'MDL-0103', name:'Stable Diffusion 3.5', provider:'Stability', mod:'Image', s1:'Resolution', v1:'1536px', s2:'Price', v2:'$0.035/image'},
    {id:'MDL-0087', name:'Runway Gen-3', provider:'Runway', mod:'Video', s1:'Max length', v1:'10s', s2:'Price', v2:'$0.10/sec'},
    {id:'MDL-0071', name:'Voyage-3', provider:'Voyage AI', mod:'Embedding', s1:'Dimensions', v1:'1024', s2:'Price', v2:'$0.02/1M tok'},
  ];
  const API_BASE = '';
  let adminSession = false;

  const adminTable = document.getElementById('admin-model-table');
  const modelForm = document.getElementById('model-form');
  const modelFormStatus = document.getElementById('model-form-status');
  const modelModal = document.getElementById('model-modal');

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

  // A page's server-rendered shell only proves the session was valid at that one
  // request — if it then expires (TTL, or the cookie gets cleared) while the tab
  // stays open, every fetch a loader makes afterward starts 401ing. This centralizes
  // that one check: call it right after awaiting a fetch, before touching response.json().
  function redirectIfSignedOut(response){
    if (response.status !== 401) return false;
    go('admin-auth');
    return true;
  }

  function setSessionRole(role){
    adminSession = role === 'admin';
    const pill = document.getElementById('persona-pill');
    if (!pill || !adminSession) return;
    pill.textContent = 'signed in as: …';
    fetch(`${API_BASE}/api/admin/me`)
      .then(response => {
        if (redirectIfSignedOut(response)) return null;
        return response.ok ? response.json() : null;
      })
      .then(data => {
        if (data && data.email) pill.textContent = `signed in as: ${data.email} (admin)`;
      })
      .catch(() => {});
  }

  function fromApiModel(model){
    const isVoice = model.modality === 'Voice';
    return {
      id:String(model.id), name:model.title, provider:model.provider, mod:model.modality,
      s1:isVoice ? 'Latency' : 'Context',
      v1:isVoice && model.latency_ms ? `~${model.latency_ms}ms` : (model.context_window || 'n/a'),
      s2:'Price', v2:model.price, sync:model.vector_synced ? 'synced' : 'indexing',
      latency:model.latency_ms || '', context:model.context_window || '',
      tags:(model.use_case_tags || []).join(', '), description:model.description || '', story:model.story || '',
      source:model.source_url || ''
    };
  }

  async function loadModels(){
    if (!adminSession) return;
    try {
      const response = await fetch(`${API_BASE}/api/models`);
      if (redirectIfSignedOut(response)) return;
      if (!response.ok) return;
      const models = await response.json();
      if (models.length) MODELS = models.map(fromApiModel);
      renderAdminTable();
    } catch (error) {
      // The local mock catalog remains available when the API is not running.
    }
  }

  // GET /api/models stays unpaginated on purpose — this table alone is paginated by
  // slicing the already-loaded array in the browser.
  const ADMIN_MODELS_PAGE_SIZE = 20;
  let adminModelsPage = 1;

  function renderAdminTable(){
    if (!adminTable) return; // admin table only exists on the admin page
    const pagination = document.getElementById('admin-models-pagination');
    const prevBtn = document.getElementById('admin-models-prev-btn');
    const nextBtn = document.getElementById('admin-models-next-btn');
    const pageLabel = document.getElementById('admin-models-page-label');
    const totalPages = Math.max(1, Math.ceil(MODELS.length / ADMIN_MODELS_PAGE_SIZE));
    adminModelsPage = Math.min(Math.max(adminModelsPage, 1), totalPages);
    const start = (adminModelsPage - 1) * ADMIN_MODELS_PAGE_SIZE;
    const page = MODELS.slice(start, start + ADMIN_MODELS_PAGE_SIZE);
    adminTable.innerHTML = page.map(m => `
      <tr>
        <td>${escapeHtml(m.name)}</td><td>${escapeHtml(m.provider)}</td><td>${escapeHtml(m.mod)}</td><td>${escapeHtml(m.v2)}</td>
        <td class="${m.sync === 'indexing' ? 'sync-pending' : 'sync-ok'}">${m.sync === 'indexing' ? '⋯ indexing' : '✓ synced'}</td>
        <td class="admin-actions">
          <button type="button" onclick="editModel('${m.id}')">Edit</button>
          <button type="button" class="delete" onclick="deleteModel('${m.id}')">Delete</button>
        </td>
      </tr>
    `).join('');
    if (pagination) pagination.style.display = MODELS.length > ADMIN_MODELS_PAGE_SIZE ? 'flex' : 'none';
    if (prevBtn) prevBtn.disabled = adminModelsPage === 1;
    if (nextBtn) nextBtn.disabled = adminModelsPage === totalPages;
    if (pageLabel) pageLabel.textContent = `Page ${adminModelsPage} of ${totalPages}`;
  }

  function adminModelsPrevPage(){
    if (adminModelsPage <= 1) return;
    adminModelsPage -= 1;
    renderAdminTable();
  }

  function adminModelsNextPage(){
    const totalPages = Math.max(1, Math.ceil(MODELS.length / ADMIN_MODELS_PAGE_SIZE));
    if (adminModelsPage >= totalPages) return;
    adminModelsPage += 1;
    renderAdminTable();
  }

  // Admin Overview: platform-usage metrics (app/services/admin_overview.py) —
  // distinct from Observability, which is AI-pipeline/LangSmith technical health.
  async function loadOverview(){
    if (!adminSession) return;
    const totalsRow = document.getElementById('overview-totals');
    const eventBars = document.getElementById('overview-event-bars');
    const feedbackRow = document.getElementById('overview-feedback');
    if (!totalsRow) return; // only present on the overview page
    try {
      const response = await fetch(`${API_BASE}/api/admin/overview`);
      if (redirectIfSignedOut(response)) return;
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const t = data.totals;
      totalsRow.innerHTML = `
        <div class="stat-tile"><span class="k">Total users</span><span class="v">${t.users}</span></div>
        <div class="stat-tile"><span class="k">Catalog size</span><span class="v">${t.models}</span></div>
        <div class="stat-tile"><span class="k">Behavioral events</span><span class="v">${t.events}</span></div>
        <div class="stat-tile"><span class="k">Recommendations generated</span><span class="v">${t.recommendations}</span></div>
      `;
      const counts = data.event_type_counts || {};
      const maxCount = Math.max(1, ...Object.values(counts));
      const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
      eventBars.innerHTML = entries.length ? entries.map(([type, count]) => `
        <div class="event-bar-row" title="${escapeHtml(type)}: ${count}">
          <span class="event-bar-label">${escapeHtml(type)}</span>
          <div class="compare-bar"><div class="compare-bar-fill cyan" style="width:${Math.round(count / maxCount * 100)}%"></div></div>
          <span class="event-bar-count">${count}</span>
        </div>
      `).join('') : '<p class="note">No events tracked yet.</p>';
      const up = data.feedback?.up || 0;
      const down = data.feedback?.down || 0;
      if (feedbackRow) {
        feedbackRow.innerHTML = (up + down) > 0
          ? `<div class="stat-tile"><span class="k">👍 Positive feedback</span><span class="v">${up}</span></div>
             <div class="stat-tile"><span class="k">👎 Negative feedback</span><span class="v">${down}</span></div>`
          : '<p class="note">No recommendation feedback recorded yet.</p>';
      }
    } catch (error) {
      totalsRow.innerHTML = '<p class="note">Could not load overview metrics — check the server logs.</p>';
    }
  }

  const OVERVIEW_ACTIVITY_PAGE_SIZE = 20;
  let overviewActivityOffset = 0;
  let overviewActivityHasMore = false;

  async function loadOverviewActivity(){
    if (!adminSession) return;
    const tbody = document.getElementById('overview-activity-table');
    const prevBtn = document.getElementById('overview-activity-prev-btn');
    const nextBtn = document.getElementById('overview-activity-next-btn');
    const pageLabel = document.getElementById('overview-activity-page-label');
    const pagination = document.getElementById('overview-activity-pagination');
    if (!tbody) return; // only present on the overview page
    tbody.innerHTML = '<tr><td colspan="4">Loading recent activity…</td></tr>';
    try {
      const response = await fetch(`${API_BASE}/api/admin/overview/activity?limit=${OVERVIEW_ACTIVITY_PAGE_SIZE}&offset=${overviewActivityOffset}`);
      if (redirectIfSignedOut(response)) return;
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      overviewActivityHasMore = Boolean(data.has_more);
      if (pagination) pagination.style.display = (overviewActivityOffset > 0 || overviewActivityHasMore) ? 'flex' : 'none';
      if (prevBtn) prevBtn.disabled = overviewActivityOffset === 0;
      if (nextBtn) nextBtn.disabled = !overviewActivityHasMore;
      if (pageLabel) pageLabel.textContent = `Page ${Math.floor(overviewActivityOffset / OVERVIEW_ACTIVITY_PAGE_SIZE) + 1}`;
      if (!data.events.length) {
        tbody.innerHTML = `<tr><td colspan="4">${overviewActivityOffset > 0 ? 'No more activity.' : 'No activity tracked yet.'}</td></tr>`;
        return;
      }
      tbody.innerHTML = data.events.map(event => {
        const model = event.model_id != null ? MODELS.find(item => String(item.id) === String(event.model_id)) : null;
        const detail = event.event_type === 'model_watchlist'
          ? `${event.metadata?.action === 'remove' ? 'Removed from' : 'Added to'} watchlist: ${model ? model.name : 'model'}`
          : event.event_type === 'model_copy' ? `Copied identifier: ${event.metadata?.slug || (model ? model.name : '')}`
          : model ? model.name : event.metadata?.query || '—';
        const when = new Date(event.created_at).toLocaleString();
        return `
          <tr>
            <td>${escapeHtml(event.visitor_id)}</td>
            <td class="log-type" style="background:var(--amber-dim); color:var(--amber); display:inline-block;">${escapeHtml(event.event_type)}</td>
            <td>${escapeHtml(detail)}</td>
            <td>${escapeHtml(when)}</td>
          </tr>
        `;
      }).join('');
    } catch (error) {
      tbody.innerHTML = '<tr><td colspan="4">Could not load activity — check the server logs.</td></tr>';
    }
  }

  function refreshOverview(){
    loadOverview();
    overviewActivityOffset = 0;
    loadOverviewActivity();
  }

  function overviewActivityPrevPage(){
    if (overviewActivityOffset === 0) return;
    overviewActivityOffset = Math.max(0, overviewActivityOffset - OVERVIEW_ACTIVITY_PAGE_SIZE);
    loadOverviewActivity();
  }

  function overviewActivityNextPage(){
    if (!overviewActivityHasMore) return;
    overviewActivityOffset += OVERVIEW_ACTIVITY_PAGE_SIZE;
    loadOverviewActivity();
  }

  // Admin users list: read-only view of who's actually registered (app/main.py
  // GET /api/admin/users). Newest-joined first, paginated 20/page.
  const USERS_PAGE_SIZE = 20;
  let usersOffset = 0;
  let usersHasMore = false;

  async function loadUsers(){
    if (!adminSession) return;
    const tbody = document.getElementById('admin-users-table');
    const empty = document.getElementById('admin-users-empty');
    const prevBtn = document.getElementById('users-prev-btn');
    const nextBtn = document.getElementById('users-next-btn');
    const pageLabel = document.getElementById('users-page-label');
    const pagination = document.getElementById('users-pagination');
    if (!tbody) return; // only present on the admin users page
    try {
      const response = await fetch(`${API_BASE}/api/admin/users?limit=${USERS_PAGE_SIZE}&offset=${usersOffset}`);
      if (redirectIfSignedOut(response)) return;
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const users = data.users;
      usersHasMore = Boolean(data.has_more);
      if (pagination) pagination.style.display = (usersOffset > 0 || usersHasMore) ? 'flex' : 'none';
      if (prevBtn) prevBtn.disabled = usersOffset === 0;
      if (nextBtn) nextBtn.disabled = !usersHasMore;
      if (pageLabel) pageLabel.textContent = `Page ${Math.floor(usersOffset / USERS_PAGE_SIZE) + 1}`;
      empty.style.display = users.length ? 'none' : 'block';
      empty.textContent = users.length ? '' : (usersOffset > 0 ? 'No more users.' : 'No users yet.');
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

  function refreshUsers(){
    usersOffset = 0;
    loadUsers();
  }

  function usersPrevPage(){
    if (usersOffset === 0) return;
    usersOffset = Math.max(0, usersOffset - USERS_PAGE_SIZE);
    loadUsers();
  }

  function usersNextPage(){
    if (!usersHasMore) return;
    usersOffset += USERS_PAGE_SIZE;
    loadUsers();
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
      if (redirectIfSignedOut(response)) return;
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

  const OBSERVABILITY_PAGE_SIZE = 25;
  let observabilityOffset = 0;
  let observabilityHasMore = false;
  let observabilityVisitorFilter = '';

  // Every agent_pipeline run is tagged visitor:<id> at trace time
  // (prepare_retrieval_recommendation) — filtering by a typed-in visitor id is a real
  // server-side LangSmith query, not a client-side filter over an already-fetched run
  // list. There's no "list of visitors" endpoint to populate a dropdown from (visitors
  // are anonymous tracker-assigned ids, not registered accounts), so this is a plain
  // text field rather than a select.
  function observabilityFilterByVisitor(){
    const input = document.getElementById('observability-visitor-filter');
    observabilityVisitorFilter = input ? input.value.trim() : '';
    observabilityOffset = 0;
    loadObservability();
  }

  async function loadObservability(){
    if (!adminSession) return;
    const unavailableBox = document.getElementById('observability-unavailable');
    const tableWrap = document.getElementById('observability-table-wrap');
    const tbody = document.getElementById('observability-run-table');
    const prevBtn = document.getElementById('observability-prev-btn');
    const nextBtn = document.getElementById('observability-next-btn');
    const pageLabel = document.getElementById('observability-page-label');
    const pagination = document.getElementById('observability-pagination');
    if (!tbody) return; // only present on the observability page
    tbody.innerHTML = '<tr><td colspan="7">Loading recent runs…</td></tr>';
    unavailableBox.style.display = 'none';
    tableWrap.style.display = '';
    try {
      const visitorParam = observabilityVisitorFilter ? `&visitor_id=${encodeURIComponent(observabilityVisitorFilter)}` : '';
      const response = await fetch(`${API_BASE}/api/admin/observability/runs?limit=${OBSERVABILITY_PAGE_SIZE}&offset=${observabilityOffset}${visitorParam}`);
      if (redirectIfSignedOut(response)) return;
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data.available) {
        tableWrap.style.display = 'none';
        unavailableBox.style.display = 'block';
        unavailableBox.textContent = data.message || 'LangSmith observability is not available.';
        if (pagination) pagination.style.display = 'none';
        return;
      }
      unavailableBox.style.display = 'none';
      tableWrap.style.display = '';
      observabilityHasMore = Boolean(data.has_more);
      if (pagination) pagination.style.display = (observabilityOffset > 0 || observabilityHasMore) ? 'flex' : 'none';
      if (prevBtn) prevBtn.disabled = observabilityOffset === 0;
      if (nextBtn) nextBtn.disabled = !observabilityHasMore;
      if (pageLabel) {
        const page = Math.floor(observabilityOffset / OBSERVABILITY_PAGE_SIZE) + 1;
        pageLabel.textContent = `Page ${page}`;
      }
      if (!data.runs.length) {
        const emptyMessage = observabilityOffset > 0
          ? 'No more runs.'
          : observabilityVisitorFilter
            ? 'No pipeline runs yet for this visitor.'
            : 'No pipeline runs yet.';
        tbody.innerHTML = `<tr><td colspan="7">${emptyMessage}</td></tr>`;
        return;
      }
      tbody.innerHTML = data.runs.map(run => {
        const ok = run.status !== 'error' && !run.error;
        const started = run.start_time ? new Date(run.start_time).toLocaleString() : '—';
        const pipelineTime = run.pipeline_latency_ms != null ? `${Math.round(run.pipeline_latency_ms)}ms` : '—';
        const wallTime = run.latency_ms != null ? `${Math.round(run.latency_ms)}ms` : '—';
        const visitorLabel = run.visitor_id != null ? escapeHtml(run.visitor_id) : '—';
        return `
          <tr class="clickable" onclick="openTraceDrawer('${run.id}')" title="View step-by-step trace">
            <td class="${ok ? 'sync-ok' : 'sync-error'}">${ok ? '✓ ' + escapeHtml(run.status) : '✕ ' + escapeHtml(run.status)}</td>
            <td>${escapeHtml(run.name)}</td>
            <td>${escapeHtml(started)}</td>
            <td>${visitorLabel}</td>
            <td>${pipelineTime}</td>
            <td>${wallTime}</td>
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

  function refreshObservability(){
    observabilityOffset = 0;
    loadObservability();
    loadCostRollup();
  }

  function observabilityPrevPage(){
    if (observabilityOffset === 0) return;
    observabilityOffset = Math.max(0, observabilityOffset - OBSERVABILITY_PAGE_SIZE);
    loadObservability();
  }

  function observabilityNextPage(){
    if (!observabilityHasMore) return;
    observabilityOffset += OBSERVABILITY_PAGE_SIZE;
    loadObservability();
  }

  // Brings a single run's step-by-step trace into the admin portal itself (rather than
  // only linking out to LangSmith) — one call to GET .../runs/{id}, which already
  // filters LangGraph's internal plumbing spans down to our own named pipeline steps
  // (see app/services/observability.py:KNOWN_STEP_NAMES).
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
      const wallTime = run.latency_ms != null ? `${Math.round(run.latency_ms)}ms wall` : null;
      const pipelineTime = run.pipeline_latency_ms != null ? `${Math.round(run.pipeline_latency_ms)}ms pipeline` : null;
      const latencySummary = [pipelineTime, wallTime].filter(Boolean).join(' · ') || '—';
      sub.textContent = `${run.name} · ${started} · ${latencySummary}`;
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

  function setFormStatus(message, kind=''){
    modelFormStatus.textContent = message;
    modelFormStatus.className = `form-status ${kind}`;
  }

  // Bulk catalog upload: admin-only, CSV/JSON -> POST /api/admin/models/bulk-upload
  // (app/services/catalog_import.py).
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
    const response = await fetch(`${API_BASE}/api/admin/models/${model.id}`, {method:'DELETE'});
    if (!response.ok) {
      setFormStatus('The model could not be deleted. Try again.', 'error');
      return;
    }
    await loadModels();
  }

  async function saveModel(event){
    event.preventDefault();
    const editId = document.getElementById('model-edit-id').value;
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
  }

  document.addEventListener('keydown', event => {
    if (modelModal && event.key === 'Escape' && modelModal.classList.contains('show')) closeModelModal();
  });

  // Real app-flow navigation: each screen only exposes the destinations reachable from it.
  function navStateFor(page){
    if (page === 'admin-overview' || page === 'admin-models' || page === 'observability' || page === 'admin-users') return 'admin';
    return 'none'; // admin-auth — logged-out screen gets no app chrome
  }

  function routeFor(page){
    if (page === 'admin-auth') return '/admin/login';
    if (page === 'admin-overview') return '/admin';
    if (page === 'admin-models') return '/admin/models';
    if (page === 'observability') return '/admin/observability';
    if (page === 'admin-users') return '/admin/users';
    return '/admin/login';
  }

  function go(page){
    window.location.href = routeFor(page);
  }

  // Runs once per real page load (called from the inline script at the bottom of base.html)
  // to wire up the single screen that was actually server-rendered.
  async function initPage(page){
    const state = navStateFor(page);
    document.getElementById('app-nav').dataset.state = state;
    document.querySelectorAll('.nav-link').forEach(l => l.classList.toggle('active', l.dataset.page === page));

    await loadModels();
    if (page === 'observability') { loadObservability(); loadCostRollup(); }
    if (page === 'admin-users') loadUsers();
    if (page === 'admin-overview') { loadOverview(); loadOverviewActivity(); }
    window.scrollTo({top:0, behavior:'instant'});
  }

  async function logout(){
    try { await fetch(`${API_BASE}/api/auth/logout`, {method:'POST'}); } catch (error) {
      // Navigate away regardless — worst case the cookie outlives this tab, not a hang.
    }
    go('admin-auth');
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
    go('admin-overview');
  }
