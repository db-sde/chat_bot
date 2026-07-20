/*!
 * DegreeBaba Chatbot Widget  v1.0.0
 * Pixel-perfect embeddable widget.
 * Install: <script src="widget.js"></script>
 *
 * Config (optional):
 *   window.DegreeBabaWidget.init({
 *     apiUrl:       "https://your-api.com/chat",
 *     botName:      "DegreeBaba Assistant",
 *     primaryColor: "#E84010",
 *     position:     "right",   // "right" | "left"
 *     page:         "course",  // "homepage" | "university" | "course" | "specialization"
 *     widgetId:     "CLIENT_ID"
 *   });
 */
(function () {
  'use strict';

  /* document.currentScript is null once we defer to DOMContentLoaded. */
  var bootScript = document.currentScript;

  /* ─────────────────────────────────────────────────────────────
     1. BOOTSTRAP — font injection + style mount
  ───────────────────────────────────────────────────────────── */
  function injectGoogleFonts() {
    if (document.getElementById('db-fonts')) return;
    var link = document.createElement('link');
    link.id = 'db-fonts';
    link.rel = 'stylesheet';
    link.href = 'https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap';
    document.head.appendChild(link);
  }

  /* ─────────────────────────────────────────────────────────────
     2. STATE
  ───────────────────────────────────────────────────────────── */
  var state = {
    open: false,
    msgs: [],
    chips: [],
    hasMore: false,
    compare: [],
    acc: {},             // accordion state { "msgId:idx": bool }
    context: null,
    picker: null,
    details: null,
    tool: null,
    endScreen: null,
    input: '',
    inputFocused: false,
    leadPhone: '',
    toolName: '',
    toolPhone: '',
    started: false,
    uid: 0,
    /* ── backend-bound state ── */
    sessionId: null,       // issued by /chat or /api/widget/guide/context
    guideBundle: null,     // GET /api/widget/guide/context payload
    pickerCache: {},       // cacheKey -> normalized rows
    pickerToken: 0,        // guards out-of-order picker searches
    busy: false,           // a /chat stream is in flight
    moreChips: null,       // config-owned "More ⌄" set from /guide/context
    ready: false,          // true once the backend opening payload has landed
    guideBusy: null,       // in-flight /guide/context promise
    viewedActions: new Set(),  // chip_ids already counted as impressions
    lastChip: null,
    /* ── The only copy of backend-owned context. Written exclusively by
       adoptServerContext() from a backend response; never inferred here. ── */
    server: {
      pageType: null,        // resolved page type
      entityId: null,        // resolved catalog entity id
      universityId: null,    // resolved parent university id
      surface: null,         // chip surface owning the visible chips
      configVersion: null,
      contentVersion: null,
      correlationId: null,
      funnelStage: null,
      interactionCount: 0
    }
  };
  var cfg = {
    botName: 'DegreeBaba Assistant',
    primaryColor: '#E84010',
    position: 'right',
    page: 'homepage',
    apiUrl: null,
    apiBase: '',
    siteKey: 'degreebaba',
    widgetId: null,
    entitySlug: null,
    universitySlug: null,
    showTypingIndicator: true,
    autoOpen: false,
    autoOpenPinned: false,
    welcomeMessage: null
  };

  function nextId() { return 'm' + (++state.uid); }

  /* ─────────────────────────────────────────────────────────────
     3. PRESENTATION CHROME
     Catalog facts, chips, results and tool questions are owned by the
     backend. Only non-factual presentation lives here: the tool badge
     glyph and title, which are design tokens, not business logic.
  ───────────────────────────────────────────────────────────── */
  var TOOL_CHROME = {
    roi:         { icon: '🧮', title: 'ROI Calculator' },
    quiz:        { icon: '🧭', title: 'Career-Path Quiz' },
    scholarship: { icon: '🎁', title: 'Scholarship Checker' }
  };
  function toolChrome(kind) { return TOOL_CHROME[kind] || { icon: '🧭', title: 'Assistant' }; }

  /* Copy shown when the backend has published nothing for a surface.
     The widget never substitutes invented values for missing data. */
  var UNAVAILABLE = 'That information has not been published for this option yet. A counsellor can confirm it for you.';

  function maskedPhone(phone) {
    var d = (phone || '').replace(/\D/g, '');
    return d.length >= 5 ? ('+91 ' + d.slice(0, 2) + ' ••••• ' + d.slice(-3)) : '+91 ' + d;
  }

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

  /* POST /api/widget/finder — deterministic catalog filters */
  function postFinder(answers) {
    var body = {};
    if (answers[0]) body.program = answers[0];
    if (answers[1] && !/^(show all|not sure)$/i.test(answers[1])) body.area = answers[1];
    if (answers[2] && !/^no preference$/i.test(answers[2])) body.approval = answers[2];
    if (answers[3] && !/^no preference$/i.test(answers[3])) body.budget = answers[3];
    return postJson('/api/widget/finder', body);
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
    else if (component.starting_fee) pills.push(money(component.starting_fee));
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
      if (component.type === 'card_list' || component.type === 'finder_results') {
        (component.items || component.cards || component.results || []).slice(0, 3)
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
    };
  }

  /* ── The chat bridge ──────────────────────────────────────── */

  /* Send one turn to /chat and stream it into the message list. */
  function send(message, opts) {
    var options = opts || {};
    var userLabel = options.echo === false ? null : (options.label || message);

    var items = [];
    if (userLabel) items.push({ kind: 'user', text: userLabel, id: nextId() });
    var tid = nextId();
    if (cfg.showTypingIndicator) items.push({ kind: 'typing', id: tid });
    state.started = true;
    state.chips = [];
    state.hasMore = false;
    state.input = '';
    state.inputFocused = false;
    state.busy = true;
    state.msgs = state.msgs.concat(items);
    render();
    scrollToBottom();

    /* ChatRequest.page_type accepts pillar/university/course/specialization
       only — "homepage" has no entity context, so send no page_type at all. */
    var body = { message: message, site_key: cfg.siteKey };
    if (CHAT_PAGE_TYPES.indexOf(ctxPageType()) >= 0) body.page_type = ctxPageType();
    if (state.sessionId) body.session_id = state.sessionId;
    if (ctxEntityId()) body.page_entity_slug = ctxEntityId();
    if (ctxUniversityId()) body.page_university_slug = ctxUniversityId();
    if (options.chip) {
      if (options.chip.chip_id) body.chip_id = options.chip.chip_id;
      if (options.chip.chip_surface) body.chip_surface = options.chip.chip_surface;
      if (options.chip.chip_config_version) body.chip_config_version = options.chip.chip_config_version;
      if (options.chip.chip_correlation_id) body.chip_correlation_id = options.chip.chip_correlation_id;
    }

    var streamed = '';
    var settled = null;

    function dropTyping() {
      state.msgs = state.msgs.filter(function (m) { return m.id !== tid; });
    }

    return requestChat(body).then(function (response) {
      var headerSession = response.headers.get('x-session-id');
      if (headerSession) state.sessionId = headerSession;
      return consumeSse(response, function (evt, data) {
        if (data && data.session_id) state.sessionId = data.session_id;
        if (evt === 'token') {
          streamed += data.token || '';
          /* Live-type into a single bot bubble, replacing the typing dots. */
          var existing = state.msgs.find(function (m) { return m.id === tid + '-t'; });
          if (existing) { existing.text = streamed; }
          else { dropTyping(); state.msgs = state.msgs.concat([{ kind: 'bot', text: streamed, id: tid + '-t' }]); }
          renderStreaming();
          return;
        }
        if (evt === 'response') { settled = data; }
      });
    }).then(function () {
      dropTyping();
      /* The final payload is authoritative — drop the streamed placeholder. */
      state.msgs = state.msgs.filter(function (m) { return m.id !== tid + '-t'; });
      if (!settled) throw new Error('No response payload received');
      applyPayload(settled, options);
      return settled;
    }).catch(function (err) {
      console.warn('DegreeBaba widget falling back to local content', err);
      dropTyping();
      state.msgs = state.msgs.filter(function (m) { return m.id !== tid + '-t'; });
      state.busy = false;
      if (options.onFail) options.onFail(err);
      else settleTurn(tid, [{ kind: 'bot', text: UNAVAILABLE }], null);
      return null;
    });
  }

  /* Tokens arrive faster than the DOM needs rebuilding — coalesce to one
     repaint per frame instead of a full re-render per token. */
  var streamFrame = 0;
  function renderStreaming() {
    if (streamFrame) return;
    streamFrame = requestAnimationFrame(function () {
      streamFrame = 0;
      render();
      if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight;
    });
  }

  /* Fold a settled payload into the visible state. */
  function applyPayload(payload, opts) {
    var options = opts || {};
    state.busy = false;
    var flow = toolFlowFrom(payload);

    if (flow && options.toolAware !== false && applyToolFlow(flow, payload)) return payload;

    var msgs = payloadToMsgs(payload).map(function (m) { return Object.assign({}, m, { id: nextId() }); });
    state.msgs = state.msgs.concat(msgs);
    /* The backend sends exactly the chips it wants shown. There is no local
       overflow split to reconstruct. */
    setChips(chipsFrom(payload), []);
    if (payload.metadata) adoptServerContext({ navigation: payload.metadata.navigation });
    var ctx = contextFrom(payload);
    if (ctx !== undefined) state.context = ctx;
    render();
    scrollToBottom();
    return payload;
  }

  /* ── Active tool webhooks: /chat drives every tool step ───── */

  /* Map the backend tool_flow lifecycle onto the .db-tool-widget phases. */
  function applyToolFlow(flow, payload) {
    var step = String(flow.step || '');
    var kind = TOOL_KIND_BY_ID[String(flow.tool || '')] || (state.tool && state.tool.kind);
    if (!kind) return false;

    if (step === 'exit') { state.tool = null; state.busy = false; return false; }

    if (step === 'reveal') {
      state.tool = null;
      state.busy = false;
      var result = flow.result || {};
      if (kind === 'quiz') {
        /* The quiz reveals inline in the stream, exactly like the static flow. */
        var msgs = payloadToMsgs(payload).map(function (m) { return Object.assign({}, m, { id: nextId() }); });
        state.msgs = state.msgs.concat(msgs);
        state.chips = chipsFrom(payload);
        render(); scrollToBottom();
        return true;
      }
      state.endScreen = endScreenFrom(kind, result, payload);
      render();
      return true;
    }

    var base = state.tool || { kind: kind, idx: 0, answers: {} };

    if (step === 'partial_reveal') {
      state.tool = Object.assign({}, base, { kind: kind, phase: 'partial', partialText: payload.message || payload.text });
      state.busy = false;
      render(); scrollToBottom();
      return true;
    }

    if (step === 'await_lead') {
      state.tool = Object.assign({}, base, { kind: kind, phase: 'lead' });
      state.busy = false;
      render(); scrollToBottom();
      return true;
    }

    /* Anything else is a question step: the options arrive as quick_actions. */
    var opts = (payload.quick_actions || []).filter(function (a) {
      return a && typeof a.message === 'string' && a.message.indexOf('tool:answer:') === 0;
    });
    if (!opts.length) return false;
    var seen = base.stepIds || [];
    if (seen.indexOf(step) < 0) seen = seen.concat([step]);

    /* The rendered text collapses entry copy and prompt together, so both are
       read from the structured tool_flow fields instead. */
    var question = flow.prompt || payload.message || payload.text || '';
    var entryCopy = flow.entry_copy || base.entryCopy || '';
    var firstTurn = !base.begun;
    state.tool = Object.assign({}, base, {
      kind: kind,
      stepId: step,
      idx: Number(flow.step_index) ? Number(flow.step_index) - 1 : seen.indexOf(step),
      stepIds: seen,
      question: question,
      entryCopy: entryCopy,
      begun: !firstTurn,
      phase: firstTurn ? 'entry' : 'step',
      options: opts.map(function (a) { return { label: a.label, message: a.message }; }),
      total: Number(flow.step_total) || Math.max(seen.length, base.total || 0, 1)
    });
    state.busy = false;
    render(); scrollToBottom();
    return true;
  }

  var TOOL_TOKEN_BY_KIND = { roi: 'roi', quiz: 'career_quiz', scholarship: 'scholarship' };
  var TOOL_KIND_BY_ID = { roi: 'roi', career_quiz: 'quiz', scholarship: 'scholarship' };

  /* Build the .db-end-screen model from the backend's revealed ToolResult. */
  function endScreenFrom(kind, result, payload) {
    var name = (state.toolName || '').trim();
    var masked = maskedPhone(state.toolPhone);
    if (kind === 'roi') {
      var months = Number(result.payback_months);
      return {
        kind: 'roi',
        name: name,
        masked: masked,
        program: result.program_name || 'this programme',
        months: Number.isFinite(months) ? months : '—',
        invest: result.fee_numeric ? formatINR(result.fee_numeric) : 'Not published',
        avgSalary: result.expected_post_program_salary_annual
          ? formatINR(result.expected_post_program_salary_annual) : 'Not published',
        emi: result.emi || 'Confirmed on call',
        verdict: result.message || (payload && (payload.message || payload.text)) || ''
      };
    }
    var waiverNum = Number(result.waiver_amount);
    return {
      kind: 'scholarship',
      name: name,
      masked: masked,
      waiver: Number.isFinite(waiverNum) ? formatINR(waiverNum) : (result.reward_band || 'Waiver confirmed'),
      net: Number.isFinite(Number(result.net_fee)) ? formatINR(result.net_fee) : 'Confirmed on call',
      /* Standard fee is the published net plus the published waiver. */
      standard: (Number.isFinite(Number(result.net_fee)) && Number.isFinite(waiverNum))
        ? formatINR(Number(result.net_fee) + waiverNum)
        : 'Not published',
      reasons: result.reasons || [result.reward_band].filter(Boolean),
      steps: (result.claim_steps || []).map(function (s, i) {
        return { n: i + 1, t: typeof s === 'string' ? s : (s.text || s.title || '') };
      })
    };
  }

  function formatINR(value) {
    var num = Number(value);
    if (!Number.isFinite(num)) return String(value || 'Not published');
    return '₹' + Math.round(num).toLocaleString('en-IN');
  }

  var scrollEl;        // set after render
  var pickerDebounce;  // timer for the picker search input
  function scrollToBottom() {
    if (scrollEl) setTimeout(function(){ scrollEl.scrollTop = scrollEl.scrollHeight; }, 30);
  }

  /* Open one bot turn: echo the user, show the typing indicator, and hand
     back the placeholder id so the caller can swap in the settled content. */
  function beginTurn(userLabel) {
    var items = [];
    if (userLabel) items.push({ kind: 'user', text: userLabel, id: nextId() });
    var tid = nextId();
    if (cfg.showTypingIndicator) items.push({ kind: 'typing', id: tid });
    state.started = true;
    state.chips = [];
    state.hasMore = false;
    state.input = '';
    state.inputFocused = false;
    state.msgs = state.msgs.concat(items);
    render();
    scrollToBottom();
    return tid;
  }

  function settleTurn(tid, msgs, chips) {
    state.msgs = state.msgs.filter(function (m) { return m.id !== tid; })
      .concat(msgs.map(function (m) { return Object.assign({}, m, { id: nextId() }); }));
    if (chips) setChips(chips);
    render();
    scrollToBottom();
  }

  /* "More" is presentation only: it reveals the overflow the backend already
     sent. The widget never invents chips and never sends this as a message. */
  function expandMore() {
    var extra = state.moreChips || [];
    if (!extra.length) { state.hasMore = false; render(); return; }
    var seen = {};
    state.chips.forEach(function (c) { seen[c.chip_id || c.label] = true; });
    state.chips = state.chips.concat(extra.filter(function (c) { return !seen[c.chip_id || c.label]; }));
    state.moreChips = [];
    state.hasMore = false;
    emitChipShown(state.chips);
    render(); scrollToBottom();
  }

  /* The backend owns chip content and order. The widget only renders. */
  function setChips(actions, more) {
    state.chips = (actions || []).map(chipFrom).filter(function (c) { return c.label; });
    state.moreChips = (more || []).map(chipFrom).filter(function (c) { return c.label; });
    state.hasMore = state.moreChips.length > 0;
    emitChipShown(state.chips);
  }

  /* Honest empty state: never fabricate catalog values. */
  function unavailableTurn(tid, copy) {
    settleTurn(tid, [{ kind: 'bot', text: copy || UNAVAILABLE }], null);
    loadFollowups(null, null).catch(function () {});
  }

  /* ── Backend handler → UI surface map ─────────────────────────
     Every deterministic chip handler published by the chip engine has a
     dedicated surface here. Nothing falls through to typed chat. */
  var PICKER_HANDLERS = {
    list_universities:    { kind: 'uni',     title: 'Browse universities' },
    list_providers:       { kind: 'uni',     title: 'Universities offering this' },
    list_programs:        { kind: 'program', title: 'Browse programs' },
    get_specializations:  { kind: 'spec',    title: 'Choose a specialization' },
    get_eligible_programs:{ kind: 'program', title: 'Programs you are eligible for' }
  };

  /* handler -> [guide-bundle info key, answer_state for follow-up chips] */
  var INFO_HANDLERS = {
    get_fees:              ['fees',           'fees'],
    get_eligibility:       ['eligibility',    'eligibility_borderline'],
    get_careers:           ['career',         'careers'],
    get_syllabus:          ['syllabus',       'syllabus'],
    get_reviews:           ['reviews',        'reviews'],
    get_average_rating:    ['reviews',        'average_rating'],
    get_approvals:         ['accreditations', 'approvals'],
    get_placement_support: ['placement',      'placement'],
    get_overview:          ['overview',       'overview'],
    get_admission_steps:   ['admissions',     'admissions']
    /* get_validity is deliberately absent: the guide bundle has no `validity`
       info key. The knowledge handler behind /chat answers it deterministically
       (see routing/knowledge_handler.py), so it falls through to send() below. */
  };

  function onChip(ch) {
    emitAnalytics('chip_tapped', ch);
    state.lastChip = ch;

    var handler = ch.handler || '';
    if (handler === 'tool_entry') { startTool(TOOL_KIND_BY_ID[ch.tool] || ch.tool, ch); return; }
    if (handler === 'compare') {
      /* Fewer than two options selected: there is nothing to compare yet, so
         open a real picker instead of telling the user to do something the
         UI gives them no way to do. */
      if (state.compare.length < 2) { openComparePicker(ch); return; }
      runGuidedComparison(ch);
      return;
    }
    if (handler === 'cta_apply' || handler === 'cta_callback') { openLeadTurn(ch); return; }
    if (PICKER_HANDLERS[handler]) { openPicker(PICKER_HANDLERS[handler], ch); return; }
    if (INFO_HANDLERS[handler]) { showInfoCard(handler, ch); return; }

    /* No deterministic handler published: this is a conversational chip. */
    send(ch.message || ch.label, { label: ch.label, chip: ch });
  }

  /* ── Guided info cards, grounded in the page bundle ─────────── */
  function showInfoCard(handler, chip) {
    var spec = INFO_HANDLERS[handler];
    var infoKey = spec[0];
    var tid = beginTurn(chip.label);

    ensureGuideBundle().then(function () {
      var data = info(infoKey);
      if (!data) { unavailableTurn(tid, UNAVAILABLE); return null; }
      var msgs = infoCardMsgs(handler, infoKey, data);
      if (!msgs.length) { unavailableTurn(tid, UNAVAILABLE); return null; }
      settleTurn(tid, msgs, null);
      emitAnalytics('card_shown', chip, { entity: analyticsEntity() });
      return loadFollowups(answerStateFor(handler, data), chip);
    }).catch(function (err) {
      console.warn('DegreeBaba widget guided card unavailable', err);
      unavailableTurn(tid, UNAVAILABLE);
    });
  }

  /* Eligibility follow-ups branch on the published outcome. */
  function answerStateFor(handler, data) {
    if (handler !== 'get_eligibility') return INFO_HANDLERS[handler][1];
    var outcome = String((data && (data.outcome || data.status)) || '').toLowerCase();
    if (outcome.indexOf('not') === 0 || outcome === 'ineligible') return 'eligibility_no';
    if (outcome === 'eligible' || outcome === 'yes') return 'eligibility_yes';
    return 'eligibility_borderline';
  }

  /* Rich cards reuse the approved renderers; plain published facts reuse
     the approved .db-info-card surface. No new classes are introduced. */
  function infoCardMsgs(handler, infoKey, data) {
    if (handler === 'get_fees') return [{ kind: 'fees', fee: feesFromBundle(data) }, leadPromptMsg('fees')];
    if (handler === 'get_eligibility') return [{ kind: 'elig', elig: eligFromBundle(data) }, leadPromptMsg('eligibility')];
    if (handler === 'get_careers') return [{ kind: 'career', career: careerFromBundle(data) }];
    if (handler === 'get_syllabus') return [{ kind: 'syllabus', syl: syllabusFromBundle(data) }];
    if (handler === 'get_reviews') return [{ kind: 'reviews', rev: reviewsFromBundle(data) }];
    if (handler === 'get_average_rating') {
      return [{ kind: 'reviews', rev: reviewsFromBundle(Object.assign({}, data, { testimonials: [], breakdown: [] })) }];
    }
    var card = publishedInfoCard(handler, data);
    return card ? [card] : [];
  }

  function leadPromptMsg(kind) {
    return {
      kind: 'lead',
      text: kind === 'fees'
        ? "Want me to check today's fee offer and seat availability? Just your number — no spam."
        : "Want me to confirm your eligibility and today's seat availability? Just your number — no spam."
    };
  }

  /* Approvals / placement / overview / admissions / validity render into the
     existing .db-info-card blocks already used by the details overlay. */
  function publishedInfoCard(handler, data) {
    var titles = {
      get_approvals: 'Accreditations',
      get_placement_support: 'Placement support',
      get_overview: 'Why choose this university',
      get_admission_steps: 'Admission process',
      get_validity: 'Degree validity'
    };
    var body = { title: titles[handler] || 'Published information' };
    if (handler === 'get_approvals') body.tags = data.items || [];
    else if (handler === 'get_admission_steps') {
      var steps = data.steps;
      body.steps = Array.isArray(steps) ? steps : (steps ? String(steps).split(/\n+/).filter(Boolean) : []);
      body.text = data.fee_note || '';
    } else if (handler === 'get_placement_support') {
      /* Placement publishes flags rather than prose. */
      body.text = data.content || '';
      body.tags = [
        data.supported ? 'Placement support included' : null,
        data.industry_projects ? 'Industry projects' : null
      ].filter(Boolean);
    } else {
      body.text = data.why_choose || data.description || data.content || data.summary || data.text || '';
    }
    if (!body.text && !(body.tags || []).length && !(body.steps || []).length) return null;
    return { kind: 'published', info: body };
  }

  /* ── Deterministic comparison via /api/widget/guide/compare ─── */
  function runGuidedComparison(chip) {
    var ids = state.compare.map(function (c) { return c.entityId; }).filter(Boolean);
    /* Any caller landing here with fewer than two resolvable ids gets routed
       into the real selection flow instead of a dead-end message. */
    if (ids.length < 2) { openComparePicker(chip); return; }
    var tid = beginTurn(chip && chip.label ? chip.label : 'Compare');
    postJson('/api/widget/guide/compare', { entity_ids: ids.slice(0, 3) }).then(function (card) {
      state.compare = [];
      settleTurn(tid, [compareFrom(card)], null);
      emitAnalytics('card_shown', chip, { entity: analyticsEntity() });
      return loadFollowups('comparison', chip);
    }).catch(function (err) {
      console.warn('DegreeBaba widget comparison unavailable', err);
      state.compare = [];
      unavailableTurn(tid, 'Those two options cannot be compared from published data yet.');
    });
  }

  /* Conversion chips must be recorded before the form opens, so the funnel
     advances and the chip is filtered out of later surfaces. */
  function openLeadTurn(chip) {
    var tid = beginTurn(chip.label);
    emitAnalytics(chip.handler === 'cta_apply' ? 'apply_clicked' : 'counsellor_clicked', chip);
    var copy = chip.handler === 'cta_apply'
      ? 'Happy to help you apply. Share your number and a counsellor will guide you through it — no spam.'
      : 'Happy to connect you. Just your number and a counsellor will call within 30 minutes — no spam.';
    postGuideChips(null, chip.chip_id, cardTypeForContext())
      .then(function (res) {
        adoptServerContext(res);
        var followup = (res && res.followup) || {};
        settleTurn(tid, [{ kind: 'lead', text: copy }], null);
        setChips(followup.actions || [], followup.more || []);
        render(); scrollToBottom();
      })
      .catch(function (err) {
        console.warn('DegreeBaba widget could not persist the conversion chip', err);
        settleTurn(tid, [{ kind: 'lead', text: copy }], null);
      });
  }

  /* ── Follow-up chips are always asked for, never invented ───── */
  /* When the follow-up call fails, fall back to the page's own opening chips
     (still a real backend set) rather than leaving the user with nothing. */
  var SAFETY_CHIPS = [
    { label: '🔍 Browse programs', handler: 'list_programs', message: '📚 Browse programs' },
    { label: '📞 Talk to a counsellor', handler: 'cta_callback', message: '📞 Talk to a counsellor' }
  ];

  function loadFollowups(answerState, chip) {
    return postGuideChips(answerState, chip && chip.chip_id, cardTypeForContext())
      .then(function (res) {
        adoptServerContext(res);
        var followup = (res && res.followup) || {};
        setChips(followup.actions || [], followup.more || []);
        render(); scrollToBottom();
        return res;
      }).catch(function (err) {
        console.warn('DegreeBaba widget follow-up chips unavailable', err);
        var bundle = state.guideBundle;
        var opening = bundle && bundle.opening;
        if (opening && (opening.top || []).length) {
          setChips(opening.top, opening.more || []);
        } else {
          setChips(SAFETY_CHIPS, []);
        }
        render(); scrollToBottom();
      });
  }

  function cardTypeForContext() {
    var page = resolvedContext().pageType;
    if (page === 'university' || page === 'course' || page === 'specialization') return page;
    return null;
  }

  /* ── Catalog picker ────────────────────────────────────────── */
  function openPicker(spec, chip) {
    state.picker = {
      title: spec.title, kind: spec.kind, query: '',
      rows: null, loading: true, chip: chip || null
    };
    render();
    refreshPicker('');
  }

  /* GET /api/widget/guide/catalog/{kind} with the current page as the filter. */
  function refreshPicker(query) {
    var p = state.picker;
    if (!p) return;
    var token = ++state.pickerToken;
    var filters = {};
    if (query) filters.q = query;
    /* Scope the list to the page context so pickers are never unfiltered. */
    if (p.kind === 'spec' || p.kind === 'program') {
      if (ctxUniversityId()) filters.university = ctxUniversityId();
    }
    if (p.kind === 'spec' && ctxPageType() === 'course' && ctxEntityId()) filters.course = ctxEntityId();
    if (p.kind === 'uni' && ctxPageType() === 'pillar' && ctxEntityId()) filters.course = ctxEntityId();

    loadGuideCatalog(p.kind, filters).then(function (rows) {
      if (token !== state.pickerToken || !state.picker) return;
      state.picker = Object.assign({}, state.picker, { rows: rows, loading: false });
      renderPickerList();
    }).catch(function (err) {
      if (token !== state.pickerToken || !state.picker) return;
      console.warn('DegreeBaba widget catalog unavailable', err);
      state.picker = Object.assign({}, state.picker, { rows: [], loading: false });
      renderPickerList();
    });
  }

  function pickerRows() {
    var p = state.picker;
    return (p && Array.isArray(p.rows)) ? p.rows : [];
  }

  /* Which catalog kind lets a user pick a comparable option for the page
     they are currently on. Reuses the exact filters refreshPicker() already
     applies for that kind, so results are the same grounded rows as every
     other picker — never a fresh, unscoped list. */
  var COMPARE_PICKER_KIND = {
    homepage: 'uni', pillar: 'uni', university: 'uni',
    course: 'program', specialization: 'spec'
  };
  var COMPARE_PICKER_TITLE = {
    uni: 'Choose two universities to compare',
    program: 'Choose two programs to compare',
    spec: 'Choose two specializations to compare'
  };

  /* "Compare" with fewer than two options selected opens a real picker
     instead of telling the user to do something the UI gives them no way
     to do. Picking two rows here compares by entity_id, same as tapping
     "+ Compare" on two recommendation cards. */
  function openComparePicker(chip) {
    var kind = COMPARE_PICKER_KIND[ctxPageType()] || 'uni';
    state.picker = {
      title: COMPARE_PICKER_TITLE[kind], kind: kind, query: '',
      rows: null, loading: true, chip: chip || null, compareMode: true
    };
    render();
    refreshPicker('');
  }

  function pickCompareItem(row) {
    var chip = state.picker && state.picker.chip;
    state.picker = null;
    state.pickerToken++;

    var entry = { entityId: row.id, title: row.name, mono: row.mono, bg: row.bg };
    var key = entry.entityId || entry.title;
    var has = state.compare.find(function (c) { return (c.entityId || c.title) === key; });
    if (has) { state.compare = state.compare.filter(function (c) { return (c.entityId || c.title) !== key; }); }
    else if (state.compare.length >= 2) { state.compare = [state.compare[1], entry]; }
    else { state.compare = state.compare.concat([entry]); }

    /* Two selected from the picker: compare immediately, no extra tap. */
    if (state.compare.length >= 2) { runGuidedComparison(chip || { label: 'Compare' }); return; }

    var tid = beginTurn(row.name);
    settleTurn(tid, [{ kind: 'bot', text: 'Added ' + row.name + '. Pick one more to compare.' }],
      [chip || { label: '⚖️ Compare', handler: 'compare', message: 'Compare' }]);
  }

  /* Selecting a catalog row is a deterministic focus change, not a chat turn. */
  /* Selecting a catalog row is a deterministic focus change. The widget sends
     the selection and adopts whatever context the backend resolves. */
  function pickItem(row) {
    var p = state.picker;
    var chip = p && p.chip;
    state.picker = null;
    state.pickerToken++;

    /* Category rows (e.g. "MBA") are not catalog entities: they narrow the
       catalog instead of resolving one. Drill into them rather than guessing. */
    if (row.isCategory) { drillIntoCategory(row, p, chip); return; }

    state.guideBundle = null;
    var tid = beginTurn(row.name);
    loadGuideContext(row.pageType || null, {
      entityId: row.id,
      universityId: (p && p.kind === 'uni') ? row.id : ctxUniversityId()
    }).then(function (bundle) {
      if (!bundle || !bundle.entity) { unavailableTurn(tid, UNAVAILABLE); return null; }
      applyBundleContext(bundle);
      settleTurn(tid, [{ kind: 'cards', cards: [cardFrom(bundle.entity)] }], null);
      emitAnalytics('card_shown', chip, { entity: analyticsEntity() });
      var opening = bundle.opening || {};
      setChips(opening.top || [], opening.more || []);
      render(); scrollToBottom();
      return null;
    }).catch(function (err) {
      console.warn('DegreeBaba widget selection failed', err);
      unavailableTurn(tid, UNAVAILABLE);
    });
  }

  /* A program category resolves to the universities offering it, not a course. */
  function drillIntoCategory(row, picker, chip) {
    var tid = beginTurn(row.name);
    loadGuideCatalog('uni', { course: row.id }).then(function (rows) {
      state.msgs = state.msgs.filter(function (m) { return m.id !== tid; });
      if (!rows.length) { unavailableTurn(tid, UNAVAILABLE); return; }
      state.picker = {
        title: 'Universities offering ' + row.name,
        kind: 'course', query: '', rows: null, loading: true,
        chip: chip, course: row.id
      };
      /* beginTurn() cleared the chips row for the "typing" moment above. The
         picker is an overlay, not a replacement for the chat underneath, so
         refill it now — otherwise closing this picker without picking leaves
         the user with nothing. */
      loadFollowups(null, chip).catch(function () {});
      render();
      /* List the actual courses for this category so the next tap resolves. */
      loadGuideCatalog('course', { course: row.id }).then(function (courses) {
        if (!state.picker) return;
        state.picker = Object.assign({}, state.picker, {
          rows: courses.length ? courses : rows, loading: false
        });
        renderPickerList();
      }).catch(function () {
        if (!state.picker) return;
        state.picker = Object.assign({}, state.picker, { rows: rows, loading: false });
        renderPickerList();
      });
    }).catch(function (err) {
      console.warn('DegreeBaba widget category drill-down failed', err);
      unavailableTurn(tid, UNAVAILABLE);
    });
  }

  function toggleCompare(card) {
    /* Identity is the catalog entity id: two "MBA" cards from different
       universities are different entities. */
    var key = card.entityId || card.title;
    var has = state.compare.find(function(c){ return (c.entityId || c.title) === key; });
    if (has) { state.compare = state.compare.filter(function(c){ return (c.entityId || c.title) !== key; }); }
    else if (state.compare.length>=2) { state.compare = [state.compare[1],card]; }
    else { state.compare = state.compare.concat([card]); }
    render();
  }
  function toggleAcc(mid, i) {
    var key = mid+':'+i;
    var cur = state.acc[key] !== undefined ? state.acc[key] : (i===0);
    state.acc[key] = !cur;
    render();
  }
  /* Never claim success before the backend confirms it. */
  function submitLead(id) {
    if ((state.leadPhone || '').replace(/\D/g, '').length < 10) return;
    if (!cfg.apiBase) return;
    var mark = function (patch) {
      state.msgs = state.msgs.map(function (m) { return m.id === id ? Object.assign({}, m, patch) : m; });
      render();
    };
    mark({ leadBusy: true, leadError: '' });
    postLead(state.leadPhone, null, 'widget_inline', state.lastChip).then(function (res) {
      state.leadPhone = '';
      mark({ leadBusy: false, leadDone: true });
      if (res && res.response) applyPayload(res.response, { toolAware: false });
    }).catch(function (err) {
      console.warn('DegreeBaba widget lead capture failed', err);
      mark({ leadBusy: false, leadDone: false, leadError: 'That did not go through. Please try again.' });
    });
  }
  /* The details overlay renders the backend CardDetails payload. Sections with
     no published content are omitted rather than filled with sample copy. */
  function openDetails(card) {
    var c = card.component || {};
    var d = c.details || {};
    state.details = {
      mono: card.mono, bg: card.bg, title: card.title, trust: card.trust, pills: card.pills,
      hero: d.description || c.summary || '',
      accr: [c.ugc_status, c.naac_grade && ('NAAC ' + c.naac_grade)].filter(Boolean)
        .concat(d.accreditations || []),
      steps: (function () {
        var raw = d.admission_steps;
        var list = Array.isArray(raw) ? raw : (raw ? String(raw).split(/\n+/) : []);
        return list.filter(Boolean).map(function (t, i) { return { n: i + 1, t: String(t).trim() }; });
      })(),
      reviews: (d.reviews || []).map(function (r) {
        return { n: [r.reviewer_name, r.reviewer_label].filter(Boolean).join(' · ') || 'Verified learner', t: r.text };
      }),
      faqs: (d.faqs || []).map(function (f) { return { q: f.question, a: f.answer }; })
    };
    render();
    emitAnalytics('card_shown', state.lastChip, { entity: { type: ctxPageType(), id: String(card.entityId || 'unknown') } });
  }

  /* Tool */
  /* Tool flows are owned by the backend ActiveFlow. The widget renders the
     current step and never computes a result of its own. */
  function startTool(kind, chip) {
    state.tool = { kind: kind, phase: 'loading', idx: 0, answers: {}, stepIds: [] };
    state.toolName = ''; state.toolPhone = '';
    state.chips = []; state.hasMore = false; state.started = true;
    render(); scrollToBottom();

    send('tool:' + TOOL_TOKEN_BY_KIND[kind], {
      echo: false,
      onFail: function () { closeTool('unavailable'); }
    });
  }

  function toolAnswer(opt, oi) {
    var t = state.tool;
    if (!t) return;
    var remote = (t.options || [])[oi];
    if (!remote || !remote.message) return;
    state.tool = Object.assign({}, t, {
      answers: Object.assign({}, t.answers, { [t.idx]: { l: opt, i: oi } }),
      phase: 'loading'
    });
    render();
    send(remote.message, { echo: false, onFail: function () { closeTool('transport_error'); } });
  }

  /* The partial → lead gate: `tool:continue` moves the flow to await_lead. */
  function toolReveal() {
    var t = state.tool;
    if (!t) return;
    state.tool = Object.assign({}, t, { phase: 'loading' });
    render();
    send('tool:continue', { echo: false, onFail: function () { closeTool('transport_error'); } });
  }

  function toolSubmit() {
    if (!(state.toolName || '').trim()) return;
    if ((state.toolPhone || '').replace(/\D/g, '').length < 10) return;
    var t = state.tool;
    state.tool = Object.assign({}, t, { phase: 'loading' });
    render();
    postLead(state.toolPhone, state.toolName, 'tool:' + TOOL_TOKEN_BY_KIND[t.kind], state.lastChip)
      .then(function (res) {
        /* The lead endpoint resumes the flow and returns the reveal payload. */
        if (res && res.response) { applyPayload(res.response); return; }
        closeTool('lead_captured');
      })
      .catch(function (err) {
        console.warn('DegreeBaba widget tool lead failed', err);
        state.tool = Object.assign({}, state.tool || t, { phase: 'lead' });
        render();
      });
  }

  /* Abandon the persisted backend ActiveFlow only — page/focus/navigation
     are untouched — then refresh chips for wherever the user actually is. */
  function abandonToolFlow(chip) {
    if (!cfg.apiBase || !state.sessionId) return;
    postJson('/api/widget/context/clear', { session_id: state.sessionId, scope: 'flow' })
      .then(function () { return loadFollowups(null, chip); })
      .catch(function (err) {
        console.warn('DegreeBaba widget could not abandon the active flow', err);
      });
  }

  /* The button reads "Skip — show a general result", but scoring without a
     phone number isn't something the backend can produce (every tool's
     result is gated behind the contact step). Say so plainly instead of
     closing in silence, which reads as the button having done nothing. */
  function toolSkip() {
    var chip = state.lastChip;
    state.tool = null;
    var tid = beginTurn(null);
    settleTurn(tid, [{
      kind: 'bot',
      text: "No problem — I can't personalise this without a quick contact step, but a counsellor can talk you through it directly."
    }], null);
    abandonToolFlow(chip);
  }

  /* Closing must clear the persisted backend ActiveFlow too, otherwise the
     next context load resurrects the tool. */
  function closeTool(reason) {
    var t = state.tool;
    state.tool = null;
    render();
    if (!t) return;
    abandonToolFlow(state.lastChip);
  }

  function onEndPrograms() {
    state.endScreen = null;
    send('Show me matching programs', { echo: false });
  }

  /* Free text always goes to the backend. The widget does no intent guessing. */
  function onSendText() {
    var t = (state.input || '').trim();
    if (!t || state.busy || !state.ready) return;
    send(t);
  }
  /* Clearing context must clear the backend session too, otherwise later turns
     keep resolving against the entity the user just dismissed. */
  function clearContext() {
    state.context = null;
    state.server = {
      pageType: 'homepage', entityId: null, universityId: null,
      surface: null, configVersion: null, contentVersion: null,
      correlationId: null, funnelStage: null, interactionCount: 0
    };
    cfg.page = 'homepage'; cfg.entitySlug = null; cfg.universitySlug = null;
    state.guideBundle = null; state.guideBusy = null;
    state.pickerCache = {}; state.compare = [];
    render();
    if (!cfg.apiBase || !state.sessionId) return;
    postJson('/api/widget/context/clear', { session_id: state.sessionId, scope: 'all' })
      .then(function () {
        state.guideBundle = null;
        return ensureGuideBundle().then(function (bundle) {
          applyBundleContext(bundle);
          var opening = bundle.opening || {};
          setChips(opening.top || [], opening.more || []);
          render(); scrollToBottom();
        });
      })
      .catch(function (err) { console.warn('DegreeBaba widget context clear failed', err); });
  }

  /* Startup: render nothing derived from guesses. The opening greeting and
     chips arrive from the backend before the user can interact. */
  function resetChat() {
    state.uid = 0;
    state.msgs = [];
    state.chips = []; state.moreChips = null; state.hasMore = false;
    state.compare = []; state.acc = {};
    state.context = null;
    state.picker = null; state.details = null; state.tool = null; state.endScreen = null;
    state.input = ''; state.inputFocused = false; state.leadPhone = ''; state.toolName = ''; state.toolPhone = '';
    state.started = false; state.ready = false;
    state.guideBundle = null; state.guideBusy = null; state.busy = false;
    state.viewedActions = new Set();
    state.pickerCache = {};
    render(); scrollToBottom();
    loadOpening();
  }

  function loadOpening() {
    if (!cfg.apiBase) { state.ready = true; render(); return; }
    var tid = nextId();
    if (cfg.showTypingIndicator) { state.msgs = [{ kind: 'typing', id: tid }]; render(); }
    ensureGuideBundle().then(function (bundle) {
      state.msgs = state.msgs.filter(function (m) { return m.id !== tid; });
      applyBundleContext(bundle);
      var opening = bundle.opening || {};
      var greeting = opening.message || opening.greeting || cfg.welcomeMessage;
      if (greeting) state.msgs = state.msgs.concat([{ kind: 'bot', text: greeting, id: nextId() }]);
      setChips(opening.top || [], opening.more || []);
      state.ready = true;
      /* A tool left mid-flow on a previous visit resumes where it stopped. */
      if (bundle.active_flow && bundle.active_flow.response) {
        applyPayload(bundle.active_flow.response);
        return;
      }
      render(); scrollToBottom();
    }).catch(function (err) {
      console.warn('DegreeBaba widget opening unavailable', err);
      state.msgs = state.msgs.filter(function (m) { return m.id !== tid; })
        .concat([{ kind: 'bot', text: UNAVAILABLE, id: nextId() }]);
      state.ready = true;
      render(); scrollToBottom();
    });
  }

  /* ─────────────────────────────────────────────────────────────
     5. RENDER (vanilla DOM — no virtual DOM overhead)
  ───────────────────────────────────────────────────────────── */
  var shadow, root, launcher, windowEl;

  /* ── SVG helpers ── */
  var SVG = {
    chat: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.9-.9L3 21l1.9-5.6A8.5 8.5 0 0 1 12.5 3 8.38 8.38 0 0 1 21 11.5z"/></svg>',
    close: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
    chevDown: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
    check: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#3B6D11" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
    checkWhite: function(w,sw){return '<svg width="'+w+'" height="'+w+'" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="'+sw+'" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>';},
    x: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
    x10: '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
    send: '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>',
    back: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>',
    currency: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#E84010" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h12M6 8h12M6 13h3m0 0c6.667 0 6.667-10 0-10M6 13l8.5 8"/></svg>',
    compare: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3h5v5M8 3H3v5m0 8v5h5m8 0h5v-5"/></svg>',
    search: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#4B5563" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></svg>',
    chevGray: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
    phone: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.9.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/></svg>',
    dash: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" stroke-width="3" stroke-linecap="round"><path d="M5 12h14"/></svg>',
    checkGreen: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#3B6D11" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
    clock: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#9A6412" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>'
  };

  function e(tag, cls, inner, attrs) {
    var s = '<' + tag + (cls ? ' class="' + cls + '"' : '') + (attrs ? ' ' + attrs : '') + '>';
    if (inner !== undefined) s += inner;
    s += '</' + tag + '>';
    return s;
  }
  function div(cls, inner, attrs) { return e('div', cls, inner, attrs); }
  function btn(cls, inner, id, extraAttrs) {
    var attrs = (id ? 'id="' + id + '" ' : '') + (extraAttrs || '');
    return e('button', cls, inner, attrs.trim());
  }
  function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

  /* ── Message renderers ── */
  function renderMsg(m) {
    if (m.kind==='typing') return div('db-msg', div('db-typing', div('db-dot')+''+div('db-dot')+''+div('db-dot')));
    if (m.kind==='user') return div('db-msg', div('db-bubble-user', esc(m.text)));
    if (m.kind==='bot') return div('db-msg', div('db-bubble-bot', esc(m.text)));
    if (m.kind==='cards') return div('db-msg', m.cards.map(function(c){ return renderCard(c,m.id); }).join(''));
    if (m.kind==='compare') return div('db-msg', renderCompare(m));
    if (m.kind==='lead') return div('db-msg', renderLead(m));
    if (m.kind==='fees') return div('db-msg', renderFees(m.fee));
    if (m.kind==='elig') return div('db-msg', renderElig(m.elig));
    if (m.kind==='career') return div('db-msg', renderCareer(m.career));
    if (m.kind==='reviews') return div('db-msg', renderReviews(m.rev));
    if (m.kind==='syllabus') return div('db-msg', renderSyllabus(m.syl, m.id));
    if (m.kind==='toolResult') return div('db-msg', renderToolResult(m.tr));
    if (m.kind==='published') return div('db-msg', renderPublished(m.info));
    return '';
  }
  function renderCard(c, mid) {
    var cardKey = c.entityId || c.title;
    var inC = !!state.compare.find(function(x){ return (x.entityId || x.title) === cardKey; });
    var cmpCls = 'db-btn-compare' + (inC ? ' db-in-compare' : '');
    var cmpLabel = inC ? '✓ Added' : '+ Compare';
    return div('db-card',
      div('db-card-head',
        div('db-card-mono', esc(c.mono), 'style="background:'+c.bg+'"') +
        div('',div('db-card-title',esc(c.title))+div('db-card-trust',esc(c.trust)))
      ) +
      div('db-pills-row', c.pills.map(function(p){return div('db-pill',esc(p));}).join('')) +
      (c.emi ? div('db-card-emi', esc(c.emi)) : '') +
      (c.job ? div('db-card-job', esc(c.job)) : '') +
      div('db-card-actions',
        btn('db-btn-primary','View details','','data-action="viewDetails" data-mid="'+mid+'" data-key="'+esc(cardKey)+'"') +
        btn(cmpCls, cmpLabel, '', 'data-action="toggleCompare" data-key="'+esc(cardKey)+'"')
      )
    );
  }
  function renderCompare(m) {
    return div('db-compare',
      div('db-compare-head',
        div('db-compare-head-empty') +
        div('db-compare-head-cell', esc(m.aName)) +
        div('db-compare-head-cell', esc(m.bName))
      ) +
      m.rows.map(function(r){
        return div('db-compare-row',
          div('db-compare-key',esc(r.k)) +
          div('db-compare-val',esc(r.a)) +
          div('db-compare-val',esc(r.b))
        );
      }).join('') +
      div('db-compare-verdict', e('span','db-verdict-label','Verdict&nbsp;') + esc(m.verdict))
    );
  }
  function renderLead(m) {
    if (m.leadDone) {
      return div('db-lead',
        div('db-lead-done',
          div('db-lead-done-icon', SVG.check) +
          div('db-lead-done-text', 'Done — a counsellor will call within 30 minutes with today\'s fee offer.')
        )
      );
    }
    return div('db-lead',
      div('db-lead-text', esc(m.text)) +
      div('db-lead-form',
        div('db-phone-wrapper',
          e('span','db-phone-prefix','+91') +
          e('input','db-phone-input','','type="tel" placeholder="Your number" data-action="leadPhoneInput" data-mid="'+m.id+'" value="'+esc(state.leadPhone)+'"')
        ) +
        btn('db-lead-send', m.leadBusy ? 'Sending…' : 'Send','','data-action="submitLead" data-mid="'+m.id+'"'+(m.leadBusy?' disabled':''))
      ) +
      div('db-lead-note', m.leadError ? esc(m.leadError) : 'No spam. One call, today\'s offer.')
    );
  }
  function renderFees(f) {
    return div('db-fees',
      div('db-fees-hero',
        div('',div('db-fees-total-label','Total programme fee')+div('db-fees-total-value',esc(f.total))) +
        div('',div('db-fees-sem-label','Per semester')+div('db-fees-sem-value',esc(f.perSem)))
      ) +
      (f.plans.length ? div('db-fees-plans', f.plans.map(function(p){
        return div('db-fees-plan-row',
          div('',div('db-fees-plan-label',esc(p.label))+div('db-fees-plan-note',esc(p.note))) +
          div('db-fees-plan-value',esc(p.value))
        );
      }).join('')) : '') +
      div('db-fees-emi', SVG.currency + e('span','',esc(f.emiNote)))
    );
  }
  function renderElig(elig) {
    return div('db-elig',
      div('db-elig-hero',
        div('db-elig-check', SVG.checkWhite(17,2.6)) +
        div('',div('db-elig-verdict',esc(elig.verdict))+div('db-elig-sub',esc(elig.sub)))
      ) +
      div('db-elig-list', elig.reqs.map(function(r){
        var icon = r.ok ? div('db-elig-icon ok', SVG.checkGreen) : div('db-elig-icon opt', SVG.dash);
        return div('db-elig-row', icon + div('',div('db-elig-req-title',esc(r.t))+(r.note?div('db-elig-req-note',esc(r.note)):'') ));
      }).join(''))
    );
  }
  function renderCareer(c) {
    return div('db-career',
      div('db-career-hero',
        div('db-career-label','Average starting salary') +
        div('',div('db-career-avg',esc(c.avg))+e('span','db-career-range',' '+esc(c.range)))
      ) +
      div('db-career-roles',
        div('db-career-roles-label','Roles you can target') +
        c.roles.map(function(r){return div('db-career-role-row',div('db-career-role-title',esc(r.t))+div('db-career-role-salary',esc(r.s)));}).join('')
      ) +
      (c.recruiters.length ? div('db-career-recruiters',
        div('db-career-recruiters-label','Top recruiters') +
        div('db-recruiter-tags', c.recruiters.map(function(r){return e('span','db-recruiter-tag',esc(r));}).join(''))
      ) : '')
    );
  }
  function renderReviews(rv) {
    return div('db-reviews',
      div('db-reviews-summary',
        div('',div('db-rating-big',esc(rv.rating))+div('db-rating-stars',esc(rv.stars))+div('db-rating-count',esc(rv.count)+' reviews')) +
        (rv.bars.length ? div('db-rating-bars', rv.bars.map(function(b){
          return div('db-bar-row', e('span','db-bar-label',esc(b.stars))+div('db-bar-track',div('db-bar-fill','','style="width:'+b.pct+'"')));
        }).join('')) : '')
      ) +
      div('db-reviews-sentiment',
        div('db-praised',div('db-praised-label','Most praised')+div('db-praised-text',esc(rv.praised))) +
        div('db-flagged',div('db-flagged-label','Most flagged')+div('db-flagged-text',esc(rv.flagged)))
      ) +
      (rv.quotes.length ? div('db-reviews-quotes', rv.quotes.map(function(q){
        return div('db-quote',div('db-quote-text',esc(q.t))+div('db-quote-name',esc(q.n)));
      }).join('')) : '')
    );
  }
  function renderSyllabus(sy, mid) {
    return div('db-syllabus',
      div('db-syllabus-head', div('db-syllabus-title',esc(sy.title))+div('db-syllabus-meta',esc(sy.meta))) +
      sy.items.map(function(it, i){
        var key = mid+':'+i;
        var open = state.acc[key] !== undefined ? state.acc[key] : (i===0);
        var numBg = open ? '#0E1F3D' : '#F3F4F6';
        var numColor = open ? '#fff' : '#0E1F3D';
        var headBg = open ? '#F7F8FA' : '#fff';
        var chevRotate = open ? 'rotate(180deg)' : 'rotate(0deg)';
        return div('db-sem-item',
          btn('db-sem-toggle', 
            div('db-sem-toggle-inner',
              div('db-sem-num',esc(it.n),'style="background:'+numBg+';color:'+numColor+'"') +
              div('db-sem-title',esc(it.title))
            ) +
            e('span','db-sem-chevron',SVG.chevGray,'style="display:inline-flex;transform:'+chevRotate+'"'),
            '',
            'data-action="toggleAcc" data-mid="'+mid+'" data-idx="'+i+'" style="background:'+headBg+'"'
          ) +
          (open ? div('db-sem-subs', it.subs.map(function(s){return div('db-sem-sub',div('db-sub-dot')+' '+esc(s));}).join('')) : '')
        );
      }).join('')
    );
  }
  function renderToolResult(tr) {
    return div('db-tool-result',
      div('db-tool-result-hero',
        div('db-tool-result-label',esc(tr.label),'style="color:'+esc(tr.labelColor||'#3B6D11')+'"') +
        div('db-tool-result-value',esc(tr.value)),
        'style="background:'+esc(tr.headBg||'#EAF3DE')+'"'
      ) +
      (tr.steps ? div('db-tool-steps',
        div('db-tool-steps-label','How to claim it') +
        tr.steps.map(function(st){
          return div('db-tool-step',div('db-tool-step-num',esc(st.n))+div('db-tool-step-text',esc(st.t)));
        }).join('')
      ) : '')
    );
  }

  /* Published facts with no bespoke card reuse the approved .db-info-card
     surface already used by the details overlay. No new classes. */
  function renderPublished(v) {
    return div('db-info-card',
      div('db-info-card-title', esc(v.title)) +
      (v.text ? div('db-info-card-body', esc(v.text)) : '') +
      ((v.tags || []).length
        ? div('db-accr-tags', v.tags.map(function (t) { return e('span','db-accr-tag',esc(t)); }).join(''))
        : '') +
      ((v.steps || []).length
        ? div('db-admission-steps', v.steps.map(function (t, i) {
            return div('db-admission-step', div('db-step-num', String(i+1)) + div('db-step-text', esc(t)));
          }).join(''))
        : '')
    );
  }

  /* ── Chips ── */
  function renderChips() {
    if (!state.chips.length) return '';
    return div('db-chips-area',
      (!state.started ? div('db-chips-hint','Or type your question below.') : '') +
      div('db-chip-grid', state.chips.map(function(ch,i){
        return btn('db-chip',esc(ch.label),'','data-action="chip" data-idx="'+i+'"');
      }).join('')) +
      (state.hasMore ? btn('db-more-btn','More ⌄','','data-action="chip" data-idx="-1"') : '')
    );
  }

  /* ── Tool widget ── */
  function renderToolWidget() {
    var t = state.tool;
    var def = toolChrome(t.kind);
    /* Questions, options and step counts are all backend-owned. */
    var len = Math.max(t.total || 0, t.idx + 1);
    var cur = { q: t.question || '', opts: (t.options || []).map(function (o) { return o.label; }) };
    var pct = ((t.idx+1)/len*100)+'%';
    var progress = (t.idx+1)+' of '+len;

    var header = div('db-tool-header',
      div('db-tool-header-left',
        div('db-tool-icon-badge',def.icon) +
        div('db-tool-title',esc(def.title))
      ) +
      btn('db-tool-close',SVG.x,'','data-action="closeTool"')
    );

    var body = '';
    if (t.phase==='entry') {
      body = div('db-tool-promise',esc(t.entryCopy || '')) +
        (t.total ? div('db-tool-step-badge', t.total + ' quick questions') : '') +
        btn('db-tool-start','Start','','data-action="toolBegin"');
    } else if (t.phase==='step') {
      var optsHtml = cur.opts.map(function(o,oi){
        var sel = t.answers[t.idx] && t.answers[t.idx].i===oi;
        return btn('db-tool-opt'+(sel?' selected':''),esc(o),'','data-action="toolAnswer" data-opt="'+esc(o)+'" data-oi="'+oi+'"');
      }).join('');
      body = div('db-tool-progress',
          div('db-progress-track',div('db-progress-fill','','style="width:'+pct+'"')) +
          e('span','db-progress-label',progress)
        ) +
        div('db-tool-question',esc(cur.q)) +
        div('db-tool-opts',optsHtml) +
        '';
    } else if (t.phase==='loading') {
      body = div('db-typing', div('db-dot')+div('db-dot')+div('db-dot'));
    } else if (t.phase==='partial') {
      body = div('db-tool-partial-box',
          div('db-tool-partial-check',SVG.checkWhite(14,2.8)) +
          div('db-tool-partial-text',esc(t.partialText || ''))
        ) +
        btn('db-tool-reveal','See my full result ›','','data-action="toolReveal"');
    } else if (t.phase==='lead') {
      body = div('db-tool-lead-text','Enter your details to see your full result.') +
        e('input','db-tool-name-input','','type="text" placeholder="Your name" data-action="toolName" value="'+esc(state.toolName)+'"') +
        div('db-tool-phone-row',
          e('span','db-tool-phone-prefix','+91') +
          e('input','db-tool-phone-input','','type="tel" placeholder="Your number" data-action="toolPhone" value="'+esc(state.toolPhone)+'"')
        ) +
        btn('db-tool-submit','Reveal my result','','data-action="toolSubmit"') +
        btn('db-tool-skip','Skip — show a general result','','data-action="toolSkip"');
    }

    return div('db-msg', '<div id="db-tool-widget">'+header+body+'</div>');
  }

  /* ── Picker ── */
  /* Shared by the full picker render and the keystroke-level list refresh. */
  function pickerListHtml() {
    var p = state.picker;
    var q = (p.query||'').toLowerCase();
    var live = Array.isArray(p.rows);
    var src = pickerRows();
    /* Server-side `q` already filtered live rows; only bundled rows need it. */
    var filtered = live ? src : src.filter(function(r){
      return !q || r.name.toLowerCase().includes(q) || (r.short||'').toLowerCase().includes(q);
    });
    /* Popular is a backend signal. Without it the section would just repeat
       the head of the list under a different heading. */
    var popular = filtered.filter(function(r){ return r.pop; });
    if (popular.length >= filtered.length) popular = [];
    var rowHtml = function(r) {
      return btn('db-picker-row',
        div('db-picker-mono',esc(r.mono),'style="background:'+r.bg+'"') +
        div('',div('db-picker-row-name',esc(r.name))+div('db-picker-row-meta',esc(r.meta))),
        '','data-action="pickItem" data-key="'+esc(r.name)+'" data-kind="'+p.kind+'"'
      );
    };
    if (p.loading && !filtered.length) return div('db-picker-empty','Loading…');
    return (!q && popular.length ? div('db-picker-section-label','⭐ Popular') + popular.map(rowHtml).join('') : '') +
      div('db-picker-section-label','All') +
      filtered.map(rowHtml).join('') +
      (filtered.length===0 ? div('db-picker-empty','Nothing matched. Try a shorter search.') : '');
  }

  function renderPicker() {
    var p = state.picker;
    return '<div id="db-picker">'+
      div('db-picker-scrim','','data-action="closePicker"') +
      div('db-picker-sheet',
        div('db-picker-header',
          div('db-picker-handle') +
          div('db-picker-title-row',
            div('db-picker-title',esc(p.title)) +
            btn('db-picker-close',SVG.x,'','data-action="closePicker"')
          ) +
          div('db-picker-search',
            SVG.search +
            e('input','db-picker-input','','placeholder="'+(p.kind==='uni'?'Search 56 universities…':'Search 40 disciplines…')+'" data-action="pickerInput" value="'+esc(p.query||'')+'"')
          )
        ) +
        div('db-picker-list', pickerListHtml())
      ) +
      '</div>';
  }

  /* ── Details overlay ── */
  function renderDetails() {
    var d = state.details;
    /* Only render a section when it actually has published content — an
       empty .db-info-card with just a heading is a visible blank strip. */
    var sections = [];
    if (d.hero) sections.push(div('db-info-card', div('db-info-card-body',esc(d.hero))));
    if (d.accr.length) sections.push(div('db-info-card', div('db-info-card-title','Accreditations') + div('db-accr-tags', d.accr.map(function(a){return e('span','db-accr-tag',esc(a));}).join(''))));
    if (d.steps.length) sections.push(div('db-info-card', div('db-info-card-title','Admission steps') + div('db-admission-steps', d.steps.map(function(s){return div('db-admission-step',div('db-step-num',esc(s.n))+div('db-step-text',esc(s.t)));}).join(''))));
    if (d.reviews.length) sections.push(div('db-info-card', div('db-info-card-title','What learners say') + div('db-review-items', d.reviews.map(function(r){return div('',div('db-review-name',esc(r.n))+div('db-review-text',esc(r.t)));}).join(''))));
    if (d.faqs.length) sections.push(div('db-info-card', div('db-info-card-title','FAQs') + div('db-faq-items', d.faqs.map(function(f){return div('',div('db-faq-q',esc(f.q))+div('db-faq-a',esc(f.a)));}).join(''))));
    return '<div id="db-details">'+
      div('db-details-header',
        btn('db-details-back', SVG.back+'Back','','data-action="closeDetails"') +
        div('db-details-title-row',
          div('db-details-mono',esc(d.mono),'style="background:'+d.bg+'"') +
          div('',div('db-details-name',esc(d.title))+div('db-details-trust',esc(d.trust)))
        )
      ) +
      div('db-details-body',
        div('db-details-pills', d.pills.map(function(p){return div('db-details-pill',esc(p));}).join('')) +
        sections.join('')
      ) +
      div('db-details-footer', btn('db-cta-primary','Ask about fees & EMI','','data-action="detailsCtaFees"')) +
      '</div>';
  }

  /* ── End screen ── */
  function renderEndScreen() {
    var e2 = state.endScreen;
    var firstName = e2.name ? e2.name.split(' ')[0] : 'there';
    var headLabel = e2.kind==='roi' ? 'Your ROI result' : 'Scholarship unlocked';
    var heroValue = e2.kind==='roi' ? (e2.months+' months') : (e2.waiver+' off');
    var heroSub = e2.kind==='roi' ? 'estimated payback period' : 'applied to your first-semester fee';

    var detail = '';
    if (e2.kind==='roi') {
      detail = div('db-info-card',
        div('db-info-card-title', esc(e2.program)+' · the maths') +
        div('db-roi-stats',
          div('db-roi-stat',div('db-roi-stat-label','Investment')+div('db-roi-stat-value',esc(e2.invest))) +
          div('db-roi-stat',div('db-roi-stat-label','Avg salary')+div('db-roi-stat-value',esc(e2.avgSalary))) +
          div('db-roi-stat',div('db-roi-stat-label','EMI/mo')+div('db-roi-stat-value',esc(e2.emi)))
        ) +
        div('db-roi-verdict',esc(e2.verdict))
      );
    } else {
      detail = div('db-info-card',
        div('db-schol-fee-row',
          div('',div('db-schol-net-label','Your fee after waiver')+div('db-schol-net-value',esc(e2.net))) +
          div('',div('db-schol-std-label','Standard fee')+div('db-schol-std-value',esc(e2.standard || 'Not published')))
        ) +
        div('db-schol-divider') +
        div('db-schol-reasons-label','Why you qualified') +
        div('db-schol-reasons', e2.reasons.map(function(r){return e('span','db-schol-reason',SVG.checkGreen+' '+esc(r));}).join(''))
      ) +
      div('db-info-card',
        div('db-info-card-title','How to claim it') +
        e2.steps.map(function(st){ return div('db-tool-step',div('db-tool-step-num',esc(st.n))+div('db-tool-step-text',esc(st.t))); }).join('') +
        div('db-offer-locked', SVG.clock + 'Offer locked for 7 days')
      );
    }

    return '<div id="db-end-screen">'+
      div('db-end-header',
        div('db-end-header-top',
          div('db-end-brand', div('db-end-brand-badge','DB')+e('span','db-end-brand-label','DegreeBaba Assistant')) +
          btn('db-end-close',SVG.close.replace('stroke="#fff"','stroke="#fff"'),'','data-action="closeEnd"')
        ) +
        div('db-end-hero',
          div('db-end-check-ring',div('db-end-check-inner',SVG.checkWhite(21,2.6))) +
          div('db-end-head-label',esc(headLabel)) +
          div('db-end-hero-value',esc(heroValue)) +
          div('db-end-hero-sub',esc(heroSub))
        )
      ) +
      div('db-end-body',
        div('db-end-confirm',
          div('db-end-confirm-icon',SVG.phone) +
          div('',
            div('db-end-confirm-name','Locked in, '+esc(firstName)+'.') +
            div('db-end-confirm-sub','A counsellor will call '+e('span','db-end-confirm-phone',esc(e2.masked))+' within 30 minutes to confirm this offer. No spam.')
          )
        ) +
        detail
      ) +
      div('db-end-footer',
        btn('db-cta-primary','See matching programs','','data-action="endPrograms"') +
        btn('db-cta-secondary','Back to chat','','data-action="closeEnd"')
      ) +
      '</div>';
  }

  /* ── Main render ── */
  function render() {
    if (!windowEl) return;

    /* Launcher icon */
    launcher.innerHTML = state.open ? SVG.close : SVG.chat;

    /* Window visibility */
    windowEl.style.display = state.open ? 'flex' : 'none';
    if (!state.open) return;

    /* Build inner HTML */
    var html = '';

    /* Header */
    html += '<div id="db-header">'+
      div('db-header-inner',
        div('db-avatar','DB') +
        div('db-header-text',
          div('db-bot-name', esc(cfg.botName)) +
          div('db-status', e('span','db-status-dot')+'Online · replies instantly')
        ) +
        btn('db-close-btn', SVG.chevDown, 'db-close-btn-el')
      ) +
      '</div>';

    /* Context chip */
    if (state.context) {
      html += '<div id="db-context-bar">'+
        div('db-context-chip',
          div('db-context-dot') +
          esc(state.context.label) +
          btn('db-context-clear', SVG.x10, '', 'data-action="clearContext"')
        ) +
        '</div>';
    }

    /* Messages */
    var msgsHtml = state.msgs.map(renderMsg).join('');
    /* Tool widget (inline) */
    if (state.tool) msgsHtml += renderToolWidget();
    /* Chips */
    if (state.chips.length && !state.tool) msgsHtml += renderChips();

    html += '<div id="db-messages">'+msgsHtml+'</div>';

    /* Compare bar */
    if (state.compare.length===2) {
      html += '<div id="db-compare-bar">'+
        btn('db-compare-run-btn', SVG.compare + 'Compare '+state.compare.length+' selected', '', 'data-action="runCompare"') +
        '</div>';
    }

    /* Input bar */
    var sendActive = (state.input||'').trim().length>0;
    var inputBorder = state.inputFocused ? '#0E1F3D' : '#E5E7EB';
    html += '<div id="db-input-bar">'+
      div('db-input-wrapper'+(state.inputFocused?' focused':''),
        e('input','db-input','','placeholder="Type your question…" id="db-input-el" value="'+esc(state.input)+'" autocomplete="off"'),
        'style="border-color:'+inputBorder+'"'
      ) +
      btn('db-send-btn'+(sendActive?' active':''), SVG.send, 'db-send-btn-el') +
      '</div>';

    /* Overlays */
    if (state.picker) html += renderPicker();
    if (state.details) html += renderDetails();
    if (state.endScreen) html += renderEndScreen();

    windowEl.innerHTML = html;

    /* Re-query scroll target */
    scrollEl = windowEl.querySelector('#db-messages');

    /* Bind events */
    bindEvents();
  }

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
    delegatesBound = true;

    /* Clear context */
    delegate('[data-action="clearContext"]', function(){ clearContext(); });

    /* Chip clicks */
    delegate('[data-action="chip"]', function(el){
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
      var name = el.getAttribute('data-key');
      var row = pickerRows().find(function(r){return r.name===name;});
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
      state.details = null;
      showInfoCard('get_fees', { label: '💰 Fees & EMI', handler: 'get_fees' });
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

  /* ─────────────────────────────────────────────────────────────
     8. PUBLIC API
  ───────────────────────────────────────────────────────────── */
  function init(options) {
    if (options) {
      if (options.botName)        cfg.botName = options.botName;
      if (options.primaryColor)   cfg.primaryColor = options.primaryColor;
      if (options.position)       cfg.position = options.position;
      if (options.page)           cfg.page = options.page;
      if (options.apiUrl)         cfg.apiUrl = options.apiUrl;
      if (options.apiBase)        cfg.apiBase = options.apiBase;
      if (options.siteKey)        cfg.siteKey = options.siteKey;
      if (options.widgetId)     { cfg.widgetId = options.widgetId; cfg.siteKey = options.widgetId; }
      if (options.entitySlug)     cfg.entitySlug = options.entitySlug;
      if (options.universitySlug) cfg.universitySlug = options.universitySlug;
    }
    /* apiUrl may point at the /chat endpoint; the API base is its origin. */
    if (!cfg.apiBase && cfg.apiUrl) {
      try { cfg.apiBase = new URL(cfg.apiUrl, window.location.href).origin; }
      catch (err) { cfg.apiBase = ''; }
    }
    applyTheme(cfg.primaryColor);
  }

  /* ─────────────────────────────────────────────────────────────
     9. AUTO-INIT
  ───────────────────────────────────────────────────────────── */
  function bootstrap() {
    injectGoogleFonts();

    /* Documented public embed contract — see README.md. Do not rename these:
       host pages in production already ship them. */
    var scriptTag = document.currentScript || bootScript;
    if (scriptTag) {
      var key = scriptTag.getAttribute('data-site-key');
      if (key) cfg.siteKey = key;
      var pageType = scriptTag.getAttribute('data-page-type');
      if (pageType) cfg.page = pageType;
      var ent = scriptTag.getAttribute('data-page-entity-slug');
      if (ent) cfg.entitySlug = ent;
      var uni = scriptTag.getAttribute('data-page-university-slug');
      if (uni) cfg.universitySlug = uni;
      if (scriptTag.getAttribute('data-auto-open') === 'true') { cfg.autoOpen = true; cfg.autoOpenPinned = true; }
      var pos = scriptTag.getAttribute('data-position');
      if (pos) cfg.position = pos;
      var api = scriptTag.getAttribute('data-api-base');
      if (api) cfg.apiBase = api;
      /* Default the API to the origin the widget was served from. */
      if (!cfg.apiBase && scriptTag.src) {
        try { cfg.apiBase = new URL(scriptTag.src, window.location.href).origin; }
        catch (err) { cfg.apiBase = ''; }
      }
    }
    if (!cfg.apiBase && cfg.apiUrl) {
      try { cfg.apiBase = new URL(cfg.apiUrl, window.location.href).origin; }
      catch (err) { cfg.apiBase = ''; }
    }

    mount();

    if (cfg.apiBase) {
      loadConfig().then(function () {
        /* Branding lands before first paint of the header in most cases. */
        if (state.open) render();
        if (cfg.autoOpen && !state.open) {
          state.open = true;
          launcher.setAttribute('aria-label', 'Close chat');
          resetChat();
        }
      }).catch(function (err) {
        console.warn('DegreeBaba widget config unavailable; using defaults', err);
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrap);
  } else {
    bootstrap();
  }

  /* Expose public API */
  window.DegreeBabaWidget = {
    init: init,
    reset: function(options) {
      init(options);
      resetChat();
    }
  };
  /* Legacy alias */
  window.ChatWidget = window.DegreeBabaWidget;

})();
