  

  /* ── Guided-command bridge ────────────────────────────────── */

  /* ActiveFlow tools use a dedicated guided endpoint. Only predefined tool
     tokens reach this function; no user-authored text is accepted. */
  function dispatchGuidedCommand(message, opts) {
    var options = opts || {};
    var userLabel = options.echo === false ? null : (options.label || message);

    var items = [];
    if (userLabel) items.push({ kind: 'user', text: userLabel, id: nextId() });
    var tid = nextId();
    state.started = true;
    state.chips = [];
    state.hasMore = false;
    state.busy = true;
    state.msgs = state.msgs.concat(items);
    render();
    scrollToBottom();

    return postGuideTool(message, options.chip).then(function (payload) {
      applyPayload(payload, options);
      return payload;
    }).catch(function (err) {
      console.warn('DegreeBaba widget falling back to local content', err);
      state.busy = false;
      if (options.onFail) options.onFail(err);
      else settleTurn(tid, [{ kind: 'bot', text: UNAVAILABLE }], null);
      return null;
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
    get_admission_steps:   ['admissions',     'admissions'],
    get_validity:          ['validity',       'validity']
  };

  function pushHistory() {
    if (!state.historyStack) state.historyStack = [];
    if (state.historyStack.length >= 25) state.historyStack.shift();
    state.historyStack.push({
      context: state.context ? Object.assign({}, state.context) : null,
      msgs: state.msgs.slice(),
      chips: state.chips.slice(),
      hasMore: state.hasMore,
      moreChips: state.moreChips ? state.moreChips.slice() : null,
      moreOpen: state.moreOpen,
      conversionChip: state.conversionChip ? Object.assign({}, state.conversionChip) : null,
      compare: state.compare.slice(),
      details: state.details ? Object.assign({}, state.details) : null,
      picker: state.picker ? Object.assign({}, state.picker) : null,
      server: state.server ? Object.assign({}, state.server) : null,
      breadcrumb: state.breadcrumb ? state.breadcrumb.slice() : []
    });
  }

  function onChip(ch) {
    pushHistory();
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
    if (handler === 'change_number') { reopenLeadForm(); return; }
    if (handler === 'compare_view') { if (ch.entityRef) switchEntity({ type: ch.entityRef.type || ctxPageType(), id: ch.entityRef.entityId, label: ch.entityRef.title }); return; }
    if (handler === 'compare_again') { openComparePicker(ch, ch.entityRef); return; }
    if (handler === 'compare_explore') { openPicker(COMPARE_PICKER_KIND[ctxPageType()] === 'uni' ? PICKER_HANDLERS.list_universities : { kind: COMPARE_PICKER_KIND[ctxPageType()], title: 'Explore another option' }, ch); return; }
    if (handler === 'cta_apply' || handler === 'cta_callback') { openLeadTurn(ch); return; }
    /* §2.2 a list_set is an enumeration: render it inline so the user can scan
       and pick. Only overflow (7+) hands off to the picker sheet. Sending every
       list straight to a modal is what buried short lists. */
    /* §7 tier-2 backfill chips carry a published FAQ; the answer travels in
       the same guide bundle, so it never needs a round trip. */
    if (handler === 'get_faq') { showFaqAnswer(ch); return; }
    if (PICKER_HANDLERS[handler]) {
      if (ch.chip_type === 'list_set') { showListSet(PICKER_HANDLERS[handler], ch); return; }
      openPicker(PICKER_HANDLERS[handler], ch);
      return;
    }
    if (INFO_HANDLERS[handler]) { showInfoCard(handler, ch); return; }

    console.warn('DegreeBaba widget has no guided surface for chip handler', handler);
    loadFollowups(null, ch).catch(function () {});
  }

  /* Strip the leading glyph the chip label carries so the question text can
     be matched against the published FAQ rows. */
  function faqQuestionOf(chip) {
    return String(chip.label || '').replace(/^\s*[^\w(]+\s*/, '').trim();
  }

  /* Answer a published FAQ from the bundle. Matched on question text, not on
     chip index: the chip id counts raw catalog rows while the bundle may omit
     unpublished ones, and an off-by-one would answer the wrong question. */
  function showFaqAnswer(chip) {
    var tid = beginTurn(chip.label);
    ensureGuideBundle().then(function (bundle) {
      var faqs = ((bundle && bundle.entity && bundle.entity.details) || {}).faqs || [];
      var wanted = faqQuestionOf(chip).toLowerCase();
      var match = faqs.find(function (f) {
        return String(f.question || '').trim().toLowerCase() === wanted;
      });
      if (!match || !String(match.answer || '').trim()) {
        unavailableTurn(tid, UNAVAILABLE);
        return null;
      }
      settleTurn(tid, [{ kind: 'faq', faq: { q: match.question, a: match.answer } }], null);
      emitAnalytics('card_shown', chip, { entity: analyticsEntity() });
      return loadFollowups(null, chip);
    }).catch(function (err) {
      console.warn('DegreeBaba widget FAQ answer unavailable', err);
      unavailableTurn(tid, UNAVAILABLE);
    });
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

  /* A recommendation card may describe an entity other than the current page.
     Resolve that exact catalog id through the guided context endpoint before
     showing its fee card; never turn the card title into a text query. */
  function showEntityFees(entityId, chip) {
    var tid = beginTurn(chip.label);
    loadGuideContext(null, { entityId: entityId }).then(function (bundle) {
      applyBundleContext(bundle);
      var data = bundle && bundle.info && bundle.info.fees;
      if (!data || !data.available) { unavailableTurn(tid, UNAVAILABLE); return; }
      settleTurn(tid, infoCardMsgs('get_fees', 'fees', data), null);
      var opening = bundle.opening || {};
      setChips(opening.top || [], opening.more || []);
      render(); scrollToBottom();
    }).catch(function (err) {
      console.warn('DegreeBaba widget entity fees unavailable', err);
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
    var sides = state.compare.slice(0, 2);
    var tid = beginTurn(chip && chip.label ? chip.label : 'Compare');
    postJson('/api/widget/guide/compare', { entity_ids: ids.slice(0, 3) }).then(function (card) {
      state.compare = [];
      /* Two entities are on screen now — the single-entity context pill
         from before the comparison would misleadingly point at only one. */
      state.context = null;
      var view = compareFrom(card);
      settleTurn(tid, [view], null);
      emitAnalytics('card_shown', chip, { entity: analyticsEntity() });
      /* §2 post-comparison chips: act on either side, or pivot to a third.
         Use the card's resolved names so the two "View" chips are distinct
         even when both programmes share a name. */
      if (sides[0]) sides[0].viewLabel = view.aName;
      if (sides[1]) sides[1].viewLabel = view.bName;
      return loadFollowups('comparison', chip).then(function () {
        prependComparisonChips(sides);
      });
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
    var captured = state.lead && state.lead.captured;
    var copy = captured
      /* §4 already captured: acknowledge quietly, offer a change-number path,
         never re-render the form. */
      ? ('Thanks' + (state.lead.name ? ', ' + state.lead.name : '') +
         ' — a counsellor will call the number you shared. No spam.')
      : (chip.handler === 'cta_apply'
        ? 'Happy to help you apply. Share your details and a counsellor will guide you through it — no spam.'
        : 'Happy to connect you. Share your details and a counsellor will call within 30 minutes — no spam.');
    var body = captured
      ? [{ kind: 'bot', text: copy }]
      : [{ kind: 'lead', text: copy }];
    if (!captured) emitAnalytics('lead_form_shown', chip);
    postGuideChips(null, chip.chip_id, cardTypeForContext())
      .then(function (res) {
        adoptServerContext(res);
        var followup = (res && res.followup) || {};
        var chips = (followup.actions || []).slice();
        if (captured) chips.unshift({ label: '✏️ Change number', handler: 'change_number', chip_id: 'change_number' });
        settleTurn(tid, body, null);
        setChips(chips, followup.more || [], followup.conversion);
        render(); scrollToBottom();
      })
      .catch(function (err) {
        console.warn('DegreeBaba widget could not persist the conversion chip', err);
        settleTurn(tid, body, null);
        if (captured) setChips([{ label: '✏️ Change number', handler: 'change_number', chip_id: 'change_number' }], []);
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
        setChips(followup.actions || [], followup.more || [], followup.conversion);
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
  /* §2.2 fetch the enumeration and render it inline as a list_set. The rows
     are catalog entities, so each one is a doorway to that entity (§11.1). */
  function showListSet(spec, chip) {
    var tid = beginTurn(chip.label);
    listFiltersFor(spec.kind).then(function (filters) {
      return loadGuideCatalog(spec.kind, filters);
    }).then(function (rows) {
      if (!rows.length) { unavailableTurn(tid, UNAVAILABLE); return null; }
      settleTurn(tid, [{ kind: 'bot', text: listPrompt(chip, rows.length) }], null);
      var inlineMax = chip.list_inline_max || 6;
      var compact = rows.length <= inlineMax;
      state.chips = rows.map(function (row) {
        return {
          label: row.name,
          /* the 2-col grid has no room for the full catalog meta line */
          meta: compact ? shortMeta(row) : row.meta,
          mono: row.mono, bg: row.bg,
          chip_type: 'list_set', handler: 'list_pick', listRow: row,
          list_inline_max: chip.list_inline_max || 6,
          list_show_top: chip.list_show_top || 5,
          chip_id: chip.chip_id, chip_surface: chip.chip_surface
        };
      });
      state.moreChips = [];
      state.hasMore = false;
      state.listChip = chip;
      /* §2.2 the conversion chip keeps its reserved slot below a divider. */
      return postGuideChips(null, chip.chip_id, cardTypeForContext())
        .then(function (res) {
          adoptServerContext(res);
          var followup = (res && res.followup) || {};
          state.conversionChip = followup.conversion ? chipFrom(followup.conversion) : null;
          render(); scrollToBottom();
        }).catch(function () { render(); scrollToBottom(); });
    }).catch(function (err) {
      console.warn('DegreeBaba widget list unavailable', err);
      unavailableTurn(tid, UNAVAILABLE);
    });
  }

  /* One distinguishing fact for the compact grid: fee if published, else the
     first meta segment. Never the whole line — it cannot fit two-up. */
  function shortMeta(row) {
    var raw = String(row.meta || '');
    var fee = raw.match(/(?:INR|₹)\s?[\d,]+/);
    if (fee) return money(fee[0]);
    var first = raw.split('·')[0];
    return first ? first.trim() : '';
  }

  function listPrompt(chip, count) {
    var label = String(chip.label || '').replace(/^[^A-Za-z]+/, '');
    return count === 1
      ? 'One option — pick it to see the details.'
      : label + ' — ' + count + ' options. Pick one to continue.';
  }

  /* Reuse exactly the scoping refreshPicker() applies, so an inline list and
     its picker overflow always show the same rows. */
  function listFiltersFor(kind) {
    var filters = {};
    if (kind === 'spec' || kind === 'program' || kind === 'course') {
      if (ctxUniversityId()) filters.university = ctxUniversityId();
    }
    if (kind === 'spec' && ctxPageType() === 'course' && ctxEntityId()) filters.course = ctxEntityId();
    return Promise.resolve(filters);
  }

  /* §11 switching the active entity is a session action: the backend resolves
     the entity, restores its per-entity consumed pool, and returns the
     breadcrumb/rail. The widget only renders the result. */
  function switchEntity(item) {
    if (!item || !item.id) return;
    state.guideBundle = null;
    state.pickerCache = {};
    var tid = beginTurn(item.label);
    loadGuideContext(item.type || null, {
      entityId: item.id,
      universityId: item.type === 'university' ? item.id : ctxUniversityId()
    }).then(function (bundle) {
      if (!bundle || !bundle.entity) { unavailableTurn(tid, UNAVAILABLE); return; }
      applyBundleContext(bundle);
      settleTurn(tid, [{ kind: 'cards', cards: [cardFrom(bundle.entity)] }], null);
      return loadFollowups(null, null);
    }).catch(function (err) {
      console.warn('DegreeBaba widget entity switch failed', err);
      unavailableTurn(tid, UNAVAILABLE);
    });
  }

  /* §9 Main menu returns to this page's opening set with chips reset to
     unconsumed, which is also the escape hatch out of any exhausted pool. */
  /* Delta §6: Main Menu returns the homepage chip set. The active entity and
     breadcrumb reset; the recently-viewed rail, per-entity consumed chips and
     the captured lead all survive (backend `main_menu` scope). */
  function goMainMenu() {
    var tid = beginTurn(null);
    /* Clear only the client's view of the active entity; the rail and lead are
       re-adopted from the server response. */
    cfg.page = 'homepage'; cfg.entitySlug = null; cfg.universitySlug = null;
    state.server.pageType = 'homepage';
    state.server.entityId = null;
    state.server.universityId = null;
    state.guideBundle = null;
    postJson('/api/widget/context/clear', Object.assign(
      { scope: 'main_menu' }, state.sessionId ? { session_id: state.sessionId } : {}
    )).catch(function () { /* the homepage load below still stands */ })
      .then(function () { return loadGuideContext('homepage', { entityId: null, universityId: null }); })
      .then(function (bundle) {
        adoptServerContext(bundle);
        applyBundleContext(bundle);
        var opening = bundle.opening || {};
        settleTurn(tid, [{ kind: 'bot', text: 'Main menu — where would you like to go?' }], null);
        setChips(opening.top || [], opening.more || [], opening.conversion);
        render(); scrollToBottom();
      }).catch(function (err) {
        console.warn('DegreeBaba widget main menu unavailable', err);
        unavailableTurn(tid, UNAVAILABLE);
      });
  }

  /* §9 Back steps one level up the breadcrumb — the entity cascade, not the
     raw message history, is what a user means by "back". */
  function goBack() {
    if (state.historyStack && state.historyStack.length > 0) {
      var prev = state.historyStack.pop();
      state.context = prev.context;
      state.msgs = prev.msgs;
      state.chips = prev.chips;
      state.hasMore = prev.hasMore;
      state.moreChips = prev.moreChips;
      state.moreOpen = prev.moreOpen;
      state.conversionChip = prev.conversionChip;
      state.compare = prev.compare;
      state.details = prev.details;
      state.picker = prev.picker;
      if (prev.server) state.server = prev.server;
      if (prev.breadcrumb) state.breadcrumb = prev.breadcrumb;
      render();
      scrollToBottom();
      return;
    }
    var crumbs = state.breadcrumb || [];
    if (crumbs.length < 2) return;
    switchEntity(crumbs[crumbs.length - 2]);
  }

  /* §2.2 list overflow: reuse the picker sheet the catalog browser already
     uses, seeded with the same rows the list was rendering. */
  function openListOverflowPicker() {
    var chip = state.lastChip;
    var handler = (chip && chip.handler) || '';
    var spec = PICKER_HANDLERS[handler];
    if (spec) { openPicker(spec, chip); return; }
    state.picker = {
      title: 'Choose an option', kind: 'uni', query: '',
      rows: null, loading: true, chip: chip || null
    };
    render();
    refreshPicker('');
  }

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

    /* §1.2 comparison opponents come from the backend validity-filtered set. */
    var source = p.opponentsFor
      ? loadOpponents(p.opponentsFor).then(function (rows) {
          if (query) {
            var q = query.toLowerCase();
            return rows.filter(function (r) { return r.name.toLowerCase().indexOf(q) >= 0; });
          }
          return rows;
        })
      : loadGuideCatalog(p.kind, filters);
    source.then(function (rows) {
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
  /* §2 render the post-comparison action set: view either side, compare A
     again, or explore another entity of the same type. Prepended ahead of the
     server\'s comparison follow-ups so the pivot actions lead. */
  function prependComparisonChips(sides) {
    if (!sides || sides.length < 2) return;
    var a = sides[0], b = sides[1];
    var aLabel = a.viewLabel || a.title, bLabel = b.viewLabel || b.title;
    var typeLabel = { university: 'university', course: 'program', specialization: 'specialization' }[ctxPageType()] || 'option';
    var pivot = [
      { label: '📇 View ' + aLabel, handler: 'compare_view', entityRef: a, chip_id: 'compare_view_a' },
      { label: '📇 View ' + bLabel, handler: 'compare_view', entityRef: b, chip_id: 'compare_view_b' },
      { label: '⚖️ Compare ' + aLabel + ' with another', handler: 'compare_again', entityRef: a, chip_id: 'compare_again' },
      { label: '🔄 Explore another ' + typeLabel, handler: 'compare_explore', chip_id: 'compare_explore' }
    ];
    var existing = {};
    state.chips.forEach(function (c) { existing[c.chip_id || c.label] = true; });
    state.chips = pivot.concat(state.chips.filter(function (c) { return !existing[c.chip_id]; }));
    render(); scrollToBottom();
  }

  /* §1.2/§2 the opponent list is validity-filtered by the backend and keyed to
     the entity being compared. `fixedSide` (from "Compare A with another")
     keeps A fixed and picks a fresh B. */
  function openComparePicker(chip, fixedSide) {
    var kind = COMPARE_PICKER_KIND[ctxPageType()] || 'uni';
    var side = fixedSide || (state.compare.length ? state.compare[0] : null);
    render();
    ensureGuideBundle().then(function (bundle) {
      var entity = (bundle && bundle.entity) || null;
      /* Anchor: an explicit fixed side, else the entity in view. */
      var anchor = side || (entity && entity.id === ctxEntityId() ? cardFrom(entity) : null);
      var anchorId = anchor && anchor.entityId;
      if (!anchorId) { unavailableTurn(beginTurn(chip && chip.label), UNAVAILABLE); return; }
      state.compare = [anchor];
      state.picker = {
        title: COMPARE_PICKER_TITLE[kind], kind: kind, query: '',
        rows: null, loading: true, chip: chip || null, compareMode: true,
        opponentsFor: anchorId
      };
      render();
      refreshPicker('');
    }).catch(function () {
      unavailableTurn(beginTurn(chip && chip.label), UNAVAILABLE);
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
      /* §8 which pairing the user actually chose. */
      emitAnalytics('compare_opponent_selected', chip, {
        attributes: { a: state.compare[0].entityId, b: state.compare[1].entityId }
      });
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
      /* beginTurn() clears the chips row while the picker opens. The picker
         is an overlay, not a replacement for the guided surface, so
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
    if (!cfg.apiBase) return;
    var mark = function (patch) {
      state.msgs = state.msgs.map(function (m) { return m.id === id ? Object.assign({}, m, patch) : m; });
      render();
    };
    var msg = state.msgs.find(function (m) { return m.id === id; });
    if (msg && msg.leadBusy) return;   // §5.1 inert while a submit is in flight

    /* §3.2/§3.3 client validation. On failure, re-prompt with the offending
       field and record which field drove the drop-off (§8). */
    if (!leadNameValid(state.leadName)) {
      emitAnalytics('lead_form_validation_failed', state.lastChip, { attributes: { field: 'name' } });
      mark({ leadError: 'Please enter your name (letters only).' });
      return;
    }
    if (!leadPhoneValid(state.leadPhone)) {
      emitAnalytics('lead_form_validation_failed', state.lastChip, { attributes: { field: 'phone' } });
      mark({ leadError: 'Enter a valid 10-digit mobile number.' });
      return;
    }

    /* §5.2 one request id per submission attempt; a retry of the same tap is
       idempotent on the backend. */
    if (!msg.leadRequestId) msg.leadRequestId = 'lead-' + nextId() + '-' + Date.now();
    mark({ leadBusy: true, leadError: '' });
    var name = state.leadName, phone = normalisePhone(state.leadPhone);
    postLead(phone, name, 'widget_inline', state.lastChip, msg.leadRequestId).then(function (res) {
      emitAnalytics('lead_form_submitted', state.lastChip);
      /* §4 remember the capture for the rest of the session. */
      state.lead = { captured: true, name: name };
      state.leadPhone = ''; state.leadName = '';
      mark({ leadBusy: false, leadDone: true });
      if (res && res.response) applyPayload(res.response, { toolAware: false });
    }).catch(function (err) {
      console.warn('DegreeBaba widget lead capture failed', err);
      var soft = err && err.status === 422;
      mark({ leadBusy: false, leadError: soft
        ? 'That number looks off — please check and try again.'
        : 'That did not go through. Please try again.' });
    });
  }

  /* §5.1 flip the Submit button without a full re-render, so typing keeps
     focus. Called on every keystroke in the form. */
  function updateLeadSubmit(el) {
    var form = el.closest ? el.closest('.db-lead') : null;
    if (!form) return;
    var submit = form.querySelector('.db-lead-submit');
    if (!submit) return;
    var ok = leadNameValid(state.leadName) && leadPhoneValid(state.leadPhone);
    submit.disabled = !ok;
    if (ok) submit.classList.remove('db-lead-submit--disabled');
    else submit.classList.add('db-lead-submit--disabled');
  }

  /* §4 the only path back to the form once a lead exists. */
  function reopenLeadForm() {
    state.lead = null;
    state.leadName = ''; state.leadPhone = '';
    var tid = beginTurn(null);
    settleTurn(tid, [{ kind: 'lead', text: 'Prefer a different number? Enter it below.' }], null);
    emitAnalytics('lead_form_shown', state.lastChip);
    loadFollowups(null, state.lastChip).catch(function () {});
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

    dispatchGuidedCommand('tool:' + TOOL_TOKEN_BY_KIND[kind], {
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
    dispatchGuidedCommand(remote.message, { echo: false, onFail: function () { closeTool('transport_error'); } });
  }

  /* The partial → lead gate: `tool:continue` moves the flow to await_lead. */
  function toolReveal() {
    var t = state.tool;
    if (!t) return;
    state.tool = Object.assign({}, t, { phase: 'loading' });
    render();
    dispatchGuidedCommand('tool:continue', { echo: false, onFail: function () { closeTool('transport_error'); } });
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
    openPicker({ kind: 'program', title: 'Browse programs' }, state.lastChip);
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
    state.leadPhone = ''; state.toolName = ''; state.toolPhone = '';
    state.started = false; state.ready = false;
    state.guideBundle = null; state.guideBusy = null; state.busy = false;
    state.viewedActions = new Set();
    state.pickerCache = {};
    render(); scrollToBottom();
    loadOpening();
  }

  function loadOpening() {
    if (!cfg.apiBase) { state.ready = true; render(); return; }
    ensureGuideBundle().then(function (bundle) {
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
      state.msgs = state.msgs.concat([{ kind: 'bot', text: UNAVAILABLE, id: nextId() }]);
      state.ready = true;
      render(); scrollToBottom();
    });
  }
