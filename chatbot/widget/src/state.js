  const responsiveActionLayouts = new Set();

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

  function currentPageKey() {
    return `${pageType}:${pageEntitySlug || pageUniversitySlug || "home"}`;
  }

  function storedRoiPageKey() {
    try {
      return window.sessionStorage.getItem(`degreebaba:${siteKey}:roi-page`) || "";
    } catch (_error) {
      return "";
    }
  }

  function rememberRoiPage() {
    try {
      window.sessionStorage.setItem(`degreebaba:${siteKey}:roi-page`, currentPageKey());
    } catch (_error) {
      // Storage can be unavailable in privacy-restricted third-party contexts.
    }
  }

  function forgetRoiPage() {
    try {
      window.sessionStorage.removeItem(`degreebaba:${siteKey}:roi-page`);
    } catch (_error) {
      // Storage can be unavailable in privacy-restricted third-party contexts.
    }
  }

  function storedCareerQuizPageKey() {
    try {
      return window.sessionStorage.getItem(`degreebaba:${siteKey}:career-quiz-page`) || "";
    } catch (_error) {
      return "";
    }
  }

  function rememberCareerQuizPage() {
    try {
      window.sessionStorage.setItem(`degreebaba:${siteKey}:career-quiz-page`, currentPageKey());
    } catch (_error) {
      // Storage can be unavailable in privacy-restricted third-party contexts.
    }
  }

  function forgetCareerQuizPage() {
    try {
      window.sessionStorage.removeItem(`degreebaba:${siteKey}:career-quiz-page`);
    } catch (_error) {
      // Storage can be unavailable in privacy-restricted third-party contexts.
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
    send: null,
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
    roiWidget: null,
    careerQuizWidget: null,
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
    endScreen: null,
    endScreenEl: null,
    lastLead: null,
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
