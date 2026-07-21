

  /* ─────────────────────────────────────────────────────────────
     6. EVENT DELEGATION
  ───────────────────────────────────────────────────────────── */
  /* Per-render: these nodes are rebuilt by innerHTML, so they need fresh handlers. */
  function bindEvents() {
    bindDelegates();

    /* Close button */
    var closeBtn = windowEl.querySelector('#db-close-btn-el');
    if (closeBtn) closeBtn.addEventListener('click', function(){ state.open = false; render(); });

    /* Input field */
    var inputEl = windowEl.querySelector('#db-input-el');
    if (inputEl) {
      inputEl.addEventListener('focus', function(){ state.inputFocused = true; updateInputBorder(); });
      inputEl.addEventListener('blur', function(){ state.inputFocused = false; updateInputBorder(); });
      inputEl.addEventListener('input', function(){ state.input = inputEl.value; updateSendBtn(); });
      inputEl.addEventListener('keydown', function(ev){ if(ev.key==='Enter') onSendText(); });
    }
    /* Send btn */
    var sendBtn = windowEl.querySelector('#db-send-btn-el');
    if (sendBtn) sendBtn.addEventListener('click', onSendText);
  }

  /* One-time: delegated handlers live on windowEl, which survives every render.
     Re-registering them per render would stack duplicate handlers on each click. */
  var delegatesBound = false;
  function bindDelegates() {
    if (delegatesBound) return;

    /* Escape dismisses the topmost overlay, innermost first. */
    windowEl.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Escape') return;
      if (state.picker) { state.picker = null; state.pickerToken++; render(); }
      else if (state.details) { state.details = null; render(); }
      else if (state.endScreen) { state.endScreen = null; render(); }
      else return;
      ev.stopPropagation();
    });
    delegatesBound = true;

    /* Clear context */
    delegate('[data-action="clearContext"]', function(){ clearContext(); });

    /* Chip clicks */
    delegate('[data-action="chip"]', function(el){
      if (state.busy) return;
      var idx = parseInt(el.getAttribute('data-idx'));
      if (idx===-1) { expandMore(); return; }
      var ch = state.chips[idx];
      if (ch) onChip(ch);
    });

    /* View details */
    delegate('[data-action="viewDetails"]', function(el){
      var title = el.getAttribute('data-key');
      var mid = el.getAttribute('data-mid');
      var msg = state.msgs.find(function(m){return m.id===mid;});
      if (msg && msg.cards) {
        var card = msg.cards.find(function(c){ return (c.entityId || c.title) === title; });
        if (card) openDetails(card);
      }
    });

    /* Toggle compare */
    delegate('[data-action="toggleCompare"]', function(el){
      var title = el.getAttribute('data-key');
      var card = null;
      state.msgs.forEach(function(m){ if(m.cards) m.cards.forEach(function(c){ if((c.entityId || c.title)===title) card=c; }); });
      if (card) toggleCompare(card);
    });

    /* Lead submit */
    delegate('[data-action="submitLead"]', function(el){
      submitLead(el.getAttribute('data-mid'));
    });
    delegate('[data-action="leadPhoneInput"]', function(el){
      state.leadPhone = el.value;
    }, 'input');

    /* Syllabus accordion */
    delegate('[data-action="toggleAcc"]', function(el){
      toggleAcc(el.getAttribute('data-mid'), parseInt(el.getAttribute('data-idx')));
    });

    /* Run compare bar */
    delegate('[data-action="runCompare"]', function(){ runGuidedComparison(state.lastChip || { label: 'Compare' }); });

    /* Picker */
    delegate('[data-action="closePicker"]', function(){
      var chip = state.picker && state.picker.chip;
      state.picker = null;
      state.pickerToken++;
      render();
      /* Defense in depth: whatever path opened this picker should already
         have real chips waiting underneath. If it somehow didn't, never
         leave the user stuck with nothing to tap. */
      if (!state.chips.length) loadFollowups(null, chip).catch(function () {});
    });
    delegate('[data-action="pickerInput"]', function(el){
      var value = el.value;
      state.picker = Object.assign({},state.picker,{query:value});
      renderPickerList();
      /* Debounce the catalog query so typing doesn't fan out one call per key. */
      clearTimeout(pickerDebounce);
      pickerDebounce = setTimeout(function(){ refreshPicker(value.trim()); }, 220);
    }, 'input');
    delegate('[data-action="pickItem"]', function(el){
      /* Rows are keyed by catalog id, never display name — many programmes
         share a name ("MBA") across universities. */
      var key = el.getAttribute('data-key');
      var row = pickerRows().find(function(r){ return (r.id || r.name) === key; });
      /* A row already shown in "✓ Selected" isn't in the catalog rows (it
         may be the current page's own entity, never fetched as a list row),
         so fall back to the compare list itself to resolve the tap. */
      if (!row && state.picker && state.picker.compareMode) {
        row = state.compare
          .map(function (c) { return { id: c.entityId, name: c.title, mono: c.mono, bg: c.bg }; })
          .find(function (r) { return (r.id || r.name) === key; });
      }
      if (!row) return;
      if (state.picker && state.picker.compareMode) pickCompareItem(row);
      else pickItem(row);
    });


    /* Tool */
    delegate('[data-action="closeTool"]', function(){ closeTool('user_closed'); });
    delegate('[data-action="toolBegin"]', function(){
      if (!state.tool) return;
      state.tool = Object.assign({}, state.tool, { phase: 'step', begun: true });
      render(); scrollToBottom();
    });
    delegate('[data-action="toolAnswer"]', function(el){ toolAnswer(el.getAttribute('data-opt'), parseInt(el.getAttribute('data-oi'))); });
    delegate('[data-action="toolReveal"]', function(){ toolReveal(); });
    delegate('[data-action="toolName"]', function(el){ state.toolName = el.value; }, 'input');
    delegate('[data-action="toolPhone"]', function(el){ state.toolPhone = el.value; }, 'input');
    delegate('[data-action="toolSubmit"]', function(){ toolSubmit(); });
    delegate('[data-action="toolSkip"]', function(){ toolSkip(); });

    /* Details */
    delegate('[data-action="closeDetails"]', function(){ state.details = null; render(); });
    delegate('[data-action="detailsCtaFees"]', function(){
      var d = state.details;
      state.details = null;
      /* The grounded fees card only describes the entity the session is
         focused on. A details card from anywhere else routes through chat,
         where the backend resolves the entity from the name. */
      if (d && d.entityId && d.entityId === ctxEntityId()) {
        showInfoCard('get_fees', { label: '💰 Fees & EMI', handler: 'get_fees' });
      } else if (d) {
        send('What are the fees for ' + (d.queryName || d.title) + '?', { label: '💰 Fees & EMI' });
      } else {
        render();
      }
    });

    /* End screen */
    delegate('[data-action="closeEnd"]', function(){ state.endScreen = null; render(); });
    delegate('[data-action="endPrograms"]', function(){ onEndPrograms(); });
  }

  function delegate(selector, handler, eventType) {
    var evt = eventType || 'click';
    windowEl.addEventListener(evt, function(ev) {
      var el = ev.target.closest(selector);
      if (el) handler(el, ev);
    }, true);
  }

  function updateInputBorder() {
    var wrap = windowEl && windowEl.querySelector('.db-input-wrapper');
    if (!wrap) return;
    if (state.inputFocused) { wrap.classList.add('focused'); wrap.style.borderColor = '#0E1F3D'; }
    else { wrap.classList.remove('focused'); wrap.style.borderColor = '#E5E7EB'; }
  }
  function updateSendBtn() {
    var btn2 = windowEl && windowEl.querySelector('#db-send-btn-el');
    if (!btn2) return;
    if ((state.input||'').trim().length > 0) { btn2.classList.add('active'); }
    else { btn2.classList.remove('active'); }
  }
  function renderPickerList() {
    /* lightweight re-render of just the list (avoids full re-render on each keypress) */
    if (!state.picker || !windowEl) return;
    var listEl = windowEl.querySelector('.db-picker-list');
    if (listEl) listEl.innerHTML = pickerListHtml();
  }

  /* ─────────────────────────────────────────────────────────────
     7. DOM MOUNT  (Shadow DOM for style isolation)
  ───────────────────────────────────────────────────────────── */
  function mount() {
    /* Host element */
    var host = document.createElement('div');
    host.id = 'db-widget-host';
    host.style.cssText = 'position:fixed;z-index:2147483647;inset:auto;pointer-events:none;';
    document.body.appendChild(host);

    /* Shadow root */
    shadow = host.attachShadow({ mode: 'open' });

    /* Inject font link into shadow */
    var fontLink = document.createElement('link');
    fontLink.rel = 'stylesheet';
    fontLink.href = 'https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap';
    shadow.appendChild(fontLink);

    /* Inject widget CSS */
    var styleLink = document.createElement('link');
    styleLink.rel = 'stylesheet';
    /* Use inline CSS if widget.css URL not available, or resolve relative to this script */
    var scriptSrc = (document.currentScript || bootScript || {}).src || '';
    var base = scriptSrc ? scriptSrc.replace(/\/[^/]+$/, '/') : '';
    styleLink.href = base + 'widget.css';
    shadow.appendChild(styleLink);

    /* Inline CSS fallback — critical styles to avoid FOUC */
    var criticalStyle = document.createElement('style');
    criticalStyle.textContent = CRITICAL_CSS;
    shadow.appendChild(criticalStyle);

    /* Widget root */
    root = document.createElement('div');
    root.id = 'db-widget-root';
    shadow.appendChild(root);

    /* Launcher button */
    launcher = document.createElement('button');
    launcher.id = 'db-launcher';
    launcher.setAttribute('aria-label', 'Open chat');
    launcher.style.pointerEvents = 'auto';
    launcher.innerHTML = SVG.chat;
    launcher.addEventListener('click', function() {
      state.open = !state.open;
      launcher.setAttribute('aria-label', state.open ? 'Close chat' : 'Open chat');
      if (state.open && !state.started) {
        resetChat();
        return; // resetChat calls render()
      }
      if (!state.open) {
        windowEl.classList.add('db-closing');
        setTimeout(function(){ windowEl.classList.remove('db-closing'); render(); }, 200);
        return;
      }
      render();
    });
    root.appendChild(launcher);

    /* Chat window */
    windowEl = document.createElement('div');
    windowEl.id = 'db-window';
    windowEl.style.display = 'none';
    windowEl.style.pointerEvents = 'auto';
    root.appendChild(windowEl);

    /* Apply position */
    if (cfg.position === 'left') {
      launcher.style.right = 'auto';
      launcher.style.left = '24px';
      windowEl.style.right = 'auto';
      windowEl.style.left = '24px';
    }
  }

  /* Critical inline CSS (subset) to avoid FOUC before widget.css loads */
  var CRITICAL_CSS = [
    '#db-launcher{position:fixed;right:24px;bottom:24px;width:60px;height:60px;border-radius:50%;border:none;background:#E84010;cursor:pointer;display:flex;align-items:center;justify-content:center;z-index:2147483640;box-shadow:0 8px 22px rgba(232,64,16,.4);}',
    '#db-window{position:fixed;right:24px;bottom:96px;width:382px;border-radius:20px;overflow:hidden;display:flex;flex-direction:column;background:#F7F8FA;box-shadow:0 24px 64px rgba(0,0,0,.18),0 0 0 1px rgba(0,0,0,.06);z-index:2147483639;}',
    '@media(max-width:480px){#db-window{right:0;bottom:0;width:100%;height:100dvh;border-radius:0;}#db-launcher{right:16px;bottom:16px;}}'
  ].join('');
