(function degreeBabaGuidedPrototypeBootstrap() {
  "use strict";

  const currentScript = document.currentScript;
  const scriptApiBase = currentScript && currentScript.dataset.apiBase;
  const apiBase = String(
    scriptApiBase || document.documentElement.dataset.apiBase || document.body?.dataset.apiBase || "",
  ).replace(/\/$/, "");
  const siteKey = String(
    (currentScript && currentScript.dataset.siteKey) ||
      document.documentElement.dataset.siteKey ||
      "degreebaba",
  ).trim() || "degreebaba";

  const SCENARIOS = Object.freeze({
    homepage: Object.freeze({ page_type: "homepage" }),
    university: Object.freeze({ page_type: "university", university: "nmims" }),
    course: Object.freeze({ page_type: "course", university: "nmims", course: "mba" }),
    specialization: Object.freeze({
      page_type: "specialization",
      university: "nmims",
      course: "mba",
      specialization: "business-analytics",
    }),
  });

  const ACTION_BANKS = Object.freeze({
    homepage: [
      ["Browse Universities", "browse_universities"],
      ["Browse Programs", "browse_programs"],
      ["Help Me Choose", "help_choose"],
      ["Is Online Degree Valid?", "online_validity"],
    ],
    university: [
      ["Programs Offered Here", "programs_here"],
      ["Student Reviews", "reviews"],
      ["Accreditations", "accreditations"],
      ["Compare With Others", "compare"],
    ],
    course: [
      ["Fees & EMI", "fees"],
      ["Specializations", "specializations"],
      ["Eligibility", "eligibility"],
      ["Compare Universities", "compare"],
    ],
    specialization: [
      ["Career & Salary", "career"],
      ["Syllabus", "syllabus"],
      ["Fees", "fees"],
      ["Other Specializations", "other_specializations"],
    ],
  });

  const MORE_ACTIONS = Object.freeze([
    ["Compare", "compare"],
    ["Fees & EMI", "fees"],
    ["Eligibility", "eligibility"],
    ["Talk To Counsellor", "lead"],
  ]);

  const PROGRAM_CATEGORIES = Object.freeze(["MBA", "MCA", "BBA", "MSc"]);
  const GUIDED_THINKING_MS = 650;
  const EMPTY_COPY = "I don't have this confirmed yet — I'd rather not guess.";

  function byId(id) {
    return document.getElementById(id);
  }

  function element(tag, className, text) {
    const value = document.createElement(tag);
    if (className) value.className = className;
    if (text !== undefined && text !== null) value.textContent = String(text);
    return value;
  }

  function makeButton(label, className, handler) {
    const value = element("button", className, label);
    value.type = "button";
    value.addEventListener("click", handler);
    return value;
  }

  function cleanText(value) {
    if (value === undefined || value === null) return "";
    if (typeof value === "object") {
      return cleanText(value.name || value.label || value.value || value.title || "");
    }
    return String(value).trim();
  }

  function firstText(...values) {
    for (const value of values) {
      const text = cleanText(value);
      if (text) return text;
    }
    return "";
  }

  function arrayOf(value) {
    if (Array.isArray(value)) return value.filter((item) => item !== null && item !== undefined);
    if (value === undefined || value === null || value === "") return [];
    return [value];
  }

  function slugify(value) {
    return cleanText(value)
      .toLowerCase()
      .replace(/&/g, " and ")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  function humanize(value) {
    return cleanText(value)
      .replace(/[-_]+/g, " ")
      .replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function displayConcept(value) {
    const rendered = cleanText(value);
    const known = {
      nmims: "NMIMS",
      mba: "MBA",
      mca: "MCA",
      bba: "BBA",
      msc: "MSc",
    };
    return known[rendered.toLowerCase()] || humanize(rendered);
  }

  function initials(value) {
    const words = cleanText(value).split(/\s+/).filter(Boolean);
    if (!words.length) return "U";
    if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
    return `${words[0][0]}${words[words.length - 1][0]}`.toUpperCase();
  }

  function newSessionId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return `prototype-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  function cloneForDebug(value) {
    try {
      return JSON.parse(JSON.stringify(value));
    } catch (_error) {
      return null;
    }
  }

  function unwrapItem(item) {
    if (!item || typeof item !== "object") return item;
    return item.entity || item.card || item.component || item;
  }

  function entityPageType(entity) {
    const value = unwrapItem(entity) || {};
    if (value.type === "university_card" || value.page_type === "university") return "university";
    if (value.kind === "specialization" || value.page_type === "specialization") {
      return "specialization";
    }
    if (value.type === "program_card" || value.kind === "course" || value.page_type === "course") {
      return "course";
    }
    return "homepage";
  }

  function entityName(entity) {
    const value = unwrapItem(entity) || {};
    return firstText(value.name, value.label, value.title, value.category, "Catalog option");
  }

  function entityId(entity) {
    const value = unwrapItem(entity) || {};
    return firstText(value.id, value.entity_id);
  }

  function entitySlug(entity) {
    const value = unwrapItem(entity) || {};
    return firstText(value.slug, value.entity_slug);
  }

  function requestError(response, payload) {
    const detail = payload && typeof payload === "object" ? cleanText(payload.detail) : "";
    const error = new Error(detail || `Request unavailable (${response.status})`);
    error.status = response.status;
    return error;
  }

  function safeLink(value) {
    const raw = cleanText(value);
    if (!raw) return "";
    try {
      const parsed = new URL(raw, window.location.href);
      return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : "";
    } catch (_error) {
      return "";
    }
  }

  function fact(label, value) {
    const text = cleanText(value);
    return text ? { label, value: text } : null;
  }

  function catalogFact(label, value) {
    return { label, value: cleanText(value) || "Not published in catalog" };
  }

  function normalizeFacts(facts) {
    return arrayOf(facts)
      .map((item) => {
        if (!item || typeof item !== "object") return null;
        return fact(firstText(item.label, item.name), firstText(item.value, item.text));
      })
      .filter(Boolean);
  }

  function appendFacts(container, facts) {
    const validFacts = facts.filter(Boolean);
    if (!validFacts.length) return;
    const grid = element("dl", "prototype-facts");
    validFacts.forEach((item) => {
      const group = element("div", "prototype-fact");
      group.append(
        element("dt", "prototype-fact__label", item.label),
        element("dd", "prototype-fact__value", item.value),
      );
      grid.appendChild(group);
    });
    container.appendChild(grid);
  }

  function appendStringList(container, values, className = "prototype-list") {
    const strings = arrayOf(values).map(cleanText).filter(Boolean);
    if (!strings.length) return false;
    const list = element("ul", className);
    strings.forEach((value) => list.appendChild(element("li", "", value)));
    container.appendChild(list);
    return true;
  }

  function appendParagraphs(container, value) {
    const text = cleanText(value);
    if (!text) return false;
    text.split(/\r?\n+/).map((part) => part.trim()).filter(Boolean).forEach((part) => {
      container.appendChild(element("p", "prototype-copy", part.replace(/^[-*•]\s*/, "")));
    });
    return true;
  }

  function makeSectionEyebrow(value) {
    return element("p", "prototype-eyebrow", value);
  }

  function recordRequest(state, kind, path, method) {
    state.requestLog.push({ kind, path, method, at: new Date().toISOString() });
    if (state.requestLog.length > 100) state.requestLog.splice(0, state.requestLog.length - 100);
  }

  class GuideApi {
    constructor(state) {
      this.state = state;
    }

    async json(path, options = {}, kind = "guide") {
      const method = options.method || "GET";
      recordRequest(this.state, kind, path, method);
      const response = await fetch(`${apiBase}${path}`, {
        mode: "cors",
        headers: { Accept: "application/json", ...(options.headers || {}) },
        ...options,
      });
      let payload = null;
      try {
        payload = await response.json();
      } catch (_error) {
        payload = null;
      }
      if (!response.ok) throw requestError(response, payload);
      return payload || {};
    }

    context(context, entityReference, signal) {
      const query = new URLSearchParams({ page_type: context.page_type });
      ["university", "course", "specialization"].forEach((key) => {
        if (context[key]) query.set(key, context[key]);
      });
      if (entityReference) query.set("entity_id", entityReference);
      return this.json(`/api/widget/guide/context?${query.toString()}`, { signal });
    }

    catalog(kind, filters = {}, signal) {
      const query = new URLSearchParams();
      ["q", "university", "course"].forEach((key) => {
        if (filters[key]) query.set(key, filters[key]);
      });
      const suffix = query.toString() ? `?${query.toString()}` : "";
      return this.json(`/api/widget/guide/catalog/${encodeURIComponent(kind)}${suffix}`, { signal });
    }

    compare(ids, signal) {
      return this.json("/api/widget/guide/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_ids: ids }),
        signal,
      });
    }

    lead(sessionId, phone, signal) {
      return this.json("/api/widget/lead", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId || null,
          phone,
          source: "guided_prototype",
        }),
        signal,
      }, "lead");
    }
  }

  class ChatTransport {
    constructor(state) {
      this.state = state;
    }

    async send(message, signal, onEvent) {
      const body = {
        message,
        session_id: this.state.sessionId,
        site_key: siteKey,
      };
      const pageType = this.state.logicalContext.page_type;
      const exactEntity = unwrapItem(this.state.bundle?.entity) || {};
      const resolved = this.state.resolvedContext || {};
      if (["university", "course", "specialization"].includes(pageType)) {
        body.page_type = pageType;
        body.page_entity_slug = firstText(
          exactEntity.slug,
          resolved.page_entity_slug,
          resolved.slug,
          this.state.entityReference,
        );
        body.page_university_slug = firstText(
          resolved.page_university_slug,
          resolved.university_slug,
          pageType === "university" ? exactEntity.slug : "",
          this.state.logicalContext.university,
        );
        if (!body.page_entity_slug) delete body.page_entity_slug;
        if (!body.page_university_slug) delete body.page_university_slug;
      }
      recordRequest(this.state, "chat", "/chat", "POST");
      const response = await fetch(`${apiBase}/chat`, {
        method: "POST",
        mode: "cors",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify(body),
        signal,
      });
      if (!response.ok) throw requestError(response, null);
      if (!response.body) throw new Error("Streaming response is unavailable");
      await this.consumeSse(response, onEvent);
    }

    async consumeSse(response, onEvent) {
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
          let eventName = "message";
          const dataLines = [];
          block.split("\n").forEach((line) => {
            if (line.startsWith("event:")) eventName = line.slice(6).trim();
            if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
          });
          if (dataLines.length) {
            try {
              onEvent(eventName, JSON.parse(dataLines.join("\n")));
            } catch (error) {
              console.warn("DegreeBaba prototype ignored malformed SSE data", error);
            }
          }
          boundary = buffer.indexOf("\n\n");
        }
        if (done) break;
      }
    }
  }

  function createState() {
    return {
      scenario: "homepage",
      logicalContext: { ...SCENARIOS.homepage },
      resolvedContext: null,
      entityReference: "",
      bundle: null,
      sessionId: newSessionId(),
      contextGeneration: 0,
      contextController: null,
      picker: null,
      compareSelections: [],
      chatBusy: false,
      guidedBusy: false,
      viewedActions: new Set(),
      requestLog: [],
    };
  }

  function contextDisplayValues(state) {
    const resolved = state.resolvedContext || {};
    const logical = state.logicalContext;
    const entity = unwrapItem(state.bundle?.entity) || {};
    const university = firstText(
      resolved.university_name,
      resolved.university,
      entityPageType(entity) === "university" ? entity.name : entity.university_name,
      logical.university ? displayConcept(logical.university) : "",
    );
    const course = firstText(
      resolved.course_name,
      resolved.course,
      resolved.category,
      ["course", "specialization"].includes(entityPageType(entity)) ? entity.category : "",
      logical.course ? displayConcept(logical.course) : "",
    );
    const specialization = firstText(
      resolved.specialization_name,
      resolved.specialization,
      entityPageType(entity) === "specialization" ? entity.name : "",
      logical.specialization ? displayConcept(logical.specialization) : "",
    );
    const values = [];
    if (university) values.push(university);
    if (course) values.push(/^online\s/i.test(course) ? course : `Online ${course}`);
    if (specialization) values.push(specialization);
    return values;
  }

  function ensureContextLabel(dom) {
    let label = dom.contextBar.querySelector("[data-context-label]");
    if (!label) {
      label = element("span", "prototype-context__label");
      label.dataset.contextLabel = "true";
      const trail = dom.contextBar.querySelector(".context-bar__trail");
      (trail || dom.contextBar).appendChild(label);
    }
    return label;
  }

  function updateContextSurfaces(dom, state) {
    dom.contextJson.textContent = JSON.stringify(state.logicalContext, null, 2);
    const values = contextDisplayValues(state);
    const visible = values.length > 0 && state.logicalContext.page_type !== "homepage";
    dom.contextBar.hidden = !visible;
    ensureContextLabel(dom).textContent = values.join(" • ");
    if (dom.clearContext) dom.clearContext.hidden = !visible;
  }

  function statusMessage(dom, message) {
    dom.statusRegion.textContent = cleanText(message);
  }

  function revealFeedNode(dom, node) {
    window.requestAnimationFrame(() => {
      const feedBox = dom.feed.getBoundingClientRect();
      const nodeBox = node.getBoundingClientRect();
      dom.feed.scrollTop += nodeBox.top - feedBox.top - 4;
    });
  }

  function appendFeed(dom, node) {
    if (dom.guidePanel && dom.guidePanel.parentNode === dom.feed) {
      dom.feed.insertBefore(node, dom.guidePanel);
    } else {
      dom.feed.appendChild(node);
    }
    revealFeedNode(dom, node);
    return node;
  }

  function collapsePrimaryCards(dom) {
    dom.feed.querySelectorAll('[data-primary-card="true"]').forEach((card) => {
      if (card.closest(".prototype-collapsed-answer")) return;
      const title = firstText(
        card.querySelector(".prototype-card__title")?.textContent,
        "Previous answer",
      );
      const disclosure = element("details", "prototype-collapsed-answer");
      disclosure.append(element("summary", "prototype-collapsed-answer__summary", title));
      card.replaceWith(disclosure);
      disclosure.appendChild(card);
    });
  }

  function feedMessage(role, text) {
    const wrapper = element("article", `prototype-message prototype-message--${role}`);
    const bubble = element("div", "prototype-message__bubble");
    appendParagraphs(bubble, text);
    wrapper.appendChild(bubble);
    return wrapper;
  }

  function loadingCard(label = "Loading catalog data…") {
    const wrapper = element("div", "prototype-state prototype-state--loading");
    const spinner = element("span", "prototype-spinner");
    spinner.setAttribute("aria-hidden", "true");
    wrapper.append(spinner, element("p", "prototype-state__copy", label));
    return wrapper;
  }

  function thinkingIndicator() {
    const wrapper = element("article", "prototype-message prototype-message--guide");
    const bubble = element("div", "prototype-message__bubble prototype-thinking");
    bubble.setAttribute("role", "status");
    bubble.setAttribute("aria-label", "DegreeBaba is thinking");
    for (let index = 0; index < 3; index += 1) {
      const dot = element("span", "prototype-thinking__dot");
      dot.setAttribute("aria-hidden", "true");
      bubble.appendChild(dot);
    }
    wrapper.appendChild(bubble);
    return wrapper;
  }

  function wait(milliseconds) {
    return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  }

  function errorCard(message, onRetry, onLead) {
    const wrapper = element("section", "prototype-state prototype-state--error");
    wrapper.append(
      makeSectionEyebrow("Catalog unavailable"),
      element("h3", "prototype-card__title", "We couldn’t load this view"),
      element("p", "prototype-copy", message || "Please try again in a moment."),
    );
    const actions = element("div", "prototype-card__actions");
    if (onRetry) actions.appendChild(makeButton("Try Again", "prototype-button prototype-button--primary", onRetry));
    if (onLead) actions.appendChild(makeButton("Talk To Counsellor", "prototype-button", onLead));
    wrapper.appendChild(actions);
    return wrapper;
  }

  function emptyInfoCopy(container, subject) {
    const copy = subject
      ? `I don't have confirmed ${subject} yet — I'd rather not guess.`
      : EMPTY_COPY;
    container.appendChild(element("p", "prototype-empty", copy));
  }

  function renderContinuation(navigator, actions) {
    const wrapper = element("div", "prototype-next-steps");
    wrapper.appendChild(element("p", "prototype-next-steps__label", "Continue exploring"));
    const row = element("div", "prototype-next-steps__actions");
    const viewed = navigator.state.viewedActions;
    const available = actions.filter(([, action]) => !viewed.has(action));
    const hasLead = available.some(([, action]) => action === "lead");
    const visible = available.filter(([, action]) => action !== "lead").slice(0, hasLead ? 2 : 3);
    if (hasLead) visible.push(available.find(([, action]) => action === "lead"));
    else if (!viewed.has("lead")) visible.splice(2, 0, ["Talk To Counsellor", "lead"]);
    visible.slice(0, 3).forEach(([label, action]) => {
      row.appendChild(makeButton(label, "prototype-chip", () => navigator.handleAction(action, label)));
    });
    const lead = row.querySelector("button:last-child");
    if (lead && visible.slice(0, 3).at(-1)?.[1] === "lead") lead.classList.add("prototype-chip--accent");
    wrapper.appendChild(row);
    return wrapper;
  }

  function entityFacts(entity) {
    const item = unwrapItem(entity) || {};
    if (entityPageType(item) === "university") {
      return [
        catalogFact("NAAC", item.naac_grade),
        catalogFact("UGC", item.ugc_status),
        catalogFact(
          "Program Count",
          item.program_count === 0 || item.program_count ? `${item.program_count}` : "",
        ),
        catalogFact("Starting Fee", item.starting_fee),
      ];
    }
    if (entityPageType(item) === "specialization") {
      return [
        catalogFact("Fee", item.fee),
        catalogFact("Duration", item.duration),
        catalogFact("Career Outcome", item.career_outcome || arrayOf(item.career_outcomes)[0]),
        catalogFact("Average Salary", item.average_salary),
      ];
    }
    return [
      catalogFact("Fee", item.fee),
      catalogFact("Duration", item.duration),
      catalogFact(
        "Specialization Count",
        item.specialization_count === 0 || item.specialization_count ? `${item.specialization_count}` : "",
      ),
      catalogFact("EMI", item.emi),
    ];
  }

  function renderEntityCard(navigator, entity, options = {}) {
    const item = unwrapItem(entity) || {};
    const pageType = entityPageType(item);
    const card = element("article", `prototype-card prototype-entity-card prototype-entity-card--${pageType}`);
    const header = element("header", "prototype-entity-card__header");
    const monogram = element("span", "prototype-monogram", initials(item.name));
    monogram.setAttribute("aria-hidden", "true");
    const heading = element("div", "prototype-entity-card__heading");
    heading.append(
      makeSectionEyebrow(pageType === "university" ? "University" : pageType === "specialization" ? "Specialization" : "Program"),
      element("h3", "prototype-card__title", entityName(item)),
    );
    const subtitle = firstText(item.university_name, pageType === "university" ? item.learning_mode : item.category);
    if (subtitle && subtitle !== entityName(item)) heading.appendChild(element("p", "prototype-card__subtitle", subtitle));
    header.append(monogram, heading);
    card.appendChild(header);
    if (item.summary) card.appendChild(element("p", "prototype-copy", item.summary));
    appendFacts(card, entityFacts(item));

    const actions = element("div", "prototype-card__actions");
    if (options.selectable) {
      actions.appendChild(makeButton("Choose", "prototype-button prototype-button--primary", () => {
        navigator.selectEntity(item);
      }));
    } else if (options.guidedAnswer) {
      [
        ["Career & Salary", "career"],
        ["Syllabus", "syllabus"],
        ["Talk To Counsellor", "lead"],
      ].filter(([, action]) => !navigator.state.viewedActions.has(action)).slice(0, 3).forEach(
        ([label, action], index) => {
          actions.appendChild(makeButton(
            label,
            `prototype-button${index === 0 ? " prototype-button--primary" : ""}`,
            () => navigator.handleAction(action, label),
          ));
        },
      );
    } else {
      actions.appendChild(makeButton("View Details", "prototype-button prototype-button--primary", () => {
        navigator.showEntityDetails(item);
      }));
      if (entityId(item)) {
        actions.appendChild(makeButton("Compare", "prototype-button", () => navigator.startCompareWithChoice(item)));
      }
    }
    card.appendChild(actions);
    return card;
  }

  function renderEntityDetails(navigator, entity) {
    const item = unwrapItem(entity) || {};
    const wrapper = element("section", "prototype-card prototype-info-card");
    wrapper.append(
      makeSectionEyebrow("Catalog overview"),
      element("h3", "prototype-card__title", entityName(item)),
    );
    let hasDetails = appendParagraphs(wrapper, firstText(item.summary, item.details?.description));
    appendFacts(wrapper, entityFacts(item));
    if (item.details?.accreditations?.length) {
      wrapper.appendChild(element("h4", "prototype-info-card__heading", "Accreditations"));
      hasDetails = appendStringList(wrapper, item.details.accreditations) || hasDetails;
    }
    if (item.details?.admission_steps) {
      wrapper.appendChild(element("h4", "prototype-info-card__heading", "Admission process"));
      hasDetails = appendParagraphs(wrapper, item.details.admission_steps) || hasDetails;
    }
    const detailsUrl = safeLink(item.details_url);
    if (detailsUrl) {
      const link = element("a", "prototype-button", "Open DegreeBaba Page");
      link.href = detailsUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      wrapper.appendChild(link);
      hasDetails = true;
    }
    if (!hasDetails && !entityFacts(item).length) emptyInfoCopy(wrapper);
    const pageType = entityPageType(item);
    const next = pageType === "university"
      ? [["Browse Programs", "programs_here"], ["View Reviews", "reviews"], ["Compare", "compare"]]
      : pageType === "course"
        ? [["Fees & EMI", "fees"], ["Specializations", "specializations"], ["Eligibility", "eligibility"]]
        : [["Career & Salary", "career"], ["Syllabus", "syllabus"], ["Other Specializations", "other_specializations"]];
    wrapper.appendChild(renderContinuation(navigator, next));
    return wrapper;
  }

  function infoBlock(state, key) {
    const info = state.bundle?.info;
    if (!info || typeof info !== "object") return {};
    const aliases = {
      fees: ["fees", "fee"],
      eligibility: ["eligibility", "requirements"],
      career: ["career", "careers", "career_outcomes"],
      syllabus: ["syllabus", "curriculum"],
      reviews: ["reviews", "student_reviews"],
      accreditations: ["accreditations", "accreditation", "recognition"],
    };
    for (const alias of aliases[key] || [key]) {
      if (Object.prototype.hasOwnProperty.call(info, alias)) {
        const value = info[alias];
        if (value && typeof value === "object") return value;
        if (value) return { content: value, available: true };
      }
    }
    return {};
  }

  function infoAvailable(data) {
    return data.available !== false && data.published !== false;
  }

  function renderFees(navigator) {
    const data = infoBlock(navigator.state, "fees");
    const entity = unwrapItem(navigator.state.bundle?.entity) || {};
    const card = element("section", "prototype-card prototype-info-card prototype-info-card--fees");
    card.append(makeSectionEyebrow("Fees"), element("h3", "prototype-card__title", "Fees & EMI"));
    const total = firstText(data.total_fee, data.total, data.fee, entity.fee);
    const semester = firstText(data.semester_fee, data.per_semester, data.starting_fee, entity.starting_fee);
    const emi = firstText(data.emi, data.emi_amount, data.monthly_emi, entity.emi);
    const facts = [
      catalogFact("Total Fee", total),
      catalogFact("Semester Fee", semester),
      catalogFact("EMI", emi),
    ];
    appendFacts(card, facts);

    const plans = arrayOf(data.emi_plans || data.plans || data.fee_plans);
    card.appendChild(element("h4", "prototype-info-card__heading", "EMI plans"));
    if (plans.length) {
      const planList = element("div", "prototype-plan-list");
      plans.forEach((plan) => {
        if (typeof plan !== "object") {
          planList.appendChild(element("p", "prototype-plan", cleanText(plan)));
          return;
        }
        const row = element("div", "prototype-plan");
        row.append(
          element("strong", "prototype-plan__name", firstText(plan.name, plan.label, plan.title, "Fee plan")),
          element("span", "prototype-plan__value", [
            firstText(plan.amount, plan.value, plan.description),
            plan.total ? `Total ${cleanText(plan.total)}` : "",
          ].filter(Boolean).join(" • ")),
        );
        planList.appendChild(row);
      });
      card.appendChild(planList);
    } else {
      card.appendChild(element("p", "prototype-empty", "EMI plans have not been published."));
    }
    card.appendChild(renderContinuation(navigator, [
      ["Check Eligibility", "eligibility"],
      ["Admission Steps", "admission_steps"],
    ]));
    return card;
  }

  function renderEligibility(navigator) {
    const data = infoBlock(navigator.state, "eligibility");
    const entity = unwrapItem(navigator.state.bundle?.entity) || {};
    const card = element("section", "prototype-card prototype-info-card prototype-info-card--eligibility");
    card.append(makeSectionEyebrow("Admissions"), element("h3", "prototype-card__title", "Eligibility"));
    const requirementItems = arrayOf(data.qualification_checklist || data.checklist || data.qualifications || data.requirements);
    const requirements = firstText(data.summary, data.content, !Array.isArray(data.requirements) ? data.requirements : "", entity.eligibility);
    let hasRequirements = false;
    hasRequirements = appendParagraphs(card, requirements);
    const checklist = requirementItems;
    card.appendChild(element("h4", "prototype-info-card__heading", "Qualification checklist"));
    if (checklist.length) {
      const list = element("ul", "prototype-checklist");
      checklist.forEach((item) => {
        const label = typeof item === "object" ? firstText(item.label, item.requirement, item.text) : cleanText(item);
        if (label) list.appendChild(element("li", "", label));
      });
      if (list.children.length) {
        card.appendChild(list);
        hasRequirements = true;
      }
      else card.appendChild(element("p", "prototype-empty", "A qualification checklist has not been published."));
    } else {
      card.appendChild(element("p", "prototype-empty", "A qualification checklist has not been published."));
    }
    if (!infoAvailable(data) || !hasRequirements) {
      if (!hasRequirements) emptyInfoCopy(card, "eligibility requirements");
    }
    card.appendChild(renderContinuation(navigator, [["View Fees", "fees"], ["Compare Options", "compare"]]));
    return card;
  }

  function renderCareer(navigator) {
    const data = infoBlock(navigator.state, "career");
    const entity = unwrapItem(navigator.state.bundle?.entity) || {};
    const card = element("section", "prototype-card prototype-info-card prototype-info-card--career");
    card.append(makeSectionEyebrow("Outcomes"), element("h3", "prototype-card__title", "Career & Salary"));
    const salary = firstText(data.average_salary, data.salary, entity.average_salary);
    appendFacts(card, [catalogFact("Average Salary", salary)]);
    const roles = data.job_roles || data.roles || data.career_outcomes || entity.career_outcomes;
    const recruiters = data.recruiters || data.companies;
    card.appendChild(element("h4", "prototype-info-card__heading", "Job roles"));
    if (!appendStringList(card, roles)) card.appendChild(element("p", "prototype-empty", "Job roles have not been published."));
    card.appendChild(element("h4", "prototype-info-card__heading", "Recruiters"));
    if (!appendStringList(card, recruiters, "prototype-tag-list")) {
      card.appendChild(element("p", "prototype-empty", "Recruiter information has not been published."));
    }
    card.appendChild(renderContinuation(navigator, [["View Syllabus", "syllabus"], ["View Fees", "fees"]]));
    return card;
  }

  function normalizeSemesters(data) {
    const raw = data.semesters || data.curriculum || data.modules;
    if (Array.isArray(raw)) return raw;
    if (raw && typeof raw === "object") {
      return Object.entries(raw).map(([name, subjects]) => ({ name, subjects }));
    }
    return [];
  }

  function renderSyllabus(navigator) {
    const data = infoBlock(navigator.state, "syllabus");
    const card = element("section", "prototype-card prototype-info-card prototype-info-card--syllabus");
    card.append(makeSectionEyebrow("Curriculum"), element("h3", "prototype-card__title", "Syllabus"));
    const semesters = normalizeSemesters(data);
    if (semesters.length) {
      const accordion = element("div", "prototype-accordion");
      semesters.forEach((semester, index) => {
        const details = element("details", "prototype-accordion__item");
        if (index === 0) details.open = true;
        const summary = element(
          "summary",
          "prototype-accordion__summary",
          firstText(semester.name, semester.title, semester.semester, `Semester ${index + 1}`),
        );
        const body = element("div", "prototype-accordion__body");
        const subjects = semester.subjects || semester.courses || semester.modules || semester.items || semester.content;
        if (!appendStringList(body, subjects)) appendParagraphs(body, subjects);
        if (!body.children.length) body.appendChild(element("p", "prototype-empty", "Subjects have not been published."));
        details.append(summary, body);
        accordion.appendChild(details);
      });
      card.appendChild(accordion);
    } else {
      const unstructured = firstText(data.content, data.summary);
      if (unstructured) {
        appendParagraphs(card, unstructured);
        card.appendChild(element("p", "prototype-note", "A semester-wise breakdown has not been published."));
      } else {
        emptyInfoCopy(card, "semester-wise syllabus");
      }
    }
    card.appendChild(renderContinuation(navigator, [["Career & Salary", "career"], ["Other Specializations", "other_specializations"]]));
    return card;
  }

  function renderReviews(navigator) {
    const data = infoBlock(navigator.state, "reviews");
    const entity = unwrapItem(navigator.state.bundle?.entity) || {};
    const card = element("section", "prototype-card prototype-info-card prototype-info-card--reviews");
    card.append(makeSectionEyebrow("Student voice"), element("h3", "prototype-card__title", "Student Reviews"));
    const rating = firstText(data.rating, data.average_rating);
    appendFacts(card, [catalogFact("Rating", rating ? `${rating}${/\/5$/.test(rating) ? "" : " / 5"}` : "")]);
    const breakdown = data.breakdown;
    card.appendChild(element("h4", "prototype-info-card__heading", "Rating breakdown"));
    if (Array.isArray(breakdown)) {
      if (!breakdown.length) {
        card.appendChild(element("p", "prototype-empty", "A rating breakdown has not been published."));
      } else {
        appendFacts(card, breakdown.map((item) => fact(firstText(item.label, item.name), firstText(item.value, item.score))).filter(Boolean));
      }
    } else if (breakdown && typeof breakdown === "object") {
      appendFacts(card, Object.entries(breakdown).map(([label, value]) => fact(humanize(label), value)).filter(Boolean));
    } else {
      card.appendChild(element("p", "prototype-empty", "A rating breakdown has not been published."));
    }
    const reviews = arrayOf(data.testimonials || data.reviews || entity.details?.reviews);
    card.appendChild(element("h4", "prototype-info-card__heading", "Testimonials"));
    if (reviews.length) {
      const list = element("div", "prototype-testimonials");
      reviews.forEach((review) => {
        const quote = element("blockquote", "prototype-testimonial");
        quote.appendChild(element("p", "prototype-copy", typeof review === "object" ? firstText(review.text, review.quote, review.content) : cleanText(review)));
        if (typeof review === "object") {
          const author = firstText(review.reviewer_name, review.name, review.author, review.reviewer_label);
          if (author) quote.appendChild(element("cite", "prototype-testimonial__author", author));
        }
        list.appendChild(quote);
      });
      card.appendChild(list);
    } else {
      card.appendChild(element("p", "prototype-empty", "Student testimonials have not been published."));
    }
    card.appendChild(renderContinuation(navigator, [["Programs Offered Here", "programs_here"], ["Compare With Others", "compare"]]));
    return card;
  }

  function renderAccreditations(navigator) {
    const data = infoBlock(navigator.state, "accreditations");
    const entity = unwrapItem(navigator.state.bundle?.entity) || {};
    const card = element("section", "prototype-card prototype-info-card prototype-info-card--accreditations");
    card.append(makeSectionEyebrow("Recognition"), element("h3", "prototype-card__title", "Accreditations"));
    appendFacts(card, [fact("NAAC", firstText(data.naac_grade, entity.naac_grade)), fact("UGC", firstText(data.ugc_status, entity.ugc_status))].filter(Boolean));
    const items = data.items || data.accreditations || entity.details?.accreditations;
    if (!appendStringList(card, items, "prototype-badge-list") && !entity.naac_grade && !entity.ugc_status) {
      emptyInfoCopy(card, "accreditation details");
    }
    card.appendChild(element(
      "p",
      "prototype-note",
      "Always verify the current recognition status for your exact university and program before enrolling.",
    ));
    card.appendChild(renderContinuation(navigator, [["Browse Programs", "programs_here"], ["Compare With Others", "compare"]]));
    return card;
  }

  function renderComparison(navigator, component) {
    const comparison = component?.comparison || component?.component || component;
    const requiredRows = [
      ["Fees", ["fees", "fee", "starting fee"]],
      ["Duration", ["duration"]],
      ["Eligibility", ["eligibility"]],
      ["Specializations", ["specializations", "specialization count"]],
      ["UGC", ["ugc", "ugc status"]],
      ["NAAC", ["naac", "naac grade"]],
    ];
    const card = element("section", "prototype-card prototype-comparison-card");
    card.append(makeSectionEyebrow("Side-by-side"), element("h3", "prototype-card__title", firstText(comparison?.title, "Comparison")));
    const items = arrayOf(comparison?.items);
    if (!items.length) {
      emptyInfoCopy(card, "comparison details");
    } else {
      const table = element("div", "prototype-comparison");
      items.forEach((item) => {
        const column = element("article", "prototype-comparison__item");
        column.appendChild(element("h4", "prototype-comparison__name", entityName(item)));
        if (item.subtitle) column.appendChild(element("p", "prototype-card__subtitle", item.subtitle));
        const published = normalizeFacts(item.facts);
        const facts = requiredRows.map(([label, aliases]) => {
          const match = published.find((entry) => aliases.includes(entry.label.toLowerCase()));
          return catalogFact(label, match?.value);
        });
        appendFacts(column, facts);
        table.appendChild(column);
      });
      card.appendChild(table);
    }
    const verdict = firstText(comparison?.verdict);
    const verdictSection = element("aside", "prototype-verdict");
    verdictSection.append(
      element("strong", "prototype-verdict__label", "Verdict"),
      element("p", "prototype-copy", verdict || "No catalog-grounded verdict is available for this selection."),
    );
    card.appendChild(verdictSection);
    card.appendChild(renderContinuation(navigator, [["Check Eligibility", "eligibility"], ["View Fees", "fees"]]));
    return card;
  }

  function renderValidity(navigator) {
    const card = element("section", "prototype-card prototype-info-card prototype-info-card--validity");
    card.append(
      makeSectionEyebrow("Before you enrol"),
      element("h3", "prototype-card__title", "Is an online degree valid?"),
      element(
        "p",
        "prototype-copy",
        "Validity depends on the recognition status of the university and the exact program. DegreeBaba surfaces published UGC and NAAC information on university cards so you can compare the catalog evidence.",
      ),
    );
    const checklist = element("ul", "prototype-checklist");
    [
      "Check the university’s current UGC entitlement.",
      "Review the published NAAC grade and accreditation details.",
      "Confirm recognition for the exact program and intake before paying.",
    ].forEach((item) => checklist.appendChild(element("li", "", item)));
    card.appendChild(checklist);
    card.appendChild(renderContinuation(navigator, [["Browse Universities", "browse_universities"], ["Compare", "compare"]]));
    return card;
  }

  class GuidedNavigator {
    constructor(state, dom, api) {
      this.state = state;
      this.dom = dom;
      this.api = api;
      this.searchTimer = null;
    }

    freshSession() {
      this.state.sessionId = newSessionId();
    }

    appendUserChoice(label) {
      const value = cleanText(label);
      if (value) appendFeed(this.dom, feedMessage("user", value));
    }

    appendGuidePrompt(message, choices = []) {
      appendFeed(this.dom, feedMessage("guide", message));
      if (!choices.length) return;
      const row = element("div", "prototype-chat-actions prototype-exploration-choices");
      const renderPage = (offset = 0) => {
        row.replaceChildren();
        const pageSize = offset === 0 ? 3 : 2;
        if (offset > 0) {
          row.appendChild(makeButton("Back", "prototype-chip", () => renderPage(offset <= 3 ? 0 : offset - 2)));
        }
        choices.slice(offset, offset + pageSize).forEach(([label, handler, accent = false]) => {
          row.appendChild(makeButton(
            label,
            `prototype-chip${accent ? " prototype-chip--accent" : ""}`,
            handler,
          ));
        });
        if (offset + pageSize < choices.length) {
          row.appendChild(makeButton("More", "prototype-chip", () => renderPage(offset + pageSize)));
        }
      };
      renderPage();
      appendFeed(this.dom, row);
    }

    async runGuidedResponse(callback) {
      if (this.state.guidedBusy) return undefined;
      this.state.guidedBusy = true;
      const contextGeneration = this.state.contextGeneration;
      const thinking = thinkingIndicator();
      appendFeed(this.dom, thinking);
      try {
        await wait(GUIDED_THINKING_MS);
        thinking.remove();
        if (contextGeneration !== this.state.contextGeneration) return undefined;
        return await callback();
      } finally {
        thinking.remove();
        this.state.guidedBusy = false;
      }
    }

    presentPrimaryCard(card, replaceNode = null) {
      this.dom.guidePanel.hidden = true;
      collapsePrimaryCards(this.dom);
      card.dataset.primaryCard = "true";
      if (replaceNode?.isConnected) {
        replaceNode.replaceWith(card);
        revealFeedNode(this.dom, card);
      } else {
        appendFeed(this.dom, card);
      }
      return card;
    }

    showPickerChoice(label, kind, options = {}) {
      if (this.state.guidedBusy) return undefined;
      this.appendUserChoice(label);
      this.dom.guidePanel.hidden = true;
      return this.runGuidedResponse(() => this.openPicker(kind, options));
    }

    setScenario(name) {
      const scenario = Object.prototype.hasOwnProperty.call(SCENARIOS, name) ? name : "homepage";
      this.state.scenario = scenario;
      this.state.logicalContext = { ...SCENARIOS[scenario] };
      this.state.resolvedContext = null;
      this.state.entityReference = "";
      this.state.bundle = null;
      this.state.compareSelections = [];
      this.state.viewedActions.clear();
      this.state.guidedBusy = false;
      this.freshSession();
      updateContextSurfaces(this.dom, this.state);
      this.renderActionBank();
      return this.loadContext("page");
    }

    clearContext() {
      const radio = this.dom.scenarioForm.querySelector('input[name="scenario"][value="homepage"]');
      if (radio) radio.checked = true;
      const pending = this.setScenario("homepage");
      statusMessage(this.dom, "Context cleared. A new chat session has started.");
      return pending;
    }

    contextForEntity(entity) {
      const item = unwrapItem(entity) || {};
      const pageType = entityPageType(item);
      const current = this.state.logicalContext;
      if (pageType === "university") {
        return {
          page_type: "university",
          university: firstText(item.slug, item.name, item.id),
        };
      }
      const university = firstText(
        item.university_slug,
        item.university_name,
        current.university,
      );
      const course = firstText(item.category_slug, item.category, pageType === "course" ? item.name : current.course);
      if (pageType === "specialization") {
        return {
          page_type: "specialization",
          university: slugify(university),
          course: slugify(course.replace(/^online\s+/i, "")),
          specialization: slugify(item.specialization || item.name),
        };
      }
      return {
        page_type: "course",
        university: slugify(university),
        course: slugify(course.replace(/^online\s+/i, "")),
      };
    }

    selectEntity(entity, selectionLabel) {
      if (this.state.guidedBusy) return undefined;
      const item = unwrapItem(entity) || {};
      const id = entityId(item);
      if (!id && !entitySlug(item)) return;
      this.closePicker();
      this.appendUserChoice(selectionLabel || entityName(item));
      this.dom.guidePanel.hidden = true;
      this.state.logicalContext = this.contextForEntity(item);
      this.state.resolvedContext = null;
      this.state.entityReference = id || entitySlug(item);
      this.state.bundle = { entity: item, context: null, related: {}, info: {} };
      this.state.scenario = this.state.logicalContext.page_type;
      const radio = this.dom.scenarioForm.querySelector(
        `input[name="scenario"][value="${this.state.scenario}"]`,
      );
      if (radio) radio.checked = true;
      this.freshSession();
      updateContextSurfaces(this.dom, this.state);
      this.renderActionBank();
      return this.loadContext("selection");
    }

    async loadContext(origin = "page") {
      this.state.contextGeneration += 1;
      const generation = this.state.contextGeneration;
      const preserveConversation = origin === "selection";
      if (preserveConversation) this.state.guidedBusy = true;
      if (this.state.contextController) this.state.contextController.abort();
      const controller = new AbortController();
      this.state.contextController = controller;
      const thinking = thinkingIndicator();
      const minimumDelay = wait(GUIDED_THINKING_MS);
      if (preserveConversation) appendFeed(this.dom, thinking);
      else this.dom.feed.replaceChildren(thinking);
      statusMessage(this.dom, "Loading guided context");
      try {
        const payload = await this.api.context(
          this.state.logicalContext,
          this.state.entityReference,
          controller.signal,
        );
        if (generation !== this.state.contextGeneration) {
          thinking.remove();
          return;
        }
        await minimumDelay;
        this.state.bundle = {
          context: payload.context || null,
          entity: payload.entity || null,
          related: payload.related || {},
          info: payload.info || {},
        };
        this.state.resolvedContext = payload.context || null;
        const resolvedEntityId = entityId(payload.entity);
        if (resolvedEntityId) this.state.entityReference = resolvedEntityId;
        updateContextSurfaces(this.dom, this.state);
        thinking.remove();
        this.renderBundle(origin);
        if (preserveConversation) this.state.guidedBusy = false;
        statusMessage(this.dom, "Guided context ready");
      } catch (error) {
        if (error && error.name === "AbortError") {
          thinking.remove();
          return;
        }
        if (generation !== this.state.contextGeneration) {
          thinking.remove();
          return;
        }
        await minimumDelay;
        console.warn("DegreeBaba guided context failed", error);
        const failure = errorCard(
          cleanText(error.message),
          () => this.loadContext(origin),
          () => this.openLead(),
        );
        if (preserveConversation) thinking.replaceWith(failure);
        else this.dom.feed.replaceChildren(failure);
        if (preserveConversation) this.state.guidedBusy = false;
        statusMessage(this.dom, "Guided context could not be loaded");
      }
    }

    renderBundle(origin = "page") {
      const preserveConversation = origin === "selection";
      if (!preserveConversation) this.dom.feed.replaceChildren();
      const pageType = this.state.logicalContext.page_type;
      this.dom.guidePanel.hidden = preserveConversation || pageType === "specialization";
      const entity = unwrapItem(this.state.bundle?.entity) || null;
      if (pageType === "homepage") {
        this.dom.feed.appendChild(feedMessage(
          "guide",
          "Explore universities and programs from the catalog, or type a question below to use the existing chatbot.",
        ));
      } else if (!entity) {
        const failure = errorCard(
          "This page context is not available in the current catalog.",
          () => this.openPicker(pageType === "university" ? "universities" : pageType === "course" ? "programs" : "specializations"),
          () => this.openLead(),
        );
        if (preserveConversation) appendFeed(this.dom, failure);
        else this.dom.feed.appendChild(failure);
      } else if (pageType === "university") {
        if (preserveConversation) this.showUniversityPrograms();
        else this.dom.feed.appendChild(feedMessage(
          "guide",
          `You're viewing ${entityName(entity)}.\n\nWhat would you like to know?`,
        ));
      } else if (pageType === "course") {
        if (preserveConversation) this.showCourseSpecializations();
        else this.dom.feed.appendChild(feedMessage(
          "guide",
          `You're viewing ${contextDisplayValues(this.state).join(" ")}.\n\nWhat would you like to know?`,
        ));
      } else {
        const specialization = firstText(entity.specialization, entity.name, "this specialization");
        const university = contextDisplayValues(this.state)[0];
        const intro = preserveConversation
          ? `Here's the strongest catalog match for ${specialization}${university ? ` at ${university}` : ""}.`
          : `You're viewing ${contextDisplayValues(this.state).join(" • ")}.\n\nHere's the specialization at a glance.`;
        const message = feedMessage("guide", intro);
        if (preserveConversation) appendFeed(this.dom, message);
        else this.dom.feed.appendChild(message);
        const card = renderEntityCard(this, entity, { guidedAnswer: true });
        if (preserveConversation) this.presentPrimaryCard(card);
        else {
          card.dataset.primaryCard = "true";
          this.dom.feed.appendChild(card);
        }
      }
      if (pageType === "homepage") {
        this.dom.feed.appendChild(feedMessage(
          "guide",
          "Choose a guided action below to begin.",
        ));
      }
      if (this.dom.guidePanel) {
        this.dom.feed.appendChild(this.dom.guidePanel);
      }
      if (!preserveConversation) this.dom.feed.scrollTop = 0;
    }

    programLabel(item) {
      return displayConcept(firstText(item.category, entityName(item).replace(/^online\s+/i, "")));
    }

    showUniversityPrograms() {
      const entity = unwrapItem(this.state.bundle?.entity) || {};
      const programs = arrayOf(this.state.bundle?.related?.courses).map(unwrapItem).filter(Boolean);
      const count = entity.program_count === 0 || entity.program_count
        ? entity.program_count
        : programs.length;
      const message = programs.length
        ? `${entityName(entity)} offers ${count} online program${Number(count) === 1 ? "" : "s"}.\n\nWhich one interests you?`
        : `Programs haven't been published for ${entityName(entity)} yet.\n\nWould you like to browse other programs or talk to a counsellor?`;
      const choices = programs.slice(0, 4).map((program) => {
        const label = this.programLabel(program);
        return [label, () => this.selectEntity(program, label)];
      });
      if (programs.length > 4) {
        choices.push(["View all programs", () => {
          this.showPickerChoice("View all programs", "programs", {
            university: this.universityFilter(),
          });
        }]);
      }
      if (!choices.length) {
        choices.push(
          ["Browse Programs", () => this.handleAction("browse_programs", "Browse Programs")],
          ["Talk To Counsellor", () => this.handleAction("lead", "Talk To Counsellor"), true],
        );
      }
      this.appendGuidePrompt(message, choices);
    }

    showCourseSpecializations() {
      const entity = unwrapItem(this.state.bundle?.entity) || {};
      const specializations = arrayOf(this.state.bundle?.related?.specializations).map(unwrapItem).filter(Boolean);
      const isSpecializationContext = this.state.logicalContext.page_type === "specialization";
      const count = isSpecializationContext
        ? specializations.length
        : entity.specialization_count === 0 || entity.specialization_count
          ? entity.specialization_count
          : specializations.length;
      const contextName = contextDisplayValues(this.state).slice(0, 2).join(" ");
      const message = specializations.length
        ? isSpecializationContext
          ? `${contextName} has ${count} other specialization${Number(count) === 1 ? "" : "s"} available.\n\nWhich one interests you?`
          : `${contextName} offers ${count} specialization${Number(count) === 1 ? "" : "s"}.\n\nWhich area interests you?`
        : "Specializations haven't been published for this course yet.\n\nWould you like to see fees or eligibility instead?";
      const choices = specializations.slice(0, 4).map((specialization) => {
        const label = entityName(specialization);
        return [label, () => this.selectEntity(specialization, label)];
      });
      if (specializations.length > 4) {
        choices.push(["View all specializations", () => {
          this.showPickerChoice("View all specializations", "specializations", {
            university: this.universityFilter(),
            course: this.courseFilter(),
          });
        }]);
      }
      if (!choices.length) {
        choices.push(
          ["Fees & EMI", () => this.handleAction("fees", "Fees & EMI")],
          ["Eligibility", () => this.handleAction("eligibility", "Eligibility")],
        );
      }
      this.appendGuidePrompt(message, choices);
    }

    showProgramQuestion(message = "Which program are you considering?") {
      const choices = PROGRAM_CATEGORIES.map((category) => [
        category,
        () => this.showProgramCategory(category),
      ]);
      this.appendGuidePrompt(message, choices);
    }

    renderActionBank() {
      const pageType = this.state.logicalContext.page_type;
      this.dom.guideHeading.textContent = pageType === "homepage" ? "How can we help?" : "Choose an option";
      const viewed = this.state.viewedActions;
      const primary = (ACTION_BANKS[pageType] || ACTION_BANKS.homepage).filter(
        ([, action]) => !viewed.has(action),
      );
      const primaryLimit = pageType === "homepage" ? 4 : 3;
      const secondary = (pageType === "homepage" ? MORE_ACTIONS : primary.slice(primaryLimit)).filter(
        ([, action]) => !viewed.has(action),
      );
      const appendAction = (container, [label, action], secondaryAction = false) => {
        const button = makeButton(label, "prototype-guide-action", () => this.handleAction(action, label));
        if (secondaryAction) button.classList.add("prototype-guide-action--secondary");
        button.dataset.guideAction = action;
        container.appendChild(button);
      };
      const renderPrimary = () => {
        this.dom.guideActions.replaceChildren();
        primary.slice(0, primaryLimit).forEach((item) => appendAction(this.dom.guideActions, item));
        this.dom.moreActions.replaceChildren();
        this.dom.moreActions.hidden = !secondary.length;
        if (secondary.length) {
          this.dom.moreActions.appendChild(makeButton("More", "prototype-more__summary", () => {
            renderSecondary(0);
          }));
        }
      };
      const renderSecondary = (offset) => {
        this.dom.guideActions.replaceChildren();
        this.dom.moreActions.replaceChildren();
        this.dom.moreActions.hidden = true;
        this.dom.guideActions.appendChild(makeButton("Back", "prototype-guide-action prototype-guide-action--secondary", renderPrimary));
        secondary.slice(offset, offset + 2).forEach((item) => appendAction(this.dom.guideActions, item, true));
        if (offset + 2 < secondary.length) {
          this.dom.guideActions.appendChild(makeButton("More", "prototype-guide-action prototype-guide-action--secondary", () => {
            renderSecondary(offset + 2);
          }));
        }
      };
      renderPrimary();
    }

    handleAction(action, label) {
      const pageType = this.state.logicalContext.page_type;
      const handlers = {
        browse_universities: () => this.openPicker("universities"),
        browse_programs: () => this.openPicker("programs", { mode: "categories" }),
        help_choose: () => this.showProgramQuestion(),
        online_validity: () => this.presentPrimaryCard(renderValidity(this)),
        programs_here: () => this.showUniversityPrograms(),
        reviews: () => this.presentPrimaryCard(renderReviews(this)),
        accreditations: () => this.presentPrimaryCard(renderAccreditations(this)),
        compare: () => this.startCompare(),
        fees: () => {
          if (pageType === "homepage") this.renderChooseFirst("fees and EMI", "programs");
          else this.presentPrimaryCard(renderFees(this));
        },
        eligibility: () => {
          if (pageType === "homepage") this.renderChooseFirst("eligibility", "programs");
          else this.presentPrimaryCard(renderEligibility(this));
        },
        admission_steps: () => this.presentPrimaryCard(
          renderEntityDetails(this, unwrapItem(this.state.bundle?.entity) || {}),
        ),
        specializations: () => this.showCourseSpecializations(),
        career: () => this.presentPrimaryCard(renderCareer(this)),
        syllabus: () => this.presentPrimaryCard(renderSyllabus(this)),
        other_specializations: () => this.showCourseSpecializations(),
        lead: () => this.openLead(),
      };
      const handler = handlers[action];
      if (!handler || this.state.guidedBusy) return undefined;
      this.state.viewedActions.add(action);
      this.appendUserChoice(label);
      this.dom.guidePanel.hidden = true;
      return this.runGuidedResponse(handler);
    }

    renderChooseFirst(subject, kind) {
      const action = kind === "programs" ? "browse_programs" : "browse_universities";
      const label = kind === "programs" ? "Browse Programs" : "Browse Universities";
      this.appendGuidePrompt(
        `First, choose a program so I can show the right ${subject}.`,
        [[label, () => this.handleAction(action, label)]],
      );
    }

    universityFilter() {
      const context = this.state.resolvedContext || {};
      const entity = unwrapItem(this.state.bundle?.entity) || {};
      return firstText(
        context.university_id,
        context.university_slug,
        typeof context.university === "object" ? context.university.id || context.university.slug : "",
        entityPageType(entity) === "university" ? entity.id : entity.university_id,
        this.state.logicalContext.university,
      );
    }

    courseFilter() {
      const context = this.state.resolvedContext || {};
      const entity = unwrapItem(this.state.bundle?.entity) || {};
      return firstText(
        context.course_id,
        context.course_slug,
        typeof context.course === "object" ? context.course.id || context.course.slug : "",
        entityPageType(entity) === "course" ? entity.id : entity.course_id,
        this.state.logicalContext.course,
      );
    }

    showEntityDetails(entity) {
      if (this.state.guidedBusy) return undefined;
      this.state.viewedActions.add("details");
      this.appendUserChoice("View Details");
      this.dom.guidePanel.hidden = true;
      return this.runGuidedResponse(() => {
        this.presentPrimaryCard(renderEntityDetails(this, entity));
      });
    }

    openPicker(kind, options = {}) {
      this.closePicker(false);
      this.state.picker = {
        kind,
        requestKind: kind === "programs" && options.mode !== "categories" ? "courses" : kind,
        mode: options.mode || "catalog",
        options,
        query: "",
        items: [],
        controller: null,
        generation: 0,
      };
      const titles = {
        universities: "Browse Universities",
        programs: options.mode === "categories" ? "Browse Programs" : "Choose a Program",
        courses: "Choose a Program",
        specializations: "Browse Specializations",
      };
      this.dom.sheetTitle.textContent = options.title || titles[kind] || "Browse Catalog";
      this.dom.sheetSearch.value = "";
      this.dom.sheetSearch.placeholder = kind === "specializations"
        ? "Search specializations"
        : kind === "universities"
          ? "Search universities"
          : options.display === "university"
            ? "Search universities"
          : "Search programs";
      this.dom.sheetSearch.hidden = kind === "programs" && options.mode === "categories";
      this.dom.sheetBackdrop.hidden = false;
      this.dom.pickerSheet.hidden = false;
      this.dom.pickerSheet.setAttribute("aria-hidden", "false");
      document.body.classList.add("prototype-sheet-open");
      this.loadPicker();
      if (!this.dom.sheetSearch.hidden) window.setTimeout(() => this.dom.sheetSearch.focus(), 0);
    }

    closePicker(reset = true) {
      window.clearTimeout(this.searchTimer);
      if (this.state.picker?.controller) this.state.picker.controller.abort();
      this.dom.sheetBackdrop.hidden = true;
      this.dom.pickerSheet.hidden = true;
      this.dom.pickerSheet.setAttribute("aria-hidden", "true");
      document.body.classList.remove("prototype-sheet-open");
      if (reset) this.state.picker = null;
    }

    schedulePickerSearch() {
      if (!this.state.picker) return;
      this.state.picker.query = this.dom.sheetSearch.value.trim();
      window.clearTimeout(this.searchTimer);
      this.searchTimer = window.setTimeout(() => this.loadPicker(), 220);
    }

    async loadPicker() {
      const picker = this.state.picker;
      if (!picker) return;
      picker.generation += 1;
      const generation = picker.generation;
      if (picker.controller) picker.controller.abort();
      picker.controller = new AbortController();
      this.dom.sheetList.replaceChildren(loadingCard("Loading catalog options…"));
      try {
        const filters = {
          q: picker.query,
          university: picker.options.university,
          course: picker.options.course,
        };
        const payload = await this.api.catalog(picker.requestKind, filters, picker.controller.signal);
        if (!this.state.picker || this.state.picker !== picker || picker.generation !== generation) return;
        picker.items = arrayOf(payload.items || payload.options || payload.results).map(unwrapItem).filter(Boolean);
        if (picker.mode === "categories") this.renderProgramCategories(picker.items);
        else if (picker.mode === "compare") this.renderCompareOptions(picker.items);
        else this.renderPickerItems(picker.items);
      } catch (error) {
        if (error && error.name === "AbortError") return;
        if (!this.state.picker || this.state.picker !== picker) return;
        console.warn("DegreeBaba guided picker failed", error);
        this.dom.sheetList.replaceChildren(errorCard(
          cleanText(error.message),
          () => this.loadPicker(),
          () => {
            this.closePicker();
            this.openLead();
          },
        ));
      }
    }

    renderProgramCategories(items) {
      this.dom.sheetList.replaceChildren();
      const heading = element("p", "prototype-picker__hint", "Choose a program category");
      const list = element("div", "prototype-picker-list");
      PROGRAM_CATEGORIES.forEach((category) => {
        const option = items.find((item) => {
          const haystack = `${entityName(item)} ${cleanText(item.category)} ${cleanText(item.id)}`.toLowerCase();
          return haystack.includes(category.toLowerCase());
        });
        const row = makeButton("", "prototype-picker-row", () => {
          this.showProgramCategory(category);
        });
        const icon = element("span", "prototype-picker-row__monogram", initials(category));
        const copy = element("span", "prototype-picker-row__copy");
        copy.append(
          element("strong", "prototype-picker-row__title", category),
          element(
            "span",
            "prototype-picker-row__meta",
            option && (option.provider_count === 0 || option.provider_count)
              ? `${option.provider_count} provider${Number(option.provider_count) === 1 ? "" : "s"}`
              : "View catalog options",
          ),
        );
        row.append(icon, copy, element("span", "prototype-picker-row__arrow", "›"));
        list.appendChild(row);
      });
      this.dom.sheetList.append(heading, list);
    }

    pickerMeta(item, kind) {
      if (kind === "universities") {
        const parts = [];
        const naac = firstText(item.naac_grade, item.naac);
        const count = item.program_count;
        if (naac) parts.push(`NAAC ${naac}`);
        if (count === 0 || count) parts.push(`${count} program${Number(count) === 1 ? "" : "s"}`);
        return parts.join(" • ") || "University";
      }
      if (kind === "programs" || kind === "courses") {
        return [firstText(item.university_name), firstText(item.fee), firstText(item.duration)].filter(Boolean).join(" • ") || "Program";
      }
      return [
        firstText(item.university_name),
        displayConcept(firstText(item.category)),
        firstText(item.duration),
      ].filter(Boolean).join(" • ") || "Specialization";
    }

    renderPickerItems(items) {
      this.dom.sheetList.replaceChildren();
      if (!items.length) {
        const empty = element("section", "prototype-state prototype-state--empty");
        empty.append(
          element("h3", "prototype-card__title", "No catalog matches"),
          element("p", "prototype-copy", "Try another search, browse a different level, or ask a counsellor for help."),
          makeButton("Talk To Counsellor", "prototype-button prototype-button--primary", () => {
            this.closePicker();
            this.openLead();
          }),
        );
        this.dom.sheetList.appendChild(empty);
        return;
      }
      const list = element("div", "prototype-picker-list");
      items.forEach((item) => {
        const displayAsUniversity = this.state.picker?.options?.display === "university";
        const label = displayAsUniversity
          ? firstText(item.university_name, entityName(item))
          : entityName(item);
        const meta = displayAsUniversity
          ? [entityName(item), firstText(item.fee), firstText(item.duration)].filter(Boolean).join(" • ")
          : this.pickerMeta(item, this.state.picker?.kind);
        const row = makeButton("", "prototype-picker-row", () => this.selectEntity(item, label));
        const monogram = element("span", "prototype-picker-row__monogram", initials(label));
        const copy = element("span", "prototype-picker-row__copy");
        copy.append(
          element("strong", "prototype-picker-row__title", label),
          element("span", "prototype-picker-row__meta", meta),
        );
        row.append(monogram, copy, element("span", "prototype-picker-row__arrow", "›"));
        list.appendChild(row);
      });
      this.dom.sheetList.appendChild(list);
    }

    showProgramCategory(category) {
      if (this.state.guidedBusy) return undefined;
      this.closePicker();
      this.appendUserChoice(category);
      this.dom.guidePanel.hidden = true;
      return this.runGuidedResponse(() => {
        this.appendGuidePrompt(`Which university would you like to explore for ${category}?`);
        this.openPicker("courses", {
          course: slugify(category),
          display: "university",
          title: `Choose a University for ${category}`,
        });
      });
    }

    compareKind() {
      const pageType = this.state.logicalContext.page_type;
      if (pageType === "course") return "courses";
      if (pageType === "specialization") return "specializations";
      return "universities";
    }

    startCompareWithChoice(startingEntity) {
      if (this.state.guidedBusy) return undefined;
      this.state.viewedActions.add("compare");
      this.appendUserChoice("Compare");
      this.dom.guidePanel.hidden = true;
      return this.runGuidedResponse(() => this.startCompare(startingEntity));
    }

    startCompare(startingEntity) {
      const current = unwrapItem(startingEntity || this.state.bundle?.entity);
      this.state.compareSelections = current && entityId(current) ? [current] : [];
      const kind = this.compareKind();
      const currentName = current ? entityName(current) : "";
      const query = current
        ? kind === "courses"
          ? firstText(current.category)
          : kind === "specializations"
            ? firstText(current.specialization, current.name)
            : ""
        : "";
      this.openPicker(kind, {
        mode: "compare",
        course: kind === "courses" ? slugify(query) : undefined,
        university: kind === "specializations" ? "" : undefined,
        currentName,
      });
      if (query && kind !== "courses") {
        this.state.picker.query = query;
        this.dom.sheetSearch.value = query;
        this.loadPicker();
      }
      this.dom.sheetTitle.textContent = "Choose 2–3 to Compare";
      this.dom.sheetSearch.hidden = false;
    }

    renderCompareOptions(items) {
      const picker = this.state.picker;
      if (!picker) return;
      const byId = new Map();
      [...this.state.compareSelections, ...items].forEach((item) => {
        const id = entityId(item);
        if (id) byId.set(id, item);
      });
      const candidates = [...byId.values()];
      this.dom.sheetList.replaceChildren();
      if (!candidates.length) {
        this.dom.sheetList.appendChild(element("p", "prototype-empty", "No comparable catalog entities are available."));
        return;
      }
      const hint = element(
        "p",
        "prototype-picker__hint",
        `${this.state.compareSelections.length} selected • choose at least 2`,
      );
      const list = element("div", "prototype-picker-list prototype-picker-list--compare");
      candidates.forEach((item) => {
        const id = entityId(item);
        const selected = this.state.compareSelections.some((entry) => entityId(entry) === id);
        const row = makeButton("", `prototype-picker-row${selected ? " prototype-picker-row--selected" : ""}`, () => {
          const index = this.state.compareSelections.findIndex((entry) => entityId(entry) === id);
          if (index >= 0) this.state.compareSelections.splice(index, 1);
          else if (this.state.compareSelections.length < 3) this.state.compareSelections.push(item);
          this.renderCompareOptions(items);
        });
        row.setAttribute("aria-pressed", String(selected));
        const check = element("span", "prototype-picker-row__check", selected ? "✓" : "");
        const copy = element("span", "prototype-picker-row__copy");
        copy.append(
          element("strong", "prototype-picker-row__title", entityName(item)),
          element("span", "prototype-picker-row__meta", this.pickerMeta(item, picker.kind)),
        );
        row.append(check, copy);
        list.appendChild(row);
      });
      const compare = makeButton(
        `Compare Selected (${this.state.compareSelections.length})`,
        "prototype-button prototype-button--primary prototype-picker__submit",
        () => this.submitComparison(),
      );
      compare.disabled = this.state.compareSelections.length < 2;
      this.dom.sheetList.append(hint, list, compare);
    }

    async submitComparison() {
      const ids = this.state.compareSelections.map(entityId).filter(Boolean).slice(0, 3);
      if (ids.length < 2 || this.state.guidedBusy) return;
      this.closePicker();
      this.appendUserChoice("Compare Selected");
      this.state.guidedBusy = true;
      const thinking = thinkingIndicator();
      const minimumDelay = wait(GUIDED_THINKING_MS);
      appendFeed(this.dom, thinking);
      try {
        const payload = await this.api.compare(ids);
        await minimumDelay;
        const comparison = renderComparison(this, payload);
        thinking.remove();
        this.presentPrimaryCard(comparison);
      } catch (error) {
        await minimumDelay;
        thinking.replaceWith(errorCard(cleanText(error.message), () => this.startCompare(), () => this.openLead()));
      } finally {
        thinking.remove();
        this.state.guidedBusy = false;
      }
    }

    openLead() {
      this.dom.leadSheet.hidden = false;
      this.dom.leadSheet.setAttribute("aria-hidden", "false");
      document.body.classList.add("prototype-sheet-open");
      const phone = this.dom.leadPhone;
      phone.removeAttribute("aria-invalid");
      const status = this.dom.leadForm.querySelector("[data-lead-status]") || element("p", "prototype-lead-status");
      status.dataset.leadStatus = "true";
      if (!status.parentNode) this.dom.leadForm.appendChild(status);
      status.textContent = "Only your phone number is submitted in this prototype.";
      window.setTimeout(() => phone.focus(), 0);
    }

    closeLead() {
      this.dom.leadSheet.hidden = true;
      this.dom.leadSheet.setAttribute("aria-hidden", "true");
      document.body.classList.remove("prototype-sheet-open");
    }

    async submitLead(event) {
      event.preventDefault();
      const phone = this.dom.leadPhone.value.replace(/\D/g, "").replace(/^91(?=\d{10}$)/, "");
      const status = this.dom.leadForm.querySelector("[data-lead-status]") || element("p", "prototype-lead-status");
      status.dataset.leadStatus = "true";
      if (!status.parentNode) this.dom.leadForm.appendChild(status);
      if (!/^[6-9]\d{9}$/.test(phone)) {
        this.dom.leadPhone.setAttribute("aria-invalid", "true");
        status.textContent = "Enter a valid 10-digit Indian mobile number.";
        return;
      }
      this.dom.leadPhone.removeAttribute("aria-invalid");
      const submit = this.dom.leadForm.querySelector('[type="submit"]');
      if (submit) submit.disabled = true;
      status.textContent = "Saving your request…";
      try {
        const response = await this.api.lead(this.state.sessionId, phone);
        if (response.session_id) this.state.sessionId = response.session_id;
        status.textContent = response.message || "Thanks — a DegreeBaba counsellor can contact you shortly.";
        const confirmation = element("section", "prototype-card prototype-lead-confirmation");
        confirmation.append(
          makeSectionEyebrow("Request received"),
          element("h3", "prototype-card__title", "A counsellor can contact you shortly"),
          element("p", "prototype-copy", status.textContent),
          renderContinuation(this, [["Keep Exploring", this.state.logicalContext.page_type === "homepage" ? "browse_universities" : "compare"]]),
        );
        this.presentPrimaryCard(confirmation);
        window.setTimeout(() => this.closeLead(), 700);
      } catch (error) {
        status.textContent = cleanText(error.message) || "We couldn’t save your request. Please try again.";
      } finally {
        if (submit) submit.disabled = false;
      }
    }
  }

  function renderChatQuickActions(dom, actions) {
    const values = arrayOf(actions).filter((action) => action && typeof action === "object");
    if (!values.length) return null;
    const row = element("div", "prototype-chat-actions");
    values.forEach((action) => {
      const label = firstText(action.label, action.title, action.message);
      const message = firstText(action.message, action.label);
      if (!label || !message) return;
      row.appendChild(makeButton(label, "prototype-chip", () => {
        dom.chatInput.value = message;
        dom.chatInput.focus();
        dom.chatInput.setSelectionRange(message.length, message.length);
        statusMessage(dom, "Suggestion added to the chat input. Press send to ask it.");
      }));
    });
    return row.children.length ? row : null;
  }

  function renderChatComponent(navigator, dom, component) {
    if (!component || typeof component !== "object") return null;
    if (component.type === "university_card" || component.type === "program_card") {
      return renderEntityCard(navigator, component);
    }
    if (component.type === "comparison_card") return renderComparison(navigator, component);
    if (component.type === "card_list") {
      const group = element("section", "prototype-chat-component prototype-chat-card-list");
      if (component.title) group.appendChild(element("h3", "prototype-card__title", component.title));
      arrayOf(component.items).forEach((item) => group.appendChild(renderEntityCard(navigator, item)));
      return group;
    }
    if (component.type === "lead_cta") {
      return makeButton(
        firstText(component.label, "Talk To Counsellor"),
        "prototype-button prototype-button--primary",
        () => navigator.openLead(),
      );
    }
    if (component.type === "quick_actions") return renderChatQuickActions(dom, component.actions);
    return null;
  }

  function renderChatPayload(navigator, dom, payload) {
    const wrapper = element("article", "prototype-message prototype-message--bot");
    const bubble = element("div", "prototype-message__bubble");
    appendParagraphs(
      bubble,
      firstText(payload?.message, payload?.text, "I’m not sure what to show yet. Try another question."),
    );
    wrapper.appendChild(bubble);
    const components = element("div", "prototype-chat-components");
    const payloadComponents = arrayOf(payload?.components);
    payloadComponents.forEach((component) => {
      const rendered = renderChatComponent(navigator, dom, component);
      if (rendered) components.appendChild(rendered);
    });
    const hasQuickActionComponent = payloadComponents.some(
      (component) => component?.type === "quick_actions",
    );
    const topLevelActions = hasQuickActionComponent
      ? null
      : renderChatQuickActions(
        dom,
        payload?.quick_actions
          || payload?.suggested_chips?.map((label) => ({ label, message: label })),
      );
    if (topLevelActions) components.appendChild(topLevelActions);
    if (payload?.cta) {
      components.appendChild(makeButton(
        firstText(payload.cta.label, "Talk To Counsellor"),
        "prototype-button prototype-button--primary",
        () => navigator.openLead(),
      ));
    }
    if (components.children.length) wrapper.appendChild(components);
    appendFeed(dom, wrapper);
  }

  function requiredDom() {
    const dom = {
      scenarioForm: byId("scenario-form"),
      contextJson: byId("context-json"),
      contextBar: byId("context-bar"),
      clearContext: byId("clear-context"),
      feed: byId("feed"),
      guidePanel: byId("guide-panel"),
      guideHeading: byId("guide-heading"),
      guideActions: byId("guide-actions"),
      moreActions: byId("more-actions"),
      sheetBackdrop: byId("sheet-backdrop"),
      pickerSheet: byId("picker-sheet"),
      sheetTitle: byId("sheet-title"),
      sheetSearch: byId("sheet-search"),
      sheetList: byId("sheet-list"),
      sheetClose: byId("sheet-close"),
      chatForm: byId("chat-form"),
      chatInput: byId("chat-input"),
      chatSubmit: byId("chat-submit"),
      leadSheet: byId("lead-sheet"),
      leadForm: byId("lead-form"),
      leadClose: byId("lead-close"),
      leadPhone: byId("lead-phone"),
      statusRegion: byId("status-region"),
    };
    const missing = Object.entries(dom).filter(([, value]) => !value).map(([key]) => key);
    if (missing.length) throw new Error(`Guided prototype is missing required DOM nodes: ${missing.join(", ")}`);
    return dom;
  }

  function install(dom, state, navigator, chatTransport) {
    dom.scenarioForm.addEventListener("change", (event) => {
      const input = event.target.closest('input[name="scenario"]');
      if (input && input.checked) navigator.setScenario(input.value);
    });
    dom.clearContext.addEventListener("click", () => navigator.clearContext());
    dom.sheetClose.addEventListener("click", () => navigator.closePicker());
    dom.sheetBackdrop.addEventListener("click", () => navigator.closePicker());
    dom.sheetSearch.addEventListener("input", () => navigator.schedulePickerSearch());
    dom.leadClose.addEventListener("click", () => navigator.closeLead());
    dom.leadForm.addEventListener("submit", (event) => navigator.submitLead(event));
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (!dom.pickerSheet.hidden) navigator.closePicker();
      else if (!dom.leadSheet.hidden) navigator.closeLead();
    });

    dom.chatForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const message = dom.chatInput.value.trim();
      if (!message || state.chatBusy) return;
      state.chatBusy = true;
      dom.chatSubmit.disabled = true;
      dom.chatInput.value = "";
      appendFeed(dom, feedMessage("user", message));
      const typing = loadingCard("DegreeBaba is checking your question…");
      typing.classList.add("prototype-chat-typing");
      appendFeed(dom, typing);
      let finalPayload = null;
      let bufferedText = "";
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 15000);
      try {
        await chatTransport.send(message, controller.signal, (eventName, payload) => {
          if (payload.session_id) state.sessionId = payload.session_id;
          if (eventName === "token" && payload.token) bufferedText += payload.token;
          if (["response", "final", "replace"].includes(eventName)) finalPayload = payload;
        });
        typing.remove();
        renderChatPayload(navigator, dom, finalPayload || { message: bufferedText });
        statusMessage(dom, "Chat response received");
      } catch (error) {
        typing.remove();
        const copy = error && error.name === "AbortError"
          ? "The advisor took too long to respond. Please try your question again."
          : "The advisor is unavailable right now. Your guided catalog explorer still works.";
        const failure = feedMessage("bot", copy);
        const retry = renderChatQuickActions(dom, [{ label: "Try Again", message }]);
        if (retry) failure.appendChild(retry);
        appendFeed(dom, failure);
        statusMessage(dom, "Chat request failed");
        console.warn("DegreeBaba prototype chat request failed", error);
      } finally {
        window.clearTimeout(timeout);
        state.chatBusy = false;
        dom.chatSubmit.disabled = false;
        dom.chatInput.focus();
      }
    });
  }

  function bootstrap() {
    if (window.DegreeBabaGuidedPrototype?.initialized) return;
    let dom;
    try {
      dom = requiredDom();
    } catch (error) {
      console.error(error);
      return;
    }
    const state = createState();
    const api = new GuideApi(state);
    const navigator = new GuidedNavigator(state, dom, api);
    const chatTransport = new ChatTransport(state);
    install(dom, state, navigator, chatTransport);

    const selectedScenario = dom.scenarioForm.querySelector('input[name="scenario"]:checked');
    const ready = navigator.setScenario(selectedScenario?.value || "homepage");
    window.DegreeBabaGuidedPrototype = Object.freeze({
      initialized: true,
      ready,
      getState() {
        return cloneForDebug({
          scenario: state.scenario,
          logicalContext: state.logicalContext,
          resolvedContext: state.resolvedContext,
          entityReference: state.entityReference,
          sessionId: state.sessionId,
          chatBusy: state.chatBusy,
          guidedBusy: state.guidedBusy,
          viewedActions: [...state.viewedActions],
          picker: state.picker ? { kind: state.picker.kind, mode: state.picker.mode, query: state.picker.query } : null,
        });
      },
      getRequestLog() {
        return cloneForDebug(state.requestLog);
      },
      setScenario(name) {
        return navigator.setScenario(name);
      },
      clearContext() {
        return navigator.clearContext();
      },
      openPicker(kind) {
        const allowed = ["universities", "programs", "specializations"];
        if (allowed.includes(kind)) navigator.openPicker(kind, kind === "programs" ? { mode: "categories" } : {});
      },
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
  else bootstrap();
}());
