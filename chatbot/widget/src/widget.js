(function degreeBabaWidgetBootstrap() {
  "use strict";

  /* Build entry: source modules are inlined at the markers below. */

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
    const normalized = String(value || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_");
    if (["discipline", "discipline_hub", "pillar_page"].includes(normalized)) return "pillar";
    return ["pillar", "university", "course", "specialization"].includes(normalized)
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

  /* @include config.js */
  /* @include state.js */

  /* @include api.js */

  /* @include ui.js */
  /* @include renderer.js */
  /* @include actions.js */
  /* @include tools.js */

  window.addEventListener("resize", refreshResponsiveActionLayouts, { passive: true });

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
    shell.dataset.position = script.dataset.position === "left" ? "left" : "right";
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
    labels.appendChild(element("span", "db-widget__status", "Online · replies instantly"));
    identity.appendChild(labels);
    const close = createButton("", "db-widget__icon-button", () => setOpen(false));
    close.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>';
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
    starter.appendChild(element("p", "db-widget__starter-label db-widget__opening-label", "Or type your question below."));
    const starterGrid = element("div", "db-widget__opening-actions");
    starter.appendChild(starterGrid);
    messages.appendChild(starter);
    state.starter = starter;
    state.starterGrid = starterGrid;
    starter.hidden = true;

    const typing = element("div", "db-widget__message-row db-widget__message-row--bot db-msg");
    typing.hidden = true;
    const typingIndicator = element("div", "db-widget__typing db-typing");
    typingIndicator.append(
      element("span", "db-widget__typing-dot db-dot"),
      element("span", "db-widget__typing-dot db-dot"),
      element("span", "db-widget__typing-dot db-dot"),
    );
    typing.appendChild(typingIndicator);
    messages.appendChild(typing);
    state.typing = typing;

    const composer = element("form", "db-widget__composer");
    const composerInner = element("div", "db-widget__composer-inner");
    const input = document.createElement("textarea");
    input.className = "db-widget__input";
    input.rows = 1;
    input.maxLength = 4000;
    input.placeholder = "Type your question...";
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
    input.addEventListener("input", () => {
      send.classList.toggle("db-widget__send--active", Boolean(input.value.trim()));
    });
    composer.append(composerInner, send);
    composer.addEventListener("submit", (event) => {
      event.preventDefault();
      sendMessage(input.value);
    });
    state.input = input;
    state.send = send;

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
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay && overlay.classList.contains("db-widget__picker-overlay")) {
        closeOverlay();
      }
    });
    state.overlay = overlay;
    state.overlayBody = overlayBody;
    state.overlayTitle = overlayTitle;
    state.overlayClose = overlayClose;

    panel.append(header, contextBar, messages, composer, privacy, compareTray, overlay);

    const launcher = element("button", "db-widget__launcher", "");
    launcher.type = "button";
    launcher.setAttribute("aria-expanded", "false");
    launcher.setAttribute("aria-controls", hostId);
    launcher.setAttribute("aria-label", "Open admission advisor");
    launcher.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.9-.9L3 21l1.9-5.6A8.5 8.5 0 0 1 12.5 3 8.38 8.38 0 0 1 21 11.5z"/></svg>';
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
