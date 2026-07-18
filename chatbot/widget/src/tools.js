  function roiFlowMetadata(payload) {
    const flow = activeFlowMetadata(payload);
    return flow && String(flow.tool || "") === "roi" ? flow : null;
  }

  function careerQuizFlowMetadata(payload) {
    const flow = activeFlowMetadata(payload);
    return flow && String(flow.tool || "") === "career_quiz" ? flow : null;
  }

  function roiQuestionNumber(step) {
    if (step === "current_salary") return 2;
    return 1;
  }

  function roiQuestionText(message) {
    const text = String(message || "").trim();
    if (!text) return "Choose an option to continue.";
    const question = text.match(/(?:^|[.!]\s+)([^.!?]*\?)\s*$/);
    return question ? question[1].trim() : text;
  }

  function roiPaybackText(message) {
    const match = String(message || "").match(/\b(\d{1,3})\s+months?\b/i);
    return match ? `${match[1]} months` : "";
  }

  function ensureRoiWidget() {
    if (state.roiWidget && state.roiWidget.row.isConnected) return state.roiWidget;
    deactivateGuidedActions();
    collapseGuidedCards();
    const view = createMessage("bot", "");
    view.row.classList.add("db-widget__message-row--roi");
    view.bubble.remove();
    const stack = element("div", "db-widget__component-stack db-widget__roi-stack");
    const card = element("section", "db-widget__roi-card db-tool-widget");
    card.setAttribute("aria-label", "ROI Calculator");

    const header = element("header", "db-widget__roi-header db-tool-header");
    const identity = element("div", "db-widget__roi-identity db-tool-header-left");
    const icon = element("span", "db-widget__roi-icon db-tool-icon-badge", "🧮");
    icon.setAttribute("aria-hidden", "true");
    const title = element("div", "db-widget__roi-title db-tool-title");
    const status = element("span", "db-widget__roi-status", "Ready when you are");
    title.append(element("strong", "", "ROI Calculator"), status);
    identity.append(icon, title);
    const close = createButton("×", "db-widget__roi-close db-tool-close", closeRoiCalculator);
    close.setAttribute("aria-label", "Collapse ROI Calculator");
    header.append(identity, close);

    const body = element("div", "db-widget__roi-body");
    const live = element("p", "db-widget__sr-only");
    live.setAttribute("aria-live", "polite");
    card.append(header, body, live);
    stack.appendChild(card);
    view.content.appendChild(stack);
    state.roiWidget = {
      view,
      row: view.row,
      card,
      body,
      live,
      status,
      mode: "idle",
      step: 0,
      payload: null,
      message: "",
      actions: [],
      components: [],
      collapsed: false,
      busy: false,
      retryMessage: "",
      chip: null,
      detailRequested: false,
      leadConfirmation: "",
    };
    anchorBotMessage(view.row);
    return state.roiWidget;
  }

  function roiActionButton(label, className, handler) {
    const button = createButton(label, className, handler);
    button.disabled = Boolean(state.roiWidget && state.roiWidget.busy);
    return button;
  }

  async function abandonPersistedRoiFlow() {
    if (!state.sessionId) {
      applyActiveFlow(null);
      forgetRoiPage();
      return;
    }
    await fetchJson("/api/widget/context/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId }),
    });
    applyActiveFlow(null);
    state.activeFlowResumeKey = "";
    forgetRoiPage();
  }

  async function closeRoiCalculator() {
    const widget = state.roiWidget;
    if (!widget || widget.busy) return;
    widget.collapsed = true;
    const unfinished = Boolean(state.activeFlow && state.activeFlow.tool === "roi");
    if (!unfinished) {
      renderRoiWidget();
      return;
    }
    widget.mode = "closed";
    widget.busy = true;
    widget.message = "The calculator is closed.";
    renderRoiWidget();
    try {
      await abandonPersistedRoiFlow();
      state.conversationStarted = false;
      await hydratePageContext();
      if (state.starter) {
        state.messages.appendChild(state.starter);
        state.starter.hidden = false;
        refreshResponsiveActionLayouts();
      }
    } catch (error) {
      widget.mode = "error";
      widget.message = "I couldn’t close the calculator just now. Please try again.";
      console.warn("DegreeBaba could not close the ROI calculator", error);
    } finally {
      widget.busy = false;
      renderRoiWidget();
    }
  }

  function renderRoiProgress(widget) {
    const progress = element("div", "db-widget__roi-progress db-tool-progress");
    const copy = element("div", "db-widget__roi-progress-copy");
    copy.append(
      element("span", "", `Question ${widget.step}`),
      element("strong", "", `${widget.step} of ${ROI_TOTAL_STEPS}`),
    );
    const track = element("div", "db-widget__roi-progress-track db-progress-track");
    track.setAttribute("role", "progressbar");
    track.setAttribute("aria-label", "ROI calculator progress");
    track.setAttribute("aria-valuemin", "0");
    track.setAttribute("aria-valuemax", String(ROI_TOTAL_STEPS));
    track.setAttribute("aria-valuenow", String(widget.step));
    const fill = element("span", "db-widget__roi-progress-fill db-progress-fill");
    fill.style.setProperty("--db-roi-progress", `${widget.step / ROI_TOTAL_STEPS * 100}%`);
    track.appendChild(fill);
    copy.classList.add("db-progress-label");
    progress.append(track, copy);
    return progress;
  }

  function renderRoiCollapsed(widget) {
    const compact = element("div", "db-widget__roi-compact");
    const payback = roiPaybackText(widget.message);
    const copy = element("div", "db-widget__roi-compact-copy");
    copy.appendChild(element(
      "strong",
      "",
      widget.mode === "complete"
        ? "Completed"
        : widget.mode === "closed"
          ? "Closed"
          : widget.mode === "idle"
            ? "Not started"
            : "In progress",
    ));
    copy.appendChild(element(
      "span",
      "",
      payback
        ? `Estimated payback: ${payback}`
        : widget.mode === "closed"
          ? "You can start again at any time"
        : widget.step
          ? `Question ${widget.step} of ${ROI_TOTAL_STEPS}`
          : "2 quick questions",
    ));
    compact.append(copy, roiActionButton(
      widget.mode === "closed" ? "Start again" : "View again",
      "db-widget__roi-link",
      () => {
      if (widget.mode === "closed") {
        widget.mode = "idle";
        widget.step = 0;
        widget.message = "";
        widget.actions = [];
        widget.components = [];
      }
      widget.collapsed = false;
      renderRoiWidget();
      anchorBotMessage(widget.row);
      },
    ));
    return compact;
  }

  function requestRoiStep(message, options = {}) {
    const widget = ensureRoiWidget();
    if (widget.busy) return;
    if (message === "tool:roi") rememberRoiPage();
    widget.busy = true;
    widget.retryMessage = message;
    widget.detailRequested = options.detail === true;
    renderRoiWidget();
    sendMessage(message, {
      chip: options.chip || null,
      displayUser: false,
      showTyping: false,
      keepStarter: false,
      blurInput: false,
      onPayload: (payload) => updateRoiWidget(payload),
      onError: (payload) => {
        widget.busy = false;
        widget.mode = "error";
        widget.message = payload.message;
        renderRoiWidget();
      },
    });
  }

  function renderRoiQuestion(widget, content) {
    content.appendChild(renderRoiProgress(widget));
    content.appendChild(element("h3", "db-widget__roi-question db-tool-question", roiQuestionText(widget.message)));
    const options = element("div", "db-widget__roi-options db-tool-opts");
    widget.actions.forEach((action) => {
      const choice = roiActionButton(action.label, "db-widget__roi-option db-tool-opt", () => {
        requestRoiStep(action.message);
      });
      options.appendChild(choice);
    });
    content.appendChild(options);
  }

  function renderRoiResult(widget, content) {
    const payback = roiPaybackText(widget.message);
    content.appendChild(element("span", "db-widget__roi-eyebrow", "Estimated ROI"));
    const outcome = element("div", "db-widget__roi-outcome db-tool-partial-box");
    const metric = element("div", "db-widget__roi-metric");
    metric.append(
      element("span", "", "Payback period"),
      element("strong", "", payback || "Estimate ready"),
    );
    outcome.appendChild(metric);
    content.appendChild(outcome);
    if (widget.message) content.appendChild(element("p", "db-widget__roi-summary", widget.message));
    if (widget.leadConfirmation) {
      content.appendChild(element("p", "db-widget__roi-confirmation", widget.leadConfirmation));
    }

    const actions = element("div", "db-widget__roi-footer-actions");
    if (widget.mode === "partial") {
      actions.classList.add("db-widget__roi-footer-actions--result");
      actions.appendChild(roiActionButton("View detailed result", "db-widget__roi-primary db-tool-reveal", () => {
        requestRoiStep("tool:continue", { detail: true });
      }));
    } else if (widget.mode === "gated") {
      actions.classList.add("db-widget__roi-footer-actions--result");
      actions.appendChild(roiActionButton("Continue to detailed result", "db-widget__roi-primary db-tool-reveal", () => {
        openLeadPanel({
          source: "roi_calculator",
          label: "View detailed result",
          requireName: true,
          roiWidget: true,
        });
      }));
    } else if (widget.mode === "complete" && widget.actions.length) {
      widget.actions.slice(0, 3).forEach((action, index) => {
        actions.appendChild(roiActionButton(
          action.label,
          index === 0 ? "db-widget__roi-primary db-tool-reveal" : "db-widget__roi-secondary db-tool-back",
          () => handleAction(action),
        ));
      });
    }
    actions.appendChild(roiActionButton("Restart", "db-widget__roi-secondary db-tool-back", () => {
      widget.mode = "idle";
      widget.step = 0;
      widget.message = "";
      widget.actions = [];
      widget.components = [];
      widget.leadConfirmation = "";
      widget.collapsed = false;
      requestRoiStep("tool:roi");
    }));
    content.appendChild(actions);

    if (widget.mode === "complete" && widget.components.length) {
      const details = element("details", "db-widget__roi-details");
      details.appendChild(element("summary", "", "Recommended programs"));
      const list = element("div", "db-widget__roi-detail-content");
      widget.components.forEach((component) => {
        const rendered = renderComponent(component);
        if (rendered) list.appendChild(rendered);
      });
      if (list.childElementCount) {
        details.appendChild(list);
        content.appendChild(details);
      }
    }
  }

  function renderRoiWidget() {
    const widget = state.roiWidget;
    if (!widget || !widget.row.isConnected) return;
    widget.status.textContent = widget.mode === "complete"
      ? "Completed"
      : widget.mode === "question"
        ? `Question ${widget.step} of ${ROI_TOTAL_STEPS}`
        : widget.mode === "closed"
          ? "Closed"
        : ["partial", "gated"].includes(widget.mode)
          ? "Estimate ready"
          : widget.mode === "idle"
            ? "Ready when you are"
            : "Needs attention";
    widget.body.replaceChildren();
    const content = element("div", "db-widget__roi-stage");
    if (widget.collapsed) {
      content.appendChild(renderRoiCollapsed(widget));
    } else if (widget.mode === "idle") {
      content.append(
        element("h3", "db-widget__roi-intro", "See how fast this program pays for itself."),
        element("p", "db-widget__roi-supporting", "2 quick questions. Your answers stay inside this calculator."),
        roiActionButton("Start", "db-widget__roi-primary db-tool-start", () => {
          requestRoiStep("tool:roi", { chip: widget.chip });
        }),
      );
    } else if (widget.mode === "question") {
      renderRoiQuestion(widget, content);
    } else if (["partial", "gated", "complete"].includes(widget.mode)) {
      renderRoiResult(widget, content);
    } else {
      content.append(
        element("h3", "db-widget__roi-intro", "The calculator could not continue."),
        element("p", "db-widget__roi-supporting", widget.message || "Please try again."),
        roiActionButton("Try again", "db-widget__roi-primary db-tool-start", () => {
          requestRoiStep(widget.retryMessage || "tool:roi");
        }),
      );
    }
    if (widget.busy) {
      content.classList.add("db-widget__roi-stage--busy");
      content.setAttribute("aria-busy", "true");
      content.appendChild(element("span", "db-widget__roi-loading", "Updating…"));
    }
    widget.body.appendChild(content);
    widget.live.textContent = widget.mode === "question"
      ? `ROI calculator question ${widget.step} of ${ROI_TOTAL_STEPS}`
      : widget.mode === "complete"
        ? "ROI calculator completed"
        : "ROI calculator updated";
  }

  function updateRoiWidget(payload) {
    const widget = ensureRoiWidget();
    const safePayload = payload && typeof payload === "object" ? payload : {};
    const flow = roiFlowMetadata(safePayload);
    const rawFlow = activeFlowMetadata(safePayload);
    widget.busy = false;
    widget.payload = safePayload;
    widget.message = String(safePayload.message || safePayload.text || "").trim();
    widget.actions = payloadActions(safePayload, Array.isArray(safePayload.components) ? safePayload.components : [])
      .map(normalizedAction)
      .filter((action) => action && action.label);
    widget.components = (Array.isArray(safePayload.components) ? safePayload.components : [])
      .filter((component) => component && !["quick_actions", "lead_cta"].includes(component.type));
    applyActionMetadata(widget.actions);
    if (rawFlow) applyActiveFlow(rawFlow);

    const step = String(flow && flow.step || rawFlow && rawFlow.step || "");
    if (["program", "current_salary"].includes(step)) {
      rememberRoiPage();
      widget.mode = "question";
      widget.step = roiQuestionNumber(step);
    } else if (step === "partial_reveal") {
      widget.mode = "partial";
      widget.step = ROI_TOTAL_STEPS;
    } else if (step === "await_lead") {
      widget.mode = "gated";
      widget.step = ROI_TOTAL_STEPS;
    } else if (step === "reveal") {
      forgetRoiPage();
      widget.mode = "complete";
      widget.step = ROI_TOTAL_STEPS;
    } else {
      forgetRoiPage();
      widget.mode = "error";
    }
    widget.collapsed = false;
    renderRoiWidget();
    anchorBotMessage(widget.row);
    if (step === "await_lead" && widget.detailRequested) {
      widget.detailRequested = false;
      openLeadPanel({
        source: "roi_calculator",
        label: "View detailed result",
        requireName: true,
        roiWidget: true,
      });
    }
  }

  function openRoiCalculator(action) {
    state.conversationStarted = true;
    if (state.starter) state.starter.hidden = true;
    deactivateGuidedActions();
    transitionNavigation("tool");
    const widget = ensureRoiWidget();
    widget.chip = action || widget.chip;
    widget.collapsed = false;
    renderRoiWidget();
    anchorBotMessage(widget.row);
  }

  function careerQuizQuestionNumber(step) {
    const match = String(step || "").match(/^q(\d+)$/i);
    return match ? Math.min(CAREER_QUIZ_TOTAL_STEPS, Math.max(1, Number(match[1]))) : 1;
  }

  function careerQuizQuestionText(message) {
    const text = String(message || "").trim();
    const trailingQuestion = text.match(/(?:^|[.!]\s+)([^.!?]*\?)\s*$/);
    if (trailingQuestion) return trailingQuestion[1].trim();
    const sections = text
      .split(/\n\s*\n/)
      .map((section) => section.trim())
      .filter(Boolean);
    return sections[sections.length - 1] || "Choose the answer that feels most like you.";
  }

  function ensureCareerQuizWidget() {
    if (state.careerQuizWidget && state.careerQuizWidget.row.isConnected) {
      return state.careerQuizWidget;
    }
    deactivateGuidedActions();
    collapseGuidedCards();
    const view = createMessage("bot", "");
    view.row.classList.add("db-widget__message-row--career-quiz");
    view.bubble.remove();
    const stack = element("div", "db-widget__component-stack db-widget__career-quiz-stack");
    const card = element("section", "db-widget__career-quiz-card db-tool-widget");
    card.setAttribute("aria-label", "Help me choose");

    const header = element("header", "db-widget__career-quiz-header db-tool-header");
    const headerLeft = element("div", "db-tool-header-left");
    headerLeft.append(
      element("span", "db-tool-icon-badge", "🎯"),
      element("h2", "db-widget__career-quiz-title db-tool-title", "Help me choose"),
    );
    header.appendChild(headerLeft);
    const close = createButton("×", "db-widget__career-quiz-close db-tool-close", closeCareerQuiz);
    close.setAttribute("aria-label", "Close Help me choose");
    header.appendChild(close);

    const body = element("div", "db-widget__career-quiz-body");
    const live = element("p", "db-widget__sr-only");
    live.setAttribute("aria-live", "polite");
    const results = element("div", "db-widget__career-quiz-results");
    card.append(header, body, live);
    stack.append(card, results);
    view.content.appendChild(stack);
    state.careerQuizWidget = {
      view,
      row: view.row,
      card,
      body,
      live,
      results,
      mode: "idle",
      step: 0,
      payload: null,
      message: "",
      actions: [],
      components: [],
      busy: false,
      retryMessage: "",
      chip: null,
      detailRequested: false,
      leadConfirmation: "",
    };
    anchorBotMessage(view.row);
    return state.careerQuizWidget;
  }

  function careerQuizButton(label, className, handler) {
    const button = createButton(label, className, handler);
    button.disabled = Boolean(state.careerQuizWidget && state.careerQuizWidget.busy);
    return button;
  }

  async function abandonPersistedCareerQuizFlow() {
    if (!state.sessionId) {
      applyActiveFlow(null);
      forgetCareerQuizPage();
      return;
    }
    await fetchJson("/api/widget/context/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId }),
    });
    applyActiveFlow(null);
    state.activeFlowResumeKey = "";
    forgetCareerQuizPage();
  }

  function removeCareerQuizWidget() {
    const widget = state.careerQuizWidget;
    if (widget && widget.row.isConnected) widget.row.remove();
    state.careerQuizWidget = null;
  }

  async function closeCareerQuiz() {
    const widget = state.careerQuizWidget;
    if (!widget || widget.busy) return;
    const unfinished = Boolean(state.activeFlow && state.activeFlow.tool === "career_quiz");
    widget.busy = true;
    renderCareerQuizWidget();
    try {
      if (unfinished) await abandonPersistedCareerQuizFlow();
      else forgetCareerQuizPage();
      removeCareerQuizWidget();
      state.conversationStarted = false;
      await hydratePageContext();
      if (state.starter) {
        state.messages.appendChild(state.starter);
        state.starter.hidden = false;
        refreshResponsiveActionLayouts();
      }
    } catch (error) {
      widget.busy = false;
      widget.mode = "error";
      widget.message = "I couldn’t close this quiz just now. Please try again.";
      renderCareerQuizWidget();
      console.warn("DegreeBaba could not close the Career Quiz", error);
    }
  }

  function requestCareerQuizStep(message, options = {}) {
    const widget = ensureCareerQuizWidget();
    if (widget.busy) return;
    if (message === "tool:career_quiz") rememberCareerQuizPage();
    widget.busy = true;
    widget.retryMessage = message;
    widget.detailRequested = options.detail === true;
    renderCareerQuizWidget();
    sendMessage(message, {
      chip: options.chip || null,
      displayUser: false,
      showTyping: false,
      keepStarter: false,
      blurInput: false,
      onPayload: (payload) => updateCareerQuizWidget(payload),
      onError: (payload) => {
        widget.busy = false;
        widget.mode = "error";
        widget.message = payload.message;
        renderCareerQuizWidget();
      },
    });
  }

  function renderCareerQuizProgress(widget) {
    const progress = element("div", "db-widget__career-quiz-progress db-tool-progress");
    const track = element("div", "db-widget__career-quiz-progress-track db-progress-track");
    track.setAttribute("role", "progressbar");
    track.setAttribute("aria-label", "Help me choose progress");
    track.setAttribute("aria-valuemin", "0");
    track.setAttribute("aria-valuemax", String(CAREER_QUIZ_TOTAL_STEPS));
    track.setAttribute("aria-valuenow", String(widget.step));
    const fill = element("span", "db-widget__career-quiz-progress-fill db-progress-fill");
    fill.style.setProperty(
      "--db-career-quiz-progress",
      `${widget.step / CAREER_QUIZ_TOTAL_STEPS * 100}%`,
    );
    track.appendChild(fill);
    progress.append(track, element(
      "strong",
      "db-widget__career-quiz-progress-label db-progress-label",
      `${widget.step} of ${CAREER_QUIZ_TOTAL_STEPS}`,
    ));
    return progress;
  }

  function renderCareerQuizQuestion(widget, content) {
    content.appendChild(renderCareerQuizProgress(widget));
    content.appendChild(element(
      "h3",
      "db-widget__career-quiz-question db-tool-question",
      careerQuizQuestionText(widget.message),
    ));
    const options = element("div", "db-widget__career-quiz-options db-tool-opts");
    widget.actions.forEach((action) => {
      options.appendChild(careerQuizButton(action.label, "db-widget__career-quiz-option db-tool-opt", () => {
        requestCareerQuizStep(action.message);
      }));
    });
    content.appendChild(options);
  }

  function renderCareerQuizRecommendations(widget) {
    widget.results.replaceChildren();
    widget.components.forEach((component) => {
      if (["card_list", "finder_results"].includes(component.type)) {
        (component.cards || component.items || component.results || []).slice(0, 3).forEach((card) => {
          const rendered = renderComponent(card);
          if (rendered) widget.results.appendChild(rendered);
        });
        return;
      }
      const rendered = renderComponent(component);
      if (rendered) widget.results.appendChild(rendered);
    });
    if (widget.mode === "complete" && widget.actions.length) {
      const actions = element("div", "db-widget__career-quiz-result-actions");
      widget.actions.slice(0, 3).forEach((action, index) => {
        actions.appendChild(careerQuizButton(
          action.label,
          index === 0 ? "db-widget__career-quiz-primary db-tool-reveal" : "db-widget__career-quiz-secondary db-tool-back",
          () => handleAction(action),
        ));
      });
      widget.results.appendChild(actions);
    }
  }

  function renderCareerQuizResult(widget, content) {
    const result = element("div", "db-widget__career-quiz-result db-tool-partial-box");
    result.appendChild(element("span", "db-widget__career-quiz-result-check", "✓"));
    result.appendChild(element(
      "p",
      "db-widget__career-quiz-result-copy",
      widget.message || "Your best-fit area is ready.",
    ));
    content.appendChild(result);
    if (widget.leadConfirmation) {
      content.appendChild(element(
        "p",
        "db-widget__career-quiz-confirmation",
        widget.leadConfirmation,
      ));
    }
    if (widget.mode === "partial") {
      content.appendChild(careerQuizButton(
        "Continue to full result",
        "db-widget__career-quiz-primary db-tool-reveal",
        () => requestCareerQuizStep("tool:continue", { detail: true }),
      ));
    } else if (widget.mode === "gated") {
      content.appendChild(careerQuizButton(
        "Continue to full result",
        "db-widget__career-quiz-primary db-tool-reveal",
        () => openLeadPanel({
          source: "career_quiz_gate",
          label: "Continue to full result",
          requireName: true,
          careerQuizWidget: true,
        }),
      ));
    }
  }

  function renderCareerQuizWidget() {
    const widget = state.careerQuizWidget;
    if (!widget || !widget.row.isConnected) return;
    widget.body.replaceChildren();
    widget.results.replaceChildren();
    const content = element("div", "db-widget__career-quiz-stage");
    if (widget.mode === "question") {
      renderCareerQuizQuestion(widget, content);
    } else if (["partial", "gated", "complete"].includes(widget.mode)) {
      renderCareerQuizResult(widget, content);
    } else if (widget.mode === "idle") {
      content.append(
        element("p", "db-widget__career-quiz-supporting", "Answer 5 quick questions and we’ll point you to your best-fit field."),
      );
    } else {
      content.append(
        element("h3", "db-widget__career-quiz-question", "The quiz could not continue."),
        element("p", "db-widget__career-quiz-supporting", widget.message || "Please try again."),
        careerQuizButton("Try again", "db-widget__career-quiz-primary db-tool-start", () => {
          requestCareerQuizStep(widget.retryMessage || "tool:career_quiz");
        }),
      );
    }
    if (widget.busy) {
      content.classList.add("db-widget__career-quiz-stage--busy");
      content.setAttribute("aria-busy", "true");
      content.appendChild(element("span", "db-widget__career-quiz-loading", "Updating…"));
    }
    widget.body.appendChild(content);
    if (widget.mode === "complete") renderCareerQuizRecommendations(widget);
    widget.live.textContent = widget.mode === "question"
      ? `Help me choose question ${widget.step} of ${CAREER_QUIZ_TOTAL_STEPS}`
      : widget.mode === "complete"
        ? "Help me choose completed"
        : "Help me choose updated";
  }

  function updateCareerQuizWidget(payload) {
    const widget = ensureCareerQuizWidget();
    const safePayload = payload && typeof payload === "object" ? payload : {};
    const flow = careerQuizFlowMetadata(safePayload);
    const rawFlow = activeFlowMetadata(safePayload);
    widget.busy = false;
    widget.payload = safePayload;
    widget.message = String(safePayload.message || safePayload.text || "").trim();
    widget.actions = payloadActions(
      safePayload,
      Array.isArray(safePayload.components) ? safePayload.components : [],
    ).map(normalizedAction).filter((action) => action && action.label);
    widget.components = (Array.isArray(safePayload.components) ? safePayload.components : [])
      .filter((component) => component && !["quick_actions", "lead_cta"].includes(component.type));
    applyActionMetadata(widget.actions);
    if (rawFlow) applyActiveFlow(rawFlow);

    const step = String(flow && flow.step || rawFlow && rawFlow.step || "");
    if (/^q\d+$/i.test(step)) {
      rememberCareerQuizPage();
      widget.mode = "question";
      widget.step = careerQuizQuestionNumber(step);
    } else if (step === "partial_reveal") {
      widget.mode = "partial";
      widget.step = CAREER_QUIZ_TOTAL_STEPS;
    } else if (step === "await_lead") {
      widget.mode = "gated";
      widget.step = CAREER_QUIZ_TOTAL_STEPS;
    } else if (step === "reveal") {
      forgetCareerQuizPage();
      widget.mode = "complete";
      widget.step = CAREER_QUIZ_TOTAL_STEPS;
    } else if (step === "exit") {
      forgetCareerQuizPage();
      removeCareerQuizWidget();
      return;
    } else {
      forgetCareerQuizPage();
      widget.mode = "error";
    }
    renderCareerQuizWidget();
    anchorBotMessage(widget.row);
    if (step === "await_lead" && widget.detailRequested) {
      widget.detailRequested = false;
      openLeadPanel({
        source: "career_quiz_gate",
        label: "Continue to full result",
        requireName: true,
        careerQuizWidget: true,
      });
    }
  }

  function openCareerQuiz(action) {
    state.conversationStarted = true;
    if (state.starter) state.starter.hidden = true;
    deactivateGuidedActions();
    transitionNavigation("tool");
    const widget = ensureCareerQuizWidget();
    widget.chip = action || widget.chip;
    renderCareerQuizWidget();
    anchorBotMessage(widget.row);
    requestCareerQuizStep("tool:career_quiz", { chip: widget.chip });
  }

  function inferProgramFromPage() {
    if (state.pageContext && state.pageContext.program) return state.pageContext.program;
    if (state.pageContext && state.pageContext.course) return state.pageContext.course;
    if (state.pageContext && state.pageContext.context && state.pageContext.context.course) {
      return state.pageContext.context.course;
    }
    const source = `${pageEntitySlug} ${document.title}`.toLowerCase().replace(/[^a-z0-9]+/g, " ");
    return PROGRAM_OPTIONS.find((program) => source.includes(program.toLowerCase())) || "";
  }

  async function finderProgramOptions() {
    try {
      const data = await loadCatalog("program");
      const options = (data.options || [])
        .map((item) => item.name)
        .filter(Boolean)
        .slice(0, 8);
      return options.length ? options : PROGRAM_OPTIONS;
    } catch (_error) {
      return PROGRAM_OPTIONS;
    }
  }

  async function finderAreaOptions() {
    try {
      const data = await loadCatalog("specialization");
      return {
        featured: data.popular.slice(0, 6).map((item) => item.name),
      };
    } catch (_error) {
      return { featured: [] };
    }
  }

  function finderSteps() {
    return [
      { key: "program", question: "Which program?", options: [...state.finder.programOptions, "Not sure"] },
      { key: "area", question: "Which area?", options: state.finder.areaOptions.length ? [...state.finder.areaOptions, "Show all", "Not sure"] : ["Show all", "Not sure"] },
      { key: "approval", question: "Approval priority?", options: ["UGC-DEB only", "NAAC A+", "No preference"] },
      { key: "budget", question: "Your budget?", options: ["Under ₹1L", "₹1–2L", "₹2–3L", "₹3L+", "No preference"] },
    ];
  }

  function startFinder() {
    state.conversationStarted = true;
    if (state.starter) state.starter.hidden = true;
    const prefilled = !state.pageContextDismissed && ["course", "specialization"].includes(pageType)
      ? inferProgramFromPage()
      : "";
    state.finder = {
      step: prefilled ? 1 : 0,
      answers: prefilled ? { program: prefilled } : {},
      prefilled: Boolean(prefilled),
      programOptions: PROGRAM_OPTIONS,
      areaOptions: [],
    };
    state.finderView = createMessage("bot", "");
    renderFinderStep();
    Promise.all([finderProgramOptions(), finderAreaOptions()]).then(([programs, { featured }]) => {
      if (!state.finder) return;
      state.finder.programOptions = programs;
      state.finder.areaOptions = featured;
      if (state.finder.step <= 1) renderFinderStep();
    });
  }

  function renderFinderStep() {
    if (!state.finder || !state.finderView) return;
    const steps = finderSteps();
    const current = steps[state.finder.step];
    if (!current) {
      submitFinder();
      return;
    }
    const view = state.finderView;
    view.bubble.remove();
    Array.from(view.content.querySelectorAll(".db-widget__component-stack")).forEach((node) => node.remove());
    const panel = element("section", "db-widget__finder db-finder-widget");
    const header = element("div", "db-widget__finder-header db-finder-title-row");
    header.appendChild(element("h3", "db-widget__finder-title db-finder-title", "Help me choose"));
    const progress = element("div", "db-widget__finder-progress db-tool-progress");
    const track = element("div", "db-widget__progress-track db-progress-track");
    const fill = element("div", "db-widget__finder-progress-fill db-progress-fill");
    fill.style.setProperty("--db-progress", `${(state.finder.step + 1) * 25}%`);
    track.appendChild(fill);
    progress.append(
      track,
      element("span", "db-widget__finder-step db-progress-label", `${state.finder.step + 1} of 4`),
    );
    const question = element("h3", "db-widget__finder-question db-finder-question", current.question);
    const options = element("div", "db-widget__finder-options db-finder-opts");
    const selectChoice = (choice) => {
      if (choice === "Show all") {
        openPicker("specialization", (item) => {
          if (!state.finder) return;
          state.finder.answers.area = item.name;
          state.finder.step += 1;
          renderFinderStep();
        });
        return;
      }
      state.finder.answers[current.key] = choice;
      state.finder.step += 1;
      renderFinderStep();
    };
    const renderOptionPage = (offset = 0, previousOffsets = []) => {
      options.replaceChildren();
      const remaining = current.options.length - offset;
      const pageSize = offset === 0 || remaining <= 2 ? 2 : 1;
      if (offset > 0) {
        const previous = previousOffsets[previousOffsets.length - 1] || 0;
        options.appendChild(createButton("Back", "db-widget__finder-option db-finder-opt", () => {
          renderOptionPage(previous, previousOffsets.slice(0, -1));
        }));
      }
      current.options.slice(offset, offset + pageSize).forEach((choice) => {
        const button = createButton(choice, "db-widget__finder-option db-finder-opt", () => {
          selectChoice(choice);
        });
        button.setAttribute("aria-pressed", "false");
        options.appendChild(button);
      });
      if (offset + pageSize < current.options.length) {
        options.appendChild(createButton("More", "db-widget__finder-option db-finder-opt", () => {
          renderOptionPage(offset + pageSize, [...previousOffsets, offset]);
        }));
      }
    };
    renderOptionPage();
    const skip = createButton("Skip → show results now", "db-widget__finder-skip db-finder-skip", submitFinder);
    panel.append(header, progress);
    if (state.finder.prefilled) {
      panel.appendChild(element("p", "db-widget__finder-prefill db-prefill-note", "Program pre-filled from this page ✓"));
    }
    panel.append(question, options, skip);
    const stack = element("div", "db-widget__component-stack");
    stack.appendChild(panel);
    view.content.appendChild(stack);
    anchorBotMessage(view.row);
  }

  function finderFallbackMessage(answers) {
    const parts = [
      answers.program && answers.program !== "Not sure" ? answers.program : "an online program",
      answers.area && answers.area !== "Not sure" ? `in ${answers.area}` : "",
      answers.approval && answers.approval !== "No preference" ? `with ${answers.approval}` : "",
      answers.budget && answers.budget !== "No preference" ? `within ${answers.budget}` : "",
    ].filter(Boolean);
    return `Recommend three ${parts.join(" ")} options for me`;
  }

  function exactlyThreeFinderCards(payload) {
    const components = Array.isArray(payload.components) ? payload.components : [];
    const cards = [];
    components.forEach((component) => {
      if (["university_card", "program_card", "course_card", "specialization_card"].includes(component.type)) cards.push(component);
      if (["card_list", "finder_results"].includes(component.type)) cards.push(...(component.cards || component.items || component.results || []));
    });
    if (!cards.length && Array.isArray(payload.results)) cards.push(...payload.results);
    return cards.slice(0, 3).map((card) => card.type ? card : { type: "program_card", ...card });
  }

  async function submitFinder() {
    if (!state.finder || state.busy) return;
    const answers = { ...state.finder.answers };
    state.busy = true;
    showTyping(true);
    try {
      const payload = await fetchJson("/api/widget/finder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          program: answers.program || null,
          area: answers.area || null,
          approval: answers.approval || null,
          budget: answers.budget || null,
        }),
      });
      if (payload.session_id) {
        state.sessionId = payload.session_id;
        rememberSessionId(state.sessionId);
      }
      const cards = exactlyThreeFinderCards(payload);
      state.finderView.row.remove();
      if (cards.length !== 3) {
        renderBotPayload({
          message: "I couldn’t find three published options for that exact combination. Relax a filter and I’ll try again.",
          quick_actions: [
            { label: "Relax my filters", action: "open_finder", message: "Relax my filters" },
            { label: "Browse programs", action: "show_programs", message: "Browse programs" },
            { label: "Talk to a counsellor", action: "open_lead", message: "Talk to a counsellor" },
          ],
        });
        return;
      }
      renderBotPayload({
        ...payload,
        message: payload.message || "Here are three published options, ordered from lower to higher fee.",
        components: [{ type: "finder_results", cards }, ...(payload.components || []).filter((item) => item.type === "lead_cta")],
        quick_actions: Array.isArray(payload.quick_actions) && payload.quick_actions.length ? payload.quick_actions : [
          { label: "Refine my choices", action: "open_finder", message: "Refine my choices" },
          { label: "Browse programs", action: "show_programs", message: "Browse programs" },
          { label: "Talk to a counsellor", action: "open_lead", message: "Talk to a counsellor" },
        ],
      });
    } catch (error) {
      state.finderView.row.remove();
      console.warn("DegreeBaba finder endpoint unavailable; using chat", error);
      state.busy = false;
      showTyping(false);
      state.finder = null;
      state.finderView = null;
      sendMessage(finderFallbackMessage(answers));
      return;
    } finally {
      state.busy = false;
      showTyping(false);
      state.finder = null;
      state.finderView = null;
    }
  }
