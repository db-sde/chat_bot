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

  const OPENING_ACTIONS = {
    homepage: [
      { label: "🎓 Browse universities", action: "open_university_picker" },
      { label: "📚 Browse programs", action: "show_programs" },
      { label: "🎯 Help me choose", action: "open_finder" },
      { label: "🛡️ Is an online degree valid?", message: "Is an online degree valid?" },
    ],
    university: [
      { label: "📚 Programs offered here", contextual: "programs" },
      { label: "⭐ Student reviews", contextual: "reviews" },
      { label: "🏅 Accreditations", contextual: "accreditations" },
      { label: "⚖️ Compare with others", contextual: "compare" },
    ],
    course: [
      { label: "💰 Fees & EMI", contextual: "fees and EMI" },
      { label: "🎯 Specializations", contextual: "specializations" },
      { label: "✅ Eligibility", contextual: "eligibility" },
      { label: "⚖️ Compare universities", contextual: "compare universities" },
    ],
    specialization: [
      { label: "💼 Career & salary", contextual: "career and salary" },
      { label: "📖 Syllabus", contextual: "syllabus" },
      { label: "💰 Fees", contextual: "fees" },
      { label: "🔄 Other specializations", contextual: "other specializations" },
    ],
  };
  const MORE_ACTIONS = [
    { label: "⚖️ Compare", message: "Compare universities" },
    { label: "💰 Fees & EMI", message: "Show me fees and EMI options" },
    { label: "✅ Eligibility", message: "What are the eligibility requirements?" },
    { label: "📞 Talk to a counsellor", action: "open_lead" },
  ];
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
    contextLabel: null,
    context: null,
    pageContext: null,
    pageContextDismissed: false,
    overlay: null,
    overlayBody: null,
    overlayTitle: null,
    overlayClose: null,
    pickerCache: new Map(),
    finder: null,
    finderView: null,
    compareSelections: [],
    compareTray: null,
    lastMessage: "",
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
      label: String(value.label || value.title || value.message || "").trim(),
      message: String(value.message || value.label || "").trim(),
    };
  }

  function contextualSubject() {
    const contextName = state.pageContext && (state.pageContext.name || state.pageContext.label);
    return contextName || pageEntitySlug || pageUniversitySlug || "this page";
  }

  function contextualMessage(topic) {
    const subject = contextualSubject();
    const messages = {
      programs: `Show programs offered at ${subject}`,
      reviews: `Show student reviews for ${subject}`,
      accreditations: `Show accreditations for ${subject}`,
      compare: `Compare ${subject} with other universities`,
      "fees and EMI": `Show fees and EMI for ${subject}`,
      specializations: `Show specializations for ${subject}`,
      eligibility: `Am I eligible for ${subject}?`,
      "compare universities": `Compare universities offering ${subject}`,
      "career and salary": `Show career and salary outcomes for ${subject}`,
      syllabus: `Show the syllabus for ${subject}`,
      fees: `Show fees for ${subject}`,
      "other specializations": `Show other specializations related to ${subject}`,
    };
    return messages[topic] || `${topic} for ${subject}`;
  }

  function actionButton(action, className = "db-widget__action") {
    const normalized = normalizedAction(action);
    if (!normalized || !normalized.label) return null;
    return createButton(normalized.label, className, () => handleAction(normalized));
  }

  function handleAction(rawAction) {
    const action = normalizedAction(rawAction);
    if (!action) return;
    const kind = String(action.action || "").toLowerCase();
    const label = action.label.toLowerCase();
    const payload = action.payload || {};
    if (kind === "open_university_picker" || kind === "open_picker" && payload.kind === "university") {
      openPicker("university");
      return;
    }
    if (kind === "open_specialization_picker" || kind === "open_picker" && payload.kind === "specialization") {
      openPicker("specialization");
      return;
    }
    if (kind === "show_programs") {
      showProgramOptions();
      return;
    }
    if (kind === "open_finder") {
      startFinder();
      return;
    }
    if (
      kind === "open_lead" ||
      kind === "lead_capture" ||
      label.includes("talk to a counsellor") ||
      label.includes("talk to a counselor")
    ) {
      openLeadPanel({ source: payload.source || "quick_action", label: action.label });
      return;
    }
    if (label.includes("browse universit")) {
      openPicker("university");
      return;
    }
    if (label.includes("browse by specialization")) {
      openPicker("specialization");
      return;
    }
    if (label.includes("browse programs")) {
      showProgramOptions();
      return;
    }
    if (label.includes("help me choose")) {
      startFinder();
      return;
    }
    if (action.contextual) {
      sendMessage(contextualMessage(action.contextual));
      return;
    }
    sendMessage(action.message || action.label);
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

  function cardReference(component) {
    const provider = component.university_name || "";
    const name = component.name || component.title || "this option";
    const label = provider && !name.toLowerCase().includes(provider.toLowerCase())
      ? `${provider} ${name}`
      : name;
    return { id: component.id || component.slug || label, label, component };
  }

  function detailsFor(component) {
    if (component.details && typeof component.details === "object") return component.details;
    return {
      description: component.description || component.summary,
      accreditations: component.accreditations || component.highlights,
      admission_steps: component.admission_steps,
      reviews: component.reviews,
      faqs: component.faqs,
      programs: component.programs,
    };
  }

  function hasDetails(component) {
    const details = detailsFor(component);
    return Object.values(details).some((value) => Array.isArray(value) ? value.length : Boolean(value));
  }

  function cardActions(component, detailsLabel = "View details") {
    const actions = element("div", "db-widget__card-actions");
    const details = createButton(detailsLabel, "db-widget__card-button db-widget__card-action--primary", () => {
      if (hasDetails(component)) openDetails(component);
      else sendMessage(`Tell me about ${cardReference(component).label}`);
    });
    const compare = createButton("+ Compare", "db-widget__card-button db-widget__card-action", () => {
      addToComparison(component);
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
    const established = component.established_year || findFact(component, ["established"]);
    const trust = trustRow([ugc, naac, established && `Est. ${established}`]);
    if (trust) card.appendChild(trust);

    const programsCount = component.program_count || component.num_programs || (component.programs || []).length;
    const stats = statPills([
      { label: "From", value: component.starting_fee || findFact(component, ["starting fee", "fee"]) },
      { label: "Programs", value: programsCount ? `${programsCount}` : "" },
      { label: "Mode", value: component.learning_mode || component.mode || findFact(component, ["learning mode", "mode"]) },
    ]);
    if (stats.childElementCount) card.appendChild(stats);
    card.appendChild(cardActions(component));
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
    card.appendChild(element("span", "db-widget__eyebrow", isSpecialization ? "Specialization" : provider || "Program"));
    const heading = provider && isSpecialization
      ? `${provider} ${component.category ? String(component.category).toUpperCase() : ""} in ${component.name}`.replace(/\s+/g, " ").trim()
      : component.name;
    card.appendChild(element("h3", "", heading));

    const ugc = component.ugc_status || findFact(component, ["ugc", "approval"]);
    const naacRaw = component.naac_grade || findFact(component, ["naac"]);
    const naac = naacRaw && !String(naacRaw).toLowerCase().includes("naac") ? `NAAC ${naacRaw}` : naacRaw;
    const trust = trustRow([ugc, naac]);
    if (trust) card.appendChild(trust);

    const specializationCount = component.specialization_count || component.num_specializations || (component.specializations || []).length;
    const stats = statPills([
      { label: "Fee", value: component.fee || component.total_fee },
      { label: "Duration", value: component.duration },
      {
        label: isSpecialization ? "Mode" : "Specializations",
        value: isSpecialization ? component.mode : specializationCount ? `${specializationCount}` : "",
      },
    ]);
    if (stats.childElementCount) card.appendChild(stats);
    const emi = component.emi || component.emi_amount;
    if (emi) card.appendChild(element("p", "db-widget__emi-line", String(emi)));
    const career = firstCareer(component);
    if (isSpecialization && career) {
      card.appendChild(element("p", "db-widget__career-line", `💼 ${career}`));
    }
    card.appendChild(cardActions(component));
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
    (actions || []).map(normalizedAction).filter(Boolean).slice(0, 3).forEach((action) => {
      const button = actionButton(action);
      if (button) row.appendChild(button);
    });
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
    if (role === "bot" && state.config.showAvatar) row.appendChild(createAvatar("db-widget__avatar--message"));
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
      return payload.quick_actions.slice(0, 3);
    }
    const component = components.find((item) => item && item.type === "quick_actions");
    if (component && Array.isArray(component.actions)) return component.actions.slice(0, 3);
    return Array.isArray(payload.suggested_chips) ? payload.suggested_chips.slice(0, 3) : [];
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
    if (Object.prototype.hasOwnProperty.call(safePayload, "context")) updateContext(safePayload.context);
    anchorBotMessage(view.row);
    return view;
  }

  function showTyping(show) {
    if (!state.config.showTypingIndicator || !state.typing) return;
    if (state.typingTimer) window.clearTimeout(state.typingTimer);
    state.typingTimer = null;
    state.typing.hidden = !show;
    if (show) {
      state.typingTimer = window.setTimeout(() => {
        state.typing.hidden = true;
        state.typingTimer = null;
      }, 800);
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
    if (!message || state.busy) return;
    state.busy = true;
    state.lastMessage = message;
    state.input.value = "";
    if (state.starter && options.keepStarter !== true) state.starter.hidden = true;
    if (options.displayUser !== false) createMessage("user", message);
    showTyping(true);
    let finalPayload = null;
    let bufferedText = "";
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);

    try {
      const body = { message, site_key: siteKey };
      if (state.sessionId) body.session_id = state.sessionId;
      if (!state.pageContextDismissed) {
        if (pageUniversitySlug) body.page_university_slug = pageUniversitySlug;
        if (pageType !== "homepage") body.page_type = pageType;
        if (pageEntitySlug) body.page_entity_slug = pageEntitySlug;
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
      renderBotPayload(finalPayload || { message: bufferedText });
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
    state.contextLabel.textContent = values.join(" · ");
  }

  async function clearContext() {
    state.pageContextDismissed = true;
    updateContext(null);
    renderStarterBank("homepage");
    state.starter.hidden = false;
    state.starterType = "homepage";
    anchorBotMessage(state.starter);
    if (!state.sessionId) return;
    try {
      const payload = await fetchJson("/api/widget/context/clear", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: state.sessionId }),
      });
      if (payload && Object.prototype.hasOwnProperty.call(payload, "context")) updateContext(payload.context);
    } catch (error) {
      // A fresh backend session guarantees the dismissed focus cannot leak into
      // the next answer when the optional clear endpoint is unavailable.
      forgetSessionId();
      console.warn("DegreeBaba context endpoint unavailable; starting a neutral session", error);
    }
  }

  function renderStarterBank(type) {
    const selected = OPENING_ACTIONS[type] || OPENING_ACTIONS.homepage;
    state.starterGrid.replaceChildren();
    selected.forEach((action) => {
      const button = actionButton(action, "db-widget__starter-action");
      if (button) state.starterGrid.appendChild(button);
    });
    const more = createButton("More ⌄", "db-widget__more-action db-widget__more-toggle", () => {
      const expanded = more.getAttribute("aria-expanded") === "true";
      more.setAttribute("aria-expanded", String(!expanded));
      extra.hidden = expanded;
      more.textContent = expanded ? "More ⌄" : "Less ⌃";
    });
    more.setAttribute("aria-expanded", "false");
    const extra = element("div", "db-widget__opening-more db-widget__starter-more");
    extra.hidden = true;
    MORE_ACTIONS.forEach((action) => {
      const button = actionButton(action, "db-widget__starter-action");
      if (button) extra.appendChild(button);
    });
    state.starterGrid.append(more, extra);
  }

  function showProgramOptions() {
    if (state.starter) state.starter.hidden = true;
    const view = createMessage("bot", "Programs are quick to browse. Which one interests you?");
    const panel = element("section", "db-widget__cascade db-widget__cascade-panel");
    panel.appendChild(element("p", "db-widget__cascade-copy", "Choose a program to see real university options."));
    const options = element("div", "db-widget__cascade-options");
    PROGRAM_OPTIONS.forEach((name) => {
      options.appendChild(createButton(name, "db-widget__cascade-option", () => {
        sendMessage(`Show universities offering ${name}`);
      }));
    });
    panel.appendChild(options);
    const stack = element("div", "db-widget__component-stack");
    stack.appendChild(panel);
    view.content.appendChild(stack);
    anchorBotMessage(view.row);
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

  function pickerRow(item, kind, popular = false, onSelect = null) {
    const row = createButton("", popular ? "db-widget__popular-item" : "db-widget__picker-row", () => {
      closeOverlay();
      if (onSelect) {
        onSelect(item);
        return;
      }
      const message = item.message || (kind === "university"
        ? `Show programs offered at ${item.name}`
        : `Show universities offering ${item.name}`);
      sendMessage(message);
    });
    row.appendChild(element("span", "db-widget__picker-name", item.name));
    if (item.meta) row.appendChild(element("span", "db-widget__picker-meta", item.meta));
    return row;
  }

  function renderPickerResults(container, data, kind, query = "", onSelect = null) {
    container.replaceChildren();
    const normalizedQuery = query.trim().toLowerCase();
    const filtered = data.items.filter((item) =>
      `${item.name} ${item.meta}`.toLowerCase().includes(normalizedQuery),
    );
    if (!normalizedQuery && data.popular.length) {
      const section = element("section", "db-widget__picker-section");
      section.appendChild(element("h3", "db-widget__picker-section-title", "⭐ Popular"));
      const grid = element("div", "db-widget__picker-popular");
      data.popular.slice(0, 8).forEach((item) => grid.appendChild(pickerRow(item, kind, true, onSelect)));
      section.appendChild(grid);
      container.appendChild(section);
    }
    if (!filtered.length) {
      container.appendChild(element("p", "db-widget__picker-empty", "No matching catalog option."));
      return;
    }
    const groups = new Map();
    filtered.sort((a, b) => a.name.localeCompare(b.name)).forEach((item) => {
      const letter = (item.name[0] || "#").toUpperCase();
      if (!groups.has(letter)) groups.set(letter, []);
      groups.get(letter).push(item);
    });
    groups.forEach((items, letter) => {
      container.appendChild(element("h3", "db-widget__picker-letter", letter));
      items.forEach((item) => container.appendChild(pickerRow(item, kind, false, onSelect)));
    });
  }

  async function openPicker(kind, onSelect = null) {
    const title = kind === "university" ? "Browse universities" : "Browse specializations";
    const body = openOverlay(title, "db-widget__picker-overlay");
    const sheet = element("section", "db-widget__picker db-widget__picker-sheet");
    sheet.style.gridTemplateRows = "auto minmax(0, 1fr)";
    const searchWrap = element("div", "db-widget__picker-search-wrap");
    const search = document.createElement("input");
    search.className = "db-widget__picker-search";
    search.type = "search";
    search.placeholder = `Search ${kind === "university" ? "universities" : "specializations"}`;
    search.setAttribute("aria-label", search.placeholder);
    searchWrap.appendChild(search);
    const content = element("div", "db-widget__picker-content db-widget__picker-list");
    content.appendChild(element("p", "db-widget__picker-empty", "Loading published options…"));
    sheet.append(searchWrap, content);
    body.appendChild(sheet);
    window.setTimeout(() => search.focus(), 0);
    try {
      const data = await loadCatalog(kind);
      renderPickerResults(content, data, kind, "", onSelect);
      search.addEventListener("input", () => renderPickerResults(content, data, kind, search.value, onSelect));
    } catch (error) {
      content.replaceChildren();
      const empty = element("section", "db-widget__error-state");
      empty.appendChild(element("span", "db-widget__state-icon", "↻"));
      empty.appendChild(element("h3", "db-widget__state-title", "The catalog list didn’t load"));
      empty.appendChild(element("p", "db-widget__state-copy", "You can retry or continue through chat."));
      const actions = element("div", "db-widget__state-actions");
      actions.append(
        createButton("Try again", "db-widget__action", () => openPicker(kind)),
        createButton("Browse in chat", "db-widget__action", () => {
          closeOverlay();
          sendMessage(kind === "university" ? "Browse universities" : "Browse specializations");
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
    current.options.forEach((choice) => {
      const button = createButton(choice, "db-widget__finder-option", () => {
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
      });
      button.setAttribute("aria-pressed", "false");
      options.appendChild(button);
    });
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
    if (state.compareSelections.some((item) => item.id === reference.id)) return;
    state.compareSelections.push(reference);
    if (state.compareSelections.length > 2) state.compareSelections.shift();
    renderCompareTray();
    if (state.compareSelections.length === 2) submitComparison();
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
    const labels = state.compareSelections.map((item) => item.label);
    state.compareSelections = [];
    renderCompareTray();
    sendMessage(`Compare ${labels[0]} and ${labels[1]}`);
  }

  function openLeadPanel(options = {}) {
    const body = openOverlay("Talk to a counsellor", "db-widget__detail-overlay db-widget__lead-overlay");
    const panel = element("section", "db-widget__detail-panel db-widget__lead-panel");
    panel.style.height = "100%";
    panel.style.gridTemplateRows = "minmax(0, 1fr)";
    const content = element("div", "db-widget__detail-body");
    const intro = element("section", "db-widget__detail-section");
    intro.appendChild(element("h3", "", "Check today’s fee offer and seat availability"));
    intro.appendChild(element("p", "", "Just your number — no spam."));
    const form = element("form", "db-widget__lead-form");
    const phone = document.createElement("input");
    phone.className = "db-widget__picker-search db-widget__lead-input";
    phone.type = "tel";
    phone.inputMode = "numeric";
    phone.autocomplete = "tel";
    phone.placeholder = "10-digit phone number";
    phone.setAttribute("aria-label", phone.placeholder);
    const status = element("p", "db-widget__state-copy");
    const submit = element("button", "db-widget__lead-button", "Check now");
    submit.type = "submit";
    form.append(phone, submit, status);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
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
        const response = await fetchJson("/api/widget/lead", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: state.sessionId || null, phone: normalized, source: options.source || "widget" }),
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
      } catch (error) {
        console.warn("DegreeBaba phone-only lead endpoint unavailable; using chat funnel", error);
        closeOverlay();
        sendMessage(`${options.label || "Talk to a counsellor"} ${normalized}`);
      }
    });
    content.append(intro, form);
    panel.appendChild(content);
    body.appendChild(panel);
    window.setTimeout(() => phone.focus(), 0);
  }

  async function hydratePageContext() {
    if (pageType === "homepage" || !pageEntitySlug) return;
    const query = new URLSearchParams({ page_type: pageType, page_entity_slug: pageEntitySlug });
    if (pageUniversitySlug) query.set("page_university_slug", pageUniversitySlug);
    try {
      const payload = await fetchJson(`/api/widget/page-context?${query.toString()}`);
      state.pageContext = payload.page_context || payload.context || payload;
      if (payload.context) updateContext(payload.context);
    } catch (_error) {
      // Optional endpoint: script data still drives the correct opening bank.
    }
  }

  function setOpen(open) {
    state.open = Boolean(open);
    state.panel.hidden = !state.open;
    state.launcher.setAttribute("aria-expanded", String(state.open));
    state.launcher.setAttribute("aria-label", state.open ? "Close admission advisor" : "Open admission advisor");
    state.launcher.classList.toggle("db-widget__launcher--open", state.open);
    if (state.open) state.input.blur();
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
    labels.appendChild(element("span", "db-widget__bot-role", "AI Admission Advisor"));
    labels.appendChild(element("span", "db-widget__status", "Online"));
    identity.appendChild(labels);
    const close = createButton("×", "db-widget__icon-button", () => setOpen(false));
    close.setAttribute("aria-label", "Minimize advisor");
    header.append(identity, close);

    const messages = element("div", "db-widget__messages");
    messages.setAttribute("role", "log");
    messages.setAttribute("aria-live", "polite");
    state.messages = messages;

    const contextBar = element("div", "db-widget__context-bar db-widget__sticky-context");
    contextBar.hidden = true;
    const contextChip = element("div", "db-widget__context-chip");
    const contextLabel = element("span", "db-widget__context-label");
    const contextClear = createButton("×", "db-widget__context-clear db-widget__context-dismiss", clearContext);
    contextClear.setAttribute("aria-label", "Clear current university and program context");
    contextChip.append(contextLabel, contextClear);
    contextBar.appendChild(contextChip);
    messages.appendChild(contextBar);
    state.contextBar = contextBar;
    state.contextLabel = contextLabel;

    const welcome = createMessage("bot", config.welcomeMessage);
    welcome.row.classList.add("db-widget__message-row--welcome");

    const starter = element("section", "db-widget__starter db-widget__opening");
    starter.appendChild(element("p", "db-widget__starter-label db-widget__opening-label", "What would you like to explore?"));
    const starterGrid = element("div", "db-widget__starter-grid db-widget__opening-actions");
    starter.appendChild(starterGrid);
    starter.appendChild(element("p", "db-widget__quiet-hint db-widget__starter-hint", "Or type your question."));
    messages.appendChild(starter);
    state.starter = starter;
    state.starterGrid = starterGrid;
    renderStarterBank(pageType);

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

    const compareTray = element("aside", "db-widget__compare-tray");
    compareTray.hidden = true;
    state.compareTray = compareTray;

    const overlay = element("section", "db-widget__overlay");
    overlay.hidden = true;
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    const overlayHeader = element("header", "db-widget__picker-header db-widget__detail-header");
    const overlayTitle = element("h2", "db-widget__picker-title db-widget__detail-title");
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
    hydratePageContext();

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
