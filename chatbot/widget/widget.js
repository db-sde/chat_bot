(function degreeBabaWidgetBootstrap() {
  "use strict";

  const script = document.currentScript || Array.from(document.scripts).find((item) =>
    /\/widget(?:\/widget)?\.js(?:\?|$)/.test(item.src),
  );
  if (!script || script.dataset.degreebabaLoaded === "true") return;
  script.dataset.degreebabaLoaded = "true";

  const requestedSiteKey = (script.dataset.siteKey || "degreebaba").trim();
  const siteKey = requestedSiteKey || "degreebaba";
  const scriptUrl = new URL(script.src, window.location.href);
  const apiBase = (script.dataset.apiBase || scriptUrl.origin).replace(/\/$/, "");
  const cssUrl = script.dataset.cssUrl || new URL("./widget.css", scriptUrl).href;
  const documentData = document.documentElement.dataset;

  function cleanPageType(value) {
    const normalized = String(value || "").trim().toLowerCase();
    return ["university", "course", "specialization"].includes(normalized)
      ? normalized
      : "homepage";
  }

  const pageUniversitySlug = (
    script.dataset.pageUniversitySlug || documentData.pageUniversitySlug || documentData.universitySlug || ""
  ).trim();
  let pageType = cleanPageType(script.dataset.pageType || documentData.pageType);
  if (pageType === "homepage" && pageUniversitySlug) pageType = "university";
  const pageEntitySlug = (
    script.dataset.pageEntitySlug ||
    documentData.pageEntitySlug ||
    (pageType === "course" ? documentData.courseSlug : "") ||
    (pageType === "specialization" ? documentData.specializationSlug : "") ||
    (pageType === "university" ? pageUniversitySlug : "") ||
    ""
  ).trim();

  const hostId = `degreebaba-widget-${siteKey.replace(/[^a-z0-9_-]/gi, "-")}`;
  if (document.getElementById(hostId)) return;

  window.DegreeBabaWidget = window.DegreeBabaWidget || {};
  const widgetNamespace = window.DegreeBabaWidget;
  widgetNamespace.instances = widgetNamespace.instances || {};
  widgetNamespace.loading = widgetNamespace.loading || {};
  if (widgetNamespace.instances[siteKey] || widgetNamespace.loading[siteKey]) return;
  widgetNamespace.loading[siteKey] = true;

  const GUIDED_THINKING_MS = 650;
  const GUIDED_VISIBLE_ACTIONS = 3;
  const NavigationStep = Object.freeze({
    HOMEPAGE: "HOMEPAGE",
    UNIVERSITY_PICKER: "UNIVERSITY_PICKER",
    UNIVERSITY_CARD: "UNIVERSITY_CARD",
    COURSE_PICKER: "COURSE_PICKER",
    COURSE_CARD: "COURSE_CARD",
    SPECIALIZATION_PICKER: "SPECIALIZATION_PICKER",
    SPECIALIZATION_CARD: "SPECIALIZATION_CARD",
    FEES: "FEES",
    ELIGIBILITY: "ELIGIBILITY",
    CAREERS: "CAREERS",
    APPROVALS: "APPROVALS",
    REVIEWS: "REVIEWS",
    SYLLABUS: "SYLLABUS",
    ADMISSIONS: "ADMISSIONS",
    VALIDITY: "VALIDITY",
    COMPARISON: "COMPARISON",
    TOOL: "TOOL",
    LEAD_CAPTURE: "LEAD_CAPTURE",
  });
  const NAVIGATION_TRANSITIONS = Object.freeze({
    reset: NavigationStep.HOMEPAGE,
    university_picker: NavigationStep.UNIVERSITY_PICKER,
    university_card: NavigationStep.UNIVERSITY_CARD,
    course_picker: NavigationStep.COURSE_PICKER,
    course_card: NavigationStep.COURSE_CARD,
    specialization_picker: NavigationStep.SPECIALIZATION_PICKER,
    specialization_card: NavigationStep.SPECIALIZATION_CARD,
    fees: NavigationStep.FEES,
    eligibility: NavigationStep.ELIGIBILITY,
    career: NavigationStep.CAREERS,
    careers: NavigationStep.CAREERS,
    approval: NavigationStep.APPROVALS,
    approvals: NavigationStep.APPROVALS,
    accreditation: NavigationStep.APPROVALS,
    accreditations: NavigationStep.APPROVALS,
    reviews: NavigationStep.REVIEWS,
    syllabus: NavigationStep.SYLLABUS,
    admission_process: NavigationStep.ADMISSIONS,
    admission_steps: NavigationStep.ADMISSIONS,
    admissions: NavigationStep.ADMISSIONS,
    online_validity: NavigationStep.VALIDITY,
    validity: NavigationStep.VALIDITY,
    comparison: NavigationStep.COMPARISON,
    tool: NavigationStep.TOOL,
    lead: NavigationStep.LEAD_CAPTURE,
  });
  const CHIP_GUIDE_ACTIONS = Object.freeze({
    browse_universities: "browse_universities",
    browse_programs: "browse_programs",
    programs_here: "programs_here",
    approvals: "accreditations",
    reviews: "reviews",
    fees_emi: "fees",
    fees_across: "fees",
    starting_fees: "fees",
    see_fees: "fees",
    eligibility: "eligibility",
    check_eligibility: "eligibility",
    specializations: "specializations",
    other_specs: "other_specializations",
    careers: "career",
    careers_from_syllabus: "career",
    syllabus: "syllabus",
    validity: "online_validity",
    validity_course: "online_validity",
    compare: "compare",
    compare_top: "compare",
    compare_others: "compare",
    compare_universities: "compare",
    apply_now: "lead",
    counsellor: "lead",
  });
  const HANDLER_GUIDE_ACTIONS = Object.freeze({
    list_universities: "browse_universities",
    get_fees: "fees",
    get_eligibility: "eligibility",
    get_specializations: "specializations",
    get_validity: "online_validity",
    get_careers: "career",
    get_syllabus: "syllabus",
    get_reviews: "reviews",
    get_approvals: "accreditations",
    compare: "compare",
    cta_apply: "lead",
    cta_callback: "lead",
  });
  const PROGRAM_OPTIONS = ["Online MBA", "Online MCA", "Online Executive MBA", "Online MSc"];

  function storedSessionId() {
    try {
      return window.sessionStorage.getItem(`degreebaba:${siteKey}:session`) || "";
    } catch (_error) {
      return "";
    }
  }

  function rememberSessionId(sessionId) {
    try {
      window.sessionStorage.setItem(`degreebaba:${siteKey}:session`, sessionId);
    } catch (_error) {
      // Storage can be unavailable in privacy-restricted third-party contexts.
    }
  }

  function forgetSessionId() {
    state.sessionId = "";
    try {
      window.sessionStorage.removeItem(`degreebaba:${siteKey}:session`);
    } catch (_error) {
      // Storage can be unavailable in privacy-restricted third-party contexts.
    }
  }

  function safeHttpUrl(value) {
    if (!value) return "";
    try {
      const resolved = new URL(String(value), apiBase);
      return ["http:", "https:"].includes(resolved.protocol) ? resolved.href : "";
    } catch (_error) {
      return "";
    }
  }

  const state = {
    config: null,
    sessionId: storedSessionId(),
    open: false,
    busy: false,
    starter: null,
    starterGrid: null,
    starterType: pageType,
    typing: null,
    typingTimer: null,
    messages: null,
    input: null,
    panel: null,
    launcher: null,
    contextBar: null,
    contextChip: null,
    contextLabel: null,
    contextCourse: null,
    contextMeta: null,
    context: null,
    pageContext: null,
    pageContextDismissed: false,
    guideBundle: null,
    guideBusy: false,
    guideGeneration: 0,
    guideReady: null,
    openingChips: null,
    navigation: null,
    navigationStep: NavigationStep.HOMEPAGE,
    currentChipSurface: "page:home",
    currentFunnelStage: "top",
    interactionCount: 0,
    configVersion: "",
    contentVersion: "",
    correlationId: "",
    conversationStarted: false,
    starterVisibleActions: [],
    starterImpressionKey: "",
    activeFlow: null,
    activeFlowResumeKey: "",
    toolLeadRequiresName: false,
    pendingLeadPersistence: null,
    viewedActions: new Set(),
    welcomeView: null,
    overlay: null,
    overlayBody: null,
    overlayTitle: null,
    overlayClose: null,
    pickerCache: new Map(),
    guidePickerCache: new Map(),
    finder: null,
    finderView: null,
    compareSelections: [],
    compareTray: null,
    pendingCompletedChipId: null,
    pendingGuidedInfo: null,
    lastMessage: "",
  };

  function transitionNavigation(event, navigation = null) {
    if (navigation && typeof navigation === "object") {
      state.navigation = navigation;
      const completedActions = Array.isArray(navigation.completed_actions)
        ? navigation.completed_actions
        : [];
      state.viewedActions.clear();
      completedActions.forEach((action) => state.viewedActions.add(String(action)));
      const serverStep = String(navigation.step || "").trim().toUpperCase();
      if (Object.prototype.hasOwnProperty.call(NavigationStep, serverStep)) {
        state.navigationStep = NavigationStep[serverStep];
      }
      const interactionCount = Number(navigation.interaction_count);
      if (Number.isFinite(interactionCount) && interactionCount >= 0) {
        state.interactionCount = interactionCount;
      }
      if (navigation.surface) state.currentChipSurface = String(navigation.surface);
      if (navigation.funnel_stage) state.currentFunnelStage = String(navigation.funnel_stage);
      return state.navigationStep;
    }
    const key = String(event || "").trim().toLowerCase();
    if (NAVIGATION_TRANSITIONS[key]) state.navigationStep = NAVIGATION_TRANSITIONS[key];
    return state.navigationStep;
  }

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

  function analyticsEntity() {
    const context = currentGuideContext() || state.context || {};
    const entity = currentGuideEntity() || {};
    const type = cleanPageType(context.page_type || state.starterType || pageType);
    return {
      type,
      id: String(entity.id || context.entity_id || (type === "homepage" ? "homepage" : "unknown")),
    };
  }

  function analyticsPayload(event, action = null, extra = {}) {
    const item = action && typeof action === "object" ? action : {};
    return {
      session_id: state.sessionId || null,
      event,
      surface: String(item.surface || extra.surface || state.currentChipSurface || "page:home"),
      funnel_stage: String(
        item.funnel_stage || extra.funnel_stage || state.currentFunnelStage || "top"
      ),
      interaction_count: Number.isFinite(Number(item.interaction_count))
        ? Number(item.interaction_count)
        : state.interactionCount,
      entity: extra.entity || item.entity || analyticsEntity(),
      config_version: String(item.config_version || state.configVersion || "unknown"),
      content_version: String(item.content_version || state.contentVersion || "unknown"),
      ...(item.correlation_id || extra.correlation_id || state.correlationId
        ? {
            correlation_id: String(
              item.correlation_id || extra.correlation_id || state.correlationId,
            ),
          }
        : {}),
      ...(item.chip_id ? { chip_id: String(item.chip_id) } : {}),
      ...(item.chip_handler || item.handler
        ? { chip_handler: String(item.chip_handler || item.handler) }
        : {}),
      ...(item.lead_tags && typeof item.lead_tags === "object"
        ? { lead_tags: item.lead_tags }
        : {}),
      ...(Array.isArray(extra.chips) ? { chips: extra.chips } : {}),
    };
  }

  function emitAnalytics(event, action = null, extra = {}) {
    const payload = analyticsPayload(event, action, extra);
    void fetch(`${apiBase}/api/widget/analytics`, {
      method: "POST",
      mode: "cors",
      keepalive: true,
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    }).catch((error) => {
      console.debug("DegreeBaba analytics unavailable", error);
    });
  }

  function emitChipShown(actions) {
    const visible = (actions || []).filter((action) => action && action.chip_id);
    if (!visible.length) return;
    emitAnalytics("chip_shown", visible[0], {
      chips: visible.map((action) => ({
        chip_id: String(action.chip_id),
        chip_handler: String(action.chip_handler || action.handler || ""),
      })),
    });
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
      transitionNavigation(type === "homepage" ? "reset" : `${type}_card`);
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

  function normalizeConfig(payload) {
    const branding = payload && payload.branding ? payload.branding : payload || {};
    const behavior = payload && payload.behavior ? payload.behavior : payload || {};
    const color = /^#[0-9a-f]{6}$/i.test(branding.primary_color || "")
      ? branding.primary_color
      : "#E84010";
    return {
      siteKey: payload.site_key || siteKey,
      botName: branding.bot_name || "DegreeBaba",
      avatarUrl: safeHttpUrl(branding.avatar_url),
      primaryColor: color,
      welcomeMessage:
        branding.welcome_message ||
        "Hi! I can help you compare universities and find the right online program.",
      showTypingIndicator: behavior.show_typing_indicator !== false,
      showAvatar: behavior.show_avatar !== false,
      autoOpen: behavior.auto_open === true,
    };
  }

  async function fetchJson(path, options = {}) {
    const response = await fetch(`${apiBase}${path}`, {
      mode: "cors",
      headers: { Accept: "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (!response.ok) {
      const error = new Error(`Request unavailable (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return response.json();
  }

  async function loadConfig() {
    return normalizeConfig(await fetchJson(`/api/widget/config/${encodeURIComponent(siteKey)}`));
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function createButton(label, className, handler) {
    const button = element("button", className, label);
    button.type = "button";
    button.addEventListener("click", handler);
    return button;
  }

  function createAvatar(sizeClass = "") {
    const avatar = element("span", `db-widget__avatar ${sizeClass}`.trim());
    avatar.setAttribute("aria-hidden", "true");
    if (state.config.avatarUrl) {
      const image = document.createElement("img");
      image.src = state.config.avatarUrl;
      image.alt = "";
      image.referrerPolicy = "no-referrer";
      avatar.appendChild(image);
    } else {
      avatar.innerHTML =
        '<svg viewBox="0 0 24 24" aria-hidden="true" width="24" height="24"><path d="M12 3a7 7 0 0 0-7 7v1.2A3 3 0 0 0 3 14v2a3 3 0 0 0 3 3h1.2l1.1 1.3a1 1 0 0 0 .8.4h5.8a1 1 0 0 0 .8-.4l1.1-1.3H18a3 3 0 0 0 3-3v-2a3 3 0 0 0-2-2.8V10a7 7 0 0 0-7-7Zm-3 8.5a1.25 1.25 0 1 1 0 2.5 1.25 1.25 0 0 1 0-2.5Zm6 0a1.25 1.25 0 1 1 0 2.5 1.25 1.25 0 0 1 0-2.5ZM8.7 16h6.6a3.7 3.7 0 0 1-6.6 0Z"/></svg>';
    }
    return avatar;
  }

  function createAiAccent() {
    const accent = element("span", "db-widget__ai-accent");
    accent.setAttribute("aria-hidden", "true");
    accent.innerHTML =
      '<svg viewBox="0 0 24 24"><path d="M12 2l1.4 5.1L18 9l-4.6 1.9L12 16l-1.4-5.1L6 9l4.6-1.9L12 2Zm6 12 .8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8L18 14Z"/></svg>';
    return accent;
  }

  function addRichText(container, value) {
    const text = String(value || "").trim();
    if (!text) return;
    let list = null;
    text.split(/\r?\n/).forEach((rawLine) => {
      const line = rawLine.trim();
      if (!line) {
        list = null;
        return;
      }
      const bullet = line.match(/^[•*-]\s+(.+)$/);
      if (bullet) {
        if (!list) {
          list = element("ul", "db-widget__message-list");
          container.appendChild(list);
        }
        list.appendChild(element("li", "", bullet[1].replace(/\*\*/g, "")));
        return;
      }
      list = null;
      const clean = line.replace(/^#{1,4}\s*/, "").replace(/\*\*/g, "");
      const heading = /:$/.test(clean) || /^#{1,4}\s/.test(line);
      container.appendChild(
        element(heading ? "h4" : "p", heading ? "db-widget__message-heading" : "", clean),
      );
    });
  }

  function initials(value) {
    const words = String(value || "U").trim().split(/\s+/).filter(Boolean);
    if (!words.length) return "U";
    if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
    return `${words[0][0]}${words[words.length - 1][0]}`.toUpperCase();
  }

  function normalizedAction(value) {
    if (typeof value === "string") return { label: value, message: value };
    if (!value || typeof value !== "object") return null;
    return {
      ...value,
      chip_id: value.chip_id || value.id || "",
      chip_handler: value.chip_handler || value.handler || "",
      label: String(value.label || value.title || value.message || "").trim(),
      message: String(value.message || value.label || "").trim(),
    };
  }

  function actionButton(action, className = "db-widget__action") {
    const normalized = normalizedAction(action);
    if (!normalized || !normalized.label) return null;
    return createButton(normalized.label, className, () => handleAction(normalized));
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

  function findFact(component, needles) {
    const facts = component.highlights || component.facts || [];
    const match = facts.find((fact) => {
      const label = String(fact && fact.label || "").toLowerCase();
      return needles.some((needle) => label.includes(needle));
    });
    return match ? String(match.value || "") : "";
  }

  function trustRow(values) {
    const usable = values.filter(Boolean);
    if (!usable.length) return null;
    const row = element("div", "db-widget__trust-row");
    usable.forEach((value) => row.appendChild(element("span", "db-widget__trust-badge", value)));
    return row;
  }

  function statPills(facts) {
    const grid = element("dl", "db-widget__fact-grid db-widget__stat-pills");
    facts.filter((fact) => fact && fact.value).slice(0, 3).forEach((fact) => {
      const item = element("div", "db-widget__fact db-widget__stat-pill");
      item.appendChild(element("dt", "db-widget__stat-label", fact.label));
      item.appendChild(element("dd", "db-widget__stat-value", fact.value));
      grid.appendChild(item);
    });
    return grid;
  }

  function compactMetadata(facts) {
    const row = element("div", "db-widget__compact-meta");
    row.setAttribute("role", "list");
    facts.filter((fact) => {
      if (!fact || fact.value === null || fact.value === undefined) return false;
      return String(fact.value).trim().length > 0;
    }).slice(0, 3).forEach((fact) => {
      const item = element("span", "db-widget__compact-meta-item", String(fact.value));
      item.setAttribute("role", "listitem");
      if (fact.label) item.setAttribute("aria-label", `${fact.label}: ${fact.value}`);
      row.appendChild(item);
    });
    return row;
  }

  function compactFee(value, prefix = "") {
    const fee = String(value || "").trim().replace(/^INR\s*/i, "₹");
    if (!fee) return "";
    return prefix && !fee.toLowerCase().startsWith(prefix.toLowerCase()) ? `${prefix}${fee}` : fee;
  }

  function publishedCount(component, directKey, alternateKey, collectionKey) {
    if (component[directKey] !== null && component[directKey] !== undefined) return component[directKey];
    if (component[alternateKey] !== null && component[alternateKey] !== undefined) return component[alternateKey];
    return Array.isArray(component[collectionKey]) ? component[collectionKey].length : null;
  }

  function cardReference(component) {
    const provider = component.university_name || "";
    const name = component.name || component.title || "this option";
    const label = provider && !name.toLowerCase().includes(provider.toLowerCase())
      ? `${provider} ${name}`
      : name;
    return { id: component.id || component.slug || label, label, component };
  }

  function detailsFor(component) {
    const specializationCount = publishedCount(
      component, "specialization_count", "num_specializations", "specializations"
    );
    const programsCount = publishedCount(component, "program_count", "num_programs", "programs");
    const keyDetails = [
      { label: "Fee", value: component.fee || component.total_fee || component.starting_fee },
      { label: "Duration", value: component.duration },
      specializationCount || specializationCount === 0
        ? { label: "Specializations", value: `${specializationCount}` }
        : null,
      programsCount || programsCount === 0 ? { label: "Programs", value: `${programsCount}` } : null,
      { label: "Learning mode", value: component.learning_mode || component.mode },
      { label: "EMI", value: component.emi || component.emi_amount },
      { label: "Established", value: component.established_year },
      { label: "Career outcome", value: firstCareer(component) },
    ].filter((item) => item && item.value !== null && item.value !== undefined && String(item.value).trim());
    const fallback = {
      description: component.description || component.summary,
      accreditations: component.accreditations || component.highlights,
      key_details: keyDetails,
      admission_steps: component.admission_steps,
      reviews: component.reviews,
      faqs: component.faqs,
      programs: component.programs,
    };
    if (!component.details || typeof component.details !== "object" || Array.isArray(component.details)) return fallback;
    return { ...fallback, ...component.details, key_details: component.details.key_details || keyDetails };
  }

  function hasDetails(component) {
    const details = detailsFor(component);
    return Object.values(details).some((value) => Array.isArray(value) ? value.length : Boolean(value));
  }

  function cardActions(component, detailsLabel = "Details") {
    const actions = element("div", "db-widget__card-actions");
    const details = createButton(detailsLabel, "db-widget__card-button db-widget__card-action--primary", () => {
      if (hasDetails(component)) openDetails(component);
      else if (component.guided === true) executeGuidedAction("fees", "View fees");
      else sendMessage(`Tell me about ${cardReference(component).label}`);
    });
    const compare = createButton("+ Compare", "db-widget__card-button db-widget__card-action", () => {
      beginGuidedComparison(component);
    });
    actions.append(details, compare);
    return actions;
  }

  function renderUniversityCard(component) {
    const card = element("article", "db-widget__card db-widget__university-card");
    const header = element("div", "db-widget__card-header");
    const mark = element("span", "db-widget__card-mark", initials(component.name));
    const title = element("div", "db-widget__card-heading");
    title.appendChild(element("span", "db-widget__eyebrow", "University"));
    title.appendChild(element("h3", "", component.name));
    header.append(mark, title);
    card.appendChild(header);

    const ugc = component.ugc_status || findFact(component, ["ugc", "approval"]);
    const naacRaw = component.naac_grade || findFact(component, ["naac"]);
    const naac = naacRaw && !String(naacRaw).toLowerCase().includes("naac") ? `NAAC ${naacRaw}` : naacRaw;
    const trust = trustRow([ugc, naac]);
    if (trust) card.appendChild(trust);

    const programsCount = publishedCount(component, "program_count", "num_programs", "programs");
    const metadata = compactMetadata([
      { label: "Starting fee", value: compactFee(component.starting_fee || findFact(component, ["starting fee", "fee"]), "From ") },
      { label: "Programs", value: programsCount || programsCount === 0 ? `${programsCount} Programs` : "" },
      { label: "Mode", value: component.learning_mode || component.mode || findFact(component, ["learning mode", "mode"]) },
    ]);
    if (metadata.childElementCount) card.appendChild(metadata);
    card.appendChild(cardActions(component));
    recordCardShown(component, "university");
    return card;
  }

  function firstCareer(component) {
    const direct = component.career_outcome || component.career || null;
    if (direct && typeof direct === "object") {
      return [direct.role || direct.title, direct.average_salary || direct.avg_salary].filter(Boolean).join(" · ");
    }
    if (direct) return [String(direct), component.average_salary].filter(Boolean).join(" · ");
    const careers = component.career_outcomes || component.job_profiles || [];
    const first = careers[0];
    if (first && typeof first === "object") {
      return [first.job_title || first.title, first.avg_salary || first.average_salary].filter(Boolean).join(" · ");
    }
    return first ? String(first).replace(/[()]/g, "") : "";
  }

  function renderProgramCard(component) {
    const card = element("article", "db-widget__card db-widget__program-card");
    const isSpecialization = component.kind === "specialization" || component.type === "specialization_card";
    const provider = component.university_name || "";
    card.appendChild(element("span", "db-widget__eyebrow", provider || (isSpecialization ? "Specialization" : "Program")));
    const heading = isSpecialization && component.category
      ? `${String(component.category).toUpperCase()} in ${component.name}`
      : component.name;
    card.appendChild(element("h3", "", heading));

    const ugc = component.ugc_status || findFact(component, ["ugc", "approval"]);
    const naacRaw = component.naac_grade || findFact(component, ["naac"]);
    const naac = naacRaw && !String(naacRaw).toLowerCase().includes("naac") ? `NAAC ${naacRaw}` : naacRaw;
    const trust = trustRow([ugc, naac]);
    if (trust) card.appendChild(trust);

    const specializationCount = publishedCount(
      component, "specialization_count", "num_specializations", "specializations"
    );
    const metadata = compactMetadata([
      { label: "Fee", value: compactFee(component.fee || component.total_fee) },
      { label: "Duration", value: component.duration },
      {
        label: isSpecialization ? "Mode" : "Specializations",
        value: isSpecialization
          ? component.mode
          : specializationCount || specializationCount === 0 ? `${specializationCount} Specs` : "",
      },
    ]);
    if (metadata.childElementCount) card.appendChild(metadata);
    card.appendChild(cardActions(component));
    recordCardShown(component, isSpecialization ? "specialization" : "course");
    return card;
  }

  const COMPARISON_ORDER = [
    "fees", "fee", "duration", "mode", "naac grade", "naac", "ugc status", "ugc",
    "specializations", "emi", "eligibility",
  ];

  function renderComparisonCard(component) {
    const card = element("article", "db-widget__card db-widget__comparison-card");
    const heading = element("div", "db-widget__comparison-heading");
    heading.appendChild(element("span", "db-widget__eyebrow", "Comparison"));
    heading.appendChild(element("h3", "", component.title || "Published comparison"));
    card.appendChild(heading);

    const items = (component.items || []).slice(0, 3);
    const labels = new Map();
    items.forEach((item) => (item.facts || []).forEach((fact) => {
      const key = String(fact.label || "").trim().toLowerCase();
      if (key) labels.set(key, String(fact.label));
    }));
    const ordered = Array.from(labels.keys()).sort((a, b) => {
      const aIndex = COMPARISON_ORDER.indexOf(a);
      const bIndex = COMPARISON_ORDER.indexOf(b);
      return (aIndex < 0 ? 999 : aIndex) - (bIndex < 0 ? 999 : bIndex) || a.localeCompare(b);
    }).slice(0, 8);
    const rows = element("div", "db-widget__comparison-rows");
    ordered.forEach((key) => {
      const row = element("section", "db-widget__comparison-row");
      row.appendChild(element("span", "db-widget__comparison-label", labels.get(key)));
      const values = element("div", "db-widget__comparison-values");
      items.forEach((item) => {
        const fact = (item.facts || []).find((candidate) => String(candidate.label || "").trim().toLowerCase() === key);
        const value = element("div", "db-widget__comparison-value");
        const itemLabel = item.subtitle ? `${item.subtitle} — ${item.name}` : item.name;
        value.appendChild(element("strong", "", `${itemLabel}: `));
        value.appendChild(document.createTextNode(fact && fact.value ? String(fact.value) : "Not published"));
        values.appendChild(value);
      });
      row.appendChild(values);
      rows.appendChild(row);
    });
    card.appendChild(rows);
    if (component.verdict) {
      const verdict = element("div", "db-widget__comparison-verdict");
      verdict.appendChild(element("strong", "", "Honest verdict"));
      verdict.appendChild(document.createTextNode(String(component.verdict)));
      card.appendChild(verdict);
    }
    recordCardShown(component, "comparison");
    return card;
  }

  function renderLeadCta(component) {
    const cta = element("section", "db-widget__lead-cta");
    const copy = element("div", "");
    copy.appendChild(element("span", "db-widget__eyebrow", "Personal help"));
    copy.appendChild(element("strong", "", component.label || "Talk to a counsellor"));
    cta.appendChild(copy);
    cta.appendChild(createButton("Check now", "db-widget__lead-button", () => {
      openLeadPanel({
        source: component.source || component.payload && component.payload.source || "lead_cta",
        label: component.label,
        component,
      });
    }));
    return cta;
  }

  function renderQuickActions(actions) {
    const row = element("div", "db-widget__quick-actions db-widget__follow-up-actions");
    const available = (actions || []).map(normalizedAction).filter((action) => action && action.label);
    const renderPage = (offset = 0) => {
      row.replaceChildren();
      const visible = offset === 0
        ? available.slice(0, 3)
        : available.slice(offset, offset + 2);
      if (offset > 0) {
        row.appendChild(createButton("Back", "db-widget__more-toggle", () => {
          renderPage(offset <= GUIDED_VISIBLE_ACTIONS ? 0 : offset - 2);
        }));
      }
      visible.forEach((action) => {
        const button = actionButton(action);
        if (button) row.appendChild(button);
      });
      emitChipShown(visible);
      const nextOffset = offset === 0 ? GUIDED_VISIBLE_ACTIONS : offset + 2;
      if (nextOffset < available.length) {
        row.appendChild(createButton("More", "db-widget__more-toggle", () => renderPage(nextOffset)));
      }
    };
    renderPage();
    return row;
  }

  function renderComponent(component) {
    if (!component || !component.type) return null;
    if (component.type === "university_card") return renderUniversityCard(component);
    if (["program_card", "specialization_card", "course_card"].includes(component.type)) return renderProgramCard(component);
    if (component.type === "comparison_card") return renderComparisonCard(component);
    if (component.type === "lead_cta") return renderLeadCta(component);
    if (component.type === "quick_actions") return renderQuickActions(component.actions);
    if (["card_list", "finder_results"].includes(component.type)) {
      const list = element("div", "db-widget__card-list");
      if (component.title) list.appendChild(element("h3", "db-widget__card-list-title", component.title));
      (component.cards || component.items || component.results || []).slice(0, 3).forEach((card) => {
        const rendered = renderComponent(card);
        if (rendered) list.appendChild(rendered);
      });
      return list;
    }
    return null;
  }

  function anchorBotMessage(row) {
    window.requestAnimationFrame(() => {
      if (!state.messages || !row || !row.isConnected) return;
      const contextHeight = state.contextBar && !state.contextBar.hidden ? state.contextBar.offsetHeight : 0;
      const top = Math.max(0, row.offsetTop - contextHeight - 8);
      if (typeof state.messages.scrollTo === "function") {
        state.messages.scrollTo({ top, behavior: "smooth" });
      } else {
        state.messages.scrollTop = top;
      }
    });
  }

  function createMessage(role, text) {
    const row = element("div", `db-widget__message-row db-widget__message-row--${role}`);
    const previousRows = state.messages
      ? state.messages.querySelectorAll(".db-widget__message-row")
      : [];
    const previousRow = previousRows.length ? previousRows[previousRows.length - 1] : null;
    const groupedBot = role === "bot" && previousRow && previousRow.classList.contains("db-widget__message-row--bot");
    if (groupedBot) row.classList.add("db-widget__message-row--grouped");
    if (role === "bot" && state.config.showAvatar && !groupedBot) {
      row.appendChild(createAvatar("db-widget__avatar--message"));
    }
    const content = element("div", "db-widget__message-content");
    const bubble = element("div", `db-widget__bubble db-widget__bubble--${role}`);
    addRichText(bubble, text);
    content.appendChild(bubble);
    row.appendChild(content);
    state.messages.appendChild(row);
    if (role === "bot") anchorBotMessage(row);
    else state.messages.scrollTop = state.messages.scrollHeight;
    return { row, content, bubble };
  }

  function payloadActions(payload, components) {
    if (Array.isArray(payload.quick_actions) && payload.quick_actions.length) {
      return payload.quick_actions;
    }
    const component = components.find((item) => item && item.type === "quick_actions");
    if (component && Array.isArray(component.actions)) return component.actions;
    return Array.isArray(payload.suggested_chips) ? payload.suggested_chips : [];
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

  function renderBotPayload(payload, existingMessage) {
    const safePayload = payload && typeof payload === "object" ? payload : {};
    const message = safePayload.message || safePayload.text || "I’m ready to help with your university search.";
    const view = existingMessage || createMessage("bot", "");
    view.bubble.replaceChildren();
    addRichText(view.bubble, message);

    Array.from(view.content.querySelectorAll(".db-widget__component-stack")).forEach((node) => node.remove());
    let components = Array.isArray(safePayload.components) ? safePayload.components.slice() : [];
    const actions = payloadActions(safePayload, components);
    applyActionMetadata(actions);
    const toolFlow = activeFlowMetadata(safePayload);
    if (toolFlow) applyActiveFlow(toolFlow);
    components = components.filter((item) => item && item.type !== "quick_actions");
    if (safePayload.cta && !components.some((item) => item.type === "lead_cta")) {
      components.push({ type: "lead_cta", ...safePayload.cta });
    }
    if (actions.length) components.push({ type: "quick_actions", actions });

    const stack = element("div", "db-widget__component-stack");
    components.forEach((component) => {
      const rendered = renderComponent(component);
      if (rendered) stack.appendChild(rendered);
    });
    if (stack.childElementCount) view.content.appendChild(stack);
    if (Object.prototype.hasOwnProperty.call(safePayload, "context")) {
      const emptyToolContext = Boolean(
        toolFlow && !contextValues(safePayload.context).length,
      );
      if (!emptyToolContext) {
        updateContext(safePayload.context);
        synchronizeGuideContext(safePayload);
      }
    }
    anchorBotMessage(view.row);
    return view;
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

  function openingMessage(type, bundle = null) {
    const context = bundle && bundle.context;
    const label = context && (context.label || contextValues(context).join(" • "));
    const messages = {
      homepage: "Explore universities and online programs. Where would you like to start?",
      university: label
        ? `You're viewing ${label}. What would you like to explore?`
        : "Explore programs, reviews, accreditations, or comparisons for this university.",
      course: label
        ? `You're viewing ${label}. What would you like to know?`
        : "Check fees, specializations, eligibility, or compare this program.",
      specialization: label
        ? `You're viewing ${label}. What would you like to know?`
        : "Explore careers, syllabus, fees, or related specializations.",
    };
    return messages[type] || messages.homepage;
  }

  function updateWelcome(bundle = state.guideBundle) {
    if (!state.welcomeView) return;
    state.welcomeView.bubble.replaceChildren();
    addRichText(state.welcomeView.bubble, openingMessage(currentGuidePageType(), bundle));
    state.welcomeView.bubble.prepend(createAiAccent());
  }

  function deactivateGuidedActions() {
    if (!state.messages) return;
    state.messages.querySelectorAll('[data-guide-actions="true"]').forEach((row) => row.remove());
  }

  function renderGuidedActions(actions) {
    const row = element("div", "db-widget__quick-actions db-widget__follow-up-actions");
    row.dataset.guideActions = "true";
    const available = (actions || []).map(normalizedAction).filter((action) => (
      action && action.label && (
        action.repeat === true ||
        !state.viewedActions.has(action.chip_id || action.action || action.guide)
      )
    ));
    const renderPage = (offset = 0) => {
      row.replaceChildren();
      const pageSize = offset === 0 ? GUIDED_VISIBLE_ACTIONS : 2;
      if (offset > 0) {
        row.appendChild(createButton("Back", "db-widget__more-toggle", () => {
          renderPage(offset <= GUIDED_VISIBLE_ACTIONS ? 0 : offset - 2);
        }));
      }
      const visible = available.slice(offset, offset + pageSize);
      visible.forEach((action) => {
        const guideAction = guideActionFor(action) || action.action;
        const className = guideAction === "lead"
          ? "db-widget__action db-widget__action--lead"
          : "db-widget__action";
        row.appendChild(createButton(action.label, className, () => {
          row.remove();
          if (typeof action.onSelect === "function") {
            recordChipTap(action);
            action.onSelect();
          } else if (action.chip_id || action.chip_handler || action.guide) {
            handleAction(action);
          } else {
            executeGuidedAction(action.action, action.label, action.options || {});
          }
        }));
      });
      emitChipShown(visible);
      if (offset + pageSize < available.length) {
        row.appendChild(createButton("More", "db-widget__more-toggle", () => {
          renderPage(offset + pageSize);
        }));
      }
    };
    renderPage();
    return row;
  }

  function renderGuidePrompt(message, actions = []) {
    deactivateGuidedActions();
    const view = createMessage("bot", message);
    const actionRow = renderGuidedActions(actions);
    if (actionRow.childElementCount) {
      const stack = element("div", "db-widget__component-stack");
      stack.appendChild(actionRow);
      view.content.appendChild(stack);
    }
    anchorBotMessage(view.row);
    return view;
  }

  function collapseGuidedCards() {
    if (!state.messages) return;
    state.messages.querySelectorAll("details.db-widget__collapsed-answer[open]").forEach((disclosure) => {
      disclosure.open = false;
    });
  }

  function presentGuidedCard(message, card, title, actions = []) {
    deactivateGuidedActions();
    collapseGuidedCards();
    const view = createMessage("bot", message);
    const stack = element("div", "db-widget__component-stack");
    const disclosure = element("details", "db-widget__collapsed-answer");
    disclosure.dataset.guidePrimary = "true";
    disclosure.open = true;
    disclosure.appendChild(element(
      "summary",
      "db-widget__collapsed-answer-summary",
      title || card.querySelector("h3") && card.querySelector("h3").textContent || "Information",
    ));
    disclosure.appendChild(card);
    disclosure.addEventListener("toggle", () => {
      if (!disclosure.open) return;
      state.messages.querySelectorAll("details.db-widget__collapsed-answer[open]").forEach((candidate) => {
        if (candidate !== disclosure) candidate.open = false;
      });
    });
    stack.appendChild(disclosure);
    const actionRow = renderGuidedActions(actions);
    if (actionRow.childElementCount) stack.appendChild(actionRow);
    view.content.appendChild(stack);
    anchorBotMessage(view.row);
    return view;
  }

  function guideSection(card, title, values, emptyCopy) {
    const section = element("section", "db-widget__detail-section");
    section.appendChild(element("h4", "", title));
    const items = Array.isArray(values) ? values.filter(Boolean) : values ? [values] : [];
    if (!items.length) {
      section.appendChild(element("p", "db-widget__state-copy", emptyCopy));
      card.appendChild(section);
      return;
    }
    const list = element("ul", "db-widget__message-list");
    items.forEach((item) => {
      if (item && typeof item === "object") {
        const label = item.name || item.label || item.title || item.reviewer_name || "";
        const value = item.amount || item.value || item.text || item.score || item.description || "";
        const total = item.total ? ` · Total ${item.total}` : "";
        list.appendChild(element("li", "", [label, value].filter(Boolean).join(": ") + total));
      } else {
        list.appendChild(element("li", "", item));
      }
    });
    section.appendChild(list);
    card.appendChild(section);
  }

  function guidedInfoCard(kind) {
    const bundle = state.guideBundle || {};
    const info = bundle.info || {};
    const entity = bundle.entity || {};
    const data = info[kind] || {};
    const card = element("article", `db-widget__card db-widget__info-card db-widget__info-card--${kind}`);
    const titles = {
      fees: ["Fees", "Fees & EMI"],
      eligibility: ["Admissions", "Eligibility"],
      career: ["Outcomes", "Career & Salary"],
      syllabus: ["Curriculum", "Syllabus"],
      reviews: ["Student voice", "Student Reviews"],
      accreditations: ["Recognition", "Accreditations"],
    };
    const [eyebrow, title] = titles[kind] || ["Details", "Published information"];
    card.append(element("span", "db-widget__eyebrow", eyebrow), element("h3", "", title));

    if (kind === "fees") {
      const facts = statPills([
        { label: "Total Fee", value: data.total_fee || entity.fee },
        { label: "Semester Fee", value: data.semester_fee },
        { label: "EMI", value: data.emi || entity.emi },
      ]);
      if (facts.childElementCount) card.appendChild(facts);
      else card.appendChild(element("p", "db-widget__state-copy", "Confirmed fee details haven't been published yet."));
      guideSection(card, "EMI plans", data.plans, "EMI plans haven't been published yet.");
    } else if (kind === "eligibility") {
      const summary = data.summary || entity.eligibility;
      card.appendChild(element(
        "p",
        summary ? "db-widget__card-summary" : "db-widget__state-copy",
        summary || "Confirmed eligibility requirements haven't been published yet.",
      ));
      guideSection(card, "Qualification checklist", data.requirements, "A qualification checklist hasn't been published yet.");
    } else if (kind === "career") {
      const facts = statPills([{ label: "Average Salary", value: data.average_salary || entity.average_salary }]);
      if (facts.childElementCount) card.appendChild(facts);
      else card.appendChild(element("p", "db-widget__state-copy", "Average salary information hasn't been published yet."));
      guideSection(card, "Job roles", data.job_roles, "Job roles haven't been published yet.");
      guideSection(card, "Recruiters", data.recruiters, "Recruiter information hasn't been published yet.");
    } else if (kind === "syllabus") {
      const semesters = Array.isArray(data.semesters) ? data.semesters : [];
      if (!semesters.length) {
        card.appendChild(element("p", "db-widget__state-copy", "A semester-wise syllabus hasn't been published yet."));
      } else {
        semesters.forEach((semester, index) => {
          const details = element("details", "db-widget__detail-section");
          if (index === 0) details.open = true;
          details.appendChild(element("summary", "", semester.title || `Semester ${index + 1}`));
          const list = element("ul", "db-widget__message-list");
          (semester.items || []).forEach((item) => list.appendChild(element("li", "", item)));
          details.appendChild(list);
          card.appendChild(details);
        });
      }
    } else if (kind === "reviews") {
      const rating = statPills([{ label: "Rating", value: data.rating ? `${data.rating} / 5` : "" }]);
      if (rating.childElementCount) card.appendChild(rating);
      guideSection(card, "Rating breakdown", data.breakdown, "A rating breakdown hasn't been published yet.");
      guideSection(card, "Testimonials", data.testimonials, "Student testimonials haven't been published yet.");
    } else if (kind === "accreditations") {
      guideSection(card, "Published recognition", data.items, "Accreditation details haven't been published yet.");
      card.appendChild(element(
        "p",
        "db-widget__card-summary",
        "Always confirm the current recognition status for the exact university and program before enrolling.",
      ));
    }
    return { card, title };
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
      accreditations: "approvals",
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
    presentGuidedCard(
      `Here's the confirmed ${result.title.toLowerCase()} information for ${currentGuideLabel()}.`,
      result.card,
      result.title,
      followups,
    );
  }

  function validityCard() {
    const card = element("article", "db-widget__card db-widget__info-card");
    card.append(
      element("span", "db-widget__eyebrow", "Before you enrol"),
      element("h3", "", "Is an online degree valid?"),
      element(
        "p",
        "db-widget__card-summary",
        "Validity depends on the recognition status of the university and the exact program.",
      ),
    );
    guideSection(card, "What to verify", [
      "Check the university's current UGC entitlement.",
      "Review its published NAAC grade and accreditations.",
      "Confirm recognition for the exact program and intake before paying.",
    ], "");
    return card;
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
      state.pendingLeadPersistence = chip && chip.chip_id
        ? persistCompletedChip(chip)
        : null;
      openLeadPanel({
        source: options.source || "guided_widget",
        label,
        chip,
        analyticsRecorded: Boolean(chip && chip.chip_id),
      });
      return;
    }
    runGuidedResponse(async () => {
      if (action === "browse_universities") {
        transitionNavigation("university_picker");
        await openPicker("university", { onSelect: selectGuidedEntity });
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
      } else if (["fees", "eligibility", "career", "syllabus", "reviews", "accreditations"].includes(action)) {
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

  function showTyping(show, autoHideMs = 800) {
    if (!state.config.showTypingIndicator || !state.typing) return;
    if (state.typingTimer) window.clearTimeout(state.typingTimer);
    state.typingTimer = null;
    if (show && state.messages) {
      state.messages.appendChild(state.typing);
      state.messages.scrollTop = state.messages.scrollHeight;
    }
    state.typing.hidden = !show;
    if (state.messages) state.messages.setAttribute("aria-busy", String(show));
    if (show && autoHideMs > 0) {
      state.typingTimer = window.setTimeout(() => {
        state.typing.hidden = true;
        if (state.messages) state.messages.setAttribute("aria-busy", "false");
        state.typingTimer = null;
      }, autoHideMs);
    }
  }

  async function consumeSse(response, onEvent) {
    if (!response.body) throw new Error("Streaming response is unavailable");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        let event = "message";
        const dataLines = [];
        block.split("\n").forEach((line) => {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
        });
        if (dataLines.length) {
          try {
            onEvent(event, JSON.parse(dataLines.join("\n")));
          } catch (error) {
            console.warn("DegreeBaba widget ignored malformed SSE data", error);
          }
        }
        boundary = buffer.indexOf("\n\n");
      }
      if (done) break;
    }
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
    state.lastMessage = message;
    state.input.value = "";
    if (state.starter && options.keepStarter !== true) state.starter.hidden = true;
    if (options.displayUser !== false) {
      createMessage("user", String(options.displayText || message));
    }
    showTyping(true);
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
      const response = await fetch(`${apiBase}/chat`, {
        method: "POST",
        mode: "cors",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`Chat request failed (${response.status})`);
      await consumeSse(response, (event, payload) => {
        if (payload.session_id) {
          state.sessionId = payload.session_id;
          rememberSessionId(state.sessionId);
        }
        if (event === "token" && payload.token) bufferedText += payload.token;
        if (["response", "final", "replace"].includes(event)) finalPayload = payload;
      });
      showTyping(false);
      const payload = finalPayload || { message: bufferedText };
      if (hadActiveFlow && !activeFlowMetadata(payload)) applyActiveFlow(null);
      renderBotPayload(payload);
    } catch (error) {
      showTyping(false);
      const timeoutMessage = error && error.name === "AbortError"
        ? "The advisor took too long to respond. Your chat is safe—please try once more."
        : "I couldn’t reach the advisor just now. Please try again in a moment.";
      renderBotPayload(errorPayload(timeoutMessage, message));
      console.error("DegreeBaba widget request failed", error);
    } finally {
      window.clearTimeout(timeout);
      state.busy = false;
      state.input.blur();
    }
  }

  function contextValues(context) {
    if (!context || typeof context !== "object") return [];
    const valueOf = (value) => {
      if (value && typeof value === "object") return value.name || value.label || value.concept || "";
      return value || "";
    };
    return [
      valueOf(context.university || context.university_concept),
      valueOf(context.course || context.course_concept || context.category),
      valueOf(context.specialization || context.specialization_concept),
    ].map((value) => String(value).trim()).filter(Boolean);
  }

  function updateContext(context) {
    const values = contextValues(context);
    state.context = values.length ? context : null;
    state.contextBar.hidden = !values.length;
    if (!values.length) return;
    const university = values[0] || "Current university";
    const academicPath = values.slice(1).join(" • ");
    const entity = state.guideBundle && state.guideBundle.entity || {};
    const metadata = [
      entity.ugc_status,
      entity.duration,
      entity.learning_mode || entity.mode,
    ].map((value) => String(value || "").trim()).filter(Boolean);
    state.contextLabel.textContent = university;
    state.contextCourse.textContent = academicPath;
    state.contextCourse.hidden = !academicPath;
    state.contextMeta.replaceChildren();
    metadata.slice(0, 3).forEach((value) => {
      state.contextMeta.appendChild(element("span", "db-widget__context-meta-item", value));
    });
    state.contextMeta.hidden = !metadata.length;
    state.contextChip.setAttribute("aria-label", `Current context: ${values.join(", ")}`);
  }

  async function loadGuideContext(entityReference = "", logicalType = "homepage") {
    const generation = ++state.guideGeneration;
    const query = new URLSearchParams();
    if (entityReference) query.set("entity_id", entityReference);
    else query.set("page_type", cleanPageType(logicalType));
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
      renderBotPayload(resumeResponse);
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

  function renderStarterBank(type) {
    const opening = state.openingChips;
    const top = opening && Array.isArray(opening.top) && opening.top.length
      ? opening.top
      : safeFallbackActions();
    const more = opening && Array.isArray(opening.more) ? opening.more : [];
    const primary = top.filter(
      (action) => !state.viewedActions.has(action.chip_id || action.guide || action.action),
    );
    const secondary = more.filter(
      (action) => !state.viewedActions.has(action.chip_id || action.guide || action.action),
    );
    state.starterVisibleActions = primary;

    state.starterGrid.replaceChildren();

    // Scroll wrapper to contain all options if they exceed max-height
    const scrollContainer = element("div", "db-widget__starter-scroll");
    const primaryGrid = element("div", "db-widget__starter-grid");

    primary.forEach((action) => {
      const button = actionButton(action, "db-widget__starter-action");
      if (button) primaryGrid.appendChild(button);
    });
    scrollContainer.appendChild(primaryGrid);
    state.starterGrid.appendChild(scrollContainer);
    emitStarterImpressions();

    if (secondary.length) {
      const secondaryGrid = element("div", "db-widget__starter-grid");
      secondaryGrid.style.display = "none";
      secondaryGrid.style.marginTop = "8px";

      secondary.forEach((action) => {
        const button = actionButton(action, "db-widget__starter-action");
        if (button) secondaryGrid.appendChild(button);
      });
      scrollContainer.appendChild(secondaryGrid);

      const toggle = createButton(
        "More",
        "db-widget__more-action db-widget__more-toggle",
        () => {
          const isHidden = secondaryGrid.style.display === "none";
          secondaryGrid.style.display = isHidden ? "grid" : "none";
          toggle.textContent = isHidden ? "Less" : "More";
          toggle.setAttribute("aria-expanded", String(isHidden));
          toggle.classList.toggle("db-widget__more-toggle--less", !isHidden);
          if (isHidden && state.open && !state.starter.hidden) emitChipShown(secondary);
        }
      );
      toggle.setAttribute("aria-expanded", "false");
      state.starterGrid.appendChild(toggle);
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

  function normalizeCatalogItem(item, kind) {
    if (typeof item === "string") return { id: item, slug: item, name: item, meta: "", popular: false };
    const name = item.name || item.label || item.university_name || item.university_full_name ||
      item.specialization_name || item.spec_name || item.title || "";
    const metaParts = [
      item.meta,
      item.naac_grade && `NAAC ${item.naac_grade}`,
      item.ugc_status || item.ugc_approved,
      (item.program_count || item.num_programs) && `${item.program_count || item.num_programs} programs`,
      item.provider_count && `${item.provider_count} providers`,
      item.university_name,
      item.fee,
      item.duration,
    ].filter(Boolean);
    return {
      ...item,
      id: item.id || item.entity_id || item.slug || name,
      slug: item.slug || item.id || name,
      name: String(name),
      meta: metaParts.join(" · "),
      kind,
      popular: item.popular === true || item.is_popular === true,
    };
  }

  async function loadCatalog(kind) {
    if (state.pickerCache.has(kind)) return state.pickerCache.get(kind);
    const payload = await fetchJson(`/api/widget/catalog/${encodeURIComponent(kind)}`);
    const rawItems = Array.isArray(payload) ? payload : payload.items || payload.options || payload.results ||
      payload.universities || payload.specializations || [];
    const items = rawItems.map((item) => normalizeCatalogItem(item, kind)).filter((item) => item.name);
    const rawPopular = Array.isArray(payload.popular) ? payload.popular : [];
    const popular = rawPopular.length
      ? rawPopular.map((item) => normalizeCatalogItem(item, kind)).filter((item) => item.name).slice(0, 8)
      : items.filter((item) => item.popular).slice(0, 8);
    const result = { items, popular };
    state.pickerCache.set(kind, result);
    return result;
  }

  async function loadGuideCatalog(kind, filters = {}) {
    const aliases = {
      university: "universities",
      universities: "universities",
      program: "programs",
      programs: "programs",
      course: "courses",
      courses: "courses",
      specialization: "specializations",
      specializations: "specializations",
    };
    const requestKind = aliases[kind] || kind;
    const query = new URLSearchParams();
    ["q", "university", "course"].forEach((key) => {
      if (filters[key]) query.set(key, filters[key]);
    });
    const cacheKey = `${requestKind}?${query.toString()}`;
    if (!filters.q && state.guidePickerCache.has(cacheKey)) {
      return state.guidePickerCache.get(cacheKey);
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    const payload = await fetchJson(`/api/widget/guide/catalog/${encodeURIComponent(requestKind)}${suffix}`);
    const rawItems = Array.isArray(payload) ? payload : payload.items || [];
    const items = rawItems.map((item) => normalizeCatalogItem(item, requestKind)).filter((item) => item.name);
    const result = { items, popular: items.filter((item) => item.popular).slice(0, 8) };
    if (!filters.q) state.guidePickerCache.set(cacheKey, result);
    return result;
  }

  function openOverlay(title, className) {
    state.input.blur();
    state.overlay.className = `db-widget__overlay ${className || ""}`.trim();
    state.overlayTitle.textContent = title;
    state.overlayBody.replaceChildren();
    state.overlay.style.gridTemplateRows = "auto minmax(0, 1fr)";
    state.overlayBody.style.minHeight = "0";
    state.overlayBody.style.overflow = "hidden";
    state.overlay.hidden = false;
    return state.overlayBody;
  }

  function closeOverlay() {
    state.overlay.hidden = true;
    state.overlayBody.replaceChildren();
    state.overlay.className = "db-widget__overlay";
  }

  function pickerTone(value) {
    const hash = Array.from(String(value || "")).reduce((total, character) => {
      return ((total * 31) + character.charCodeAt(0)) >>> 0;
    }, 0);
    return `${hash % 6}`;
  }

  function pickerRow(item, kind, popular = false, options = {}) {
    const displayName = options.display === "university"
      ? item.university_name || item.name
      : item.name;
    const rowClass = popular
      ? "db-widget__popular-item db-widget__popular-item--rich"
      : "db-widget__picker-row db-widget__picker-row--rich";
    const row = createButton("", rowClass, () => {
      closeOverlay();
      if (typeof options.onSelect === "function") {
        options.onSelect(item, displayName);
        return;
      }
      selectGuidedEntity(item, displayName);
    });
    row.dataset.tone = pickerTone(displayName);
    row.appendChild(element("span", "db-widget__picker-monogram", initials(displayName)));
    const copy = element("span", "db-widget__picker-copy");
    copy.appendChild(element("span", "db-widget__picker-name", displayName));
    const displayMeta = options.display === "university"
      ? [item.name, item.fee, item.duration].filter(Boolean).join(" · ")
      : item.meta;
    if (displayMeta) copy.appendChild(element("span", "db-widget__picker-meta", displayMeta));
    row.append(copy, element("span", "db-widget__picker-arrow", "›"));
    return row;
  }

  function renderPickerResults(container, data, kind, query = "", options = {}) {
    container.replaceChildren();
    const normalizedQuery = query.trim().toLowerCase();
    const filtered = data.items.filter((item) => {
      const displayName = options.display === "university" ? item.university_name || item.name : item.name;
      return `${displayName} ${item.meta}`.toLowerCase().includes(normalizedQuery);
    });
    if (!normalizedQuery && data.popular.length) {
      const section = element("section", "db-widget__picker-section");
      section.appendChild(element("h3", "db-widget__picker-section-title", "⭐ Popular"));
      const grid = element("div", "db-widget__picker-popular");
      data.popular.slice(0, 8).forEach((item) => grid.appendChild(pickerRow(item, kind, true, options)));
      section.appendChild(grid);
      container.appendChild(section);
    }
    if (!filtered.length) {
      container.appendChild(element("p", "db-widget__picker-empty", "No matching option."));
      return;
    }
    const allSection = element("section", "db-widget__picker-section db-widget__picker-section--all");
    const sectionLabel = normalizedQuery ? `${filtered.length} Results` : "All";
    allSection.appendChild(element("h3", "db-widget__picker-section-title", sectionLabel));
    const list = element("div", "db-widget__picker-results");
    filtered.sort((a, b) => {
      const aName = options.display === "university" ? a.university_name || a.name : a.name;
      const bName = options.display === "university" ? b.university_name || b.name : b.name;
      return aName.localeCompare(bName);
    }).forEach((item) => list.appendChild(pickerRow(item, kind, false, options)));
    allSection.appendChild(list);
    container.appendChild(allSection);
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
    const body = openOverlay(title, "db-widget__picker-overlay");
    const sheet = element("section", "db-widget__picker db-widget__picker-sheet");
    sheet.style.gridTemplateRows = "auto minmax(0, 1fr)";
    const searchWrap = element("div", "db-widget__picker-search-wrap");
    const search = document.createElement("input");
    search.className = "db-widget__picker-search";
    search.type = "search";
    search.placeholder = options.display === "university" ? "Search universities" : `Search ${label}`;
    search.setAttribute("aria-label", search.placeholder);
    searchWrap.appendChild(search);
    const content = element("div", "db-widget__picker-content db-widget__picker-list");
    content.appendChild(element("p", "db-widget__picker-empty", "Loading published options…"));
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

  function inferProgramFromPage() {
    if (state.pageContext && state.pageContext.program) return state.pageContext.program;
    const source = `${pageEntitySlug} ${document.title}`.toLowerCase();
    const options = [
      ["executive", "Online Executive MBA"], ["mba", "Online MBA"], ["mca", "Online MCA"], ["msc", "Online MSc"],
    ];
    const match = options.find(([needle]) => source.includes(needle));
    return match ? match[1] : "";
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
      { key: "program", question: "Which program?", options: [...PROGRAM_OPTIONS, "Not sure"] },
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
      areaOptions: [],
    };
    state.finderView = createMessage("bot", "");
    renderFinderStep();
    finderAreaOptions().then(({ featured }) => {
      if (!state.finder) return;
      state.finder.areaOptions = featured;
      if (state.finder.step === 1) renderFinderStep();
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
    view.bubble.replaceChildren();
    const intro = state.finder.prefilled && state.finder.step === 1
      ? `1 of 4 ✓ · ${state.finder.answers.program}`
      : "Four quick taps—no typing needed.";
    addRichText(view.bubble, intro);
    Array.from(view.content.querySelectorAll(".db-widget__component-stack")).forEach((node) => node.remove());
    const panel = element("section", "db-widget__finder");
    const header = element("div", "db-widget__finder-header");
    header.append(
      element("h3", "db-widget__finder-question", current.question),
      element("span", "db-widget__finder-step", `${state.finder.step + 1} of 4`),
    );
    const progress = element("div", "db-widget__finder-progress");
    const track = element("div", "db-widget__progress-track");
    const fill = element("div", "db-widget__finder-progress-fill");
    fill.style.setProperty("--db-progress", `${(state.finder.step + 1) * 25}%`);
    track.appendChild(fill);
    progress.appendChild(track);
    const options = element("div", "db-widget__finder-options");
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
        options.appendChild(createButton("Back", "db-widget__finder-option", () => {
          renderOptionPage(previous, previousOffsets.slice(0, -1));
        }));
      }
      current.options.slice(offset, offset + pageSize).forEach((choice) => {
        const button = createButton(choice, "db-widget__finder-option", () => {
          selectChoice(choice);
        });
        button.setAttribute("aria-pressed", "false");
        options.appendChild(button);
      });
      if (offset + pageSize < current.options.length) {
        options.appendChild(createButton("More", "db-widget__finder-option", () => {
          renderOptionPage(offset + pageSize, [...previousOffsets, offset]);
        }));
      }
    };
    renderOptionPage();
    const skip = createButton("Skip → show results now", "db-widget__finder-skip", submitFinder);
    panel.append(header, progress, options, skip);
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

  function detailSection(body, title, value) {
    if (!value || Array.isArray(value) && !value.length) return;
    const section = element("section", "db-widget__detail-section");
    section.appendChild(element("h3", "", title));
    const values = Array.isArray(value) ? value : [value];
    values.forEach((item) => {
      if (item && typeof item === "object") {
        const heading = item.question || item.label || item.body_name || item.reviewer_name || "";
        const copy = item.answer || item.value || item.body_detail || item.body_descriptor || item.review_text || item.text || "";
        if (heading) section.appendChild(element("h4", "", heading));
        if (copy) section.appendChild(element("p", "", copy));
      } else if (item) {
        section.appendChild(element("p", "", item));
      }
    });
    body.appendChild(section);
  }

  function openDetails(component) {
    const body = openOverlay(component.name || "Program details", "db-widget__detail-overlay");
    const panel = element("section", "db-widget__detail-panel db-widget__details-panel");
    panel.style.height = "100%";
    panel.style.gridTemplateRows = "minmax(0, 1fr)";
    const detailBody = element("div", "db-widget__detail-body db-widget__details-body");
    const details = detailsFor(component);
    detailSection(detailBody, "Overview", details.description || details.hero_description);
    detailSection(detailBody, "Key details", details.key_details);
    detailSection(detailBody, "Accreditations", details.accreditations);
    detailSection(detailBody, "Admission steps", details.admission_steps);
    detailSection(detailBody, "Student reviews", details.reviews);
    detailSection(detailBody, "FAQs", details.faqs);
    if (!detailBody.childElementCount) {
      detailBody.appendChild(element("p", "db-widget__picker-empty", "No additional published detail is available yet."));
    }
    panel.appendChild(detailBody);
    body.appendChild(panel);
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
    const filters = {};
    if (kind === "course" && entity.category) filters.course = entity.category;
    if (kind === "specialization" && entity.name) filters.q = entity.name;
    return openPicker(kind, {
      title: state.compareSelections.length ? "Choose one more option" : "Choose an option to compare",
      display: kind === "course" ? "university" : undefined,
      filters,
      onSelect: (item) => {
        const selectionCount = addToComparison(item);
        if (selectionCount <= 1) {
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

  function renderCompareTray() {
    state.compareTray.replaceChildren();
    state.compareTray.hidden = !state.compareSelections.length;
    if (!state.compareSelections.length) return;
    const header = element("div", "db-widget__compare-tray-header");
    header.append(
      element("span", "", `${state.compareSelections.length} of 2 selected`),
      createButton("Clear", "db-widget__compare-remove", () => {
        state.compareSelections = [];
        renderCompareTray();
      }),
    );
    const items = element("div", "db-widget__compare-tray-items");
    state.compareSelections.forEach((item) => {
      const chip = element("div", "db-widget__compare-tray-item");
      chip.appendChild(element("span", "", item.label));
      chip.appendChild(createButton("×", "db-widget__compare-remove", () => {
        state.compareSelections = state.compareSelections.filter((candidate) => candidate.id !== item.id);
        renderCompareTray();
      }));
      items.appendChild(chip);
    });
    state.compareTray.append(header, items);
    if (state.compareSelections.length === 2) {
      state.compareTray.appendChild(createButton("Compare now", "db-widget__compare-submit", submitComparison));
    }
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
    const requiresName = options.requireName === true || state.toolLeadRequiresName;
    const actionMeta = normalizedAction(options.chip || options.component) || {};
    transitionNavigation("lead");
    if (!options.analyticsRecorded) {
      emitAnalytics(isApplication ? "apply_clicked" : "counsellor_clicked", null);
    }
    const body = openOverlay(
      isApplication ? "Start your application" : "Talk to a counsellor",
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
      isApplication ? "Take the next step with an admissions counsellor" : "Talk to a real admissions counsellor",
    ));
    intro.appendChild(element(
      "p",
      "",
      "Share your phone number and a DegreeBaba counsellor can help with fees, eligibility, and next steps.",
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
      isApplication ? "Continue with a counsellor" : "Request a callback",
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
        form.replaceChildren(element(
          "p",
          "db-widget__state-copy",
          response.message || "Thanks — a DegreeBaba counsellor can contact you shortly.",
        ));
        if (response.response && typeof response.response === "object") {
          closeOverlay();
          renderBotPayload({
            message: response.message || "Thanks — your details are saved.",
          });
          renderBotPayload(response.response);
        }
      } catch (error) {
        console.warn("DegreeBaba phone-only lead endpoint unavailable; using chat funnel", error);
        closeOverlay();
        sendMessage(`${options.label || "Talk to a counsellor"} ${normalized}`);
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
    if (state.open) {
      state.input.blur();
      emitStarterImpressions();
    }
    else closeOverlay();
  }

  function buildWidget(config) {
    state.config = config;
    const host = element("div", "db-widget-host");
    host.id = hostId;
    const shadow = host.attachShadow({ mode: "open" });
    const stylesheet = document.createElement("link");
    stylesheet.rel = "stylesheet";
    stylesheet.href = cssUrl;
    shadow.appendChild(stylesheet);

    const shell = element("section", "db-widget");
    shell.style.setProperty("--db-primary", config.primaryColor);
    shell.classList.toggle("db-widget--no-avatar", !config.showAvatar);

    const panel = element("section", "db-widget__panel");
    panel.hidden = true;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", `${config.botName} chat`);
    state.panel = panel;

    const header = element("header", "db-widget__header");
    const identity = element("div", "db-widget__identity");
    if (config.showAvatar) identity.appendChild(createAvatar("db-widget__avatar--header"));
    const labels = element("div", "db-widget__identity-copy");
    labels.appendChild(element("strong", "db-widget__bot-name", config.botName));
    labels.appendChild(element("span", "db-widget__bot-role", "Admissions guide"));
    labels.appendChild(element("span", "db-widget__status", "Online"));
    identity.appendChild(labels);
    const close = createButton("×", "db-widget__icon-button", () => setOpen(false));
    close.setAttribute("aria-label", "Minimize advisor");
    header.append(identity, close);

    const messages = element("div", "db-widget__messages");
    messages.setAttribute("role", "log");
    messages.setAttribute("aria-live", "polite");
    messages.setAttribute("aria-relevant", "additions text");
    messages.setAttribute("aria-busy", "false");
    state.messages = messages;

    const contextBar = element("div", "db-widget__context-bar db-widget__sticky-context");
    contextBar.hidden = true;
    const contextChip = element("div", "db-widget__context-chip");
    const contextCopy = element("div", "db-widget__context-copy");
    const universityLine = element("div", "db-widget__context-line db-widget__context-line--university");
    const universityIcon = element("span", "db-widget__context-icon");
    universityIcon.setAttribute("aria-hidden", "true");
    universityIcon.innerHTML = '<svg viewBox="0 0 24 24"><path d="M3 21h18M5 21V9l7-4 7 4v12M9 21v-6h6v6M8 11h.01M12 11h.01M16 11h.01"/></svg>';
    const contextLabel = element("strong", "db-widget__context-label");
    universityLine.append(universityIcon, contextLabel);
    const courseLine = element("div", "db-widget__context-line db-widget__context-line--course");
    const courseIcon = element("span", "db-widget__context-icon");
    courseIcon.setAttribute("aria-hidden", "true");
    courseIcon.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5v-16ZM4 18.5A2.5 2.5 0 0 1 6.5 16H20"/></svg>';
    const contextCourse = element("span", "db-widget__context-course");
    courseLine.append(courseIcon, contextCourse);
    const contextMeta = element("div", "db-widget__context-meta");
    contextCopy.append(universityLine, courseLine, contextMeta);
    const contextClear = createButton("×", "db-widget__context-clear db-widget__context-dismiss", clearContext);
    contextClear.setAttribute("aria-label", "Clear current university and program context");
    contextChip.append(contextCopy, contextClear);
    contextBar.appendChild(contextChip);
    messages.appendChild(contextBar);
    state.contextBar = contextBar;
    state.contextChip = contextChip;
    state.contextLabel = contextLabel;
    state.contextCourse = contextCourse;
    state.contextMeta = contextMeta;

    const welcome = createMessage("bot", openingMessage(pageType));
    welcome.row.classList.add("db-widget__message-row--welcome");
    welcome.bubble.prepend(createAiAccent());
    state.welcomeView = welcome;

    const starter = element("section", "db-widget__starter db-widget__opening");
    starter.appendChild(element("p", "db-widget__starter-label db-widget__opening-label", "What would you like to explore?"));
    const starterGrid = element("div", "db-widget__starter-grid db-widget__opening-actions");
    starter.appendChild(starterGrid);
    starter.appendChild(element("p", "db-widget__quiet-hint db-widget__starter-hint", "Or type your question."));
    messages.appendChild(starter);
    state.starter = starter;
    state.starterGrid = starterGrid;
    starter.hidden = true;

    const typing = element("div", "db-widget__typing");
    typing.hidden = true;
    if (config.showAvatar) typing.appendChild(createAvatar("db-widget__avatar--message"));
    const dots = element("div", "db-widget__typing-dots");
    dots.append(element("span"), element("span"), element("span"));
    typing.appendChild(dots);
    messages.appendChild(typing);
    state.typing = typing;

    const composer = element("form", "db-widget__composer");
    const composerInner = element("div", "db-widget__composer-inner");
    const input = document.createElement("textarea");
    input.className = "db-widget__input";
    input.rows = 1;
    input.maxLength = 4000;
    input.placeholder = "Ask about courses, fees, eligibility…";
    input.setAttribute("aria-label", "Message the admission advisor");
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        composer.requestSubmit();
      }
    });
    composerInner.appendChild(input);
    const send = element("button", "db-widget__send", "");
    send.type = "submit";
    send.setAttribute("aria-label", "Send message");
    send.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>';
    composer.append(composerInner, send);
    composer.addEventListener("submit", (event) => {
      event.preventDefault();
      sendMessage(input.value);
    });
    state.input = input;

    const privacy = element("p", "db-widget__privacy", "Admissions guidance · Your choices stay in this chat");

    const compareTray = element("aside", "db-widget__compare-tray");
    compareTray.hidden = true;
    state.compareTray = compareTray;

    const overlay = element("section", "db-widget__overlay");
    overlay.hidden = true;
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    const overlayHeader = element("header", "db-widget__picker-header db-widget__detail-header");
    const overlayTitle = element("h2", "db-widget__picker-title db-widget__detail-title");
    overlayTitle.id = `${hostId}-overlay-title`;
    overlay.setAttribute("aria-labelledby", overlayTitle.id);
    const overlayClose = createButton("×", "db-widget__picker-close db-widget__detail-close", closeOverlay);
    overlayClose.setAttribute("aria-label", "Close panel");
    overlayHeader.append(overlayTitle, overlayClose);
    const overlayBody = element("div", "db-widget__overlay-body");
    overlay.append(overlayHeader, overlayBody);
    state.overlay = overlay;
    state.overlayBody = overlayBody;
    state.overlayTitle = overlayTitle;
    state.overlayClose = overlayClose;

    panel.append(header, messages, composer, privacy, compareTray, overlay);

    const launcher = element("button", "db-widget__launcher", "");
    launcher.type = "button";
    launcher.setAttribute("aria-expanded", "false");
    launcher.setAttribute("aria-controls", hostId);
    launcher.setAttribute("aria-label", "Open admission advisor");
    launcher.innerHTML =
      '<span class="db-widget__launcher-spark">✦</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16v12H7l-3 3V4Zm4 5h8v2H8V9Z"/></svg>';
    launcher.addEventListener("click", () => setOpen(!state.open));
    state.launcher = launcher;

    shell.append(panel, launcher);
    shadow.appendChild(shell);
    document.body.appendChild(host);

    shadow.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (!state.overlay.hidden) closeOverlay();
      else setOpen(false);
    });

    const autoOpenOverride = script.dataset.autoOpen;
    const shouldOpen = autoOpenOverride === "true" || (autoOpenOverride !== "false" && config.autoOpen);
    setOpen(shouldOpen);
    state.guideReady = hydratePageContext();

    delete widgetNamespace.loading[siteKey];
    widgetNamespace.instances[siteKey] = {
      open: () => setOpen(true),
      close: () => setOpen(false),
      sendMessage,
      openFinder: startFinder,
      openPicker,
      clearContext,
      siteKey,
    };
    window.dispatchEvent(new CustomEvent("degreebaba:ready", { detail: { siteKey } }));
  }

  loadConfig()
    .then(buildWidget)
    .catch((error) => {
      delete widgetNamespace.loading[siteKey];
      console.error("DegreeBaba widget did not initialize", error);
    });
})();
