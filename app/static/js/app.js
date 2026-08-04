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
  const COMPARE_STORAGE_KEY = 'smartreco.compareSelection';
  const eventQueue = [];
  const EVENT_BATCH_SIZE = 8;
  const EVENT_FLUSH_MS = 4000;
  let eventFlushTimer = null;

  function escapeHtml(value){
    return String(value ?? '').replace(/[&<>'"]/g, character => ({
      '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;'
    }[character]));
  }

  function setSessionRole(role){
    userSession = role === 'user';
    adminSession = role === 'admin';
    const pill = document.getElementById('persona-pill');
    if (pill && userSession) pill.textContent = 'signed in as: AI engineer';
    if (pill && adminSession) pill.textContent = 'signed in as: curator (admin)';
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

  function fromApiModel(model){
    const isVoice = model.modality === 'Voice';
    return {
      id:String(model.id), name:model.title, provider:model.provider, mod:model.modality,
      color:modelColor({mod:model.modality}), s1:isVoice ? 'Latency' : 'Context',
      v1:isVoice && model.latency_ms ? `~${model.latency_ms}ms` : (model.context_window || 'n/a'),
      s2:'Price', v2:model.price, sync:model.vector_synced ? 'synced' : 'indexing', api:true,
      latency:model.latency_ms || '', context:model.context_window || '',
      tags:(model.use_case_tags || []).join(', '), description:model.description || '', source:model.source_url || ''
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

  function renderCatalog(){
    grid.innerHTML = MODELS.map(m => `
      <div class="card" onclick="openModel('${m.id}')">
        <div class="stripe" style="background:${modelColor(m)}"></div>
        <div class="card-body">
          <div class="card-top">
            <span class="part-id">${escapeHtml(m.id)}</span>
            <span class="modality-tag" style="background:color-mix(in srgb, ${modelColor(m)} 22%, transparent); color:${modelColor(m)};">${escapeHtml(m.mod)}</span>
          </div>
          <h3>${escapeHtml(m.name)}</h3>
          <p class="provider">${escapeHtml(m.provider)}</p>
          <div class="spec-row"><span>${escapeHtml(m.s1)}</span><b>${escapeHtml(m.v1)}</b></div>
          <div class="spec-row"><span>${escapeHtml(m.s2)}</span><b>${escapeHtml(m.v2)}</b></div>
          <div class="card-actions">
            <div class="btn ${compareSelection.includes(m.id) ? 'on' : ''}" onclick="event.stopPropagation(); toggleCompareModel('${m.id}');">${compareSelection.includes(m.id) ? '✓ Comparing' : '+ Compare'}</div>
            <div class="btn primary" onclick="event.stopPropagation(); openModel('${m.id}');">View</div>
          </div>
        </div>
      </div>
    `).join('');
  }

  function renderAdminTable(){
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

  function renderDetail(modelId){
    const model = MODELS.find(item => String(item.id) === String(modelId));
    if (!model) return;
    selectedModelId = model.id;
    const color = modelColor(model);
    const modality = document.getElementById('detail-modality');
    modality.textContent = model.mod;
    modality.style.background = `color-mix(in srgb, ${color} 22%, transparent)`;
    modality.style.color = color;
    document.getElementById('detail-title').textContent = model.name;
    document.getElementById('detail-provider').textContent = `${model.provider} · ${model.id}`;
    document.getElementById('detail-description').textContent = model.description || `${model.name} from ${model.provider}.`;
    document.getElementById('detail-specs').innerHTML = [
      [model.s1, model.v1], ['Price', model.v2],
      ['Context window', model.context || 'n/a'],
      ['Source', model.source || 'Catalog record']
    ].map(([label, value]) => `<tr><td>${escapeHtml(label)}</td><td>${escapeHtml(value)}</td></tr>`).join('');
    document.getElementById('detail-tags').innerHTML = (model.tags || '').split(',').map(tag => tag.trim()).filter(Boolean)
      .map(tag => `<span class="use-tag">${escapeHtml(tag)}</span>`).join('');
    document.getElementById('detail-related').innerHTML = MODELS.filter(item => String(item.id) !== String(model.id)).slice(0, 3)
      .map(item => `<div class="related-item"><span>${escapeHtml(item.name)}</span><span class="rlt">${escapeHtml(item.v1)} · ${escapeHtml(item.v2)}</span></div>`).join('');
    document.getElementById('detail-note').textContent = userSession
      ? 'This model view has been recorded in your activity.'
      : 'Sign in to record model views and shape your recommendation.';
    updateCompareButton('detail-compare-btn', model.id);
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
    selectedModelId = String(modelId);
    renderDetail(selectedModelId);
    go('detail');
  }

  async function loadDashboard(){
    if (!userSession) return;
    try {
      const response = await fetch(`${API_BASE}/api/recommendations/me`);
      if (!response.ok) return;
      const recommendation = await response.json();
      if (recommendation.status === 'pending' || !recommendation.models?.length) {
        document.getElementById('dashboard-tags').innerHTML = '<span class="badge reason">status: learning</span><span class="badge conf">recommendation pending</span>';
        document.getElementById('dashboard-narrative').textContent = 'Your activity is being collected. Once enough signal is available, your grounded recommendation will appear here.';
        document.getElementById('dashboard-delta').textContent = 'No recommendation stored yet.';
        document.getElementById('recommendation-grid').innerHTML = '<p class="note">Browse and compare models to give the recommendation engine something real to work with.</p>';
      } else {
        const candidates = recommendation.models.map(fromApiModel);
        const hasNarrative = Boolean(recommendation.narrative);
        document.getElementById('dashboard-tags').innerHTML = hasNarrative
          ? '<span class="badge reason">status: generated</span><span class="badge conf">grounded candidates</span>'
          : '<span class="badge reason">status: retrieval ready</span><span class="badge conf">grounded candidates</span>';
        document.getElementById('dashboard-narrative').textContent = recommendation.narrative || 'These candidates were retrieved from the catalog using your recent activity. A generated explanation will appear when Mesh is configured.';
        document.getElementById('dashboard-delta').textContent = hasNarrative
          ? `Generated from ${candidates.length} grounded catalog candidate${candidates.length === 1 ? '' : 's'}.`
          : `${candidates.length} catalog candidate${candidates.length === 1 ? '' : 's'} retrieved from your activity.`;
        document.getElementById('recommendation-grid').innerHTML = candidates.map(model => `
          <div class="card" onclick="openModel('${model.id}')">
            <div class="stripe" style="background:${modelColor(model)}"></div>
            <div class="card-body">
              <div class="card-top"><span class="part-id">${escapeHtml(model.id)}</span><span class="modality-tag" style="background:color-mix(in srgb, ${modelColor(model)} 22%, transparent); color:${modelColor(model)};">${escapeHtml(model.mod)}</span></div>
              <h3>${escapeHtml(model.name)}</h3><p class="provider">${escapeHtml(model.provider)}</p>
              <div class="spec-row"><span>${escapeHtml(model.s1)}</span><b>${escapeHtml(model.v1)}</b></div>
              <div class="spec-row"><span>${escapeHtml(model.s2)}</span><b>${escapeHtml(model.v2)}</b></div>
            </div>
          </div>`).join('');
      }
    } catch (error) {
      // Keep the honest pending state when the recommendation API is unavailable.
    }
  }

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
      if (!payload.events.length) {
        log.innerHTML = '<p class="note">No activity recorded yet. Start by searching or opening a model.</p>';
        return;
      }
      log.innerHTML = payload.events.map(event => {
        const model = MODELS.find(item => String(item.id) === String(event.model_id));
        const detail = model ? model.name : event.metadata?.query || 'Catalog activity';
        const dwell = event.metadata?.dwell_seconds ? ` <span>· dwell ${escapeHtml(event.metadata.dwell_seconds)}s</span>` : '';
        return `<div class="log-row"><div class="log-time">${escapeHtml(new Date(event.created_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}))}</div><div class="log-type" style="background:var(--amber-dim); color:var(--amber);">${escapeHtml(event.type)}</div><div class="log-detail">${escapeHtml(detail)}${dwell}</div></div>`;
      }).join('');
      document.getElementById('activity-note').textContent = `${payload.events.length} persisted event${payload.events.length === 1 ? '' : 's'} · event ingestion is active.`;
    } catch (error) {
      log.innerHTML = '<p class="note">Activity is temporarily unavailable.</p>';
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
    } catch (error) {
      eventQueue.unshift(...events);
    }
    if (eventQueue.length) scheduleEventFlush();
  }

  function trackEvent(eventType, modelId=null, metadata={}){
    if (!userSession) return;
    const numericModelId = Number(modelId);
    const event = {event_type:eventType, metadata};
    if (Number.isInteger(numericModelId)) event.model_id = numericModelId;
    eventQueue.push(event);
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
    const seconds = Math.round((Date.now() - dwellStartedAt) / 1000);
    if (seconds >= 1) trackEvent('model_view', dwellModelId, {dwell_seconds: seconds});
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
    if (selectedModelId) updateCompareButton('detail-compare-btn', selectedModelId);
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
      [chosen[0].s1, m => m.v1],
      ['Price', m => m.v2],
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
    if (event.key === 'Escape' && modelModal.classList.contains('show')) closeModelModal();
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

  renderCatalog();
  renderAdminTable();

  // Real app-flow navigation: each screen only exposes the destinations a user could actually
  // reach from it. Auth state (none / AI engineer / admin) drives which nav links exist at all —
  // there is no single tab bar exposing every screen as an equal peer.
  const BUILDER_PAGES = ['catalog', 'detail', 'compare', 'dashboard', 'activity'];
  const TRAY_PAGES = ['catalog', 'detail', 'compare'];

  function navStateFor(page){
    if (page === 'admin') return 'admin';
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
    return '/catalog';
  }

  function go(page, push=true){
    finalizeDwell();
    const route = routeFor(page);
    if (push && `${window.location.pathname}${window.location.search}` !== route) {
      window.history.pushState({page}, '', route);
    }
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-' + page).classList.add('active');

    const state = navStateFor(page);
    const nav = document.getElementById('app-nav');
    nav.dataset.state = state;
    document.querySelectorAll('.nav-link').forEach(l => l.classList.toggle('active', l.dataset.page === page));

    updateTrayVisibility();
    if (page === 'detail') {
      const modelId = selectedModelId || MODELS[0]?.id;
      renderDetail(modelId);
      startDwell(modelId);
    }
    if (page === 'compare') renderCompare();
    if (page === 'dashboard') loadDashboard();
    if (page === 'activity') loadActivity();
    window.scrollTo({top:0, behavior:'instant'});
  }

  window.addEventListener('popstate', () => {
    const path = window.location.pathname;
    if (path === '/login') return go('auth', false);
    if (path === '/admin/login') return go('admin-auth', false);
    if (path === '/catalog' || path === '/') return go('catalog', false);
    if (path === '/compare') {
      restoreCompareFromUrl();
      return go('compare', false);
    }
    if (path === '/dashboard') return go('dashboard', false);
    if (path === '/activity') return go('activity', false);
    if (path === '/admin') return go('admin', false);
    if (path.startsWith('/models/')) return go('detail', false);
    go('catalog', false);
  });

  function logout(){
    const wasAdmin = document.getElementById('app-nav').dataset.state === 'admin';
    document.getElementById('persona-pill').textContent = 'not signed in';
    go(wasAdmin ? 'admin-auth' : 'auth');
  }

  renderTray();

  document.querySelectorAll('#modality-filters .chip').forEach(c => c.addEventListener('click', () => c.classList.toggle('active')));
  let searchTimer;
  document.querySelector('.searchbar input').addEventListener('input', event => {
    const query = event.target.value.trim();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      searchModels(query);
      trackEvent('search', null, {query});
    }, 220);
  });

  // ---- auth (AI engineer) ----
  const AUTH_COPY = {
    login: {
      eyebrow: 'Sign in', heading: 'Welcome back',
      sub: 'Sign in to pick up where you left off — your comparisons and dashboard are waiting.',
      button: 'Sign in →',
      switch: 'New here? <span onclick="setAuthMode(\'register\')">Create an account</span>',
    },
    register: {
      eyebrow: 'Get started', heading: 'Create your account',
      sub: 'Free during the beta — takes about 30 seconds, no credit card.',
      button: 'Create account →',
      switch: 'Already have an account? <span onclick="setAuthMode(\'login\')">Sign in</span>',
    },
  };

  function setAuthMode(mode){
    const registering = mode === 'register';
    document.querySelectorAll('#auth-toggle .opt').forEach(x => x.classList.toggle('active', x.dataset.mode === mode));
    document.getElementById('auth-form').classList.toggle('register-mode', registering);
    const copy = AUTH_COPY[mode];
    document.getElementById('auth-eyebrow').textContent = copy.eyebrow;
    document.getElementById('auth-heading').textContent = copy.heading;
    document.getElementById('auth-subheading').textContent = copy.sub;
    document.getElementById('auth-submit-btn').textContent = copy.button;
    document.getElementById('auth-switch').innerHTML = copy.switch;
    document.getElementById('auth-error').classList.remove('show');
    document.querySelector('#auth-form .only-register input').tabIndex = registering ? 0 : -1;
  }

  document.querySelectorAll('#auth-toggle .opt').forEach(o => o.addEventListener('click', () => setAuthMode(o.dataset.mode)));

  async function submitAuth(event){
    if (event) event.preventDefault();
    document.getElementById('auth-error').classList.remove('show');
    const fields = document.querySelectorAll('#auth-form input');
    const registering = document.getElementById('auth-form').classList.contains('register-mode');
    const credentials = {email:fields[0].value, password:fields[1].value};
    try {
      let response = await fetch(`${API_BASE}/api/auth/${registering ? 'register' : 'login'}`, {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(credentials)
      });
      if (registering && response.ok) {
        response = await fetch(`${API_BASE}/api/auth/login`, {
          method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(credentials)
        });
      }
      if (!response.ok) throw new Error('login failed');
      userSession = true;
      await loadModels();
    } catch (error) {
      document.getElementById('auth-error').classList.add('show');
      return;
    }
    document.getElementById('persona-pill').textContent = 'signed in as: AI engineer';
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
      adminSession = true;
      await loadModels();
    } catch (error) {
      document.getElementById('admin-auth-error').classList.add('show');
      return;
    }
    document.getElementById('persona-pill').textContent = 'signed in as: curator (admin)';
    go('admin');
  }
