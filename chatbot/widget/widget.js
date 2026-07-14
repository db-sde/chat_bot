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
  const pageUniversitySlug = (
    script.dataset.pageUniversitySlug || document.documentElement.dataset.universitySlug || ""
  ).trim();
  const hostId = `degreebaba-widget-${siteKey.replace(/[^a-z0-9_-]/gi, "-")}`;
  if (document.getElementById(hostId)) return;

  window.DegreeBabaWidget = window.DegreeBabaWidget || {};
  const widgetNamespace = window.DegreeBabaWidget;
  widgetNamespace.instances = widgetNamespace.instances || {};
  widgetNamespace.loading = widgetNamespace.loading || {};
  if (widgetNamespace.instances[siteKey] || widgetNamespace.loading[siteKey]) return;
  widgetNamespace.loading[siteKey] = true;

  const STARTER_ACTIONS = [
    "Compare Universities",
    "Find Best MBA",
    "MBA Fees",
    "Talk To Counsellor",
  ];

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
    typing: null,
    messages: null,
    input: null,
    panel: null,
    launcher: null,
  };

  function normalizeConfig(payload) {
    const branding = payload && payload.branding ? payload.branding : payload || {};
    const behavior = payload && payload.behavior ? payload.behavior : payload || {};
    const color = /^#[0-9a-f]{6}$/i.test(branding.primary_color || "")
      ? branding.primary_color
      : "#FF6B00";
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

  async function loadConfig() {
    const response = await fetch(
      `${apiBase}/api/widget/config/${encodeURIComponent(siteKey)}`,
      { headers: { Accept: "application/json" }, mode: "cors" },
    );
    if (!response.ok) {
      throw new Error(`Widget configuration unavailable (${response.status})`);
    }
    return normalizeConfig(await response.json());
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
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
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a7 7 0 0 0-7 7v1.2A3 3 0 0 0 3 14v2a3 3 0 0 0 3 3h1.2l1.1 1.3a1 1 0 0 0 .8.4h5.8a1 1 0 0 0 .8-.4l1.1-1.3H18a3 3 0 0 0 3-3v-2a3 3 0 0 0-2-2.8V10a7 7 0 0 0-7-7Zm-3 8.5a1.25 1.25 0 1 1 0 2.5 1.25 1.25 0 0 1 0-2.5Zm6 0a1.25 1.25 0 1 1 0 2.5 1.25 1.25 0 0 1 0-2.5ZM8.7 16h6.6a3.7 3.7 0 0 1-6.6 0Z"/></svg>';
    }
    return avatar;
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

  function actionButton(label, message, className = "db-widget__action") {
    const button = element("button", className, label);
    button.type = "button";
    button.addEventListener("click", () => sendMessage(message || label));
    return button;
  }

  function factGrid(facts) {
    const grid = element("dl", "db-widget__fact-grid");
    (facts || []).forEach((fact) => {
      if (!fact || !fact.label || !fact.value) return;
      const item = element("div", "db-widget__fact");
      item.appendChild(element("dt", "", fact.label));
      item.appendChild(element("dd", "", fact.value));
      grid.appendChild(item);
    });
    return grid;
  }

  function renderUniversityCard(component) {
    const card = element("article", "db-widget__card db-widget__university-card");
    const header = element("div", "db-widget__card-header");
    const mark = element("span", "db-widget__card-mark", (component.name || "U").slice(0, 2));
    const logoUrl = safeHttpUrl(component.logo_url);
    if (logoUrl) {
      mark.textContent = "";
      const logo = document.createElement("img");
      logo.src = logoUrl;
      logo.alt = "";
      logo.referrerPolicy = "no-referrer";
      mark.appendChild(logo);
    }
    const title = element("div", "db-widget__card-heading");
    title.appendChild(element("span", "db-widget__eyebrow", "University"));
    title.appendChild(element("h3", "", component.name));
    header.append(mark, title);
    card.appendChild(header);
    if (component.summary) card.appendChild(element("p", "db-widget__card-summary", component.summary));
    if (component.highlights && component.highlights.length) {
      card.appendChild(factGrid(component.highlights.slice(0, 4)));
    }
    if (component.programs && component.programs.length) {
      const programs = element("div", "db-widget__tag-row");
      component.programs.slice(0, 4).forEach((name) =>
        programs.appendChild(element("span", "db-widget__tag", name)),
      );
      card.appendChild(programs);
    }
    const detailsUrl = safeHttpUrl(component.details_url);
    if (detailsUrl) {
      const link = element("a", "db-widget__card-button", "View details");
      link.href = detailsUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      card.appendChild(link);
    } else {
      card.appendChild(
        actionButton(
          "View details",
          `Tell me about ${component.name}`,
          "db-widget__card-button",
        ),
      );
    }
    return card;
  }

  function renderProgramCard(component) {
    const card = element("article", "db-widget__card db-widget__program-card");
    const context = component.university_name || "Program";
    const label = component.kind === "specialization" ? `${context} · Specialization` : context;
    card.appendChild(element("span", "db-widget__eyebrow", label));
    card.appendChild(element("h3", "", component.name));
    if (component.summary) card.appendChild(element("p", "db-widget__card-summary", component.summary));
    const facts = [];
    if (component.duration) facts.push({ label: "Duration", value: component.duration });
    if (component.fee) facts.push({ label: "Published fee", value: component.fee });
    if (component.eligibility) facts.push({ label: "Eligibility", value: component.eligibility });
    if (component.mode) facts.push({ label: "Mode", value: component.mode });
    if (facts.length) card.appendChild(factGrid(facts));
    if (component.specializations && component.specializations.length) {
      card.appendChild(element("h4", "db-widget__card-label", "Popular specializations"));
      const tags = element("div", "db-widget__tag-row");
      component.specializations.slice(0, 5).forEach((name) =>
        tags.appendChild(element("span", "db-widget__tag", name)),
      );
      card.appendChild(tags);
    }
    if (component.career_outcomes && component.career_outcomes.length) {
      card.appendChild(element("h4", "db-widget__card-label", "Career relevance"));
      card.appendChild(
        element("p", "db-widget__card-summary", component.career_outcomes.slice(0, 3).join(" · ")),
      );
    }
    const detailsUrl = safeHttpUrl(component.details_url);
    if (detailsUrl) {
      const link = element("a", "db-widget__card-button", "Explore program");
      link.href = detailsUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      card.appendChild(link);
    } else {
      card.appendChild(
        actionButton(
          "Explore program",
          `Tell me about ${component.university_name || ""} ${component.name}`.trim(),
          "db-widget__card-button",
        ),
      );
    }
    return card;
  }

  function renderComparisonCard(component) {
    const card = element("article", "db-widget__card db-widget__comparison-card");
    const heading = element("div", "db-widget__comparison-heading");
    heading.appendChild(element("span", "db-widget__eyebrow", "Side-by-side"));
    heading.appendChild(element("h3", "", component.title || "University comparison"));
    card.appendChild(heading);
    const items = element("div", "db-widget__comparison-items");
    (component.items || []).forEach((entry) => {
      const column = element("section", "db-widget__comparison-item");
      column.appendChild(element("h4", "", entry.name));
      if (entry.subtitle) column.appendChild(element("p", "db-widget__comparison-subtitle", entry.subtitle));
      column.appendChild(factGrid(entry.facts || []));
      items.appendChild(column);
    });
    card.appendChild(items);
    card.appendChild(
      actionButton("Help me choose", "Help me choose between these options", "db-widget__card-button"),
    );
    return card;
  }

  function renderLeadCta(component) {
    const cta = element("section", "db-widget__lead-cta");
    const copy = element("div", "");
    copy.appendChild(element("span", "db-widget__eyebrow", "Need a human opinion?"));
    copy.appendChild(element("strong", "", component.label || "Talk to a counsellor"));
    cta.appendChild(copy);
    const button = element("button", "db-widget__lead-button", "Book callback");
    button.type = "button";
    button.addEventListener("click", () => {
      const destination = safeHttpUrl(component.url);
      if (destination) {
        window.open(destination, "_blank", "noopener,noreferrer");
      } else {
        sendMessage(component.label || "Talk to a counsellor");
      }
    });
    cta.appendChild(button);
    return cta;
  }

  function renderQuickActions(component) {
    const row = element("div", "db-widget__quick-actions");
    (component.actions || []).forEach((action) => {
      if (!action || !action.label) return;
      row.appendChild(actionButton(action.label, action.message || action.label));
    });
    return row;
  }

  function renderComponent(component) {
    if (!component || !component.type) return null;
    if (component.type === "university_card") return renderUniversityCard(component);
    if (component.type === "program_card") return renderProgramCard(component);
    if (component.type === "comparison_card") return renderComparisonCard(component);
    if (component.type === "lead_cta") return renderLeadCta(component);
    if (component.type === "quick_actions") return renderQuickActions(component);
    return null;
  }

  function createMessage(role, text) {
    const row = element("div", `db-widget__message-row db-widget__message-row--${role}`);
    if (role === "bot" && state.config.showAvatar) row.appendChild(createAvatar("db-widget__avatar--message"));
    const content = element("div", "db-widget__message-content");
    const bubble = element("div", `db-widget__bubble db-widget__bubble--${role}`);
    addRichText(bubble, text);
    content.appendChild(bubble);
    row.appendChild(content);
    state.messages.appendChild(row);
    state.messages.scrollTop = state.messages.scrollHeight;
    return { row, content, bubble };
  }

  function renderBotPayload(payload, existingMessage) {
    const message = payload.message || payload.text || "I’m ready to help with your university search.";
    const view = existingMessage || createMessage("bot", "");
    view.bubble.replaceChildren();
    addRichText(view.bubble, message);

    Array.from(view.content.querySelectorAll(".db-widget__component-stack")).forEach((node) => node.remove());
    const stack = element("div", "db-widget__component-stack");
    let components = Array.isArray(payload.components) ? payload.components : [];
    if (
      Array.isArray(payload.suggested_chips) &&
      payload.suggested_chips.length &&
      !components.some((item) => item.type === "quick_actions")
    ) {
      components = [...components, {
        type: "quick_actions",
        actions: payload.suggested_chips.map((label) => ({ label, message: label })),
      }];
    }
    if (payload.cta && !components.some((item) => item.type === "lead_cta")) {
      components = [...components, { type: "lead_cta", ...payload.cta }];
    }
    components.forEach((component) => {
      const rendered = renderComponent(component);
      if (rendered) stack.appendChild(rendered);
    });
    if (stack.childElementCount) view.content.appendChild(stack);
    state.messages.scrollTop = state.messages.scrollHeight;
    return view;
  }

  function showTyping(show) {
    if (!state.config.showTypingIndicator || !state.typing) return;
    state.typing.hidden = !show;
    if (show) state.messages.scrollTop = state.messages.scrollHeight;
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

  async function sendMessage(rawMessage) {
    const message = String(rawMessage || "").trim();
    if (!message || state.busy) return;
    state.busy = true;
    state.input.value = "";
    if (state.starter) state.starter.hidden = true;
    createMessage("user", message);
    showTyping(true);
    let streamedView = null;
    let streamedText = "";
    let finalPayload = null;

    try {
      const body = { message, site_key: siteKey };
      if (state.sessionId) body.session_id = state.sessionId;
      if (pageUniversitySlug) body.page_university_slug = pageUniversitySlug;
      const response = await fetch(`${apiBase}/chat`, {
        method: "POST",
        mode: "cors",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`Chat request failed (${response.status})`);
      await consumeSse(response, (event, payload) => {
        if (payload.session_id) {
          state.sessionId = payload.session_id;
          rememberSessionId(state.sessionId);
        }
        if (event === "token" && payload.token) {
          showTyping(false);
          streamedText += payload.token;
          if (!streamedView) streamedView = createMessage("bot", streamedText);
          streamedView.bubble.replaceChildren();
          addRichText(streamedView.bubble, streamedText);
        }
        if (["response", "final", "replace"].includes(event)) finalPayload = payload;
      });
      showTyping(false);
      renderBotPayload(finalPayload || { message: streamedText }, streamedView);
    } catch (error) {
      showTyping(false);
      const view = streamedView || createMessage("bot", "");
      view.bubble.replaceChildren();
      addRichText(
        view.bubble,
        "I couldn’t reach the advisor just now. Please try again in a moment.",
      );
      console.error("DegreeBaba widget request failed", error);
    } finally {
      state.busy = false;
      state.input.focus();
    }
  }

  function setOpen(open) {
    state.open = Boolean(open);
    state.panel.hidden = !state.open;
    state.launcher.setAttribute("aria-expanded", String(state.open));
    state.launcher.setAttribute("aria-label", state.open ? "Close admission advisor" : "Open admission advisor");
    state.launcher.classList.toggle("db-widget__launcher--open", state.open);
    if (state.open) window.setTimeout(() => state.input.focus(), 120);
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
    labels.appendChild(element("span", "db-widget__bot-role", "AI Admission Advisor"));
    const status = element("span", "db-widget__status", "Online");
    labels.appendChild(status);
    identity.appendChild(labels);
    const close = element("button", "db-widget__icon-button", "×");
    close.type = "button";
    close.setAttribute("aria-label", "Minimize advisor");
    close.addEventListener("click", () => setOpen(false));
    header.append(identity, close);

    const messages = element("div", "db-widget__messages");
    messages.setAttribute("role", "log");
    messages.setAttribute("aria-live", "polite");
    state.messages = messages;

    const welcome = createMessage("bot", config.welcomeMessage);
    welcome.row.classList.add("db-widget__message-row--welcome");

    const starter = element("section", "db-widget__starter");
    starter.appendChild(element("p", "db-widget__starter-label", "What would you like to explore?"));
    const starterGrid = element("div", "db-widget__starter-grid");
    STARTER_ACTIONS.forEach((label) => starterGrid.appendChild(actionButton(label, label, "db-widget__starter-action")));
    starter.appendChild(starterGrid);
    messages.appendChild(starter);
    state.starter = starter;

    const typing = element("div", "db-widget__typing");
    typing.hidden = true;
    if (config.showAvatar) typing.appendChild(createAvatar("db-widget__avatar--message"));
    const dots = element("div", "db-widget__typing-dots");
    dots.append(element("span"), element("span"), element("span"));
    typing.appendChild(dots);
    messages.appendChild(typing);
    state.typing = typing;

    const composer = element("form", "db-widget__composer");
    const input = document.createElement("textarea");
    input.className = "db-widget__input";
    input.rows = 1;
    input.maxLength = 4000;
    input.placeholder = "Ask about universities, fees, careers…";
    input.setAttribute("aria-label", "Message the admission advisor");
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        composer.requestSubmit();
      }
    });
    const send = element("button", "db-widget__send", "");
    send.type = "submit";
    send.setAttribute("aria-label", "Send message");
    send.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 4 16 8-16 8 3-8-3-8Zm3.8 7h7.4L6.5 6.7 7.8 11Zm-1.3 6.3 8.7-4.3H7.8l-1.3 4.3Z"/></svg>';
    composer.append(input, send);
    composer.addEventListener("submit", (event) => {
      event.preventDefault();
      sendMessage(input.value);
    });
    state.input = input;

    const privacy = element("p", "db-widget__privacy", "Catalog-backed guidance · Your choices stay in this chat");
    panel.append(header, messages, composer, privacy);

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

    const autoOpenOverride = script.dataset.autoOpen;
    const shouldOpen = autoOpenOverride === "true" || (autoOpenOverride !== "false" && config.autoOpen);
    setOpen(shouldOpen);

    delete widgetNamespace.loading[siteKey];
    widgetNamespace.instances[siteKey] = {
      open: () => setOpen(true),
      close: () => setOpen(false),
      sendMessage,
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
