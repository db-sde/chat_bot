  /* ─────────────────────────────────────────────────────────────
     3B. BACKEND — FastAPI transport + payload mapping
     Every call degrades to the static data above when the backend
     is unreachable, so the rendered layout never changes shape.
  ───────────────────────────────────────────────────────────── */

  /* ── Deterministic avatar fallbacks (initials + palette) ── */
  var MONO_PALETTE = ['#0E1F3D','#7A1E1E','#1E4620','#5A3B00','#3A2560','#0B3B4A','#5A1030','#153E2E','#334155'];
  function initialsFor(name) {
    var words = String(name || '').replace(/[^A-Za-z0-9 ]/g, ' ').trim().split(/\s+/).filter(Boolean);
    if (!words.length) return '??';
    if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  function colorFor(name) {
    var s = String(name || ''), h = 0;
    for (var i = 0; i < s.length; i++) { h = (h * 31 + s.charCodeAt(i)) >>> 0; }
    return MONO_PALETTE[h % MONO_PALETTE.length];
  }

  /* ── Transport ── */
  var CHAT_PAGE_TYPES = ['pillar', 'university', 'course', 'specialization'];
  function apiUrl(path) { return cfg.apiBase.replace(/\/$/, '') + path; }

  function safeHttpUrl(value) {
    if (!value) return '';
    try {
      var resolved = new URL(String(value), cfg.apiBase || window.location.href);
      return (resolved.protocol === 'http:' || resolved.protocol === 'https:') ? resolved.href : '';
    } catch (err) { return ''; }
  }

  function fetchJson(path, options) {
    var opts = options || {};
    return fetch(apiUrl(path), Object.assign({
      mode: 'cors',
      headers: Object.assign({ Accept: 'application/json' }, opts.headers || {})
    }, opts)).then(function (res) {
      if (!res.ok) { var e = new Error('Request failed (' + res.status + ')'); e.status = res.status; throw e; }
      return res.json();
    });
  }

  function postJson(path, body) {
    return fetchJson(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
  }

  /* GET /api/widget/config/{site_key} */
  function loadConfig() {
    return fetchJson('/api/widget/config/' + encodeURIComponent(cfg.siteKey)).then(function (payload) {
      var branding = (payload && payload.branding) || {};
      var behavior = (payload && payload.behavior) || {};
      if (branding.bot_name) cfg.botName = branding.bot_name;
      if (/^#[0-9a-f]{6}$/i.test(branding.primary_color || '')) cfg.primaryColor = branding.primary_color;
      if (branding.welcome_message) cfg.welcomeMessage = branding.welcome_message;
      cfg.avatarUrl = safeHttpUrl(branding.avatar_url);
      cfg.showTypingIndicator = behavior.show_typing_indicator !== false;
      /* data-auto-open is an explicit per-page opt-in and outranks the tenant default. */
      if (!cfg.autoOpenPinned) cfg.autoOpen = behavior.auto_open === true;
      applyTheme(cfg.primaryColor);
      return payload;
    });
  }

  /* Re-point the CSS accent without editing widget.css or its class names. */
  function applyTheme(color) {
    if (!shadow || !color || color.toUpperCase() === '#E84010') return;
    var el = shadow.getElementById('db-theme');
    if (!el) {
      el = document.createElement('style');
      el.id = 'db-theme';
      shadow.appendChild(el);
    }
    var bg = ['#db-launcher', '.db-avatar', '.db-context-dot', '.db-lead-send', '.db-bar-fill',
      '.db-sub-dot', '.db-cta-primary', '.db-progress-fill', '.db-tool-start', '.db-tool-submit',
      '.db-end-brand-badge', '.db-send-btn.active'];
    var fg = ['.db-btn-compare.db-in-compare', '.db-verdict-label', '.db-rating-stars',
      '.db-tool-icon-badge', '.db-finder-skip'];
    el.textContent =
      bg.join(',') + '{background:' + color + ';}' +
      fg.join(',') + '{color:' + color + ';}' +
      '.db-tool-opt.selected{border-color:' + color + ';}' +
      '#db-launcher{box-shadow:0 8px 22px ' + color + '66;}';
  }

  /* POST /chat — SSE. Emits "token" (streaming text) then "response" (full payload). */
  function requestChat(body, signal) {
    return fetch(apiUrl('/chat'), {
      method: 'POST',
      mode: 'cors',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal: signal
    }).then(function (res) {
      if (!res.ok) throw new Error('Chat request failed (' + res.status + ')');
      return res;
    });
  }

  function consumeSse(response, onEvent) {
    if (!response.body) throw new Error('Streaming response is unavailable');
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = '';
    function pump() {
      return reader.read().then(function (chunk) {
        buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done });
        buffer = buffer.replace(/\r\n/g, '\n');
        var boundary = buffer.indexOf('\n\n');
        while (boundary >= 0) {
          var block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          var evt = 'message', dataLines = [];
          block.split('\n').forEach(function (line) {
            if (line.indexOf('event:') === 0) evt = line.slice(6).trim();
            if (line.indexOf('data:') === 0) dataLines.push(line.slice(5).replace(/^ /, ''));
          });
          if (dataLines.length) {
            try { onEvent(evt, JSON.parse(dataLines.join('\n'))); }
            catch (err) { console.warn('DegreeBaba widget ignored malformed SSE data', err); }
          }
          boundary = buffer.indexOf('\n\n');
        }
        if (chunk.done) return;
        return pump();
      });
    }
    return pump();
  }

  /* Business context: the server's resolved value wins; the embed attributes
     are only a seed for the very first resolution. */
  function ctxPageType() { return state.server.pageType || cfg.page || 'homepage'; }
  function ctxEntityId() { return state.server.entityId || cfg.entitySlug || null; }
  function ctxUniversityId() { return state.server.universityId || cfg.universitySlug || null; }

  /* GET /api/widget/guide/context — grounded page bundle (entity + info + related) */
  function loadGuideContext(pageType, overrides) {
    var o = overrides || {};
    var page = pageType || o.pageType || ctxPageType();
    var entity = ('entityId' in o) ? o.entityId : ctxEntityId();
    var university = ('universityId' in o) ? o.universityId : ctxUniversityId();
    var params = new URLSearchParams();
    params.set('page_type', page);
    if (state.sessionId) params.set('session_id', state.sessionId);
    if (entity) params.set('entity_id', entity);
    if (university) params.set('university', university);
    return fetchJson('/api/widget/guide/context?' + params.toString()).then(function (bundle) {
      state.guideBundle = bundle;
      if (bundle && bundle.session_id) state.sessionId = bundle.session_id;
      return bundle;
    }).catch(function (err) {
      /* An entity-typed page with no resolvable entity 404s. That is a missing
         page context, not a dead backend — retry unscoped before giving up. */
      if (err && err.status === 404 && page !== 'homepage') {
        return loadGuideContext('homepage', { entityId: null, universityId: null });
      }
      throw err;
    });
  }

  /* GET /api/widget/guide/catalog/{kind}?q=&university=&course= */
  var CATALOG_KINDS = { uni: 'universities', spec: 'specializations', course: 'courses', program: 'programs' };
  function loadGuideCatalog(kind, filters) {
    var f = filters || {};
    /* "programs" is the catalog-wide category rollup. Once a university is in
       context the caller wants that university's actual courses. */
    var requestKind = (kind === 'program' && f.university) ? 'courses' : (CATALOG_KINDS[kind] || kind);
    var query = new URLSearchParams();
    ['q', 'university', 'course'].forEach(function (key) { if (f[key]) query.set(key, f[key]); });
    var suffix = query.toString() ? '?' + query.toString() : '';
    var cacheKey = requestKind + suffix;
    if (state.pickerCache[cacheKey]) return Promise.resolve(state.pickerCache[cacheKey]);
    return fetchJson('/api/widget/guide/catalog/' + encodeURIComponent(requestKind) + suffix)
      .then(function (payload) {
        var raw = Array.isArray(payload) ? payload : (payload.items || []);
        var rows = raw.map(function (item) { return normalizeCatalogRow(item, requestKind); })
          .filter(function (r) { return r.name; });
        state.pickerCache[cacheKey] = rows;
        return rows;
      });
  }

  function normalizeCatalogRow(item, kind) {
    if (typeof item === 'string') {
      return { mono: initialsFor(item), bg: colorFor(item), name: item, short: item, meta: '', pop: false, id: item };
    }
    var name = item.name || item.label || item.university_name || item.specialization_name || item.title || '';
    var meta = [
      item.meta,
      item.naac_grade && ('NAAC ' + item.naac_grade),
      item.ugc_status,
      (item.program_count || item.program_count === 0) && (item.program_count + ' program' + (item.program_count === 1 ? '' : 's')),
      item.provider_count && (item.provider_count + ' provider' + (item.provider_count === 1 ? '' : 's')),
      item.university_name,
      item.category,
      item.fee,
      item.duration
    ].filter(Boolean).join(' · ');
    return {
      mono: initialsFor(name),
      bg: colorFor(name),
      name: String(name),
      short: String(item.short_name || item.category || name),
      meta: meta,
      pop: item.popular === true || item.is_popular === true,
      id: item.id || item.entity_id || item.slug || name,
      kind: kind,
      pageType: item.page_type || null,
      /* program_option rows are catalog categories, not resolvable entities. */
      isCategory: item.type === 'program_option',
      raw: item
    };
  }

  /* POST /api/widget/lead */
  function postLead(phone, name, source, chip) {
    var c = chip || {};
    return postJson('/api/widget/lead', Object.assign({
      phone: String(phone || '').replace(/\s+/g, ''),
      source: source || 'widget'
    }, state.sessionId ? { session_id: state.sessionId } : {},
      (name && String(name).trim().length >= 2) ? { name: String(name).trim() } : {},
      c.chip_id ? { chip_id: c.chip_id } : {},
      c.chip_surface ? { chip_surface: c.chip_surface } : {},
      c.chip_config_version ? { chip_config_version: c.chip_config_version } : {},
      c.chip_correlation_id ? { chip_correlation_id: c.chip_correlation_id } : {}
    )).then(function (res) {
      if (res && res.session_id) state.sessionId = res.session_id;
      return res;
    });
  }


  /* POST /api/widget/guide/chips — config-owned follow-up chips */
  /* The session stores the catalog-resolved id and page type. Echoing the raw
     slug back makes the backend flag the guided context as stale (409). */
  function resolvedContext() {
    return { pageType: ctxPageType(), entityId: ctxEntityId() };
  }

  function postGuideChips(answerState, completedChipId, cardType) {
    var resolved = resolvedContext();
    /* Surface, config version and correlation id let the backend detect a
       stale surface and attribute the interaction. */
    return postJson('/api/widget/guide/chips', Object.assign({
      page_type: resolved.pageType
    }, state.sessionId ? { session_id: state.sessionId } : {},
      resolved.entityId ? { entity_id: resolved.entityId } : {},
      answerState ? { answer_state: answerState } : {},
      completedChipId ? { completed_chip_id: completedChipId } : {},
      cardType ? { card_type: cardType } : {},
      state.server.surface ? { surface: state.server.surface } : {},
      state.server.configVersion ? { config_version: state.server.configVersion } : {},
      state.server.correlationId ? { correlation_id: state.server.correlationId } : {}
    ));
  }

  /* POST /api/widget/analytics — fire-and-forget funnel telemetry. */
  function analyticsEntity() {
    var bundle = state.guideBundle || {};
    var ctx = bundle.context || {};
    var entity = bundle.entity || {};
    var type = ctx.page_type || ctxPageType();
    return { type: type, id: String(entity.id || ctx.entity_id || (type === 'homepage' ? 'homepage' : 'unknown')) };
  }

  function emitAnalytics(event, chip, extra) {
    if (!cfg.apiBase) return;
    var item = chip || {};
    var more = extra || {};
    var payload = Object.assign({
      event: event,
      surface: String(item.chip_surface || more.surface || state.server.surface || 'page:home'),
      funnel_stage: String(item.funnel_stage || more.funnel_stage || state.server.funnelStage || 'top'),
      interaction_count: Number.isFinite(Number(item.interaction_count))
        ? Number(item.interaction_count)
        : (state.server.interactionCount || 0),
      entity: more.entity || analyticsEntity(),
      config_version: String(item.chip_config_version || state.server.configVersion || 'unknown'),
      content_version: String(item.content_version || more.content_version || state.server.contentVersion || 'not_applicable')
    }, state.sessionId ? { session_id: state.sessionId } : {},
      (item.chip_correlation_id || state.server.correlationId) ? { correlation_id: String(item.chip_correlation_id || state.server.correlationId) } : {},
      item.chip_id ? { chip_id: String(item.chip_id) } : {},
      item.handler ? { chip_handler: String(item.handler) } : {},
      item.lead_tags ? { lead_tags: item.lead_tags } : {},
      Array.isArray(more.chips) ? { chips: more.chips } : {});
    void fetch(apiUrl('/api/widget/analytics'), {
      method: 'POST', mode: 'cors', keepalive: true,
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(payload)
    }).catch(function (err) { console.debug('DegreeBaba analytics unavailable', err); });
  }

  /* One impression event per newly visible chip set. */
  function emitChipShown(chips) {
    var visible = (chips || []).filter(function (c) { return c && c.chip_id && !state.viewedActions.has(c.chip_id); });
    if (!visible.length) return;
    visible.forEach(function (c) { state.viewedActions.add(c.chip_id); });
    emitAnalytics('chip_shown', visible[0], {
      chips: visible.map(function (c) { return { chip_id: String(c.chip_id), chip_handler: String(c.handler || '') }; })
    });
  }

  /* Load the page bundle once per focus change. */
  function ensureGuideBundle() {
    if (state.guideBundle) return Promise.resolve(state.guideBundle);
    if (state.guideBusy) return state.guideBusy;
    state.guideBusy = loadGuideContext().then(function (bundle) {
      state.guideBusy = null;
      return bundle;
    }).catch(function (err) { state.guideBusy = null; throw err; });
    return state.guideBusy;
  }

  /* The single writer of backend-owned context. Every backend response that
     carries navigation/attribution metadata funnels through here, so the
     widget can never drift from the session the backend is tracking. */
  function adoptServerContext(source) {
    var src = source || {};
    var ctx = src.context || {};
    var meta = src.opening || src.followup || {};
    var nav = src.navigation || {};
    var srv = state.server;

    var previousEntity = srv.entityId;
    if (ctx.page_type) srv.pageType = ctx.page_type;
    if ('entity_id' in ctx) srv.entityId = ctx.entity_id || null;
    if (src.entity && src.entity.id) srv.entityId = src.entity.id;
    if (nav.page_type) srv.pageType = nav.page_type;
    if ('entity_id' in nav && nav.entity_id) srv.entityId = nav.entity_id;

    if (meta.surface) srv.surface = meta.surface;
    if (nav.surface) srv.surface = nav.surface;
    if (meta.config_version) srv.configVersion = meta.config_version;
    if (nav.config_version) srv.configVersion = nav.config_version;
    if (meta.content_version) srv.contentVersion = meta.content_version;
    if (meta.correlation_id) srv.correlationId = meta.correlation_id;
    if (meta.funnel_stage) srv.funnelStage = meta.funnel_stage;
    if (nav.funnel_stage) srv.funnelStage = nav.funnel_stage;
    if (typeof meta.interaction_count === 'number') srv.interactionCount = meta.interaction_count;
    if (typeof nav.interaction_count === 'number') srv.interactionCount = nav.interaction_count;

    /* A different entity invalidates everything scoped to the old one. */
    if (srv.entityId !== previousEntity) {
      state.pickerCache = {};
      state.guideBundle = null;
    }
  }

  function applyBundleContext(bundle) {
    adoptServerContext(bundle);
    /* The parent university is only knowable from a resolved bundle. */
    var related = (bundle && bundle.related) || {};
    var ctx = (bundle && bundle.context) || {};
    var parent = (related.universities || [])[0];
    if (ctx.page_type === 'university' && ctx.entity_id) state.server.universityId = ctx.entity_id;
    else if (parent && parent.id) state.server.universityId = parent.id;

    var label = ctx.label || [ctx.university, ctx.course, ctx.specialization].filter(Boolean).join(' · ');
    state.context = label ? { label: label, entityId: ctx.entity_id || null } : null;
  }

  /* ── Payload → UI mapping ─────────────────────────────────── */

  function cardFrom(component) {
    var name = component.name || '';
    var pills = [];
    if (component.fee) pills.push(money(component.fee));
    else if (component.starting_fee) {
      var cleaned = money(component.starting_fee);
      pills.push(cleaned.indexOf('₹') === 0 ? 'From ' + cleaned : cleaned);
    }
    if (component.duration) pills.push(String(component.duration));
    if (component.specialization_count || component.specialization_count === 0) {
      pills.push(component.specialization_count + ' spec' + (component.specialization_count === 1 ? '' : 's'));
    } else if (component.program_count || component.program_count === 0) {
      pills.push(component.program_count + ' program' + (component.program_count === 1 ? '' : 's'));
    } else if (component.mode || component.learning_mode) {
      pills.push(String(component.mode || component.learning_mode));
    }
    (component.highlights || []).forEach(function (h) {
      if (pills.length < 3 && h && h.value) pills.push(String(h.value));
    });
    /* "MBA" alone is ambiguous across publishers — lead the trust line with
       the university the backend published for this card. */
    var trust = [
      component.university_name,
      component.ugc_status,
      component.naac_grade && ('NAAC ' + component.naac_grade)
    ].filter(Boolean).join(' · ');
    var career = component.career_outcome || (component.career_outcomes || [])[0];
    var markSource = component.university_name || name;
    return {
      mono: initialsFor(markSource),
      bg: colorFor(markSource),
      title: String(name),
      trust: trust || (component.category || component.summary || 'Published programme'),
      pills: pills.length ? pills : ['Details published'],
      /* Published EMI copy often already reads "From ₹…" — don't double the prefix. */
      emi: component.emi ? (/^\s*(emi|from)\b/i.test(component.emi) ? money(component.emi) : 'EMI from ' + money(component.emi)) : '',
      job: career ? ('💼 ' + career + (component.average_salary ? ' · ' + money(component.average_salary) : '')) : '',
      entityId: component.id || component.slug || null,
      component: component
    };
  }

  function compareFrom(component) {
    var items = component.items || [];
    var a = items[0] || { facts: [] }, b = items[1] || { facts: [] };
    var keys = [], seen = {};
    (a.facts || []).concat(b.facts || []).forEach(function (f) {
      if (f && f.label && !seen[f.label]) { seen[f.label] = true; keys.push(f.label); }
    });
    var pick = function (item, label) {
      var hit = (item.facts || []).find(function (f) { return f.label === label; });
      return hit ? String(hit.value) : '—';
    };
    /* Programme names collide across publishers ("MBA" vs "MBA"); the backend
       subtitle carries the university that makes each column identifiable. */
    var columnName = function (item, fallback) {
      return item.subtitle || item.name || fallback;
    };
    return {
      kind: 'compare',
      aName: columnName(a, 'Option A'),
      bName: columnName(b, 'Option B'),
      rows: keys.map(function (k) { return { k: k, a: pick(a, k), b: pick(b, k) }; }),
      verdict: component.verdict || 'Both are UGC-recognised — pick on fees, specialisations and cohort fit.'
    };
  }

  /* Config-owned chip handlers that map onto a local UI surface (picker sheet,
     rich card, wizard) instead of a plain chat turn. */
  var HANDLER_ACTIONS = {
    list_universities: 'browseUni',
    list_providers: 'browseUni',
    get_specializations: 'browseSpec',
    get_fees: 'fees',
    get_eligibility: 'eligibility',
    get_careers: 'career',
    get_syllabus: 'syllabus',
    get_reviews: 'reviews',
    get_average_rating: 'reviews'
  };

  /* Backend quick_actions / suggested_chips -> chip objects the UI already understands. */
  function chipFrom(action) {
    if (typeof action === 'string') return { label: action, action: 'chip', handler: '', message: action };
    var label = action.label || action.message || '';
    var handler = action.chip_handler || action.handler || '';
    return {
      label: label,
      handler: handler,
      action: 'chip',
      message: action.message || label,
      tool: action.tool || null,
      chip_id: action.chip_id || null,
      chip_surface: action.surface || null,
      chip_config_version: action.config_version || null,
      chip_correlation_id: action.correlation_id || null,
      funnel_stage: action.funnel_stage || null,
      interaction_count: (typeof action.interaction_count === 'number') ? action.interaction_count : null,
      content_version: action.content_version || null,
      lead_tags: action.lead_tags || null,
      tool: action.tool || null
    };
  }

  function chipsFrom(payload) {
    var actions = [];
    if (Array.isArray(payload.quick_actions) && payload.quick_actions.length) actions = payload.quick_actions;
    else {
      var comp = (payload.components || []).find(function (c) { return c && c.type === 'quick_actions'; });
      if (comp && Array.isArray(comp.actions)) actions = comp.actions;
      else if (Array.isArray(payload.suggested_chips)) actions = payload.suggested_chips;
    }
    return actions.map(chipFrom).filter(function (c) { return c.label; });
  }

  var CARD_TYPES = ['university_card', 'program_card', 'course_card', 'specialization_card'];

  /* Flatten one ResponsePayload into the message specs render() already knows. */
  function payloadToMsgs(payload) {
    var msgs = [];
    var text = payload.message || payload.text;
    if (text) msgs.push({ kind: 'bot', text: text });

    var cards = [];
    (payload.components || []).forEach(function (component) {
      if (!component || !component.type) return;
      if (CARD_TYPES.indexOf(component.type) >= 0) { cards.push(cardFrom(component)); return; }
      if (component.type === 'card_list') {
        (component.items || []).slice(0, 3)
          .forEach(function (c) { cards.push(cardFrom(c)); });
        return;
      }
      if (component.type === 'comparison_card') {
        if (cards.length) { msgs.push({ kind: 'cards', cards: cards }); cards = []; }
        msgs.push(compareFrom(component));
        return;
      }
      if (component.type === 'lead_cta') {
        if (cards.length) { msgs.push({ kind: 'cards', cards: cards }); cards = []; }
        msgs.push({ kind: 'lead', text: component.label || 'Share your number and a counsellor will call you — no spam.' });
      }
    });
    if (cards.length) msgs.push({ kind: 'cards', cards: cards });

    if (payload.cta && !(payload.components || []).some(function (c) { return c && c.type === 'lead_cta'; })) {
      msgs.push({ kind: 'lead', text: payload.cta.label || 'Want a counsellor to call you? Just your number — no spam.' });
    }
    return msgs;
  }

  function contextFrom(payload) {
    var ctx = payload.context;
    if (!ctx) return undefined;
    var label = ctx.label || [ctx.university, ctx.course, ctx.specialization].filter(Boolean).join(' · ');
    return label ? { label: label, entityId: ctx.entity_id || null } : null;
  }

  function toolFlowFrom(payload) {
    var meta = payload && payload.metadata;
    var flow = meta && meta.tool_flow;
    return (flow && typeof flow === 'object') ? flow : null;
  }

  /* ── Rich cards derived from the guide bundle's published `info` ── */
  function info(kind) {
    var bundle = state.guideBundle || {};
    var value = (bundle.info || {})[kind];
    return (value && value.available) ? value : null;
  }

  /* Published amounts arrive as "INR 93,000.0" — render them as designed. */
  function money(value, emptyCopy) {
    var text = String(value == null ? '' : value).trim();
    if (!text) return emptyCopy || 'Not published';
    text = text.replace(/\s*\(.*?\)/g, '')
               .replace(/\s+per\s+semester\s*$/i, '')
               .replace(/\s+starting\s+fee\s*$/i, '')
               .replace(/\s+total\s+fee\s*$/i, '');
    return text.replace(/\bINR\s*/gi, '₹').replace(/(\d[\d,]*)\.0+(?=\D|$)/g, '$1');
  }

  function feesFromBundle(d) {
    var entity = (state.guideBundle || {}).entity || {};
    return {
      total: money(d.total_fee || entity.fee),
      perSem: money(String(d.semester_fee || '').replace(/\s+per\s+semester\s*$/i, '')),
      plans: (d.plans || []).map(function (p) {
        return {
          label: p.name || p.label || 'Payment plan',
          value: money(p.amount || p.value || p.total),
          note: p.note || (p.total && p.total !== p.amount ? 'Total ' + money(p.total) : '')
        };
      }),
      emiNote: money(d.emi || entity.emi, 'EMI options are confirmed by a counsellor.')
    };
  }
  function eligFromBundle(d) {
    var entity = (state.guideBundle || {}).entity || {};
    return {
      verdict: 'Published requirements',
      sub: d.summary || entity.eligibility || 'Review the criteria below',
      reqs: (d.requirements || []).map(function (r) {
        if (typeof r === 'string') return { ok: true, t: r };
        return {
          ok: !(r.optional === true || r.ok === false),
          optional: r.optional === true,
          t: r.title || r.label || r.text || 'Requirement',
          note: r.note || ''
        };
      })
    };
  }
  function careerFromBundle(d) {
    return {
      avg: money(d.average_salary),
      range: '',
      roles: (d.job_roles || []).map(function (r) {
        return typeof r === 'object'
          ? { t: r.title || r.name || r.label || 'Role', s: r.salary || r.value ? money(r.salary || r.value) : '' }
          : { t: String(r), s: '' };
      }),
      recruiters: (d.recruiters || []).map(function (r) {
        return typeof r === 'object' ? (r.name || r.label || '') : String(r);
      }).filter(Boolean)
    };
  }
  function reviewsFromBundle(d) {
    var rating = Number.parseFloat(d.rating);
    var filled = Number.isFinite(rating) ? Math.max(0, Math.min(5, Math.floor(rating))) : 0;
    var themes = (d.breakdown || []);
    return {
      rating: d.rating ? String(d.rating) : '—',
      stars: '★'.repeat(filled) + '☆'.repeat(5 - filled),
      count: String(d.review_count || 0),
      bars: themes.map(function (b) { return { stars: b.label || b.name || '', pct: b.value || b.score || '0%' }; }),
      praised: (themes[0] && (themes[0].label || themes[0].name)) || 'Published learner feedback',
      flagged: (themes[themes.length - 1] && (themes[themes.length - 1].label || themes[themes.length - 1].name)) || '—',
      quotes: (d.testimonials || []).slice(0, 2).map(function (t) {
        return {
          n: [t.reviewer_name, t.reviewer_label].filter(Boolean).join(' · ') || 'Verified learner',
          t: '“' + String(t.text || '').trim() + '”'
        };
      })
    };
  }
  function syllabusFromBundle(d) {
    var entity = (state.guideBundle || {}).entity || {};
    var semesters = d.semesters || [];
    return {
      title: (entity.name ? entity.name + ' · Syllabus' : 'Syllabus'),
      meta: semesters.length + (semesters.length === 1 ? ' section' : ' sections'),
      items: semesters.map(function (s, i) {
        return { n: 'S' + (i + 1), title: s.title || ('Semester ' + (i + 1)), subs: s.items || [] };
      })
    };}