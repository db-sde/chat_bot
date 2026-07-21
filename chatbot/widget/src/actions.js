  

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
      /* Two entities are on screen now — the single-entity context pill
         from before the comparison would misleadingly point at only one. */
      state.context = null;
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
    /* A category-scoped course list (drill-down from Browse Programs, or
       comparing a course against the same programme elsewhere) spans
       universities by design — the category is the only filter. */
    if (p.kind === 'course' && p.course) filters = query ? { q: query, course: p.course } : { course: p.course };

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
    course: 'course', specialization: 'spec'
  };
  var COMPARE_PICKER_TITLE = {
    uni: 'Choose two universities to compare',
    course: 'Choose two programs to compare',
    spec: 'Choose two specializations to compare'
  };

  /* "Compare" with fewer than two options selected opens a real picker
     instead of telling the user to do something the UI gives them no way
     to do. Picking two rows here compares by entity_id, same as tapping
     "+ Compare" on two recommendation cards.

     A user who taps "Compare" while already looking at something (a
     university/course/specialization page) means "compare THIS against
     something else" — not "let me pick two unrelated things from scratch".
     So the entity they're already on pre-fills as the first side. */
  function openComparePicker(chip) {
    var kind = COMPARE_PICKER_KIND[ctxPageType()] || 'uni';
    state.picker = {
      title: COMPARE_PICKER_TITLE[kind], kind: kind, query: '',
      rows: null, loading: true, chip: chip || null, compareMode: true
    };
    render();

    /* The bundle supplies both halves of the setup: the current entity
       pre-fills as the first side (a user on a page comparing means
       "compare THIS against something else"), and on a course page its
       category scopes the list to the same programme at other
       universities — comparing one university's MCA against its own BCom
       is not what anyone means by "compare this program". */
    ensureGuideBundle().then(function (bundle) {
      var p = state.picker;
      if (!p || !p.compareMode) return;
      var entity = (bundle && bundle.entity) || null;
      if (kind === 'course' && entity && entity.category) {
        state.picker = p = Object.assign({}, p, { course: String(entity.category) });
      }
      if (!state.compare.length && entity && entity.id === ctxEntityId()) {
        state.compare = [cardFrom(entity)];
      }
      refreshPicker(p.query || '');
    }).catch(function () {
      refreshPicker('');
    });
  }

  function pickCompareItem(row) {
    var entry = { entityId: row.id, title: row.name, mono: row.mono, bg: row.bg };
    var key = entry.entityId || entry.title;
    var wasSelected = !!state.compare.find(function (c) { return (c.entityId || c.title) === key; });

    if (wasSelected) {
      /* Tapping an already-picked row un-picks it. This is purely a list
         edit — the picker stays open so the user can choose someone else. */
      state.compare = state.compare.filter(function (c) { return (c.entityId || c.title) !== key; });
      renderPickerList();
      return;
    }

    var chip = state.picker && state.picker.chip;
    state.compare = state.compare.length >= 2
      ? [state.compare[1], entry]
      : state.compare.concat([entry]);

    /* Two selected: compare immediately, no extra tap. */
    if (state.compare.length >= 2) {
      state.picker = null;
      state.pickerToken++;
      runGuidedComparison(chip || { label: 'Compare' });
      return;
    }

    renderPickerList();
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
      entityId: card.entityId || null,
      /* Disambiguates same-named programmes when the CTA has to go through
         chat ("MBA" alone could be any university's). */
      queryName: [c.university_name, card.title].filter(Boolean).join(' '),
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
