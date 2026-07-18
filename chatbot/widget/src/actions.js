  function safeFallbackActions() {
    const shared = {
      surface: state.currentChipSurface || "safe:fallback",
      funnel_stage: "bottom",
      interaction_count: state.interactionCount,
      config_version: state.configVersion,
      content_version: state.contentVersion,
      correlation_id: state.correlationId,
    };
    return [
      {
        ...shared,
        label: "Apply now",
        message: "Apply now",
        chip_id: "apply_now",
        chip_handler: "cta_apply",
        guide: "lead",
      },
      {
        ...shared,
        label: "Talk to a counsellor",
        message: "Talk to a counsellor",
        chip_id: "counsellor",
        chip_handler: "cta_callback",
        guide: "lead",
      },
    ];
  }

  function applyActionMetadata(actions) {
    const action = (actions || []).map(normalizedAction).find((item) => (
      item && (
        item.surface || item.funnel_stage || item.config_version ||
        item.content_version || item.interaction_count != null || item.correlation_id
      )
    ));
    if (action) applyChipMetadata(action);
  }

  function activeFlowMetadata(payload) {
    const metadata = payload && payload.metadata;
    const flow = metadata && metadata.tool_flow;
    return flow && typeof flow === "object" ? flow : null;
  }

  function applyActiveFlow(flow) {
    const restorePageStep = () => {
      const type = currentGuidePageType();
      transitionNavigation(["homepage", "pillar"].includes(type) ? "reset" : `${type}_card`);
    };
    if (!flow || typeof flow !== "object") {
      state.activeFlow = null;
      state.toolLeadRequiresName = false;
      restorePageStep();
      return;
    }
    const tool = String(flow.tool || "");
    const step = String(flow.step || "");
    if (!tool || !step || ["reveal", "exit"].includes(step)) {
      state.activeFlow = null;
      state.toolLeadRequiresName = false;
      restorePageStep();
      return;
    }
    state.activeFlow = { tool, step };
    state.toolLeadRequiresName = step === "await_lead" || flow.requires_lead === true;
    state.currentChipSurface = `tool:${tool}`;
    state.currentFunnelStage = "bottom";
    if (flow.version) state.contentVersion = String(flow.version);
    transitionNavigation("tool");
  }

  function recordChipTap(action) {
    if (!action || !action.chip_id) return;
    emitAnalytics("chip_tapped", action);
    const handler = String(action.chip_handler || action.handler || "");
    if (handler === "cta_apply") emitAnalytics("apply_clicked", action);
    if (handler === "cta_callback") emitAnalytics("counsellor_clicked", action);
  }

  function recordCardShown(component, type) {
    if (!component) return;
    emitAnalytics("card_shown", null, {
      entity: {
        type,
        id: String(
          component.id || component.slug ||
          component.items && component.items[0] && component.items[0].id ||
          `${type}:unknown`
        ),
      },
    });
  }

  function guideActionFor(action) {
    if (!action) return "";
    if (action.guide) return String(action.guide);
    const chipId = String(action.chip_id || action.id || "");
    const handler = String(action.chip_handler || action.handler || "");
    return CHIP_GUIDE_ACTIONS[chipId] || HANDLER_GUIDE_ACTIONS[handler] || "";
  }

  function handleAction(rawAction) {
    const action = normalizedAction(rawAction);
    if (!action) return;
    applyChipMetadata(action);
    recordChipTap(action);
    const kind = String(action.action || "").toLowerCase();
    const label = action.label.toLowerCase();
    const payload = action.payload || {};
    if (String(action.chip_handler) === "tool_entry" && action.tool) {
      if (String(action.tool) === "roi") {
        openRoiCalculator(action);
        return;
      }
      if (String(action.tool) === "career_quiz") {
        openCareerQuiz(action);
        return;
      }
      transitionNavigation("tool");
      const toolMessage = action.message && action.message !== action.label
        ? action.message
        : `tool:${action.tool}`;
      sendMessage(toolMessage, { displayText: action.label, chip: action });
      return;
    }
    const guideAction = guideActionFor(action);
    if (guideAction) {
      executeGuidedAction(guideAction, action.label, { ...payload, chip: action });
      return;
    }
    if (kind === "open_university_picker" || kind === "open_picker" && payload.kind === "university") {
      executeGuidedAction("browse_universities", action.label, { ...payload, chip: action });
      return;
    }
    if (kind === "open_specialization_picker" || kind === "open_picker" && payload.kind === "specialization") {
      executeGuidedAction("specializations", action.label, { ...payload, chip: action });
      return;
    }
    if (kind === "show_programs") {
      executeGuidedAction("browse_programs", action.label, { ...payload, chip: action });
      return;
    }
    if (kind === "open_finder") {
      executeGuidedAction("finder", action.label, { ...payload, chip: action });
      return;
    }
    if (
      kind === "open_lead" ||
      kind === "lead_capture" ||
      label.includes("talk to a counsellor") ||
      label.includes("talk to a counselor")
    ) {
      executeGuidedAction("lead", action.label, {
        source: payload.source || "quick_action",
        chip: action,
      });
      return;
    }
    if (label.includes("browse universit")) {
      executeGuidedAction("browse_universities", action.label);
      return;
    }
    if (label.includes("browse by specialization")) {
      executeGuidedAction("specializations", action.label);
      return;
    }
    if (label.includes("browse programs")) {
      executeGuidedAction("browse_programs", action.label);
      return;
    }
    if (label.includes("help me choose")) {
      executeGuidedAction("finder", action.label);
      return;
    }
    if (action.contextual) {
      const guideActions = {
        programs: "programs_here",
        reviews: "reviews",
        accreditations: "accreditations",
        compare: "compare",
        "fees and EMI": "fees",
        specializations: "specializations",
        eligibility: "eligibility",
        "compare universities": "compare",
        "career and salary": "career",
        syllabus: "syllabus",
        fees: "fees",
        "other specializations": "other_specializations",
      };
      executeGuidedAction(guideActions[action.contextual] || action.contextual, action.label, {
        ...payload,
        chip: action,
      });
      return;
    }
    const message = action.message || action.label;
    sendMessage(message, {
      displayText: message !== action.label ? action.label : message,
      chip: action,
    });
  }

  function synchronizeGuideContext(payload) {
    if (!payload || !Object.prototype.hasOwnProperty.call(payload, "context")) return;
    const responseContext = payload.context && typeof payload.context === "object"
      ? payload.context
      : {};
    const responseEntityId = responseContext.entity_id || "";
    const guideContext = currentGuideContext() || {};
    const guideEntityId = guideContext.entity_id || "";
    if (responseEntityId && responseEntityId !== guideEntityId) {
      const responseType = payload.metadata && payload.metadata.page_type || state.starterType;
      state.guideReady = loadGuideContext(responseEntityId, responseType).catch((error) => {
        console.warn("DegreeBaba could not synchronize guided context", error);
        return null;
      });
    } else if (!responseEntityId && guideEntityId && !contextValues(responseContext).length) {
      state.guideReady = loadGuideContext("", "homepage").catch((error) => {
        console.warn("DegreeBaba could not reset guided context", error);
        return null;
      });
    } else if (state.guideBundle) {
      state.guideBundle.context = responseContext;
    }
  }

  function guidedWait(milliseconds) {
    return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  }

  function currentGuideContext() {
    return state.guideBundle && state.guideBundle.context || null;
  }

  function currentGuideEntity() {
    return state.guideBundle && state.guideBundle.entity || null;
  }

  function currentGuidePageType() {
    const context = currentGuideContext();
    return cleanPageType(context && context.page_type || state.starterType || pageType);
  }

  function currentGuideLabel() {
    const context = currentGuideContext();
    const values = contextValues(context);
    return context && context.label || values.join(" ") || "this option";
  }

  function applyServerNavigation(payload) {
    if (!payload || typeof payload !== "object") return;
    if (payload.session_id) {
      state.sessionId = String(payload.session_id);
      rememberSessionId(state.sessionId);
    }
    if (payload.navigation) transitionNavigation("hydrate", payload.navigation);
  }

  function applyChipMetadata(chipPayload) {
    if (!chipPayload || typeof chipPayload !== "object") return;
    if (chipPayload.surface) state.currentChipSurface = String(chipPayload.surface);
    if (chipPayload.funnel_stage) {
      state.currentFunnelStage = String(chipPayload.funnel_stage);
    }
    if (chipPayload.config_version) state.configVersion = String(chipPayload.config_version);
    if (chipPayload.content_version) state.contentVersion = String(chipPayload.content_version);
    if (chipPayload.correlation_id) state.correlationId = String(chipPayload.correlation_id);
    const count = Number(chipPayload.interaction_count);
    if (Number.isFinite(count) && count >= 0) state.interactionCount = count;
  }

  function openingFromPayload(payload) {
    const opening = payload && payload.opening && typeof payload.opening === "object"
      ? payload.opening
      : null;
    if (!opening) return null;
    applyChipMetadata(opening);
    const top = Array.isArray(opening.top) ? opening.top.map(normalizedAction).filter(Boolean) : [];
    const more = Array.isArray(opening.more) ? opening.more.map(normalizedAction).filter(Boolean) : [];
    return { ...opening, top, more };
  }

  async function loadFollowupChips({
    cardType = null,
    answerState = null,
    completedChipId = null,
    surface = null,
  } = {}) {
    const context = currentGuideContext() || {};
    const entity = currentGuideEntity() || {};
    const body = {
      session_id: state.sessionId || null,
      page_type: currentGuidePageType(),
      surface: surface || state.currentChipSurface || null,
      entity_id: entity.id || context.entity_id || null,
      completed_chip_id: completedChipId || null,
      config_version: state.configVersion || null,
      correlation_id: state.correlationId || null,
      card_type: cardType,
      answer_state: answerState,
    };
    try {
      const payload = await fetchJson("/api/widget/guide/chips", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      applyServerNavigation(payload);
      const followup = payload && payload.followup && typeof payload.followup === "object"
        ? payload.followup
        : {};
      applyChipMetadata(followup);
      const actions = Array.isArray(followup.chips)
        ? followup.chips
        : Array.isArray(followup.actions) ? followup.actions : [];
      return actions.map(normalizedAction).filter((action) => action && action.label);
    } catch (error) {
      console.warn("DegreeBaba follow-up chips unavailable; using safe actions", error);
      return safeFallbackActions();
    }
  }

  async function persistCompletedChip(action) {
    const chip = normalizedAction(action);
    if (!chip || !chip.chip_id) return false;
    try {
      if (state.guideReady) await state.guideReady;
    } catch (_error) {
      // The lead request remains a second persistence opportunity.
    }
    const context = currentGuideContext() || {};
    const entity = currentGuideEntity() || {};
    try {
      const payload = await fetchJson("/api/widget/guide/chips", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: state.sessionId || null,
          page_type: currentGuidePageType(),
          surface: chip.surface || state.currentChipSurface || null,
          entity_id: entity.id || context.entity_id || null,
          completed_chip_id: chip.chip_id,
          config_version: chip.config_version || state.configVersion || null,
          correlation_id: chip.correlation_id || state.correlationId || null,
        }),
      });
      applyServerNavigation(payload);
      const completed = payload && payload.navigation && payload.navigation.completed_actions;
      return Array.isArray(completed) && completed.includes(chip.chip_id);
    } catch (error) {
      console.warn("DegreeBaba could not persist the conversion chip", error);
      return false;
    }
  }

  function renderInlineLeadCard(kind, options = {}) {
    const isApplication = kind === "application" || /apply/i.test(String(options.label || ""));
    const actionMeta = normalizedAction(options.chip) || {};
    const card = element("div", "db-widget__inline-lead db-lead");
    card.appendChild(element(
      "div",
      "db-widget__inline-lead-text db-lead-text",
      isApplication
        ? "Ready to apply? Share your number and a DegreeBaba admissions counsellor will help with the next step."
        : kind === "fees"
        ? "Want me to check today's fee offer and seat availability? Just your number — no spam."
        : kind === "eligibility"
          ? "Want a counsellor to verify your eligibility? Share your number for one callback."
          : "Happy to connect you. Share your number for one admissions callback — no spam.",
    ));
    const form = element("div", "db-widget__inline-lead-form db-lead-form");
    const phoneWrapper = element("div", "db-widget__inline-phone-wrapper db-phone-wrapper");
    phoneWrapper.appendChild(element("span", "db-widget__inline-phone-prefix db-phone-prefix", "+91"));
    const phone = document.createElement("input");
    phone.className = "db-widget__inline-phone-input db-phone-input";
    phone.type = "tel";
    phone.inputMode = "numeric";
    phone.autocomplete = "tel";
    phone.placeholder = "Your number";
    phone.setAttribute("aria-label", "10-digit mobile number");
    phoneWrapper.appendChild(phone);
    const submit = element("button", "db-widget__inline-lead-send db-lead-send", "Send");
    submit.type = "button";
    const status = element("div", "db-widget__inline-lead-note db-lead-note", "No spam. One call about your admission query.");
    form.append(phoneWrapper, submit);
    card.append(form, status);
    const submitLead = async () => {
      const normalized = phone.value.replace(/\D/g, "").replace(/^91(?=\d{10}$)/, "");
      if (!/^[6-9]\d{9}$/.test(normalized)) {
        phone.setAttribute("aria-invalid", "true");
        status.textContent = "Please enter a valid 10-digit mobile number.";
        return;
      }
      phone.removeAttribute("aria-invalid");
      submit.disabled = true;
      status.textContent = "Saving your request…";
      if (!options.analyticsRecorded) {
        emitAnalytics(isApplication ? "apply_clicked" : "counsellor_clicked", null);
      }
      try {
        const chipPersisted = options.persistence ? await options.persistence : false;
        const leadBody = {
          session_id: state.sessionId || null,
          phone: normalized,
          source: options.source || `widget_${kind}`,
        };
        if (actionMeta.chip_id && !chipPersisted) leadBody.chip_id = actionMeta.chip_id;
        const chipSurface = actionMeta.surface || state.currentChipSurface;
        const chipConfigVersion = actionMeta.config_version || state.configVersion;
        const chipCorrelationId = actionMeta.correlation_id || state.correlationId;
        if (chipSurface) leadBody.chip_surface = chipSurface;
        if (chipConfigVersion) leadBody.chip_config_version = chipConfigVersion;
        if (chipCorrelationId) leadBody.chip_correlation_id = chipCorrelationId;
        const response = await fetchJson("/api/widget/lead", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(leadBody),
        });
        if (response.session_id) {
          state.sessionId = response.session_id;
          rememberSessionId(state.sessionId);
        }
        card.replaceChildren();
        const done = element("div", "db-widget__inline-lead-done db-lead-done");
        done.append(
          richCardIcon("db-widget__inline-lead-done-icon db-lead-done-icon", RICH_CARD_ICONS.checkGreen),
          element("div", "db-widget__inline-lead-done-text db-lead-done-text", response.message || "Thanks — a DegreeBaba counsellor can contact you shortly."),
        );
        card.appendChild(done);
      } catch (error) {
        submit.disabled = false;
        status.textContent = error.message || "We couldn't save that request. Please try again.";
      }
    };
    submit.addEventListener("click", submitLead);
    phone.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); submitLead(); }
    });
    return card;
  }

  async function ensureGuideBundle() {
    if (state.guideReady) await state.guideReady;
    if (!state.guideBundle) throw new Error("Guided context is unavailable");
    return state.guideBundle;
  }

  async function showGuidedInfo(kind, chip = null) {
    const bundle = await ensureGuideBundle();
    if (!bundle.entity) {
      state.pendingGuidedInfo = { kind, chip };
      transitionNavigation("course_picker");
      const context = bundle.context || {};
      if (currentGuidePageType() === "pillar" && context.course) {
        await openPicker("course", {
          title: `Choose a University for ${context.course}`,
          display: "university",
          filters: { course: context.course },
          onSelect: selectGuidedEntity,
        });
        return;
      }
      await showProgramOptions();
      return;
    }
    transitionNavigation(kind);
    const result = guidedInfoCard(kind);
    const answerStates = {
      fees: "fees",
      eligibility: "eligibility_borderline",
      career: "careers",
      syllabus: "syllabus",
      reviews: "reviews",
      rating: "average_rating",
      accreditations: "approvals",
      admissions: "admissions",
      placement: "placement",
      overview: "overview",
    };
    const followups = await loadFollowupChips({
      answerState: answerStates[kind] || kind,
      completedChipId: chip && chip.chip_id,
    });
    emitAnalytics("card_shown", null, {
      entity: {
        type: kind,
        id: String(bundle.entity.id || bundle.context && bundle.context.entity_id || kind),
      },
    });
    const publishedInfo = kind === "rating"
      ? bundle.info && bundle.info.reviews
      : bundle.info && bundle.info[kind];
    const intro = Boolean(publishedInfo && publishedInfo.available)
      ? `Here's the confirmed ${result.title.toLowerCase()} information for ${currentGuideLabel()}.`
      : `${result.title} details haven't been published for ${currentGuideLabel()} yet.`;
    presentGuidedCard(
      intro,
      result.card,
      result.title,
      followups,
    );
  }

  async function showUniversityPrograms() {
    const bundle = await ensureGuideBundle();
    const entity = bundle.entity || {};
    const programs = Array.isArray(bundle.related && bundle.related.courses)
      ? bundle.related.courses
      : [];
    const name = bundle.context && bundle.context.university || entity.name || "This university";
    const count = entity.program_count === 0 || entity.program_count
      ? entity.program_count
      : programs.length;
    const actions = programs.map((program) => ({
      label: program.category ? String(program.category).toUpperCase() : program.name,
      onSelect: () => selectGuidedEntity(program, program.category ? String(program.category).toUpperCase() : program.name),
    }));
    if (!actions.length) {
      actions.push(...safeFallbackActions());
    }
    renderGuidePrompt(
      programs.length
        ? `${name} offers ${count} online program${Number(count) === 1 ? "" : "s"}. Which one interests you?`
        : `Programs haven't been published for ${name} yet. I can help you apply or connect with a counsellor.`,
      actions,
    );
  }

  async function showCourseSpecializations(chip = null) {
    const bundle = await ensureGuideBundle();
    const entity = bundle.entity || {};
    const specializations = Array.isArray(bundle.related && bundle.related.specializations)
      ? bundle.related.specializations
      : [];
    const pageTypeValue = currentGuidePageType();
    const count = pageTypeValue === "specialization"
      ? specializations.length
      : entity.specialization_count === 0 || entity.specialization_count
        ? entity.specialization_count
        : specializations.length;
    const actions = specializations.map((specialization) => ({
      label: specialization.name,
      onSelect: () => selectGuidedEntity(specialization, specialization.name),
    }));
    transitionNavigation("specialization_picker");
    if (!actions.length) {
      const followups = await loadFollowupChips({
        answerState: "no_specializations",
        completedChipId: chip && chip.chip_id,
      });
      renderGuidePrompt(
        "Specializations haven't been published for this course yet. You can continue with fees, eligibility, admissions, or careers.",
        followups,
      );
      return;
    }
    renderGuidePrompt(
      pageTypeValue === "specialization"
        ? `${currentGuideLabel()} has ${count} other specialization${Number(count) === 1 ? "" : "s"}. Which one interests you?`
        : `${currentGuideLabel()} offers ${count} specialization${Number(count) === 1 ? "" : "s"}. Which area interests you?`,
      actions,
    );
  }

  async function selectGuidedEntity(entity, selectionLabel) {
    if (!entity || state.guideBusy || state.busy) return;
    closeOverlay();
    deactivateGuidedActions();
    if (state.starter) state.starter.hidden = true;
    createMessage("user", selectionLabel || entity.name || "View option");
    emitAnalytics("cascade_step", null, {
      entity: {
        type: entity.kind || entity.page_type || (
          entity.type === "university_card" ? "university" : "course"
        ),
        id: String(entity.id || entity.slug || "unknown"),
      },
    });
    await runGuidedResponse(async () => {
      const bundle = await loadGuideContext(entity.id || entity.slug);
      if (!bundle) return;
      if (!bundle.entity) throw new Error("Selected option is unavailable");
      const resolvedType = cleanPageType(bundle.context && bundle.context.page_type);
      state.starterType = resolvedType;
      state.pageContextDismissed = false;
      if (resolvedType === "university") {
        transitionNavigation("university_card");
        await showUniversityPrograms();
        return;
      }
      if (resolvedType === "course") {
        transitionNavigation("course_card");
        if (state.pendingGuidedInfo) {
          const pending = state.pendingGuidedInfo;
          state.pendingGuidedInfo = null;
          await showGuidedInfo(pending.kind, pending.chip);
          return;
        }
        const course = { ...bundle.entity, guided: true };
        const followups = await loadFollowupChips({ cardType: "course" });
        presentGuidedCard(
          `Here's the confirmed course information for ${currentGuideLabel()}.`,
          renderProgramCard(course),
          bundle.context.course || bundle.entity.name,
          followups,
        );
        return;
      }
      transitionNavigation("specialization_card");
      const specialization = { ...bundle.entity, guided: true };
      const followups = await loadFollowupChips({ cardType: "specialization" });
      const card = renderProgramCard(specialization);
      presentGuidedCard(
        `Here's the strongest match for ${bundle.context.specialization || bundle.entity.name}.`,
        card,
        bundle.context.specialization || bundle.entity.name,
        followups,
      );
    });
  }

  async function runGuidedResponse(callback) {
    if (state.guideBusy || state.busy) return undefined;
    state.guideBusy = true;
    const generation = state.guideGeneration;
    showTyping(true, 0);
    try {
      await guidedWait(GUIDED_THINKING_MS);
      if (generation !== state.guideGeneration && state.pageContextDismissed) return undefined;
      return await callback();
    } catch (error) {
      console.warn("DegreeBaba guided navigation unavailable", error);
      renderGuidePrompt(
        "I couldn't load that right now. You can try another option or ask a counsellor for help.",
        safeFallbackActions(),
      );
      return undefined;
    } finally {
      showTyping(false);
      state.guideBusy = false;
    }
  }

  function executeGuidedAction(action, label, options = {}) {
    if (!action || state.guideBusy || state.busy) return;
    const chip = options.chip || null;
    state.conversationStarted = true;
    state.viewedActions.add(chip && chip.chip_id || action);
    deactivateGuidedActions();
    if (state.starter) state.starter.hidden = true;
    createMessage("user", label || action);
    if (action === "lead") {
      transitionNavigation("lead");
      const isApplication = /apply/i.test(String(label || ""));
      const analyticsRecorded = Boolean(chip && chip.chip_id);
      const persistence = analyticsRecorded ? persistCompletedChip(chip) : null;
      if (!analyticsRecorded) {
        emitAnalytics(isApplication ? "apply_clicked" : "counsellor_clicked", null);
      }
      if (state.toolLeadRequiresName) {
        state.pendingLeadPersistence = persistence;
        openLeadPanel({
          source: options.source || "guided_widget",
          label,
          chip,
          analyticsRecorded: true,
          requireName: true,
        });
        return;
      }
      runGuidedResponse(async () => {
        const leadStack = element("div", "db-widget__rich-card-stack");
        leadStack.appendChild(renderInlineLeadCard(
          isApplication ? "application" : "counsellor",
          {
            source: options.source || "guided_widget",
            label,
            chip,
            persistence,
            analyticsRecorded: true,
          },
        ));
        presentGuidedCard("", leadStack, isApplication ? "Apply now" : "Talk to a counsellor");
      });
      return;
    }
    runGuidedResponse(async () => {
      if (action === "browse_universities") {
        transitionNavigation("university_picker");
        const context = currentGuideContext() || {};
        await openPicker("university", {
          onSelect: selectGuidedEntity,
          filters: currentGuidePageType() === "pillar" && context.course
            ? { course: context.course }
            : {},
        });
      } else if (action === "browse_programs") {
        transitionNavigation("course_picker");
        await showProgramOptions();
      } else if (action === "finder") {
        startFinder();
      } else if (action === "programs_here") {
        transitionNavigation("course_picker");
        if (currentGuideEntity()) await showUniversityPrograms();
        else await showProgramOptions();
      } else if (action === "specializations" || action === "other_specializations") {
        transitionNavigation("specialization_picker");
        if (currentGuideEntity()) await showCourseSpecializations(chip);
        else await openPicker("specialization", { onSelect: selectGuidedEntity });
      } else if (["fees", "eligibility", "career", "syllabus", "reviews", "rating", "accreditations", "admissions", "placement", "overview"].includes(action)) {
        await showGuidedInfo(action, chip);
      } else if (action === "compare") {
        await beginGuidedComparison(null, chip);
      } else if (action === "online_validity") {
        transitionNavigation("validity");
        const followups = await loadFollowupChips({
          answerState: "validity",
          completedChipId: chip && chip.chip_id,
        });
        emitAnalytics("card_shown", null, {
          entity: {
            type: "validity",
            id: String(currentGuideContext() && currentGuideContext().entity_id || "validity"),
          },
        });
        presentGuidedCard(
          "An online degree can be valid when the university and exact program have the right recognition.",
          validityCard(),
          "Online degree validity",
          followups,
        );
      }
    });
  }

  function errorPayload(message, retryMessage) {
    return {
      message,
      components: [{
        type: "quick_actions",
        actions: [
          { label: "Try again", message: retryMessage },
          { label: "Talk to a counsellor", action: "open_lead" },
        ],
      }],
    };
  }

  async function sendMessage(rawMessage, options = {}) {
    const message = String(rawMessage || "").trim();
    if (!message || state.busy || state.guideBusy) return;
    state.busy = true;
    state.conversationStarted = true;
    state.pendingGuidedInfo = null;
    try {
      if (state.guideReady) await state.guideReady;
    } catch (error) {
      console.warn("DegreeBaba initial guide hydration did not complete", error);
    }
    const hadActiveFlow = Boolean(state.activeFlow);
    const hadRoiFlow = Boolean(state.activeFlow && state.activeFlow.tool === "roi");
    const hadCareerQuizFlow = Boolean(
      state.activeFlow && state.activeFlow.tool === "career_quiz",
    );
    state.lastMessage = message;
    state.input.value = "";
    if (state.send) state.send.classList.remove("db-widget__send--active");
    if (state.starter && options.keepStarter !== true) state.starter.hidden = true;
    if (options.displayUser !== false) {
      createMessage("user", String(options.displayText || message));
    }
    if (options.showTyping !== false) showTyping(true);
    let finalPayload = null;
    let bufferedText = "";
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);

    try {
      const body = { message, site_key: siteKey };
      if (options.chip && options.chip.chip_id) {
        body.chip_id = String(options.chip.chip_id);
        body.chip_surface = String(
          options.chip.surface || state.currentChipSurface || "",
        ) || null;
        body.chip_config_version = String(
          options.chip.config_version || state.configVersion || "",
        ) || null;
        body.chip_correlation_id = String(
          options.chip.correlation_id || state.correlationId || "",
        ) || null;
      }
      if (state.sessionId) body.session_id = state.sessionId;
      if (!state.pageContextDismissed) {
        const guideContext = currentGuideContext();
        const guideEntity = currentGuideEntity();
        const guidedType = guideContext && cleanPageType(guideContext.page_type);
        if (guidedType && guidedType !== "homepage") {
          body.page_type = guidedType;
          body.page_entity_slug = guideEntity && (guideEntity.slug || guideEntity.id) || guideContext.entity_id;
          const linkedUniversity = guideEntity && guideEntity.linked_university;
          const guidedUniversitySlug =
            guideContext.university_slug ||
            guideEntity && guideEntity.university_slug ||
            linkedUniversity && typeof linkedUniversity === "object" && (linkedUniversity.slug || linkedUniversity.id) ||
            typeof linkedUniversity === "string" && linkedUniversity ||
            "";
          if (guidedUniversitySlug) body.page_university_slug = guidedUniversitySlug;
        } else {
          if (pageUniversitySlug) body.page_university_slug = pageUniversitySlug;
          if (pageType !== "homepage") body.page_type = pageType;
          if (pageEntitySlug) body.page_entity_slug = pageEntitySlug;
        }
      }
      const response = await requestChat(body, controller.signal);
      await consumeSse(response, (event, payload) => {
        if (payload.session_id) {
          state.sessionId = payload.session_id;
          rememberSessionId(state.sessionId);
        }
        if (event === "token" && payload.token) bufferedText += payload.token;
        if (["response", "final", "replace"].includes(event)) finalPayload = payload;
      });
      if (options.showTyping !== false) showTyping(false);
      const payload = finalPayload || { message: bufferedText };
      if (hadActiveFlow && !activeFlowMetadata(payload)) applyActiveFlow(null);
      if (typeof options.onPayload === "function") options.onPayload(payload);
      else if (roiFlowMetadata(payload)) updateRoiWidget(payload);
      else if (careerQuizFlowMetadata(payload)) updateCareerQuizWidget(payload);
      else {
        if (hadRoiFlow && state.roiWidget) {
          state.roiWidget.collapsed = true;
          renderRoiWidget();
        }
        if (hadCareerQuizFlow && state.careerQuizWidget) {
          forgetCareerQuizPage();
          removeCareerQuizWidget();
        }
        renderBotPayload(payload);
      }
    } catch (error) {
      if (options.showTyping !== false) showTyping(false);
      const timeoutMessage = error && error.name === "AbortError"
        ? "The advisor took too long to respond. Your chat is safe—please try once more."
        : "I couldn’t reach the advisor just now. Please try again in a moment.";
      const failure = errorPayload(timeoutMessage, message);
      if (typeof options.onError === "function") options.onError(failure, error);
      else renderBotPayload(failure);
      console.error("DegreeBaba widget request failed", error);
    } finally {
      window.clearTimeout(timeout);
      state.busy = false;
      if (options.blurInput !== false) state.input.blur();
    }
  }

  async function loadGuideContext(entityReference = "", logicalType = "homepage") {
    const generation = ++state.guideGeneration;
    const query = new URLSearchParams();
    const normalizedType = cleanPageType(logicalType);
    if (normalizedType === "pillar") {
      query.set("page_type", "pillar");
      if (entityReference) query.set("course", entityReference);
    } else if (entityReference) query.set("entity_id", entityReference);
    else query.set("page_type", normalizedType);
    if (state.sessionId) query.set("session_id", state.sessionId);
    const payload = await fetchJson(`/api/widget/guide/context?${query.toString()}`);
    if (generation !== state.guideGeneration) return null;
    applyServerNavigation(payload);
    state.openingChips = openingFromPayload(payload);
    state.guideBundle = {
      context: payload.context || null,
      entity: payload.entity || null,
      related: payload.related || {},
      info: payload.info || {},
    };
    state.pageContext = payload.context || null;
    state.starterType = cleanPageType(payload.context && payload.context.page_type || logicalType);
    updateContext(payload.context);
    updateWelcome(state.guideBundle);
    const activeFlow = payload.active_flow && typeof payload.active_flow === "object"
      ? payload.active_flow
      : null;
    const roiOrigin = storedRoiPageKey();
    const careerQuizOrigin = storedCareerQuizPageKey();
    if (
      activeFlow && String(activeFlow.tool || "") === "roi" &&
      roiOrigin && roiOrigin !== currentPageKey()
    ) {
      try {
        await abandonPersistedRoiFlow();
        state.conversationStarted = false;
        return loadGuideContext(entityReference, logicalType);
      } catch (error) {
        console.warn("DegreeBaba could not reset ROI after the page context changed", error);
      }
    }
    if (
      activeFlow && String(activeFlow.tool || "") === "career_quiz" &&
      careerQuizOrigin && careerQuizOrigin !== currentPageKey()
    ) {
      try {
        await abandonPersistedCareerQuizFlow();
        state.conversationStarted = false;
        return loadGuideContext(entityReference, logicalType);
      } catch (error) {
        console.warn("DegreeBaba could not reset the Career Quiz after the page context changed", error);
      }
    }
    const resumeResponse = activeFlow && activeFlow.response && typeof activeFlow.response === "object"
      ? activeFlow.response
      : null;
    const resumeKey = activeFlow
      ? `${String(activeFlow.tool || "")}:${String(activeFlow.step || "")}`
      : "";
    const shouldResume = Boolean(
      resumeResponse && resumeKey && resumeKey !== state.activeFlowResumeKey,
    );
    if (activeFlow) {
      state.conversationStarted = true;
      applyActiveFlow(activeFlow);
    } else {
      state.activeFlowResumeKey = "";
      applyActiveFlow(null);
    }
    state.starter.hidden = state.conversationStarted;
    renderStarterBank(state.starterType);
    if (shouldResume) {
      state.activeFlowResumeKey = resumeKey;
      if (String(activeFlow.tool || "") === "roi") updateRoiWidget(resumeResponse);
      else if (String(activeFlow.tool || "") === "career_quiz") {
        updateCareerQuizWidget(resumeResponse);
      }
      else renderBotPayload(resumeResponse);
    }
    return state.guideBundle;
  }

  async function clearContext() {
    state.guideGeneration += 1;
    const clearGeneration = state.guideGeneration;
    state.pageContextDismissed = true;
    state.guideBundle = {
      context: {
        page_type: "homepage",
        university: null,
        course: null,
        specialization: null,
        entity_id: null,
        label: null,
      },
      entity: null,
      related: {},
      info: {},
    };
    state.guideReady = Promise.resolve(state.guideBundle);
    state.openingChips = null;
    state.pendingGuidedInfo = null;
    state.pendingCompletedChipId = null;
    state.pendingLeadPersistence = null;
    state.pageContext = null;
    state.viewedActions.clear();
    state.currentChipSurface = "page:home";
    state.currentFunnelStage = "top";
    transitionNavigation("reset");
    updateContext(null);
    updateWelcome(state.guideBundle);
    state.starter.hidden = true;
    state.starterGrid.replaceChildren();
    state.starterVisibleActions = [];
    state.starterType = "homepage";
    if (state.sessionId) {
      try {
        const payload = await fetchJson("/api/widget/context/clear", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: state.sessionId }),
        });
        if (
          clearGeneration === state.guideGeneration &&
          state.pageContextDismissed &&
          payload &&
          Object.prototype.hasOwnProperty.call(payload, "context")
        ) updateContext(payload.context);
      } catch (error) {
        // A fresh backend session guarantees the dismissed focus cannot leak into
        // the next answer when the optional clear endpoint is unavailable.
        forgetSessionId();
        console.warn("DegreeBaba context endpoint unavailable; starting a neutral session", error);
      }
    }
    try {
      state.guideReady = loadGuideContext("", "homepage");
      await state.guideReady;
      const opening = state.openingChips;
      const actions = opening ? [...opening.top, ...opening.more] : safeFallbackActions();
      renderGuidePrompt("Context cleared. What would you like to explore next?", actions);
    } catch (error) {
      renderGuidePrompt(
        "Context cleared. I can still help you apply or speak with a counsellor.",
        safeFallbackActions(),
      );
    }
  }

  function emitStarterImpressions() {
    if (!state.open || !state.starter || state.starter.hidden) return;
    const actions = state.starterVisibleActions || [];
    const key = [
      state.currentChipSurface,
      state.configVersion,
      state.correlationId,
      ...actions.map((action) => action.chip_id || action.label),
    ].join("|");
    if (!actions.length || key === state.starterImpressionKey) return;
    state.starterImpressionKey = key;
    emitChipShown(actions);
  }

  async function showProgramOptions() {
    const data = await loadGuideCatalog("programs");
    const items = data.items.length
      ? data.items
      : PROGRAM_OPTIONS.map((name) => ({ id: name.replace(/^Online\s+/i, "").toLowerCase(), name }));
    renderGuidePrompt(
      "Which program are you considering?",
      items.map((program) => ({
        label: program.name,
        onSelect: () => selectProgramCategory(program),
      })),
    );
  }

  function selectProgramCategory(program) {
    if (!program || state.guideBusy || state.busy) return;
    deactivateGuidedActions();
    createMessage("user", program.name);
    transitionNavigation("course_picker");
    emitAnalytics("cascade_step", null, {
      entity: { type: "course", id: String(program.id || program.slug || program.name) },
    });
    runGuidedResponse(async () => {
      renderGuidePrompt(`Which university would you like to explore for ${program.name}?`);
      await openPicker("course", {
        title: `Choose a University for ${program.name}`,
        display: "university",
        filters: { course: program.id || program.slug || program.name },
        onSelect: selectGuidedEntity,
      });
    });
  }

  async function openPicker(kind, onSelectOrOptions = null) {
    const options = typeof onSelectOrOptions === "function"
      ? { onSelect: onSelectOrOptions }
      : onSelectOrOptions && typeof onSelectOrOptions === "object" ? onSelectOrOptions : {};
    const labels = {
      university: "universities",
      universities: "universities",
      course: "programs",
      courses: "programs",
      specialization: "specializations",
      specializations: "specializations",
    };
    const label = labels[kind] || kind;
    if (["university", "universities"].includes(kind)) transitionNavigation("university_picker");
    if (["course", "courses"].includes(kind)) transitionNavigation("course_picker");
    if (["specialization", "specializations"].includes(kind)) {
      transitionNavigation("specialization_picker");
    }
    const title = options.title || `Browse ${label}`;
    const body = openOverlay(title, "db-widget__picker-overlay db-picker");
    const sheet = element("section", "db-widget__picker db-widget__picker-sheet db-picker-sheet");
    sheet.style.gridTemplateRows = "auto minmax(0, 1fr)";
    const searchWrap = element("div", "db-widget__picker-search-wrap");
    const searchField = element("div", "db-widget__picker-search-field db-picker-search");
    const searchIcon = element("span", "db-widget__picker-search-icon");
    searchIcon.setAttribute("aria-hidden", "true");
    searchIcon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-4-4"></path></svg>';
    const search = document.createElement("input");
    search.className = "db-widget__picker-search db-picker-input";
    search.type = "search";
    search.placeholder = options.display === "university" ? "Search universities" : `Search ${label}`;
    search.setAttribute("aria-label", search.placeholder);
    searchField.append(searchIcon, search);
    searchWrap.appendChild(searchField);
    if (options.selectionLabel) {
      const selection = element("div", "db-widget__picker-selection");
      selection.append(
        element("span", "db-widget__picker-selection-label", "Selected"),
        element("strong", "", options.selectionLabel),
      );
      searchWrap.prepend(selection);
    }
    const content = element("div", "db-widget__picker-content db-widget__picker-list db-picker-list");
    content.appendChild(element("p", "db-widget__picker-empty db-picker-empty", "Loading published options…"));
    sheet.append(searchWrap, content);
    body.appendChild(sheet);
    window.setTimeout(() => search.focus(), 0);
    try {
      const data = await loadGuideCatalog(kind, options.filters || {});
      const searchableLabel = options.display === "university" ? "universities" : label;
      search.placeholder = `Search ${data.items.length} ${searchableLabel}…`;
      search.setAttribute("aria-label", `Search ${searchableLabel}`);
      renderPickerResults(content, data, kind, "", options);
      search.addEventListener("input", () => renderPickerResults(content, data, kind, search.value, options));
    } catch (error) {
      content.replaceChildren();
      const empty = element("section", "db-widget__error-state");
      empty.appendChild(element("span", "db-widget__state-icon", "↻"));
      empty.appendChild(element("h3", "db-widget__state-title", "The options didn’t load"));
      empty.appendChild(element("p", "db-widget__state-copy", "You can retry or ask a counsellor for help."));
      const actions = element("div", "db-widget__state-actions");
      actions.append(
        createButton("Try again", "db-widget__action", () => openPicker(kind, options)),
        createButton("Talk to a counsellor", "db-widget__action db-widget__action--lead", () => {
          closeOverlay();
          openLeadPanel({ source: "guided_picker_error" });
        }),
      );
      empty.appendChild(actions);
      content.appendChild(empty);
      console.warn("DegreeBaba catalog picker unavailable", error);
    }
  }

  function addToComparison(component) {
    const reference = cardReference(component);
    if (!reference.id || state.compareSelections.some((item) => item.id === reference.id)) return 0;
    state.compareSelections.push(reference);
    if (state.compareSelections.length > 2) state.compareSelections.shift();
    const selectionCount = state.compareSelections.length;
    renderCompareTray();
    if (selectionCount === 2) submitComparison();
    return selectionCount;
  }

  function comparisonPickerKind() {
    const selected = state.compareSelections[0] && state.compareSelections[0].component;
    if (selected) {
      if (selected.type === "university_card") return "university";
      if (selected.kind === "specialization" || selected.type === "specialization_card") return "specialization";
      if (["program_card", "course_card"].includes(selected.type) || selected.kind === "course") return "course";
    }
    const type = currentGuidePageType();
    if (type === "course") return "course";
    if (type === "specialization") return "specialization";
    return "university";
  }

  function openComparisonPicker() {
    const kind = comparisonPickerKind();
    const entity = state.compareSelections[0] && state.compareSelections[0].component || currentGuideEntity() || {};
    const selected = state.compareSelections[0] || null;
    const optionLabel = kind === "university" ? "university" : kind === "course" ? "program" : "specialization";
    const filters = {};
    if (kind === "course" && entity.category) filters.course = entity.category;
    if (kind === "specialization" && entity.name) filters.q = entity.name;
    return openPicker(kind, {
      title: selected ? `Choose a different ${optionLabel}` : `Choose a ${optionLabel} to compare`,
      display: kind === "course" ? "university" : undefined,
      filters,
      excludeIds: state.compareSelections.map((item) => item.id),
      selectionLabel: selected && selected.label,
      onSelect: (item) => {
        const selectionCount = addToComparison(item);
        if (selectionCount === 1) {
          window.setTimeout(() => openComparisonPicker(), 0);
        }
      },
    });
  }

  function beginGuidedComparison(startingComponent = null, chip = null) {
    transitionNavigation("comparison");
    state.pendingCompletedChipId = chip && chip.chip_id || null;
    const launch = () => {
      state.compareSelections = [];
      const starting = startingComponent || currentGuideEntity();
      if (starting && starting.id) state.compareSelections.push(cardReference(starting));
      renderCompareTray();
      return openComparisonPicker();
    };
    if (state.guideBusy) return launch();
    if (state.busy) return undefined;
    state.viewedActions.add("compare");
    deactivateGuidedActions();
    if (state.starter) state.starter.hidden = true;
    createMessage("user", "Compare options");
    return runGuidedResponse(launch);
  }

  function submitComparison() {
    if (state.compareSelections.length !== 2) return;
    const selections = state.compareSelections.slice();
    const ids = selections.map((item) => item.id).filter(Boolean);
    if (ids.length !== 2) return;
    const labels = state.compareSelections.map((item) => item.label);
    state.compareSelections = [];
    renderCompareTray();
    createMessage("user", `Compare ${labels[0]} and ${labels[1]}`);
    runGuidedResponse(async () => {
      const component = await fetchJson("/api/widget/guide/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_ids: ids }),
      });
      const followups = await loadFollowupChips({
        answerState: "comparison",
        completedChipId: state.pendingCompletedChipId,
      });
      state.pendingCompletedChipId = null;
      presentGuidedCard(
        "Here's a side-by-side comparison using the published details.",
        renderComparisonCard(component),
        component.title || "Comparison",
        followups,
      );
    });
  }

  function openLeadPanel(options = {}) {
    const isApplication = /apply/i.test(String(options.label || ""));
    const isRoiResult = options.roiWidget === true;
    const isCareerQuizResult = options.careerQuizWidget === true;
    const requiresName = options.requireName === true || state.toolLeadRequiresName;
    const actionMeta = normalizedAction(options.chip || options.component) || {};
    transitionNavigation("lead");
    if (!options.analyticsRecorded) {
      emitAnalytics(isApplication ? "apply_clicked" : "counsellor_clicked", null);
    }
    const body = openOverlay(
      isRoiResult
        ? "Your detailed ROI"
        : isCareerQuizResult
          ? "Your program matches"
          : isApplication
            ? "Start your application"
            : "Talk to a counsellor",
      "db-widget__detail-overlay db-widget__lead-overlay",
    );
    const panel = element("section", "db-widget__detail-panel db-widget__lead-panel");
    panel.style.height = "100%";
    panel.style.gridTemplateRows = "minmax(0, 1fr)";
    const content = element("div", "db-widget__detail-body");
    const intro = element("section", "db-widget__detail-section");
    intro.appendChild(element(
      "h3",
      "",
      isRoiResult
        ? "Unlock your detailed ROI result"
        : isCareerQuizResult
          ? "Unlock your best-fit program matches"
        : isApplication
          ? "Take the next step with an admissions counsellor"
          : "Talk to a real admissions counsellor",
    ));
    intro.appendChild(element(
      "p",
      "",
      isRoiResult
        ? "Share your details to view the full estimate and get help understanding the result."
        : isCareerQuizResult
          ? "Share your details to see the three published programs matched to your quiz result."
        : "Share your phone number and a DegreeBaba counsellor can help with fees, eligibility, and next steps.",
    ));
    const form = element("form", "db-widget__lead-form");
    const name = document.createElement("input");
    name.className = "db-widget__picker-search db-widget__lead-input";
    name.type = "text";
    name.autocomplete = "name";
    name.maxLength = 50;
    name.placeholder = "Your name";
    name.setAttribute("aria-label", name.placeholder);
    const phone = document.createElement("input");
    phone.className = "db-widget__picker-search db-widget__lead-input";
    phone.type = "tel";
    phone.inputMode = "numeric";
    phone.autocomplete = "tel";
    phone.placeholder = "10-digit phone number";
    phone.setAttribute("aria-label", phone.placeholder);
    const status = element("p", "db-widget__state-copy");
    const submit = element(
      "button",
      "db-widget__lead-button",
      isRoiResult
        ? "View detailed result"
        : isCareerQuizResult
          ? "View my matches"
          : isApplication
            ? "Continue with a counsellor"
            : "Request a callback",
    );
    submit.type = "submit";
    if (requiresName) form.appendChild(name);
    form.append(phone, submit, status);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const normalizedName = name.value.trim().replace(/\s+/g, " ");
      if (requiresName && normalizedName.length < 2) {
        status.textContent = "Please enter your name to reveal the full result.";
        name.setAttribute("aria-invalid", "true");
        return;
      }
      name.removeAttribute("aria-invalid");
      const normalized = phone.value.replace(/\D/g, "").replace(/^91(?=\d{10}$)/, "");
      if (!/^[6-9]\d{9}$/.test(normalized)) {
        status.textContent = "Please enter a valid 10-digit mobile number.";
        phone.setAttribute("aria-invalid", "true");
        return;
      }
      phone.removeAttribute("aria-invalid");
      submit.disabled = true;
      status.textContent = "Saving your request…";
      try {
        const persistence = state.pendingLeadPersistence;
        state.pendingLeadPersistence = null;
        const chipPersisted = persistence ? await persistence : false;
        const leadBody = {
          session_id: state.sessionId || null,
          phone: normalized,
          source: options.source || "widget",
        };
        if (requiresName) leadBody.name = normalizedName;
        if (actionMeta.chip_id && !chipPersisted) leadBody.chip_id = actionMeta.chip_id;
        const chipSurface = actionMeta.surface || state.currentChipSurface;
        const chipConfigVersion = actionMeta.config_version || state.configVersion;
        const chipCorrelationId = actionMeta.correlation_id || state.correlationId;
        if (chipSurface) leadBody.chip_surface = chipSurface;
        if (chipConfigVersion) leadBody.chip_config_version = chipConfigVersion;
        if (chipCorrelationId) leadBody.chip_correlation_id = chipCorrelationId;
        const response = await fetchJson("/api/widget/lead", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(leadBody),
        });
        if (response.session_id) {
          state.sessionId = response.session_id;
          rememberSessionId(state.sessionId);
        }
        state.lastLead = { name: normalizedName, phone: normalized };
        form.replaceChildren(element(
          "p",
          "db-widget__state-copy",
          response.message || "Thanks — a DegreeBaba counsellor can contact you shortly.",
        ));
        if (response.response && typeof response.response === "object") {
          closeOverlay();
          if (options.roiWidget && state.roiWidget) {
            state.roiWidget.leadConfirmation = response.message || "Your details are saved.";
            updateRoiWidget(response.response);
          } else if (options.careerQuizWidget && state.careerQuizWidget) {
            state.careerQuizWidget.leadConfirmation = response.message || "Your details are saved.";
            updateCareerQuizWidget(response.response);
          } else {
            renderBotPayload({
              message: response.message || "Thanks — your details are saved.",
            });
            renderBotPayload(response.response);
          }
        }
      } catch (error) {
        console.warn("DegreeBaba phone-only lead endpoint unavailable; using chat funnel", error);
        if (options.roiWidget || options.careerQuizWidget) {
          submit.disabled = false;
          status.textContent = "I couldn’t save that just now. Please check your connection and try again.";
        } else {
          closeOverlay();
          sendMessage(`${options.label || "Talk to a counsellor"} ${normalized}`);
        }
      }
    });
    content.append(intro, form);
    panel.appendChild(content);
    body.appendChild(panel);
    window.setTimeout(() => (requiresName ? name : phone).focus(), 0);
  }

  async function hydratePageContext() {
    try {
      if (pageType === "homepage") {
        return await loadGuideContext("", "homepage");
      }
      if (!pageEntitySlug) {
        if (pageType === "university" && pageUniversitySlug) {
          return await loadGuideContext(pageUniversitySlug, pageType);
        }
        throw new Error("Page entity slug is required for guided context");
      }
      const query = new URLSearchParams({ page_type: pageType, page_entity_slug: pageEntitySlug });
      if (pageUniversitySlug) query.set("page_university_slug", pageUniversitySlug);
      const payload = await fetchJson(`/api/widget/page-context?${query.toString()}`);
      state.pageContext = payload.page_context || payload.context || payload;
      if (payload.context) updateContext(payload.context);
      return await loadGuideContext(payload.entity_id || payload.slug || pageEntitySlug, pageType);
    } catch (error) {
      try {
        return await loadGuideContext(pageEntitySlug || pageUniversitySlug, pageType);
      } catch (fallbackError) {
        updateWelcome();
        console.warn("DegreeBaba page guidance unavailable", error, fallbackError);
        return null;
      }
    }
  }

  function setOpen(open) {
    state.open = Boolean(open);
    state.panel.hidden = !state.open;
    state.launcher.setAttribute("aria-expanded", String(state.open));
    state.launcher.setAttribute("aria-label", state.open ? "Close admission advisor" : "Open admission advisor");
    state.launcher.classList.toggle("db-widget__launcher--open", state.open);
    state.launcher.innerHTML = state.open
      ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>'
      : '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.9-.9L3 21l1.9-5.6A8.5 8.5 0 0 1 12.5 3 8.38 8.38 0 0 1 21 11.5z"/></svg>';
    if (state.open) {
      state.input.blur();
      refreshResponsiveActionLayouts();
    }
    else closeOverlay();
  }
