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
    chaptersExpanded: false,
    offlineModelsExpanded: false,
    hardware: null,
    cancelling: false,
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
  const toggleChaptersBtn = $("toggleChaptersBtn");
  const chaptersBody = $("chaptersBody");
  const chaptersSummary = $("chaptersSummary");

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
  const dialogueVoiceAltSelect = $("dialogueVoiceAltSelect");
  const paragraphPauseRange = $("paragraphPauseRange");
  const paragraphPauseValue = $("paragraphPauseValue");
  const sentencePauseChk = $("sentencePauseChk");
  const pronunciationMapInput = $("pronunciationMapInput");
  const pronunciationPresetSelect = $("pronunciationPresetSelect");
  const pronunciationExportBtn = $("pronunciationExportBtn");
  const pronunciationImportBtn = $("pronunciationImportBtn");
  const pronunciationImportFile = $("pronunciationImportFile");

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
  const toggleOfflineModelsBtn = $("toggleOfflineModelsBtn");
  const offlineModelsBody = $("offlineModelsBody");
  const offlineModelsSummary = $("offlineModelsSummary");

  function init() {
    bindEvents();
    updateRangeLabels();
    setChaptersExpanded(false);
    setOfflineModelsExpanded(false);
    loadHardwareInfo();
    loadInitialSettings().then(() => {
      refreshProviders().then(() => {
        refreshProviderStatus();
        loadOfflineModels();
      });
    });
  }

  async function loadHardwareInfo() {
    try {
      const res = await fetchJSON('/api/hardware');
      if (res.ok && res.hardware) {
        state.hardware = res.hardware;
      } else {
        state.hardware = null;
      }
    } catch (e) {
      state.hardware = null;
    }
    updateProviderMeta();
  }

  function formatHardwareSummary(hw) {
    if (!hw) return '';
    const parts = [];
    try {
      const n = hw.gpus && hw.gpus.nvidia;
      const a = hw.gpus && hw.gpus.amd;
      if (n && n.present) parts.push(`NVIDIA GPU detected${(n.names && n.names[0]) ? ': ' + n.names[0] : ''}`);
      if (a && a.present) parts.push(`AMD GPU detected${(a.names && a.names[0]) ? ': ' + a.names[0] : ''}`);
      if ((!n || !n.present) && (!a || !a.present)) parts.push('No NVIDIA/AMD GPU detected');
      const torch = hw.torch || {};
      if (torch.installed) {
        if (torch.cuda_available) parts.push(`PyTorch GPU acceleration available${hw.acceleration && hw.acceleration.backend ? ' (' + hw.acceleration.backend + ')' : ''}`);
        else parts.push('PyTorch installed (GPU acceleration unavailable)');
      } else {
        parts.push('PyTorch not installed (heavy GPU engines unavailable)');
      }
    } catch (e) {
      return '';
    }
    return parts.join(' • ');
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
    if (paragraphPauseRange) paragraphPauseRange.addEventListener("input", updateRangeLabels);

    selectAllBtn.addEventListener("click", () => setAllChapters(true));
    selectNoneBtn.addEventListener("click", () => setAllChapters(false));
    if (toggleChaptersBtn) toggleChaptersBtn.addEventListener("click", () => setChaptersExpanded(!state.chaptersExpanded));

    generateBtn.addEventListener("click", () => startGeneration());
    cancelBtn.addEventListener("click", () => cancelGeneration());

    if (toggleOfflineModelsBtn) toggleOfflineModelsBtn.addEventListener("click", () => setOfflineModelsExpanded(!state.offlineModelsExpanded));
    if (refreshModelsBtn) refreshModelsBtn.addEventListener("click", () => loadOfflineModels());
    modelLanguageFilter.addEventListener("change", () => loadOfflineModels());
    modelGenderFilter.addEventListener("change", () => renderOfflineModels());

    [speedRange, pitchRange, styleSelect, toneProfileSelect, dialogueVoiceSelect, dialogueVoiceAltSelect, paragraphPauseRange, sentencePauseChk, pronunciationMapInput, outputFormat, bitrateSelect, combineChk, pauseRange, outputDir].forEach(el => {
      if (!el) return;
      el.addEventListener("change", () => saveSettings());
    });

    if (pronunciationPresetSelect) {
      pronunciationPresetSelect.addEventListener("change", () => {
        applyPronunciationPreset(pronunciationPresetSelect.value);
        pronunciationPresetSelect.value = "";
        saveSettings();
      });
    }
    if (pronunciationExportBtn) pronunciationExportBtn.addEventListener("click", () => exportPronunciationMap());
    if (pronunciationImportBtn && pronunciationImportFile) {
      pronunciationImportBtn.addEventListener("click", () => pronunciationImportFile.click());
      pronunciationImportFile.addEventListener("change", () => importPronunciationMapFile(pronunciationImportFile.files && pronunciationImportFile.files[0]));
    }
  }

  function updateRangeLabels() {
    speedValue.textContent = `${parseFloat(speedRange.value).toFixed(2)}×`;
    const p = parseFloat(pitchRange.value);
    pitchValue.textContent = (p > 0 ? "+" : "") + p;
    pauseValue.textContent = `${pauseRange.value} ms`;
    if (paragraphPauseRange && paragraphPauseValue) {
      paragraphPauseValue.textContent = `${paragraphPauseRange.value} ms`;
    }
  }

  function parsePronunciationMapText(text) {
    const map = {};
    const lines = String(text || "").split(/\r?\n/);
    for (const raw of lines) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;
      let idx = line.indexOf('=>');
      let sepLen = 2;
      if (idx === -1) { idx = line.indexOf('='); sepLen = 1; }
      if (idx === -1) continue;
      const from = line.slice(0, idx).trim();
      const to = line.slice(idx + sepLen).trim();
      if (from && to) map[from] = to;
    }
    return map;
  }

  function formatPronunciationMapText(map) {
    if (!map || typeof map !== 'object') return '';
    return Object.entries(map)
      .filter(([k, v]) => String(k || '').trim() && String(v || '').trim())
      .map(([k, v]) => `${String(k).trim()} = ${String(v).trim()}`)
      .join('\n');
  }

  function getBuiltInPronunciationPresets() {
    return {
      'en-tech': {
        'SQL': 'sequel',
        'GUI': 'gooey',
        'CLI': 'command line interface',
        'API': 'A P I',
        'URL': 'U R L',
        'CPU': 'C P U',
        'GPU': 'G P U',
      },
      'en-names': {
        'Dr.': 'Doctor',
        'Mr.': 'Mister',
        'Mrs.': 'Misses',
        'St.': 'Saint',
      },
      'hu-names': {
        'dr.': 'doktor',
        'Dr.': 'Doktor',
        'kb.': 'körülbelül',
        'stb.': 's a többi',
      },
    };
  }

  function applyPronunciationPreset(key) {
    if (!key) return;
    if (key === 'clear') {
      if (pronunciationMapInput) pronunciationMapInput.value = '';
      return;
    }
    const presets = getBuiltInPronunciationPresets();
    const preset = presets[key];
    if (!preset || !pronunciationMapInput) return;
    const current = parsePronunciationMapText(pronunciationMapInput.value);
    const merged = Object.assign({}, current, preset);
    pronunciationMapInput.value = formatPronunciationMapText(merged);
  }

  function exportPronunciationMap() {
    if (!pronunciationMapInput) return;
    const map = parsePronunciationMapText(pronunciationMapInput.value);
    const json = JSON.stringify(map, null, 2);
    const blob = new Blob([json], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'bookcoder-pronunciation-map.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function importPronunciationMapFile(file) {
    if (!file || !pronunciationMapInput) return;
    try {
      const text = await file.text();
      let imported = {};
      try {
        const parsed = JSON.parse(text);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          imported = parsed;
        } else {
          throw new Error('JSON must be an object map');
        }
      } catch (e) {
        // Fallback: parse as line-based "from = to" text
        imported = parsePronunciationMapText(text);
      }
      const cleaned = {};
      for (const [k, v] of Object.entries(imported || {})) {
        const ks = String(k || '').trim();
        const vs = String(v || '').trim();
        if (ks && vs) cleaned[ks] = vs;
      }
      const current = parsePronunciationMapText(pronunciationMapInput.value);
      pronunciationMapInput.value = formatPronunciationMapText(Object.assign({}, current, cleaned));
      await saveSettings();
    } catch (e) {
      showGenError(`Failed to import pronunciation map: ${e.message || e}`);
    } finally {
      if (pronunciationImportFile) pronunciationImportFile.value = '';
    }
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
      const hw = formatHardwareSummary(state.hardware);
      engineStatusBox.textContent = hw ? `No narration engine selected. ${hw}` : 'No narration engine selected.';
      return;
    }
    providerMeta.textContent = p.description || '';
    const parts = [];
    parts.push(p.available ? `Available` : `Unavailable`);
    if (p.reason) parts.push(p.reason);
    if (typeof p.downloaded_voice_count === 'number' && ['piper', 'coqui-xtts', 'mms-tts'].includes(p.id)) {
      parts.push(`${p.downloaded_voice_count} downloaded model(s)/voice(s)`);
    }
    const hw = formatHardwareSummary(state.hardware);
    if (hw) parts.push(hw);
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
    const providers = state.providers || [];
    const messages = [];
    const selected = p || providers.find(x => x.id === state.selectedProviderId);

    // Prefer context for selected offline/heavy provider if relevant
    if (selected && ['piper', 'coqui-xtts', 'mms-tts'].includes(selected.id)) {
      if (!selected.available) {
        messages.push(`${selected.name}: ${selected.reason || 'Unavailable.'}`);
      } else if (selected.id === 'piper' && (selected.downloaded_voice_count || 0) === 0) {
        messages.push('Piper runtime is installed, but no offline voices are downloaded yet. Download a Piper voice model below, then select it in the Voice menu.');
      } else if ((selected.id === 'coqui-xtts' || selected.id === 'mms-tts')) {
        const pid = selected.id;
        const downloaded = (state.offlineModels || []).filter(m => (m.provider_id || '') === pid && m.downloaded).length;
        if (downloaded === 0) {
          messages.push(`${selected.name} runtime is installed, but no models are downloaded/cached yet. Use the download option below (first download may be large).`);
        }
      }
    }

    // General unavailable runtime hints (helpful when browsing all models)
    providers.forEach(pr => {
      if (!['piper', 'coqui-xtts', 'mms-tts'].includes(pr.id)) return;
      if (!pr.available && pr.reason) {
        messages.push(`${pr.name}: ${pr.reason}`);
      }
    });

    const unique = Array.from(new Set(messages.filter(Boolean)));
    if (!unique.length) {
      offlineRuntimeNotice.classList.add('hidden');
      offlineRuntimeNotice.textContent = '';
      return;
    }
    offlineRuntimeNotice.textContent = unique.join(' ');
    offlineRuntimeNotice.className = 'alert alert-info';
    offlineRuntimeNotice.classList.remove('hidden');
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
      setSuggestedOutputDirForBook(res.book, res.file);
      setChaptersExpanded(false); // collapse by default for newly loaded books (especially long ones)
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
      updateChaptersSummary();
      setChaptersExpanded(false);
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
      setSuggestedOutputDirForBook(book, file);
    }

    renderChapters();
  }

  function setSuggestedOutputDirForBook(book, file) {
    if (!outputDir) return;
    const baseName = (book && (book.title || book.filename)) || (file && file.filename) || 'Audiobook';
    const safe = String(baseName).replace(/[^\w\s\-\.]/g, '').replace(/\s+/g, ' ').trim() || 'Audiobook';
    outputDir.value = `~/BookCoderAudiobooks/${safe}`;
  }

  function renderChapters() {
    const book = state.book;
    if (!book || !book.chapters || !book.chapters.length) {
      chaptersList.innerHTML = '';
      chaptersEmpty.classList.remove('hidden');
      updateChaptersSummary();
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
      cb.addEventListener('change', () => { ch.included = cb.checked; item.classList.toggle('excluded', !ch.included); updateChaptersSummary(); });
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
    updateChaptersSummary();
  }

  function setChaptersExpanded(expanded) {
    state.chaptersExpanded = !!expanded;
    if (chaptersBody) chaptersBody.classList.toggle('hidden', !state.chaptersExpanded);
    if (toggleChaptersBtn) {
      toggleChaptersBtn.textContent = state.chaptersExpanded ? 'Hide chapters ▴' : 'Show chapters ▾';
      toggleChaptersBtn.setAttribute('aria-expanded', state.chaptersExpanded ? 'true' : 'false');
    }
  }

  function updateChaptersSummary() {
    if (!chaptersSummary) return;
    const book = state.book;
    if (!book || !Array.isArray(book.chapters) || book.chapters.length === 0) {
      chaptersSummary.textContent = 'Upload a book to see extracted chapters. Chapters are collapsed to keep settings easy to reach.';
      return;
    }
    const total = book.chapters.length;
    const selected = book.chapters.filter(c => c && c.included).length;
    const words = book.chapters.filter(c => c && c.included).reduce((sum, c) => sum + (c.word_count || 0), 0);
    chaptersSummary.textContent = `${total} chapter${total === 1 ? '' : 's'} extracted • ${selected} selected${words ? ` • ~${words.toLocaleString()} words` : ''}. Click "Show chapters" to review, reorder, or exclude.`;
  }

  function setOfflineModelsExpanded(expanded) {
    state.offlineModelsExpanded = !!expanded;
    if (offlineModelsBody) offlineModelsBody.classList.toggle('hidden', !state.offlineModelsExpanded);
    if (toggleOfflineModelsBtn) {
      toggleOfflineModelsBtn.textContent = state.offlineModelsExpanded ? 'Hide ▴' : 'Expand ▾';
      toggleOfflineModelsBtn.setAttribute('aria-expanded', state.offlineModelsExpanded ? 'true' : 'false');
    }
  }

  function updateOfflineModelsSummary() {
    if (!offlineModelsSummary) return;
    const models = state.offlineModels || [];
    const pid = state.selectedProviderId || '';
    const pname = pid ? providerLabel(pid) : 'offline engines';

    if (pid === 'edge-tts') {
      offlineModelsSummary.textContent = 'Edge TTS is online-only and does not use offline model downloads.';
      return;
    }

    if (!models.length) {
      if (['piper', 'coqui-xtts', 'mms-tts'].includes(pid)) {
        offlineModelsSummary.textContent = `No offline models listed for ${pname}. Expand to check language filters or refresh.`;
      } else {
        offlineModelsSummary.textContent = 'Download and manage offline voice models for Piper, Coqui XTTS, and MMS-TTS. Select an offline narration engine to view its models.';
      }
      return;
    }

    const total = models.length;
    const downloaded = models.filter(m => m && m.downloaded).length;
    const downloading = models.filter(m => m && (m.downloading || m.status === 'downloading')).length;
    let text = `${total} ${pname} model${total === 1 ? '' : 's'} listed • ${downloaded} downloaded`;
    if (downloading) text += ` • ${downloading} downloading`;
    text += '. Expand to download, remove, or use models.';
    offlineModelsSummary.textContent = text;
  }

  function providerLabel(providerId) {
    if (providerId === 'piper') return 'Piper';
    if (providerId === 'coqui-xtts') return 'Coqui XTTS';
    if (providerId === 'mms-tts') return 'MMS-TTS';
    return providerId || 'Offline';
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
    await loadOfflineModels();
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
    const currentDialogueAlt = dialogueVoiceAltSelect ? dialogueVoiceAltSelect.value : '';

    voiceSelect.innerHTML = '';
    if (dialogueVoiceSelect) {
      dialogueVoiceSelect.innerHTML = '';
      const sameOpt = document.createElement('option');
      sameOpt.value = '';
      sameOpt.textContent = 'Same as narrator voice';
      dialogueVoiceSelect.appendChild(sameOpt);
    }
    if (dialogueVoiceAltSelect) {
      dialogueVoiceAltSelect.innerHTML = '';
      const sameAltOpt = document.createElement('option');
      sameAltOpt.value = '';
      sameAltOpt.textContent = 'Same as dialogue voice';
      dialogueVoiceAltSelect.appendChild(sameAltOpt);
    }

    if (!voices.length) {
      const opt = document.createElement('option');
      opt.value = '';
      if (['piper', 'coqui-xtts', 'mms-tts'].includes(state.selectedProviderId)) {
        opt.textContent = 'No offline models downloaded — expand Offline Voice Models to download';
      } else {
        opt.textContent = 'No voices available';
      }
      voiceSelect.appendChild(opt);
      if (dialogueVoiceAltSelect) {
        const altEmpty = document.createElement('option');
        altEmpty.value = '';
        altEmpty.textContent = 'No voices available';
        dialogueVoiceAltSelect.appendChild(altEmpty);
      }
      updateVoiceMeta();
      return;
    }

    const groups = { Female: [], Male: [], Other: [] };
    voices.forEach(v => {
      const g = (v.gender || '').toLowerCase().includes('female') ? 'Female'
              : (v.gender || '').toLowerCase().includes('male') ? 'Male' : 'Other';
      groups[g].push(v);
    });

    const appendGroupedOptions = (selectEl) => {
      if (!selectEl) return;
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

    appendGroupedOptions(voiceSelect);
    appendGroupedOptions(dialogueVoiceSelect);
    appendGroupedOptions(dialogueVoiceAltSelect);

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

    if (dialogueVoiceAltSelect) {
      const pendingDialogueAlt = state._pendingDialogueVoiceAltId;
      if (pendingDialogueAlt && voices.some(v => v.id === pendingDialogueAlt)) {
        dialogueVoiceAltSelect.value = pendingDialogueAlt;
        state._pendingDialogueVoiceAltId = null;
      } else if (currentDialogueAlt && voices.some(v => v.id === currentDialogueAlt)) {
        dialogueVoiceAltSelect.value = currentDialogueAlt;
      } else {
        dialogueVoiceAltSelect.value = '';
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
      const params = new URLSearchParams();
      if (filter === 'current') {
        const lang = getEffectiveLanguage();
        if (lang) params.set('language', lang);
      } else if (filter === 'en' || filter === 'hu') {
        params.set('language', filter);
      }
      if (state.selectedProviderId && ['piper', 'coqui-xtts', 'mms-tts'].includes(state.selectedProviderId)) {
        params.set('provider', state.selectedProviderId);
      } else if (state.selectedProviderId === 'edge-tts') {
        // No offline models for Edge
        state.offlineModels = [];
        modelsDirInfo.textContent = 'Edge TTS is online-only and does not use offline model downloads.';
        renderOfflineModels();
        ensureDownloadPolling();
        return;
      } else if (state.selectedProviderId) {
        params.set('provider', state.selectedProviderId);
      }
      const qs = params.toString();
      const url = qs ? `/api/offline-models?${qs}` : '/api/offline-models';
      const res = await fetchJSON(url);
      if (res.ok) {
        state.offlineModels = res.models || [];
        if (res.models_dir) {
          modelsDirInfo.textContent = res.models_dir;
          if (res.locations && typeof res.locations === 'object') {
            const extra = Object.entries(res.locations)
              .filter(([pid, path]) => pid !== 'piper' && path)
              .map(([pid, path]) => `${providerLabel(pid)}: ${path}`);
            if (extra.length) modelsDirInfo.textContent = `${res.models_dir} (Piper). ${extra.join(' | ')}`;
          }
        } else if (res.locations && res.locations.piper) {
          modelsDirInfo.textContent = res.locations.piper;
        } else {
          modelsDirInfo.textContent = res.error || '—';
        }
      } else {
        state.offlineModels = [];
        modelsDirInfo.textContent = res.error || '—';
      }
    } catch (e) {
      state.offlineModels = [];
      modelsDirInfo.textContent = '—';
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
    updateOfflineModelsSummary();
    updateOfflineRuntimeNotice((state.providers || []).find(p => p.id === state.selectedProviderId));

    if (!models.length) {
      let msg = 'No offline models match the selected filters.';
      if (state.selectedProviderId === 'edge-tts') {
        msg = 'Edge TTS uses online voices and does not require offline model downloads.';
      } else if (['piper', 'coqui-xtts', 'mms-tts'].includes(state.selectedProviderId)) {
        msg = `No ${providerLabel(state.selectedProviderId)} models match the selected filters. Try changing the language/gender filter or click Refresh.`;
      }
      offlineModelsList.innerHTML = `<div class="empty-state">${msg}</div>`;
      return;
    }
    offlineModelsList.innerHTML = '';
    models.forEach(m => {
      const providerId = m.provider_id || 'piper';
      const card = document.createElement('div');
      card.className = 'model-card' + (m.downloaded ? ' downloaded' : '');
      card.dataset.key = m.key;
      card.dataset.providerId = providerId;

      const main = document.createElement('div');
      const name = document.createElement('div');
      name.className = 'model-name';
      name.textContent = m.name || m.key;
      const tags = document.createElement('div');
      tags.className = 'model-tags';
      tags.appendChild(makeTag(providerLabel(providerId), 'tag-provider'));
      tags.appendChild(makeTag(langName(m.language), 'tag-lang'));
      tags.appendChild(makeTag(m.gender || 'Neutral', m.gender === 'Female' ? 'tag-female' : (m.gender === 'Male' ? 'tag-male' : '')));
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
        const msg = m.message || 'Downloading…';
        txt.textContent = (typeof m.progress === 'number' && m.progress > 0) ? `${msg} (${pct}%)` : msg;
        progWrap.appendChild(track);
        progWrap.appendChild(txt);
        side.appendChild(progWrap);
      } else {
        const makeIconBtn = (icon, title, extraClass, onClick) => {
          const btn = document.createElement('button');
          btn.className = `icon-btn model-icon-btn${extraClass ? ' ' + extraClass : ''}`;
          btn.type = 'button';
          btn.title = title;
          btn.setAttribute('aria-label', title);
          btn.textContent = icon;
          btn.addEventListener('click', onClick);
          return btn;
        };

        const dlBtn = makeIconBtn('⬇', m.downloaded ? 'Re-download model' : (m.partial ? 'Re-download model' : 'Download model'), 'model-icon-download', () => downloadOfflineModel(providerId, m.key));
        actions.appendChild(dlBtn);

        if (m.downloaded || m.partial) {
          const delBtn = makeIconBtn('🗑', m.downloaded ? 'Delete downloaded model' : 'Remove incomplete model files', 'model-icon-delete', () => deleteOfflineModel(providerId, m.key));
          actions.appendChild(delBtn);
        }

        if (m.downloaded) {
          const useBtn = document.createElement('button');
          useBtn.className = 'btn btn-success btn-sm';
          useBtn.type = 'button';
          useBtn.textContent = 'Use';
          useBtn.title = 'Use this voice/model for narration';
          useBtn.addEventListener('click', () => useOfflineModel(m));
          actions.appendChild(useBtn);
        }
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

  async function downloadOfflineModel(providerId, key) {
    try {
      const pid = providerId || 'piper';
      const res = await fetchJSON(`/api/offline-models/${encodeURIComponent(pid)}/${encodeURIComponent(key)}/download`, { method: 'POST' });
      if (!res.ok) throw new Error(res.error || 'Failed to start download');
      await loadOfflineModels();
      ensureDownloadPolling();
    } catch (e) {
      showGenError(e.message || String(e));
    }
  }

  async function deleteOfflineModel(providerId, key) {
    if (!confirm('Delete/remove this offline model? You can download it again later if supported.')) return;
    try {
      const pid = providerId || 'piper';
      const res = await fetchJSON(`/api/offline-models/${encodeURIComponent(pid)}/${encodeURIComponent(key)}/delete`, { method: 'POST' });
      if (!res.ok) throw new Error(res.error || 'Failed to delete model');
      await refreshProviders();
      await loadVoices(getEffectiveLanguage());
      await loadOfflineModels();
    } catch (e) {
      showGenError(e.message || String(e));
    }
  }

  async function useOfflineModel(m) {
    const providerId = m.provider_id || 'piper';
    state.selectedProviderId = providerId;
    await refreshProviders();
    if ((state.providers || []).some(p => p.id === providerId)) {
      providerSelect.value = providerId;
      state.selectedProviderId = providerId;
    }
    updateProviderMeta();
    await loadVoices(m.language || getEffectiveLanguage());
    const vid = m.voice_id || (providerId === 'piper' ? `piper:${m.key}` : '');
    if (vid && (state.voices || []).some(v => v.id === vid)) {
      voiceSelect.value = vid;
      state._pendingVoiceId = null;
    } else if (vid) {
      state._pendingVoiceId = vid;
    }
    updateVoiceMeta();
    await refreshProviderStatus();
    await saveSettings();
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
      const params = new URLSearchParams();
      if (filter === 'current') {
        const lang = getEffectiveLanguage();
        if (lang) params.set('language', lang);
      } else if (filter === 'en' || filter === 'hu') {
        params.set('language', filter);
      }
      if (state.selectedProviderId && ['piper', 'coqui-xtts', 'mms-tts'].includes(state.selectedProviderId)) {
        params.set('provider', state.selectedProviderId);
      } else if (state.selectedProviderId === 'edge-tts') {
        state.offlineModels = [];
        renderOfflineModels();
        ensureDownloadPolling();
        return;
      } else if (state.selectedProviderId) {
        params.set('provider', state.selectedProviderId);
      }
      const qs = params.toString();
      const url = qs ? `/api/offline-models?${qs}` : '/api/offline-models';
      const res = await fetchJSON(url);
      if (res.ok) {
        const prevDownloading = (state.offlineModels || []).some(m => m.downloading || m.status === 'downloading');
        state.offlineModels = res.models || [];
        const nowDownloading = (state.offlineModels || []).some(m => m.downloading || m.status === 'downloading');
        renderOfflineModels();
        if (prevDownloading && !nowDownloading) {
          // downloads finished/changed state -> refresh providers/voices
          await refreshProviders();
          if (['piper', 'coqui-xtts', 'mms-tts'].includes(state.selectedProviderId)) {
            await loadVoices(getEffectiveLanguage());
          }
          refreshProviderStatus();
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
      if (['piper', 'coqui-xtts', 'mms-tts'].includes(state.selectedProviderId)) {
        showGenError('Please download and select an offline voice model first (expand "Offline Voice Models").');
      } else {
        showGenError('Please select a narration voice.');
      }
      return;
    }

    hideGenError();
    resultBox.classList.add('hidden');
    state.cancelling = false;
    progressWrap.classList.remove('hidden');
    setProgress(0, 'Starting', 'Preparing audiobook generation…');
    generateBtn.disabled = true;
    cancelBtn.disabled = false;
    cancelBtn.textContent = 'Cancel';
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
      dialogue_voice_alt_id: dialogueVoiceAltSelect ? dialogueVoiceAltSelect.value : '',
      voice_cast_map: buildVoiceCastMap(),
      paragraph_pause_ms: paragraphPauseRange ? (parseInt(paragraphPauseRange.value, 10) || 450) : ((state.settings && typeof state.settings.paragraph_pause_ms === 'number') ? state.settings.paragraph_pause_ms : 450),
      sentence_pause_hint: sentencePauseChk ? !!sentencePauseChk.checked : ((state.settings && typeof state.settings.sentence_pause_hint === 'boolean') ? state.settings.sentence_pause_hint : true),
      pronunciation_map: pronunciationMapInput ? parsePronunciationMapText(pronunciationMapInput.value) : ((state.settings && state.settings.pronunciation_map) || {}),
      output_dir: outputDir.value,
      output_format: (outputFormat && outputFormat.value) ? outputFormat.value : 'mp3',
      bitrate_kbps: parseInt(bitrateSelect.value, 10) || 128,
      combine: !!combineChk.checked,
      chapter_pause_ms: parseInt(pauseRange.value, 10) || 1200,
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
      if (data.status === 'cancelling') {
        state.cancelling = true;
        setProgress(null, 'Cancelling', 'Cancelling… waiting for the current step to finish.');
      } else if (data.status && data.status !== 'running') {
        if (data.status === 'done') handleJobEvent({ type: 'done', result: data.result });
        else if (data.status === 'error') handleJobEvent({ type: 'error', message: data.error || 'Error' });
        else if (data.status === 'cancelled') handleJobEvent({ type: 'cancelled' });
      }
      return;
    }
    if (data.type === 'progress') {
      const pct = Math.max(0, Math.min(100, Math.round((data.fraction || 0) * 100)));
      if (state.cancelling) {
        const msg = data.message ? `Cancelling… ${data.message}` : 'Cancelling… waiting for the current step to finish.';
        setProgress(pct, 'Cancelling', msg);
      } else {
        const stageLabel = stageName(data.stage);
        setProgress(pct, stageLabel, data.message || '');
      }
      return;
    }
    if (data.type === 'done') {
      state.cancelling = false;
      setProgress(100, 'Complete', data.message || 'Audiobook generation complete.');
      showResult(data.result);
      closeProgressStream();
      resetGenerationUI();
      return;
    }
    if (data.type === 'error') {
      state.cancelling = false;
      showGenError(data.message || 'An error occurred during generation.');
      closeProgressStream();
      resetGenerationUI();
      return;
    }
    if (data.type === 'cancelled') {
      state.cancelling = false;
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
    cancelBtn.disabled = false;
    cancelBtn.textContent = 'Cancel';
    cancelBtn.classList.add('hidden');
    state.cancelling = false;
    state.jobId = null;
  }

  function closeProgressStream() {
    if (state.eventSource) { try { state.eventSource.close(); } catch(e){} state.eventSource = null; }
  }

  async function cancelGeneration() {
    if (!state.jobId) return;
    state.cancelling = true;
    cancelBtn.disabled = true;
    setProgress(null, 'Cancelling', 'Cancelling… waiting for the current step to finish.');
    try {
      await fetchJSON(`/api/jobs/${encodeURIComponent(state.jobId)}/cancel`, { method: 'POST' });
    } catch (e) {
      // keep UI in cancelling state; job may still stop if signal was received earlier
      setProgress(null, 'Cancelling', 'Cancel requested. Waiting for the current step to finish…');
    } finally {
      // keep button disabled while cancelling to avoid repeated requests
      cancelBtn.disabled = true;
    }
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

  function buildVoiceCastMap() {
    const narrator = voiceSelect ? voiceSelect.value : '';
    const dialogue = dialogueVoiceSelect ? dialogueVoiceSelect.value : '';
    const dialogueAlt = dialogueVoiceAltSelect ? dialogueVoiceAltSelect.value : '';
    const map = {};
    if (narrator) map.narrator = narrator;
    if (dialogue) map.dialogue = dialogue;
    if (dialogueAlt) map.dialogue_alt = dialogueAlt;
    // also keep legacy-friendly alias if both are set
    return map;
  }

  async function saveSettings() {
    try {
      const paragraphPauseMs = paragraphPauseRange ? (parseInt(paragraphPauseRange.value, 10) || 450) : ((state.settings && typeof state.settings.paragraph_pause_ms === 'number') ? state.settings.paragraph_pause_ms : 450);
      const sentencePauseHint = sentencePauseChk ? !!sentencePauseChk.checked : ((state.settings && typeof state.settings.sentence_pause_hint === 'boolean') ? state.settings.sentence_pause_hint : true);
      const pronunciationMap = pronunciationMapInput ? parsePronunciationMapText(pronunciationMapInput.value) : ((state.settings && state.settings.pronunciation_map) || {});
      const voiceCastMap = buildVoiceCastMap();
      const settings = {
        provider_id: state.selectedProviderId,
        language: getEffectiveLanguage(),
        voice_id: voiceSelect.value,
        speed: parseFloat(speedRange.value),
        pitch: parseFloat(pitchRange.value),
        style: styleSelect.value,
        tone_profile: toneProfileSelect ? toneProfileSelect.value : 'natural',
        dialogue_voice_id: dialogueVoiceSelect ? dialogueVoiceSelect.value : '',
        dialogue_voice_alt_id: dialogueVoiceAltSelect ? dialogueVoiceAltSelect.value : '',
        voice_cast_map: voiceCastMap,
        paragraph_pause_ms: paragraphPauseMs,
        sentence_pause_hint: sentencePauseHint,
        pronunciation_map: pronunciationMap,
        output_format: (outputFormat && outputFormat.value) ? outputFormat.value : 'mp3',
        output_bitrate_kbps: parseInt(bitrateSelect.value, 10) || 128,
        combine_into_single_file: !!combineChk.checked,
        chapter_pause_ms: parseInt(pauseRange.value, 10) || 1200,
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
    if (typeof s.paragraph_pause_ms === 'number' && paragraphPauseRange) paragraphPauseRange.value = s.paragraph_pause_ms;
    if (typeof s.sentence_pause_hint === 'boolean' && sentencePauseChk) sentencePauseChk.checked = s.sentence_pause_hint;
    if (s.pronunciation_map && pronunciationMapInput) pronunciationMapInput.value = formatPronunciationMapText(s.pronunciation_map);
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
    if (typeof s.dialogue_voice_alt_id === 'string') state._pendingDialogueVoiceAltId = s.dialogue_voice_alt_id;
    if (s.voice_cast_map && typeof s.voice_cast_map === 'object') {
      if (!state._pendingDialogueVoiceId && s.voice_cast_map.dialogue) state._pendingDialogueVoiceId = s.voice_cast_map.dialogue;
      if (!state._pendingDialogueVoiceAltId && s.voice_cast_map.dialogue_alt) state._pendingDialogueVoiceAltId = s.voice_cast_map.dialogue_alt;
    }
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
