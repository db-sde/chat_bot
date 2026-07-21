
  /* ── Active tool webhooks: /chat drives every tool step ───── */

  /* Map the backend tool_flow lifecycle onto the .db-tool-widget phases. */
  function applyToolFlow(flow, payload) {
    var step = String(flow.step || '');
    var kind = TOOL_KIND_BY_ID[String(flow.tool || '')] || (state.tool && state.tool.kind);
    if (!kind) return false;

    if (step === 'exit') { state.tool = null; state.busy = false; return false; }

    /* The user closed the tool while this response was in flight. The
       abandon call is already on its way; rendering this step would
       resurrect a tool the user just dismissed. */
    if (!state.tool && step !== 'reveal') { state.busy = false; return true; }

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
