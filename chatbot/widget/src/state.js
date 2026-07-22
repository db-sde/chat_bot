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
    leadPhone: '',
    toolName: '',
    toolPhone: '',
    started: false,
    uid: 0,
    /* ── backend-bound state ── */
    sessionId: null,       // issued by guided widget endpoints
    guideBundle: null,     // GET /api/widget/guide/context payload
    pickerCache: {},       // cacheKey -> normalized rows
    pickerToken: 0,        // guards out-of-order picker searches
    busy: false,           // a guided backend command is in flight
    moreChips: null,
    moreOpen: false,          // §10 the More panel is collapsed by default
    conversionChip: null,     // §8 the reserved conversion slot
    breadcrumb: [],           // §11.4
    recentlyViewed: [],       // §11.3,       // config-owned "More ⌄" set from /guide/context
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
    autoOpen: false,
    autoOpenPinned: false,
    welcomeMessage: null
  };

  function nextId() { return 'm' + (++state.uid); }
