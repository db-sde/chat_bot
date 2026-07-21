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
