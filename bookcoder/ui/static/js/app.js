(() => {
  const $ = (id) => document.getElementById(id);

  const state = {
    book: null,
    file: null,
    voices: [],
    providers: [],
    selectedProviderId: '',
    provider: null, // current provider info from voices response
    offlineModels: [],
    jobId: null,
    eventSource: null,
    pendingFiles: [],
    busy: false,
    downloadPollTimer: null,
  };

  // Elements
  const dropZone = $("dropZone");
  const fileInput = $("fileInput");
  const browseBtn = $("browseBtn");
  const replaceBtn = $("replaceBtn");
  const removeBtn = $("removeBtn");
  const uploadError = $("uploadError");
  const uploadInfo = $("uploadInfo");
  const fileCard = $("fileCard");
  const bookMeta = $("bookMeta");
  const fileName = $("fileName");
  const fileDetails = $("fileDetails");
  const bookTitle = $("bookTitle");
  const bookAuthor = $("bookAuthor");
  const detectedLanguage = $("detectedLanguage");
  const languageOverride = $("languageOverride");
  const chaptersList = $("chaptersList");
  const chaptersEmpty = $("chaptersEmpty");
  const selectAllBtn = $("selectAllBtn");
  const selectNoneBtn = $("selectNoneBtn");

  const providerSelect = $("providerSelect");
  const providerMeta = $("providerMeta");
  const voiceSelect = $("voiceSelect");
  const voiceMeta = $("voiceMeta");
  const previewBtn = $("previewBtn");
  const previewAudio = $("previewAudio");
  const previewStatus = $("previewStatus");
  const engineStatusBox = $("engineStatusBox");

  const speedRange = $("speedRange");
  const speedValue = $("speedValue");
  const pitchRange = $("pitchRange");
  const pitchValue = $("pitchValue");
  const pitchHelp = $("pitchHelp");
  const styleSelect = $("styleSelect");
  const toneProfileSelect = $("toneProfileSelect");
  const dialogueVoiceSelect = $("dialogueVoiceSelect");

  const outputDir = $("outputDir");
  const outputFormat = $("outputFormat");
  const bitrateSelect = $("bitrateSelect");
  const combineChk = $("combineChk");
  const pauseRange = $("pauseRange");
  const pauseValue = $("pauseValue");
  const generateBtn = $("generateBtn");
  const cancelBtn = $("cancelBtn");
  const progressWrap = $("progressWrap");
  const progressBar = $("progressBar");
  const progressPct = $("progressPct");
  const progressStage = $("progressStage");
  const progressMessage = $("progressMessage");
  const resultBox = $("resultBox");
  const genError = $("genError");
  const providerStatus = $("providerStatus");

  // Offline models elements
  const refreshModelsBtn = $("refreshModelsBtn");
  const modelLanguageFilter = $("modelLanguageFilter");
  const modelGenderFilter = $("modelGenderFilter");
  const modelsDirInfo = $("modelsDirInfo");
  const offlineRuntimeNotice = $("offlineRuntimeNotice");
  const offlineModelsList = $("offlineModelsList");

  function init() {
    bindEvents();
    updateRangeLabels();
    loadInitialSettings().then(() => {
      refreshProviders().then(() => {
        refreshProviderStatus();
        loadOfflineModels();
      });
    });
  }

  function bindEvents() {
    browseBtn.addEventListener("click", (e) => { e.stopPropagation(); fileInput.click(); });
    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } });
    fileInput.addEventListener("change", () => handleFiles(fileInput.files));

    ;["dragenter", "dragover"].forEach(evt => dropZone.addEventListener(evt, (e) => {
      e.preventDefault(); e.stopPropagation(); dropZone.classList.add("dragover");
    }));
    ;["dragleave", "drop"].forEach(evt => dropZone.addEventListener(evt, (e) => {
      e.preventDefault(); e.stopPropagation(); dropZone.classList.remove("dragover");
    }));
    dropZone.addEventListener("drop", (e) => {
      const dt = e.dataTransfer;
      if (dt && dt.files && dt.files.length) handleFiles(dt.files);
    });

    replaceBtn.addEventListener("click", () => fileInput.click());
    removeBtn.addEventListener("click", () => removeCurrentBook());

    languageOverride.addEventListener("change", () => onLanguageChange());

    providerSelect.addEventListener("change", () => onProviderChange());
    voiceSelect.addEventListener("change", () => updateVoiceMeta());
    previewBtn.addEventListener("click", () => previewVoice());

    speedRange.addEventListener("input", updateRangeLabels);
    pitchRange.addEventListener("input", updateRangeLabels);
    pauseRange.addEventListener("input", updateRangeLabels);

    selectAllBtn.addEventListener("click", () => setAllChapters(true));
    selectNoneBtn.addEventListener("click", () => setAllChapters(false));

    generateBtn.addEventListener("click", () => startGeneration());
    cancelBtn.addEventListener("click", () => cancelGeneration());

    refreshModelsBtn.addEventListener("click", () => loadOfflineModels());
    modelLanguageFilter.addEventListener("change", () => loadOfflineModels());
    modelGenderFilter.addEventListener("change", () => renderOfflineModels());

    [speedRange, pitchRange, styleSelect, toneProfileSelect, dialogueVoiceSelect, outputFormat, bitrateSelect, combineChk, pauseRange, outputDir].forEach(el => {
      if (!el) return;
      el.addEventListener("change", () => saveSettings());
    });
  }

  function updateRangeLabels() {
    speedValue.textContent = `${parseFloat(speedRange.value).toFixed(2)}×`;
    const p = parseFloat(pitchRange.value);
    pitchValue.textContent = (p > 0 ? "+" : "") + p;
    pauseValue.textContent = `${pauseRange.value} ms`;
  }

  async function loadInitialSettings() {
    try {
      const res = await fetchJSON(`/api/settings`);
      if (res.ok && res.settings) {
        applySettings(res.settings);
      }
      if (res.last_output_dir && !outputDir.value) {
        outputDir.value = res.last_output_dir;
      }
    } catch (e) { /* ignore */ }
  }

  async function refreshProviders() {
    try {
      const lang = getEffectiveLanguage();
      const res = await fetchJSON(`/api/providers?language=${encodeURIComponent(lang)}`);
      if (res.ok) {
        state.providers = res.providers || [];
      } else {
        state.providers = [];
      }
    } catch (e) {
      state.providers = [];
    }
    renderProviderSelect();
  }

  function renderProviderSelect() {
    const providers = state.providers || [];
    const prev = state.selectedProviderId || providerSelect.value;
    providerSelect.innerHTML = '';

    if (!providers.length) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = 'No narration engines available';
      providerSelect.appendChild(opt);
      state.selectedProviderId = '';
      updateProviderMeta();
      return;
    }

    providers.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id;
      let label = p.name;
      if (!p.available) label += ' (unavailable)';
      if (p.id === 'piper' && typeof p.downloaded_voice_count === 'number') {
        label += ` — ${p.downloaded_voice_count} voice(s) downloaded`;
      }
      opt.textContent = label;
      providerSelect.appendChild(opt);
    });

    let chosen = '';
    if (prev && providers.some(p => p.id === prev)) {
      chosen = prev;
    } else {
      // Prefer previously remembered provider from settings? handled by applySettings/load
      // Default: edge if available, else piper if available
      const edge = providers.find(p => p.id === 'edge-tts' && p.available);
      const piper = providers.find(p => p.id === 'piper' && p.available);
      if (edge) chosen = edge.id;
      else if (piper) chosen = piper.id;
      else chosen = (providers.find(p => p.available) || providers[0]).id;
    }
    providerSelect.value = chosen;
    state.selectedProviderId = chosen;
    updateProviderMeta();
  }

  function updateProviderMeta() {
    const p = (state.providers || []).find(x => x.id === state.selectedProviderId);
    if (!p) {
      providerMeta.textContent = '';
      engineStatusBox.textContent = 'No narration engine selected.';
      return;
    }
    providerMeta.textContent = p.description || '';
    const parts = [];
    parts.push(p.available ? `Available` : `Unavailable`);
    if (p.reason) parts.push(p.reason);
    if (p.id === 'piper' && typeof p.downloaded_voice_count === 'number') {
      parts.push(`${p.downloaded_voice_count} downloaded voice(s)`);
    }
    engineStatusBox.textContent = parts.join(' • ');

    // Pitch support UI
    const supportsPitch = !!p.supports_pitch;
    pitchRange.disabled = !supportsPitch;
    if (!supportsPitch) {
      pitchHelp.textContent = 'Pitch adjustment is not supported by this engine.';
    } else {
      pitchHelp.textContent = 'Adjust tone if supported by the engine.';
    }

    // Show/hide or highlight offline panel notice
    updateOfflineRuntimeNotice(p);
  }

  function updateOfflineRuntimeNotice(p) {
    const piper = (state.providers || []).find(x => x.id === 'piper');
    if (!piper) {
      offlineRuntimeNotice.classList.add('hidden');
      return;
    }
    if (!piper.available) {
      offlineRuntimeNotice.textContent = piper.reason || 'Piper offline runtime is not installed. Install piper-tts to enable offline narration.';
      offlineRuntimeNotice.className = 'alert alert-info';
      offlineRuntimeNotice.classList.remove('hidden');
      return;
    }
    if (p && p.id === 'piper' && (p.downloaded_voice_count || 0) === 0) {
      offlineRuntimeNotice.textContent = 'No offline voices downloaded yet. Download one or more Piper voices below, then select one in the Voice menu.';
      offlineRuntimeNotice.className = 'alert alert-info';
      offlineRuntimeNotice.classList.remove('hidden');
      return;
    }
    offlineRuntimeNotice.classList.add('hidden');
  }

  async function refreshProviderStatus() {
    try {
      const lang = getEffectiveLanguage();
      const pid = state.selectedProviderId || '';
      const res = await fetchJSON(`/api/voices?language=${encodeURIComponent(lang)}&provider=${encodeURIComponent(pid)}`);
      if (res.ok) {
        state.provider = res.provider || null;
        providerStatus.textContent = res.provider ? `Narration engine: ${res.provider.name}` : 'Narration engine ready';
        providerStatus.className = 'pill pill-ok';
      } else {
        providerStatus.textContent = res.error || 'Narration engine unavailable';
        providerStatus.className = 'pill pill-warn';
      }
    } catch (e) {
      providerStatus.textContent = 'Narration engine status unknown';
      providerStatus.className = 'pill pill-warn';
    }
  }

  function handleFiles(fileList) {
    hideUploadError();
    const files = Array.from(fileList || []);
    if (!files.length) return;
    const valid = [];
    for (const f of files) {
      const ext = (f.name.split('.').pop() || '').toLowerCase();
      if (!['epub','mobi','azw3','txt'].includes(ext)) {
        showUploadError(`Unsupported file format for "${f.name}". Supported formats: EPUB (.epub), MOBI (.mobi), AZW3 (.azw3), TXT (.txt).`);
        continue;
      }
      valid.push(f);
    }
    if (!valid.length) return;
    if (state.book) {
      state.pendingFiles = valid.slice(1);
      uploadFile(valid[0]);
    } else {
      state.pendingFiles = valid.slice(1);
      uploadFile(valid[0]);
    }
    if (state.pendingFiles.length > 0) {
      showUploadInfo(`${state.pendingFiles.length} additional file(s) queued. Remove the current book after processing to load the next.`);
    }
    fileInput.value = '';
  }

  async function uploadFile(file) {
    if (state.busy) return;
    setBusy(true);
    hideUploadError();
    resultBox.classList.add('hidden');
    genError.classList.add('hidden');
    showUploadInfo(`Uploading and analyzing "${file.name}"…`);
    const fd = new FormData();
    fd.append('file', file);
    try {
      const resp = await fetch('/api/upload', { method: 'POST', body: fd });
      const res = await resp.json().catch(() => ({}));
      if (!resp.ok || !res.ok) {
        throw new Error(res.error || `Upload failed (${resp.status})`);
      }
      state.book = res.book;
      state.file = res.file;
      renderBook();
      if (res.settings) {
        applySettings(res.settings);
        if (res.settings.provider_id && (state.providers || []).some(p => p.id === res.settings.provider_id)) {
          state.selectedProviderId = res.settings.provider_id;
          providerSelect.value = res.settings.provider_id;
        }
      }
      updateProviderMeta();
      await loadVoices(getEffectiveLanguage());
      hideUploadInfo();
      if (state.pendingFiles.length > 0) {
        showUploadInfo(`Loaded "${res.file.filename}". ${state.pendingFiles.length} more file(s) queued.`);
      }
    } catch (e) {
      showUploadError(e.message || String(e));
      hideUploadInfo();
    } finally {
      setBusy(false);
    }
  }

  function renderBook() {
    const book = state.book;
    const file = state.file;
    if (!book || !file) {
      fileCard.classList.add('hidden');
      bookMeta.classList.add('hidden');
      chaptersList.innerHTML = '';
      chaptersEmpty.classList.remove('hidden');
      return;
    }
    fileCard.classList.remove('hidden');
    bookMeta.classList.remove('hidden');
    fileName.textContent = file.filename;
    fileDetails.textContent = `${formatBytes(file.size)} • ${(file.format || '').toUpperCase()}`;
    bookTitle.textContent = book.title || '—';
    bookAuthor.textContent = book.author || 'Unknown';
    const det = book.detected_language === 'hu' ? 'Hungarian (Magyar)' : 'English';
    detectedLanguage.textContent = det + ' (auto-detected from text)';
    const sel = book.selected_language || book.detected_language || 'en';
    languageOverride.value = sel;

    if (!outputDir.value) {
      const safe = (book.title || book.filename || 'Audiobook').replace(/[^\w\s\-\.]/g, '').trim() || 'Audiobook';
      outputDir.value = `~/BookCoderAudiobooks/${safe}`;
    }

    renderChapters();
  }

  function renderChapters() {
    const book = state.book;
    if (!book || !book.chapters || !book.chapters.length) {
      chaptersList.innerHTML = '';
      chaptersEmpty.classList.remove('hidden');
      return;
    }
    chaptersEmpty.classList.add('hidden');
    chaptersList.innerHTML = '';
    book.chapters.forEach((ch, idx) => {
      const item = document.createElement('div');
      item.className = 'chapter-item' + (ch.included ? '' : ' excluded');
      item.dataset.id = ch.id;

      const checkWrap = document.createElement('div');
      checkWrap.className = 'chapter-check';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = !!ch.included;
      cb.addEventListener('change', () => { ch.included = cb.checked; item.classList.toggle('excluded', !ch.included); });
      checkWrap.appendChild(cb);

      const body = document.createElement('div');
      const t = document.createElement('div');
      t.className = 'chapter-title';
      t.textContent = ch.title || `Chapter ${idx + 1}`;
      const meta = document.createElement('div');
      meta.className = 'chapter-meta';
      meta.textContent = `#${idx + 1} • ${ch.word_count || 0} words`;
      const prev = document.createElement('div');
      prev.className = 'chapter-preview';
      prev.textContent = ch.preview || '';
      body.appendChild(t); body.appendChild(meta); body.appendChild(prev);

      const controls = document.createElement('div');
      controls.className = 'chapter-controls';
      const up = document.createElement('button');
      up.className = 'icon-btn'; up.type = 'button'; up.title = 'Move up'; up.textContent = '↑';
      up.disabled = idx === 0;
      up.addEventListener('click', () => moveChapter(idx, -1));
      const down = document.createElement('button');
      down.className = 'icon-btn'; down.type = 'button'; down.title = 'Move down'; down.textContent = '↓';
      down.disabled = idx === book.chapters.length - 1;
      down.addEventListener('click', () => moveChapter(idx, 1));
      controls.appendChild(up); controls.appendChild(down);

      item.appendChild(checkWrap);
      item.appendChild(body);
      item.appendChild(controls);
      chaptersList.appendChild(item);
    });
  }

  function moveChapter(index, delta) {
    const arr = state.book.chapters;
    const ni = index + delta;
    if (ni < 0 || ni >= arr.length) return;
    const tmp = arr[index];
    arr[index] = arr[ni];
    arr[ni] = tmp;
    arr.forEach((c, i) => c.index = i);
    renderChapters();
  }

  function setAllChapters(val) {
    if (!state.book) return;
    state.book.chapters.forEach(c => c.included = !!val);
    renderChapters();
  }

  function getEffectiveLanguage() {
    return languageOverride.value || (state.book && (state.book.selected_language || state.book.detected_language)) || 'en';
  }

  async function onLanguageChange() {
    const lang = getEffectiveLanguage();
    if (state.book) {
      try {
        const res = await fetchJSON(`/api/book/${state.book.id}/language`, {
          method: 'POST', body: { language: lang, provider_id: state.selectedProviderId }
        });
        if (res.ok && res.book) {
          state.book = res.book;
          renderBook();
        }
        if (res.settings) applySettings(res.settings);
      } catch (e) {
        showGenError(`Failed to change language: ${e.message || e}`);
      }
    }
    await refreshProviders();
    await loadVoices(lang);
    await loadOfflineModels();
    saveSettings();
  }

  async function onProviderChange() {
    state.selectedProviderId = providerSelect.value || '';
    updateProviderMeta();
    await loadVoices(getEffectiveLanguage());
    await refreshProviders(); // update counts/labels
    providerSelect.value = state.selectedProviderId;
    updateProviderMeta();
    refreshProviderStatus();
    saveSettings();
  }

  async function loadVoices(language) {
    try {
      const lang = language || getEffectiveLanguage();
      const pid = state.selectedProviderId || '';
      const res = await fetchJSON(`/api/voices?language=${encodeURIComponent(lang)}&provider=${encodeURIComponent(pid)}`);
      if (res.provider) state.provider = res.provider;
      state.voices = res.voices || [];
      renderVoices();
      if (res.hint) {
        previewStatus.textContent = res.hint;
      } else if (!res.ok && res.error) {
        previewStatus.textContent = res.error;
      } else {
        previewStatus.textContent = '';
      }
      // Update pitch support from actual provider response if available
      if (res.provider && typeof res.provider.supports_pitch === 'boolean') {
        pitchRange.disabled = !res.provider.supports_pitch;
        pitchHelp.textContent = res.provider.supports_pitch ? 'Adjust tone if supported by the engine.' : 'Pitch adjustment is not supported by this engine.';
      }
    } catch (e) {
      state.voices = [];
      renderVoices();
      previewStatus.textContent = 'Could not load voices.';
    }
  }

  function renderVoices() {
    const voices = state.voices || [];
    const current = voiceSelect.value;
    const currentDialogue = dialogueVoiceSelect ? dialogueVoiceSelect.value : '';

    voiceSelect.innerHTML = '';
    if (dialogueVoiceSelect) {
      dialogueVoiceSelect.innerHTML = '';
      const sameOpt = document.createElement('option');
      sameOpt.value = '';
      sameOpt.textContent = 'Same as narrator voice';
      dialogueVoiceSelect.appendChild(sameOpt);
    }

    if (!voices.length) {
      const opt = document.createElement('option');
      opt.value = '';
      if (state.selectedProviderId === 'piper') {
        opt.textContent = 'No offline voices downloaded — download a model below';
      } else {
        opt.textContent = 'No voices available';
      }
      voiceSelect.appendChild(opt);
      updateVoiceMeta();
      return;
    }

    const groups = { Female: [], Male: [], Other: [] };
    voices.forEach(v => {
      const g = (v.gender || '').toLowerCase().includes('female') ? 'Female'
              : (v.gender || '').toLowerCase().includes('male') ? 'Male' : 'Other';
      groups[g].push(v);
    });

    const appendGroupedOptions = (selectEl, includeSame) => {
      if (!selectEl) return;
      if (includeSame) {
        // already added "Same as narrator voice"
      }
      for (const [label, list] of Object.entries(groups)) {
        if (!list.length) continue;
        const og = document.createElement('optgroup');
        og.label = label;
        list.forEach(v => {
          const opt = document.createElement('option');
          opt.value = v.id;
          opt.textContent = `${v.name}${v.locale ? ' — ' + v.locale : ''}${v.style ? ' (' + v.style + ')' : ''}`;
          og.appendChild(opt);
        });
        selectEl.appendChild(og);
      }
    };

    appendGroupedOptions(voiceSelect, false);
    appendGroupedOptions(dialogueVoiceSelect, true);

    if (current && voices.some(v => v.id === current)) {
      voiceSelect.value = current;
    } else if (voices[0]) {
      voiceSelect.value = voices[0].id;
    }

    const pending = state._pendingVoiceId;
    if (pending && voices.some(v => v.id === pending)) {
      voiceSelect.value = pending;
      state._pendingVoiceId = null;
    }

    if (dialogueVoiceSelect) {
      const pendingDialogue = state._pendingDialogueVoiceId;
      if (pendingDialogue && voices.some(v => v.id === pendingDialogue)) {
        dialogueVoiceSelect.value = pendingDialogue;
        state._pendingDialogueVoiceId = null;
      } else if (currentDialogue && voices.some(v => v.id === currentDialogue)) {
        dialogueVoiceSelect.value = currentDialogue;
      } else {
        dialogueVoiceSelect.value = '';
      }
    }

    updateVoiceMeta();
  }

  function updateVoiceMeta() {
    const id = voiceSelect.value;
    const v = (state.voices || []).find(x => x.id === id);
    if (!v) { voiceMeta.textContent = ''; return; }
    const parts = [];
    if (v.gender) parts.push(v.gender);
    if (v.locale) parts.push(v.locale);
    if (v.description) parts.push(v.description);
    voiceMeta.textContent = parts.join(' • ');
    saveSettings();
  }

  async function previewVoice() {
    const voiceId = voiceSelect.value;
    if (!voiceId) { previewStatus.textContent = 'Select a voice first.'; return; }
    previewBtn.disabled = true;
    previewStatus.textContent = 'Generating preview…';
    previewAudio.classList.add('hidden');
    try {
      const resp = await fetch('/api/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          voice_id: voiceId,
          provider_id: state.selectedProviderId,
          language: getEffectiveLanguage(),
          speed: parseFloat(speedRange.value),
          pitch: parseFloat(pitchRange.value),
        })
      });
      const ct = resp.headers.get('content-type') || '';
      if (!resp.ok || ct.includes('application/json')) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || 'Preview failed');
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      previewAudio.src = url;
      previewAudio.classList.remove('hidden');
      previewStatus.textContent = 'Preview ready.';
      try { await previewAudio.play(); } catch (e) {}
    } catch (e) {
      previewStatus.textContent = e.message || String(e);
    } finally {
      previewBtn.disabled = false;
    }
  }

  // ---- Offline models ----
  async function loadOfflineModels() {
    try {
      const filter = modelLanguageFilter.value;
      let langParam = '';
      if (filter === 'current') langParam = getEffectiveLanguage();
      else if (filter === 'en' || filter === 'hu') langParam = filter;
      const url = langParam ? `/api/offline-models?language=${encodeURIComponent(langParam)}` : '/api/offline-models';
      const res = await fetchJSON(url);
      if (res.ok) {
        state.offlineModels = res.models || [];
        modelsDirInfo.textContent = res.models_dir || '—';
      } else {
        state.offlineModels = [];
        modelsDirInfo.textContent = res.error || '—';
      }
    } catch (e) {
      state.offlineModels = [];
    }
    renderOfflineModels();
    ensureDownloadPolling();
  }

  function renderOfflineModels() {
    const genderFilter = modelGenderFilter.value;
    let models = (state.offlineModels || []).slice();
    if (genderFilter && genderFilter !== 'all') {
      models = models.filter(m => (m.gender || '').toLowerCase() === genderFilter.toLowerCase());
    }
    if (!models.length) {
      offlineModelsList.innerHTML = `<div class="empty-state">No offline voice models match the selected filters.</div>`;
      return;
    }
    offlineModelsList.innerHTML = '';
    models.forEach(m => {
      const card = document.createElement('div');
      card.className = 'model-card' + (m.downloaded ? ' downloaded' : '');
      card.dataset.key = m.key;

      const main = document.createElement('div');
      const name = document.createElement('div');
      name.className = 'model-name';
      name.textContent = m.name || m.key;
      const tags = document.createElement('div');
      tags.className = 'model-tags';
      tags.appendChild(makeTag(langName(m.language), 'tag-lang'));
      tags.appendChild(makeTag(m.gender || '', m.gender === 'Female' ? 'tag-female' : (m.gender === 'Male' ? 'tag-male' : '')));
      if (m.quality) tags.appendChild(makeTag(m.quality, ''));
      if (m.downloaded) tags.appendChild(makeTag('Downloaded', 'tag-ok'));
      else if (m.downloading || (m.status === 'downloading')) tags.appendChild(makeTag('Downloading', 'tag-warn'));
      else if (m.partial) tags.appendChild(makeTag('Incomplete', 'tag-warn'));
      const desc = document.createElement('div');
      desc.className = 'model-desc';
      desc.textContent = m.description || '';
      main.appendChild(name);
      main.appendChild(tags);
      main.appendChild(desc);

      const side = document.createElement('div');
      side.className = 'model-side';
      const size = document.createElement('div');
      size.className = 'model-size';
      size.textContent = m.size_hint_mb ? `~${m.size_hint_mb} MB` : '';
      side.appendChild(size);

      const actions = document.createElement('div');
      actions.className = 'model-actions';

      const downloading = m.downloading || m.status === 'downloading';
      if (downloading) {
        const progWrap = document.createElement('div');
        progWrap.className = 'dl-progress';
        const track = document.createElement('div');
        track.className = 'dl-progress-track';
        const bar = document.createElement('div');
        bar.className = 'dl-progress-bar';
        const pct = typeof m.progress === 'number' ? m.progress : 0;
        bar.style.width = `${pct}%`;
        track.appendChild(bar);
        const txt = document.createElement('div');
        txt.className = 'dl-progress-text';
        txt.textContent = m.message ? `${m.message} ${pct ? '('+pct+'%)' : ''}` : `Downloading… ${pct}%`;
        progWrap.appendChild(track);
        progWrap.appendChild(txt);
        side.appendChild(progWrap);
      } else if (m.downloaded) {
        const useBtn = document.createElement('button');
        useBtn.className = 'btn btn-success btn-sm';
        useBtn.type = 'button';
        useBtn.textContent = 'Use voice';
        useBtn.addEventListener('click', () => useOfflineModel(m));
        const delBtn = document.createElement('button');
        delBtn.className = 'btn btn-danger btn-sm';
        delBtn.type = 'button';
        delBtn.textContent = 'Delete';
        delBtn.addEventListener('click', () => deleteOfflineModel(m.key));
        actions.appendChild(useBtn);
        actions.appendChild(delBtn);
      } else {
        const dlBtn = document.createElement('button');
        dlBtn.className = 'btn btn-primary btn-sm';
        dlBtn.type = 'button';
        dlBtn.textContent = m.partial ? 'Re-download' : 'Download';
        dlBtn.addEventListener('click', () => downloadOfflineModel(m.key));
        actions.appendChild(dlBtn);
      }
      side.appendChild(actions);

      card.appendChild(main);
      card.appendChild(side);
      offlineModelsList.appendChild(card);
    });
  }

  function makeTag(text, extraClass) {
    const span = document.createElement('span');
    span.className = 'tag' + (extraClass ? ' ' + extraClass : '');
    span.textContent = text || '';
    return span;
  }

  function langName(code) {
    if (code === 'hu') return 'Hungarian';
    if (code === 'en') return 'English';
    return code || '';
  }

  async function downloadOfflineModel(key) {
    try {
      const res = await fetchJSON(`/api/offline-models/${encodeURIComponent(key)}/download`, { method: 'POST' });
      if (!res.ok) throw new Error(res.error || 'Failed to start download');
      await loadOfflineModels();
      ensureDownloadPolling();
    } catch (e) {
      showGenError(e.message || String(e));
    }
  }

  async function deleteOfflineModel(key) {
    if (!confirm('Delete this downloaded offline voice model? You can download it again later.')) return;
    try {
      const res = await fetchJSON(`/api/offline-models/${encodeURIComponent(key)}/delete`, { method: 'POST' });
      if (!res.ok) throw new Error(res.error || 'Failed to delete model');
      await refreshProviders();
      await loadVoices(getEffectiveLanguage());
      await loadOfflineModels();
    } catch (e) {
      showGenError(e.message || String(e));
    }
  }

  async function useOfflineModel(m) {
    // Switch to Piper provider and select this voice
    state.selectedProviderId = 'piper';
    if ((state.providers || []).some(p => p.id === 'piper')) {
      providerSelect.value = 'piper';
    } else {
      await refreshProviders();
      providerSelect.value = 'piper';
      state.selectedProviderId = 'piper';
    }
    // Set language to model language if desired? keep current selection logic simple
    updateProviderMeta();
    await loadVoices(m.language || getEffectiveLanguage());
    // select the voice
    const vid = m.voice_id || `piper:${m.key}`;
    if ((state.voices || []).some(v => v.id === vid)) {
      voiceSelect.value = vid;
    }
    updateVoiceMeta();
    await refreshProviderStatus();
    saveSettings();
    // scroll narration into view? not necessary
  }

  function ensureDownloadPolling() {
    const anyDownloading = (state.offlineModels || []).some(m => m.downloading || m.status === 'downloading');
    if (anyDownloading) {
      if (!state.downloadPollTimer) {
        state.downloadPollTimer = setInterval(async () => {
          await pollDownloads();
        }, 1200);
      }
    } else {
      if (state.downloadPollTimer) {
        clearInterval(state.downloadPollTimer);
        state.downloadPollTimer = null;
      }
    }
  }

  async function pollDownloads() {
    // Reload model statuses; server merges progress
    try {
      const filter = modelLanguageFilter.value;
      let langParam = '';
      if (filter === 'current') langParam = getEffectiveLanguage();
      else if (filter === 'en' || filter === 'hu') langParam = filter;
      const url = langParam ? `/api/offline-models?language=${encodeURIComponent(langParam)}` : '/api/offline-models';
      const res = await fetchJSON(url);
      if (res.ok) {
        const prevDownloading = (state.offlineModels || []).some(m => m.downloading || m.status === 'downloading');
        state.offlineModels = res.models || [];
        const nowDownloading = (state.offlineModels || []).some(m => m.downloading || m.status === 'downloading');
        const anyDone = (state.offlineModels || []).some(m => m.status === 'done' || (m.downloaded && prevDownloading));
        renderOfflineModels();
        if (prevDownloading && !nowDownloading) {
          // downloads finished/changed state -> refresh providers/voices
          await refreshProviders();
          if (state.selectedProviderId === 'piper') {
            await loadVoices(getEffectiveLanguage());
          }
          refreshProviderStatus();
        } else if (anyDone && state.selectedProviderId === 'piper') {
          await loadVoices(getEffectiveLanguage());
        }
      }
    } catch (e) { /* ignore */ }
    ensureDownloadPolling();
  }

  // ---- Generation ----
  async function startGeneration() {
    if (!state.book) { showGenError('Please upload a book first.'); return; }
    const included = state.book.chapters.filter(c => c.included);
    if (!included.length) { showGenError('Please select at least one chapter to narrate.'); return; }
    if (!voiceSelect.value) {
      if (state.selectedProviderId === 'piper') {
        showGenError('Please download and select an offline Piper voice model first.');
      } else {
        showGenError('Please select a narration voice.');
      }
      return;
    }

    hideGenError();
    resultBox.classList.add('hidden');
    progressWrap.classList.remove('hidden');
    setProgress(0, 'Starting', 'Preparing audiobook generation…');
    generateBtn.disabled = true;
    cancelBtn.classList.remove('hidden');

    await saveSettings();

    const payload = {
      book_id: state.book.id,
      language: getEffectiveLanguage(),
      provider_id: state.selectedProviderId,
      voice_id: voiceSelect.value,
      speed: parseFloat(speedRange.value),
      pitch: parseFloat(pitchRange.value),
      style: styleSelect.value,
      tone_profile: toneProfileSelect ? toneProfileSelect.value : 'natural',
      dialogue_voice_id: dialogueVoiceSelect ? dialogueVoiceSelect.value : '',
      output_dir: outputDir.value,
      output_format: (outputFormat && outputFormat.value) ? outputFormat.value : 'mp3',
      bitrate_kbps: parseInt(bitrateSelect.value, 10) || 128,
      combine: !!combineChk.checked,
      chapter_pause_ms: parseInt(pauseRange.value, 10) || 1200,
      paragraph_pause_ms: (state.settings && typeof state.settings.paragraph_pause_ms === 'number') ? state.settings.paragraph_pause_ms : 450,
      chapters: state.book.chapters.map(c => ({ id: c.id, included: !!c.included })),
    };

    try {
      const res = await fetchJSON('/api/generate', { method: 'POST', body: payload });
      if (!res.ok) throw new Error(res.error || 'Failed to start generation');
      state.jobId = res.job_id;
      if (res.output_dir) outputDir.value = res.output_dir;
      listenProgress(res.job_id);
    } catch (e) {
      showGenError(e.message || String(e));
      resetGenerationUI();
    }
  }

  function listenProgress(jobId) {
    if (state.eventSource) { try { state.eventSource.close(); } catch(e){} }
    const es = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/events`);
    state.eventSource = es;
    es.onmessage = (ev) => {
      let data = null;
      try { data = JSON.parse(ev.data); } catch(e) { return; }
      handleJobEvent(data);
    };
    es.onerror = () => { if (!state.jobId) return; };
  }

  function handleJobEvent(data) {
    if (!data) return;
    if (data.type === 'snapshot') {
      if (data.status && data.status !== 'running') {
        if (data.status === 'done') handleJobEvent({ type: 'done', result: data.result });
        else if (data.status === 'error') handleJobEvent({ type: 'error', message: data.error || 'Error' });
        else if (data.status === 'cancelled') handleJobEvent({ type: 'cancelled' });
      }
      return;
    }
    if (data.type === 'progress') {
      const pct = Math.max(0, Math.min(100, Math.round((data.fraction || 0) * 100)));
      const stageLabel = stageName(data.stage);
      setProgress(pct, stageLabel, data.message || '');
      return;
    }
    if (data.type === 'done') {
      setProgress(100, 'Complete', data.message || 'Audiobook generation complete.');
      showResult(data.result);
      closeProgressStream();
      resetGenerationUI();
      return;
    }
    if (data.type === 'error') {
      showGenError(data.message || 'An error occurred during generation.');
      closeProgressStream();
      resetGenerationUI();
      return;
    }
    if (data.type === 'cancelled') {
      setProgress(null, 'Cancelled', 'Generation cancelled.');
      closeProgressStream();
      resetGenerationUI();
      return;
    }
  }

  function stageName(stage) {
    switch (stage) {
      case 'parse': return 'Parsing';
      case 'detect': return 'Detecting language';
      case 'synthesize': return 'Narrating';
      case 'combine': return 'Combining audio';
      case 'done': return 'Complete';
      default: return 'Working';
    }
  }

  function setProgress(pct, stage, message) {
    progressWrap.classList.remove('hidden');
    if (pct != null) {
      progressBar.style.width = `${pct}%`;
      progressPct.textContent = `${pct}%`;
    }
    if (stage) progressStage.textContent = stage;
    if (message != null) progressMessage.textContent = message;
  }

  function showResult(result) {
    if (!result) return;
    const files = result.chapter_files || [];
    const combined = result.combined_file;
    const outDir = result.output_dir || outputDir.value || '';
    const sample = (files && files.length ? files[0] : (combined || '')) || '';
    const isM4a = /\.m4a$/i.test(sample) || ((outputFormat && outputFormat.value) === 'm4a');
    const fmtLabel = isM4a ? 'AAC (M4A)' : 'MP3';
    const extLabel = isM4a ? '.m4a' : '.mp3';

    let html = `<h3>✓ Audiobook generated successfully</h3>`;
    html += `<div>Output folder: <code>${escapeHtml(outDir)}</code></div>`;
    html += `<ul>`;
    html += `<li>${files.length} chapter audio file(s) created (${fmtLabel}, ${extLabel}).</li>`;
    if (combined) {
      html += `<li>Combined audiobook: <code>${escapeHtml(basename(combined))}</code></li>`;
    }
    if (isM4a) {
      html += `<li>Audio encoded as AAC in an M4A container for direct copy to iPhone.</li>`;
    } else {
      html += `<li>Audio encoded for high-quality audiobook playback (MP3).</li>`;
    }
    html += `</ul>`;
    resultBox.innerHTML = html;
    resultBox.classList.remove('hidden');
  }

  function resetGenerationUI() {
    generateBtn.disabled = false;
    cancelBtn.classList.add('hidden');
    state.jobId = null;
  }

  function closeProgressStream() {
    if (state.eventSource) { try { state.eventSource.close(); } catch(e){} state.eventSource = null; }
  }

  async function cancelGeneration() {
    if (!state.jobId) return;
    cancelBtn.disabled = true;
    try {
      await fetchJSON(`/api/jobs/${encodeURIComponent(state.jobId)}/cancel`, { method: 'POST' });
      progressMessage.textContent = 'Cancelling…';
    } catch (e) { /* ignore */ }
    finally { cancelBtn.disabled = false; }
  }

  async function removeCurrentBook() {
    if (state.book) {
      try { await fetchJSON(`/api/book/${state.book.id}/remove`, { method: 'POST' }); } catch(e) {}
    }
    state.book = null;
    state.file = null;
    renderBook();
    hideUploadError();
    resultBox.classList.add('hidden');
    genError.classList.add('hidden');
    if (state.pendingFiles.length > 0) {
      const next = state.pendingFiles.shift();
      showUploadInfo(`Loading next queued file: "${next.name}"…`);
      uploadFile(next);
    } else {
      hideUploadInfo();
    }
  }

  async function saveSettings() {
    try {
      const settings = {
        provider_id: state.selectedProviderId,
        language: getEffectiveLanguage(),
        voice_id: voiceSelect.value,
        speed: parseFloat(speedRange.value),
        pitch: parseFloat(pitchRange.value),
        style: styleSelect.value,
        tone_profile: toneProfileSelect ? toneProfileSelect.value : 'natural',
        dialogue_voice_id: dialogueVoiceSelect ? dialogueVoiceSelect.value : '',
        output_format: (outputFormat && outputFormat.value) ? outputFormat.value : 'mp3',
        output_bitrate_kbps: parseInt(bitrateSelect.value, 10) || 128,
        combine_into_single_file: !!combineChk.checked,
        chapter_pause_ms: parseInt(pauseRange.value, 10) || 1200,
        paragraph_pause_ms: (state.settings && typeof state.settings.paragraph_pause_ms === 'number') ? state.settings.paragraph_pause_ms : 450,
        last_output_dir: outputDir.value,
      };
      await fetchJSON('/api/settings', { method: 'POST', body: settings });
      state.settings = Object.assign({}, state.settings || {}, settings);
    } catch (e) { /* non-fatal */ }
  }

  function applySettings(s) {
    if (!s) return;
    state.settings = Object.assign({}, state.settings || {}, s);
    if (typeof s.speed === 'number') speedRange.value = s.speed;
    if (typeof s.pitch === 'number') pitchRange.value = s.pitch;
    if (s.style) styleSelect.value = s.style;
    if (s.tone_profile && toneProfileSelect) toneProfileSelect.value = s.tone_profile;
    if (s.output_format && outputFormat) {
      const fmt = String(s.output_format).toLowerCase();
      outputFormat.value = (fmt === 'm4a' || fmt === 'aac' || fmt === 'mp4') ? 'm4a' : 'mp3';
    }
    if (s.output_bitrate_kbps) bitrateSelect.value = String(s.output_bitrate_kbps);
    if (typeof s.combine_into_single_file === 'boolean') combineChk.checked = s.combine_into_single_file;
    if (typeof s.chapter_pause_ms === 'number') pauseRange.value = s.chapter_pause_ms;
    if (s.provider_id) {
      state.selectedProviderId = s.provider_id;
      if (providerSelect && providerSelect.options.length) {
        try { providerSelect.value = s.provider_id; } catch(e){}
      }
    }
    // voice/dialogue voice will be applied after voices load; store temporarily
    if (s.voice_id) state._pendingVoiceId = s.voice_id;
    if (typeof s.dialogue_voice_id === 'string') state._pendingDialogueVoiceId = s.dialogue_voice_id;
    updateRangeLabels();
  }

  function showUploadError(msg) { uploadError.textContent = msg; uploadError.classList.remove('hidden'); }
  function hideUploadError() { uploadError.classList.add('hidden'); uploadError.textContent = ''; }
  function showUploadInfo(msg) { uploadInfo.textContent = msg; uploadInfo.classList.remove('hidden'); }
  function hideUploadInfo() { uploadInfo.classList.add('hidden'); uploadInfo.textContent = ''; }
  function showGenError(msg) { genError.textContent = msg; genError.classList.remove('hidden'); }
  function hideGenError() { genError.classList.add('hidden'); genError.textContent = ''; }

  function setBusy(b) {
    state.busy = b;
    dropZone.style.pointerEvents = b ? 'none' : '';
    dropZone.style.opacity = b ? '0.7' : '';
  }

  async function fetchJSON(url, opts = {}) {
    const init = Object.assign({}, opts);
    if (init.body && !(init.body instanceof FormData) && typeof init.body !== 'string') {
      init.headers = Object.assign({ 'Content-Type': 'application/json' }, init.headers || {});
      init.body = JSON.stringify(init.body);
    }
    const resp = await fetch(url, init);
    const text = await resp.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { ok: false, error: text || resp.statusText }; }
    if (!resp.ok && data.ok === undefined) data.ok = false;
    return data;
  }

  function formatBytes(bytes) {
    if (!bytes && bytes !== 0) return '';
    const units = ['B','KB','MB','GB'];
    let b = bytes, i = 0;
    while (b >= 1024 && i < units.length - 1) { b /= 1024; i++; }
    return `${b.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
  }
  function basename(p) { if (!p) return ''; return p.split(/[/\\]/).pop(); }
  function escapeHtml(s) { return String(s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

  document.addEventListener('DOMContentLoaded', init);
})();
