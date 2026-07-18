  function findFact(component, needles) {
    const facts = component.highlights || component.facts || [];
    const match = facts.find((fact) => {
      const label = String(fact && fact.label || "").toLowerCase();
      return needles.some((needle) => label.includes(needle));
    });
    return match ? String(match.value || "") : "";
  }

  function trustLine(values) {
    const text = values.filter(Boolean).join("  ·  ");
    return text ? element("div", "db-widget__card-trust db-card-trust", text) : null;
  }

  const TONE_COLORS = ["#0E1F3D", "#7A1E1E", "#1E4620", "#5A3B00", "#3A2560", "#0B3B4A"];
  function toneColor(value) {
    return TONE_COLORS[Number(pickerTone(value))] || TONE_COLORS[0];
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

  function cardPills(values) {
    const row = element("div", "db-widget__pills-row db-pills-row");
    values.filter((value) => value !== null && value !== undefined && String(value).trim()).slice(0, 3)
      .forEach((value) => row.appendChild(element("div", "db-widget__pill db-pill", String(value))));
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
    const actions = element("div", "db-widget__card-actions db-card-actions");
    const details = createButton(detailsLabel, "db-widget__card-button db-widget__card-action--primary db-btn-primary", () => {
      if (hasDetails(component)) openDetails(component);
      else if (component.guided === true) executeGuidedAction("fees", "View fees");
      else sendMessage(`Tell me about ${cardReference(component).label}`);
    });
    const compare = createButton("+ Compare", "db-widget__card-button db-widget__card-action db-btn-compare", () => {
      beginGuidedComparison(component);
    });
    actions.append(details, compare);
    return actions;
  }

  function renderUniversityCard(component) {
    const card = element("div", "db-widget__card db-widget__university-card db-card");
    const header = element("div", "db-widget__card-header db-card-head");
    const mark = element("div", "db-widget__card-mark db-card-mono", initials(component.name));
    mark.style.background = toneColor(component.name);
    const title = element("div", "db-widget__card-heading");
    title.appendChild(element("div", "db-widget__card-title db-card-title", component.name));
    const ugc = component.ugc_status || findFact(component, ["ugc", "approval"]);
    const naacRaw = component.naac_grade || findFact(component, ["naac"]);
    const naac = naacRaw && !String(naacRaw).toLowerCase().includes("naac") ? `NAAC ${naacRaw}` : naacRaw;
    const trust = trustLine([ugc, naac]);
    if (trust) title.appendChild(trust);
    header.append(mark, title);
    card.appendChild(header);

    const programsCount = publishedCount(component, "program_count", "num_programs", "programs");
    const rating = component.average_rating
      ? `★ ${component.average_rating}${component.review_count ? ` (${component.review_count})` : ""}`
      : "";
    const pills = cardPills([
      compactFee(component.starting_fee || findFact(component, ["starting fee", "fee"]), "From "),
      programsCount || programsCount === 0 ? `${programsCount} Programs` : "",
      rating || component.learning_mode || component.mode || findFact(component, ["learning mode", "mode"]),
    ]);
    if (pills.childElementCount) card.appendChild(pills);
    card.appendChild(cardActions(component, "View details"));
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
    const card = element("div", "db-widget__card db-widget__program-card db-card");
    const isSpecialization = component.kind === "specialization" || component.type === "specialization_card";
    const provider = component.university_name || "";
    const category = String(component.category || "").trim().toUpperCase();
    const programLabel = category ? `Online ${category}` : "";
    const baseHeading = isSpecialization
      ? [provider, programLabel].filter(Boolean).join(" ") + `${provider || programLabel ? " · " : ""}${component.name}`
      : provider && !String(component.name).toLowerCase().includes(provider.toLowerCase())
        ? `${provider} ${component.name}`
        : component.name;
    const header = element("div", "db-widget__card-header db-card-head");
    const mark = element("div", "db-widget__card-mark db-card-mono", initials(provider || baseHeading));
    mark.style.background = toneColor(provider || baseHeading);
    const title = element("div", "db-widget__card-heading");
    title.appendChild(element("div", "db-widget__card-title db-card-title", baseHeading));

    const ugc = component.ugc_status || findFact(component, ["ugc", "approval"]);
    const naacRaw = component.naac_grade || findFact(component, ["naac"]);
    const naac = naacRaw && !String(naacRaw).toLowerCase().includes("naac") ? `NAAC ${naacRaw}` : naacRaw;
    const rating = component.average_rating
      ? `★ ${component.average_rating}${component.review_count ? ` (${component.review_count})` : ""}`
      : "";
    const trust = trustLine([ugc, naac, rating]);
    if (trust) title.appendChild(trust);
    header.append(mark, title);
    card.appendChild(header);

    const specializationCount = publishedCount(
      component, "specialization_count", "num_specializations", "specializations"
    );
    const pills = cardPills([
      compactFee(component.fee || component.total_fee),
      component.duration,
      isSpecialization
        ? component.mode
        : specializationCount || specializationCount === 0
          ? `${specializationCount} Specs`
          : component.mode,
    ]);
    if (pills.childElementCount) card.appendChild(pills);
    if (component.emi) card.appendChild(element("div", "db-widget__card-emi db-card-emi", displayCurrency(component.emi)));
    const career = firstCareer(component);
    if (career) card.appendChild(element("div", "db-widget__card-job db-card-job", `💼 ${displayCurrency(career)}`));
    card.appendChild(cardActions(component, "View details"));
    recordCardShown(component, isSpecialization ? "specialization" : "course");
    return card;
  }

  function renderComparisonCard(component) {
    const card = element("div", "db-widget__card db-widget__comparison-card db-compare");
    card.setAttribute("aria-label", component.title || "Published comparison");
    const items = (component.items || []).slice(0, 2);
    const head = element("div", "db-widget__comparison-head db-compare-head");
    head.appendChild(element("div", "db-widget__comparison-head-empty db-compare-head-empty"));
    items.forEach((item) => {
      head.appendChild(element(
        "div",
        "db-widget__comparison-head-cell db-compare-head-cell",
        item.subtitle ? `${item.subtitle} — ${item.name}` : item.name,
      ));
    });
    card.appendChild(head);

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
      const row = element("div", "db-widget__comparison-row db-compare-row");
      row.appendChild(element("span", "db-widget__comparison-label db-compare-key", labels.get(key)));
      items.forEach((item) => {
        const fact = (item.facts || []).find((candidate) => String(candidate.label || "").trim().toLowerCase() === key);
        row.appendChild(element(
          "div",
          "db-widget__comparison-value db-compare-val",
          fact && fact.value ? String(fact.value) : "Not published",
        ));
      });
      rows.appendChild(row);
    });
    card.appendChild(rows);
    if (component.verdict) {
      const verdict = element("div", "db-widget__comparison-verdict db-compare-verdict");
      verdict.appendChild(element("span", "db-verdict-label", "Verdict "));
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
    const available = (actions || []).map(normalizedAction).filter((action) => action && action.label);
    const rendered = available
      .map((action) => actionButton(action))
      .filter(Boolean);
    return responsiveActionGrid(available, rendered, { onVisible: emitChipShown });
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
      const messageBounds = state.messages.getBoundingClientRect();
      const rowBounds = row.getBoundingClientRect();
      const rowTopInStream = rowBounds.top - messageBounds.top + state.messages.scrollTop;
      const top = Math.max(0, rowTopInStream - 8);
      if (typeof state.messages.scrollTo === "function") {
        state.messages.scrollTo({ top, behavior: "smooth" });
      } else {
        state.messages.scrollTop = top;
      }
    });
  }

  function createMessage(role, text) {
    const row = element("div", `db-widget__message-row db-widget__message-row--${role} db-msg`);
    const content = element("div", "db-widget__message-content");
    const bubble = element(
      "div",
      `db-widget__bubble db-widget__bubble--${role} db-bubble-${role}`,
    );
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
    const scholarshipReveal = toolFlow
      && String(toolFlow.tool) === "scholarship"
      && String(toolFlow.step) === "reveal";
    if (scholarshipReveal) {
      const cardTypes = ["university_card", "program_card", "course_card", "specialization_card", "card_list", "finder_results"];
      const revealComponents = components.filter((item) => cardTypes.includes(item.type));
      components = components.filter((item) => !cardTypes.includes(item.type) && item.type !== "lead_cta");
      openEndScreen("scholarship", toolFlow, revealComponents);
    }
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

  function openingMessage(type, bundle = null) {
    const context = bundle && bundle.context;
    const label = context && (context.label || contextValues(context).join(" • "));
    const messages = {
      homepage: "Explore universities and online programs. Where would you like to start?",
      pillar: label
        ? `Explore ${label} programs across universities. What would you like to compare first?`
        : "Explore universities, fees, specializations, and eligibility for this discipline.",
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
    const available = (actions || []).map(normalizedAction).filter((action) => (
      action && action.label && (
        action.repeat === true ||
        !state.viewedActions.has(action.chip_id || action.action || action.guide)
      )
    ));
    let row;
    const buttons = available.map((action) => {
      const guideAction = guideActionFor(action) || action.action;
      const className = guideAction === "lead"
        ? "db-widget__action db-widget__action--lead db-chip"
        : "db-widget__action db-chip";
      return createButton(action.label, className, () => {
        row.remove();
        if (typeof action.onSelect === "function") {
          recordChipTap(action);
          action.onSelect();
        } else if (action.chip_id || action.chip_handler || action.guide) {
          handleAction(action);
        } else {
          executeGuidedAction(action.action, action.label, action.options || {});
        }
      });
    });
    row = responsiveActionGrid(available, buttons, { onVisible: emitChipShown });
    row.dataset.guideActions = "true";
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
    const isRichCard = card.classList.contains("db-widget__rich-card-stack");
    const isReferenceCard = card.matches(
      ".db-widget__program-card, .db-widget__university-card, .db-widget__comparison-card",
    );
    const view = createMessage("bot", isRichCard ? "" : message);
    if (isRichCard) view.bubble.remove();
    const stack = element("div", "db-widget__component-stack");
    if (isRichCard || isReferenceCard) {
      card.dataset.guidePrimary = "true";
      stack.appendChild(card);
    } else {
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
    }
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

  const RICH_CARD_ICONS = Object.freeze({
    checkWhite: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5"></path></svg>',
    checkGreen: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#3B6D11" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5"></path></svg>',
    chevron: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"></path></svg>',
    currency: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#E84010" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>',
    dash: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" stroke-width="3" stroke-linecap="round" aria-hidden="true"><path d="M5 12h14"></path></svg>',
    checkWhite21: '<svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5"></path></svg>',
    phone: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.9.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>',
    clock: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#9A6412" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M12 7v5l3 2"></path></svg>',
    endClose: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6L6 18M6 6l12 12"></path></svg>',
  });

  function richCardIcon(className, svg, tag = "div") {
    const icon = element(tag, className);
    icon.innerHTML = svg;
    return icon;
  }

  function publishedValue(value, emptyCopy = "Not published") {
    const text = String(value || "").trim();
    return text || emptyCopy;
  }

  function displayCurrency(value, emptyCopy = "Not published") {
    return publishedValue(value, emptyCopy).replace(/\bINR\s*/gi, "₹");
  }

  function displayFeeAmount(value, { stripSemester = false } = {}) {
    let rendered = displayCurrency(value).replace(/(\d[\d,]*)\.0(?=\s|$)/g, "$1");
    if (stripSemester) rendered = rendered.replace(/\s+per\s+semester\s*$/i, "");
    return rendered;
  }

  function renderFeesCard(data, entity) {
    const card = element("div", "db-widget__fees db-fees");
    const hero = element("div", "db-widget__fees-hero db-fees-hero");
    const total = element("div");
    total.append(
      element("div", "db-widget__fees-total-label db-fees-total-label", "Total programme fee"),
      element("div", "db-widget__fees-total-value db-fees-total-value", displayFeeAmount(data.total_fee || entity.fee)),
    );
    const semester = element("div");
    semester.append(
      element("div", "db-widget__fees-sem-label db-fees-sem-label", "Per semester"),
      element("div", "db-widget__fees-sem-value db-fees-sem-value", displayFeeAmount(data.semester_fee, { stripSemester: true })),
    );
    hero.append(total, semester);
    card.appendChild(hero);
    const plans = Array.isArray(data.plans) ? data.plans.filter(Boolean) : [];
    if (plans.length) {
      const planList = element("div", "db-widget__fees-plans db-fees-plans");
      plans.forEach((plan) => {
        const row = element("div", "db-widget__fees-plan-row db-fees-plan-row");
        const copy = element("div");
        copy.appendChild(element(
          "div",
          "db-widget__fees-plan-label db-fees-plan-label",
          publishedValue(plan.name || plan.label || plan.title, "Payment plan"),
        ));
        const planNote = plan.note || (
          plan.total && plan.total !== plan.amount ? `Total ${displayCurrency(plan.total)}` : ""
        );
        if (planNote) {
          copy.appendChild(element("div", "db-widget__fees-plan-note db-fees-plan-note", planNote));
        }
        row.append(
          copy,
          element("div", "db-widget__fees-plan-value db-fees-plan-value", displayFeeAmount(plan.amount || plan.value || plan.total)),
        );
        planList.appendChild(row);
      });
      card.appendChild(planList);
    } else {
      card.appendChild(element(
        "p",
        "db-widget__rich-card-empty",
        "Payment-plan details haven't been published yet.",
      ));
    }
    const emi = String(data.emi || entity.emi || "").trim();
    if (emi) {
      const note = element("div", "db-widget__fees-emi db-fees-emi");
      note.append(richCardIcon("", RICH_CARD_ICONS.currency), element("span", "", displayFeeAmount(emi)));
      card.appendChild(note);
    }
    return card;
  }

  function renderEligibilityCard(data, entity) {
    const card = element("div", "db-widget__elig db-elig");
    const summary = String(data.summary || entity.eligibility || "").trim();
    const hero = element("div", "db-widget__elig-hero db-elig-hero");
    hero.append(
      richCardIcon("db-widget__elig-check db-elig-check", RICH_CARD_ICONS.checkWhite),
      (() => {
        const copy = element("div");
        copy.append(
          element("div", "db-widget__elig-verdict db-elig-verdict", "Published requirements"),
          element("div", "db-widget__elig-sub db-elig-sub", summary || "Review the criteria below"),
        );
        return copy;
      })(),
    );
    card.appendChild(hero);
    const requirements = Array.isArray(data.requirements) ? data.requirements.filter(Boolean) : [];
    if (requirements.length) {
      const list = element("div", "db-widget__elig-list db-elig-list");
      requirements.forEach((requirement) => {
        const row = element("div", "db-widget__elig-row db-elig-row");
        const copy = element("div");
        copy.appendChild(element("div", "db-widget__elig-req-title db-elig-req-title", typeof requirement === "object"
          ? publishedValue(requirement.title || requirement.label || requirement.text)
          : requirement));
        if (requirement && typeof requirement === "object" && requirement.note) {
          copy.appendChild(element("div", "db-widget__elig-req-note db-elig-req-note", requirement.note));
        }
        const isOptional = requirement && typeof requirement === "object" &&
          (requirement.optional === true || requirement.ok === false);
        row.append(
          isOptional
            ? richCardIcon("db-widget__elig-icon db-widget__elig-icon--opt db-elig-icon opt", RICH_CARD_ICONS.dash)
            : richCardIcon("db-widget__elig-icon db-widget__elig-icon--ok db-elig-icon ok", RICH_CARD_ICONS.checkGreen),
          copy,
        );
        list.appendChild(row);
      });
      card.appendChild(list);
    } else if (!summary) {
      card.appendChild(element(
        "p",
        "db-widget__rich-card-empty",
        "A qualification checklist hasn't been published yet.",
      ));
    }
    return card;
  }

  function renderCareerCard(data, entity) {
    const card = element("div", "db-widget__career db-career");
    const averageSalary = String(data.average_salary || entity.average_salary || "").trim();
    if (averageSalary) {
      const hero = element("div", "db-widget__career-hero db-career-hero");
      hero.append(
        element("div", "db-widget__career-label db-career-label", "Average starting salary"),
        element("div", "db-widget__career-avg db-career-avg", averageSalary),
      );
      card.appendChild(hero);
    }
    const roles = Array.isArray(data.job_roles) ? data.job_roles.filter(Boolean) : [];
    const rolesSection = element("div", "db-widget__career-roles db-career-roles");
    rolesSection.appendChild(element("div", "db-widget__career-roles-label db-career-roles-label", "Roles you can target"));
    if (roles.length) {
      roles.forEach((role) => {
        const row = element("div", "db-widget__career-role-row db-career-role-row");
        const roleTitle = typeof role === "object" ? role.title || role.name || role.label : role;
        const salary = typeof role === "object" ? role.salary || role.value : "";
        row.appendChild(element("div", "db-widget__career-role-title db-career-role-title", publishedValue(roleTitle)));
        if (salary) row.appendChild(element("div", "db-widget__career-role-salary db-career-role-salary", salary));
        rolesSection.appendChild(row);
      });
    } else {
      rolesSection.appendChild(element("p", "db-widget__rich-card-empty", "Job roles haven't been published yet."));
    }
    card.appendChild(rolesSection);
    const recruiters = Array.isArray(data.recruiters) ? data.recruiters.filter(Boolean) : [];
    if (recruiters.length) {
      const recruiterSection = element("div", "db-widget__career-recruiters db-career-recruiters");
      recruiterSection.appendChild(element("div", "db-widget__career-recruiters-label db-career-recruiters-label", "Top recruiters"));
      const tags = element("div", "db-widget__recruiter-tags db-recruiter-tags");
      recruiters.forEach((recruiter) => tags.appendChild(element(
        "span",
        "db-widget__recruiter-tag db-recruiter-tag",
        typeof recruiter === "object" ? publishedValue(recruiter.name || recruiter.label) : recruiter,
      )));
      recruiterSection.appendChild(tags);
      card.appendChild(recruiterSection);
    }
    return card;
  }

  function reviewPercentage(value) {
    const match = String(value || "").trim().match(/^(\d+(?:\.\d+)?)%$/);
    if (!match) return 0;
    return Math.max(0, Math.min(100, Number(match[1])));
  }

  function renderReviewsCard(data) {
    const card = element("div", "db-widget__reviews db-reviews");
    const rating = String(data.rating || "").trim();
    const reviewCount = Number(data.review_count);
    const scopeLabel = String(data.scope_label || "").trim();
    if (scopeLabel) {
      card.appendChild(element("p", "db-widget__reviews-scope", scopeLabel));
    }
    const breakdown = Array.isArray(data.breakdown) ? data.breakdown.filter(Boolean) : [];
    if (rating || breakdown.length) {
      const summary = element("div", "db-widget__reviews-summary db-reviews-summary");
      const score = element("div");
      score.appendChild(element("div", "db-widget__rating-big db-rating-big", rating || "—"));
      const numericRating = Number.parseFloat(rating);
      if (Number.isFinite(numericRating)) {
        const filled = Math.max(0, Math.min(5, Math.floor(numericRating)));
        score.appendChild(element("div", "db-widget__rating-stars db-rating-stars", `${"★".repeat(filled)}${"☆".repeat(5 - filled)}`));
      }
      if (Number.isFinite(reviewCount) && reviewCount > 0) {
        score.appendChild(element(
          "div",
          "db-widget__rating-count db-rating-count",
          `${reviewCount} published review${reviewCount === 1 ? "" : "s"}`,
        ));
      }
      summary.appendChild(score);
      if (breakdown.length) {
        const bars = element("div", "db-widget__rating-bars db-rating-bars");
        breakdown.forEach((item) => {
          const row = element("div", "db-widget__bar-row db-bar-row");
          const label = typeof item === "object" ? item.label || item.name || "" : "";
          const value = typeof item === "object" ? item.value || item.score || "" : item;
          const track = element("div", "db-widget__bar-track db-bar-track");
          const fill = element("div", "db-widget__bar-fill db-bar-fill");
          fill.style.width = `${reviewPercentage(value)}%`;
          track.appendChild(fill);
          row.append(
            element("span", "db-widget__bar-label db-bar-label", label),
            track,
          );
          bars.appendChild(row);
        });
        summary.appendChild(bars);
      }
      card.appendChild(summary);
    }
    const testimonials = Array.isArray(data.testimonials) ? data.testimonials.filter(Boolean) : [];
    if (testimonials.length) {
      const quotes = element("div", "db-widget__reviews-quotes db-reviews-quotes");
      const preview = [];
      const representedPrograms = new Set();
      testimonials.forEach((testimonial) => {
        if (preview.length >= 3) return;
        const program = testimonial && typeof testimonial === "object"
          ? String(testimonial.reviewer_label || "").trim()
          : "";
        if (program && representedPrograms.has(program)) return;
        if (program) representedPrograms.add(program);
        preview.push(testimonial);
      });
      testimonials.forEach((testimonial) => {
        if (preview.length < 3 && !preview.includes(testimonial)) preview.push(testimonial);
      });
      preview.forEach((testimonial) => {
        const quote = element("blockquote", "db-widget__quote db-quote");
        const text = typeof testimonial === "object" ? testimonial.text || testimonial.description : testimonial;
        quote.appendChild(element("p", "db-widget__quote-text db-quote-text", publishedValue(text)));
        if (testimonial && typeof testimonial === "object") {
          const attribution = [
            testimonial.reviewer_name,
            testimonial.rating ? `${testimonial.rating}/5` : "",
            testimonial.theme,
            testimonial.reviewer_label,
          ].filter(Boolean).join(" · ");
          if (attribution) quote.appendChild(element("footer", "db-widget__quote-name db-quote-name", attribution));
        }
        quotes.appendChild(quote);
      });
      card.appendChild(quotes);
    }
    if (!rating && !breakdown.length && !testimonials.length) {
      card.appendChild(element("p", "db-widget__rich-card-empty", "Student reviews haven't been published yet."));
    }
    return card;
  }

  function renderSyllabusCard(data, entity) {
    const card = element("div", "db-widget__syllabus db-syllabus");
    const semesters = Array.isArray(data.semesters) ? data.semesters.filter(Boolean) : [];
    const head = element("div", "db-widget__syllabus-head db-syllabus-head");
    head.append(
      element("div", "db-widget__syllabus-title db-syllabus-title", `${entity.name || entity.category || "Program"} · Syllabus`),
      element("div", "db-widget__syllabus-meta db-syllabus-meta", semesters.length ? `${semesters.length} semesters` : "Published curriculum"),
    );
    card.appendChild(head);
    if (!semesters.length) {
      card.appendChild(element("p", "db-widget__rich-card-empty", "A semester-wise syllabus hasn't been published yet."));
      return card;
    }
    semesters.forEach((semester, index) => {
      const item = element("div", "db-widget__sem-item db-sem-item");
      const subItems = (semester.items || []).filter(Boolean);
      const semState = { open: index === 0 };
      const paint = () => {
        item.replaceChildren();
        const toggle = element("button", "db-widget__sem-toggle db-sem-toggle");
        toggle.type = "button";
        toggle.style.background = semState.open ? "#F7F8FA" : "#fff";
        const inner = element("div", "db-widget__sem-toggle-inner db-sem-toggle-inner");
        const num = element("div", "db-widget__sem-num db-sem-num", `S${index + 1}`);
        num.style.background = semState.open ? "#0E1F3D" : "#F3F4F6";
        num.style.color = semState.open ? "#fff" : "#0E1F3D";
        inner.append(num, element("div", "db-widget__sem-title db-sem-title", semester.title || `Semester ${index + 1}`));
        const chevron = richCardIcon("db-widget__sem-chevron db-sem-chevron", RICH_CARD_ICONS.chevron, "span");
        chevron.style.display = "inline-flex";
        chevron.style.transform = semState.open ? "rotate(180deg)" : "rotate(0deg)";
        toggle.append(inner, chevron);
        toggle.addEventListener("click", () => { semState.open = !semState.open; paint(); });
        item.appendChild(toggle);
        if (semState.open) {
          const subs = element("div", "db-widget__sem-subs db-sem-subs");
          subItems.forEach((subject) => {
            const sub = element("div", "db-widget__sem-sub db-sem-sub");
            sub.append(element("div", "db-widget__sub-dot db-sub-dot"), document.createTextNode(String(subject)));
            subs.appendChild(sub);
          });
          item.appendChild(subs);
        }
      };
      paint();
      card.appendChild(item);
    });
    return card;
  }

  function guidedInfoCard(kind) {
    const bundle = state.guideBundle || {};
    const info = bundle.info || {};
    const entity = bundle.entity || {};
    const data = kind === "rating" ? info.reviews || {} : info[kind] || {};
    const titles = {
      fees: ["Fees", "Fees & EMI"],
      eligibility: ["Admissions", "Eligibility"],
      career: ["Outcomes", "Career & Salary"],
      syllabus: ["Curriculum", "Syllabus"],
      reviews: ["Student voice", "Student Reviews"],
      rating: ["Student voice", "Average rating"],
      accreditations: ["Recognition", "Accreditations"],
      admissions: ["Next steps", "Admission process"],
      placement: ["Career support", "Placement support"],
      overview: ["University fit", "Why choose this university"],
    };
    const [eyebrow, title] = titles[kind] || ["Details", "Published information"];
    const richRenderers = {
      fees: () => renderFeesCard(data, entity),
      eligibility: () => renderEligibilityCard(data, entity),
      career: () => renderCareerCard(data, entity),
      syllabus: () => renderSyllabusCard(data, entity),
      reviews: () => renderReviewsCard(data),
      rating: () => renderReviewsCard({
        rating: data.rating,
        review_count: data.review_count,
        breakdown: [],
        testimonials: [],
      }),
    };
    if (richRenderers[kind]) {
      const stack = element("div", "db-widget__rich-card-stack");
      stack.appendChild(richRenderers[kind]());
      if (["fees", "eligibility"].includes(kind)) stack.appendChild(renderInlineLeadCard(kind));
      return { card: stack, title };
    }

    const card = element("article", `db-widget__card db-widget__info-card db-widget__info-card--${kind}`);
    card.append(element("span", "db-widget__eyebrow", eyebrow), element("h3", "", title));
    if (kind === "accreditations") {
      guideSection(card, "Published recognition", data.items, "Accreditation details haven't been published yet.");
      card.appendChild(element(
        "p",
        "db-widget__card-summary",
        "Always confirm the current recognition status for the exact university and program before enrolling.",
      ));
    } else if (kind === "admissions") {
      guideSection(
        card,
        "Published admission steps",
        data.steps,
        "Admission-process details haven't been published yet.",
      );
      if (data.fee_note) guideSection(card, "Fee note", data.fee_note, "");
    } else if (kind === "placement") {
      guideSection(
        card,
        "Published placement support",
        data.content,
        "Placement-support details haven't been published yet.",
      );
      if (data.supported) guideSection(card, "Support status", "Available", "");
      if (data.industry_projects) guideSection(card, "Industry projects", "Available", "");
    } else if (kind === "overview") {
      guideSection(
        card,
        "Why students consider it",
        data.why_choose || data.description,
        "A university overview hasn't been published yet.",
      );
    }
    return { card, title };
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
    if (!values.length) {
      state.contextLabel.textContent = "";
      state.contextCourse.textContent = "";
      state.contextCourse.hidden = true;
      state.contextCourse.parentElement.hidden = true;
      state.contextMeta.replaceChildren();
      state.contextMeta.hidden = true;
      state.contextChip.removeAttribute("aria-label");
      return;
    }
    const university = values[0] || "Current university";
    const academicPath = values.slice(1).join(" • ");
    const entity = state.guideBundle && state.guideBundle.entity || {};
    const metadata = [
      entity.ugc_status,
      entity.duration,
      entity.learning_mode || entity.mode,
    ].map((value) => String(value || "").trim()).filter(Boolean);
    state.contextLabel.textContent = university;
    state.contextCourse.textContent = academicPath ? `· ${academicPath}` : "";
    state.contextCourse.hidden = !academicPath;
    state.contextCourse.parentElement.hidden = !academicPath;
    state.contextMeta.replaceChildren();
    metadata.slice(0, 3).forEach((value) => {
      state.contextMeta.appendChild(element("span", "db-widget__context-meta-item", value));
    });
    state.contextMeta.hidden = !metadata.length;
    state.contextChip.setAttribute("aria-label", `Current context: ${values.join(", ")}`);
  }

  function renderStarterBank(type) {
    const opening = state.openingChips;
    const configured = opening
      ? [
          ...(Array.isArray(opening.top) ? opening.top : []),
          ...(Array.isArray(opening.more) ? opening.more : []),
        ]
      : safeFallbackActions();
    const available = configured.filter(
      (action) => !state.viewedActions.has(action.chip_id || action.guide || action.action),
    );

    state.starterGrid.replaceChildren();
    const buttons = available
      .map((action) => actionButton(action, "db-widget__starter-action"))
      .filter(Boolean);
    const grid = responsiveActionGrid(available, buttons, {
      className: "db-widget__starter-grid",
      onVisible(visible) {
        state.starterVisibleActions = visible;
        emitStarterImpressions();
      },
    });
    state.starterGrid.appendChild(grid);
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
      ? "db-widget__popular-item db-widget__popular-item--rich db-picker-row"
      : "db-widget__picker-row db-widget__picker-row--rich db-picker-row";
    const row = createButton("", rowClass, () => {
      closeOverlay();
      if (typeof options.onSelect === "function") {
        options.onSelect(item, displayName);
        return;
      }
      selectGuidedEntity(item, displayName);
    });
    const mono = element("div", "db-widget__picker-monogram db-picker-mono", initials(displayName));
    mono.style.background = toneColor(displayName);
    row.appendChild(mono);
    const copy = element("div", "db-widget__picker-copy");
    copy.appendChild(element("div", "db-widget__picker-name db-picker-row-name", displayName));
    const displayMeta = options.display === "university"
      ? [item.name, item.fee, item.duration].filter(Boolean).join(" · ")
      : item.meta;
    if (displayMeta) copy.appendChild(element("div", "db-widget__picker-meta db-picker-row-meta", displayMeta));
    row.appendChild(copy);
    return row;
  }

  function renderPickerResults(container, data, kind, query = "", options = {}) {
    container.replaceChildren();
    const normalizedQuery = query.trim().toLowerCase();
    const excludedIds = new Set((options.excludeIds || []).map((value) => String(value)));
    const filtered = data.items.filter((item) => {
      if (excludedIds.has(String(item.id))) return false;
      const displayName = options.display === "university" ? item.university_name || item.name : item.name;
      return `${displayName} ${item.meta}`.toLowerCase().includes(normalizedQuery);
    });
    const popular = data.popular.filter((item) => !excludedIds.has(String(item.id)));
    if (!normalizedQuery && popular.length) {
      const section = element("section", "db-widget__picker-section");
      section.appendChild(element("h3", "db-widget__picker-section-title db-picker-section-label", "⭐ Popular"));
      const grid = element("div", "db-widget__picker-popular");
      popular.slice(0, 8).forEach((item) => grid.appendChild(pickerRow(item, kind, true, options)));
      section.appendChild(grid);
      container.appendChild(section);
    }
    if (!filtered.length) {
      container.appendChild(element("p", "db-widget__picker-empty db-picker-empty", "No matching option."));
      return;
    }
    const allSection = element("section", "db-widget__picker-section db-widget__picker-section--all");
    const sectionLabel = normalizedQuery ? `${filtered.length} Results` : "All";
    allSection.appendChild(element("h3", "db-widget__picker-section-title db-picker-section-label", sectionLabel));
    const list = element("div", "db-widget__picker-results");
    filtered.sort((a, b) => {
      const aName = options.display === "university" ? a.university_name || a.name : a.name;
      const bName = options.display === "university" ? b.university_name || b.name : b.name;
      return aName.localeCompare(bName);
    }).forEach((item) => list.appendChild(pickerRow(item, kind, false, options)));
    allSection.appendChild(list);
    container.appendChild(allSection);
  }

  function openDetails(component) {
    const body = openOverlay(component.name || "Program details", "db-widget__detail-overlay db-details");
    state.overlay.style.gridTemplateRows = "minmax(0, 1fr)";
    const panel = element("div", "db-widget__detail-panel db-widget__details-panel db-details");
    panel.style.height = "100%";
    panel.style.gridTemplateRows = "auto minmax(0, 1fr) auto";
    const details = detailsFor(component);
    // detailSection(detailBody, "Key details", details.key_details)
    const header = element("div", "db-widget__details-header db-details-header");
    const back = createButton("‹ Back", "db-widget__details-back db-details-back", closeOverlay);
    const titleRow = element("div", "db-widget__details-title-row db-details-title-row");
    const name = component.name || component.title || "Program details";
    const mark = element("div", "db-widget__details-mono db-details-mono", initials(component.university_name || name));
    mark.style.background = toneColor(component.university_name || name);
    const titleCopy = element("div");
    titleCopy.appendChild(element("div", "db-widget__details-name db-details-name", name));
    const trust = [
      component.ugc_status || findFact(component, ["ugc", "approval"]),
      component.naac_grade || findFact(component, ["naac"]),
    ].filter(Boolean).join(" · ");
    if (trust) titleCopy.appendChild(element("div", "db-widget__details-trust db-details-trust", trust));
    titleRow.append(mark, titleCopy);
    header.append(back, titleRow);

    const detailBody = element("div", "db-widget__detail-body db-widget__details-body db-details-body");
    const keyDetails = Array.isArray(details.key_details) ? details.key_details.filter(Boolean) : [];
    if (keyDetails.length) {
      const pills = element("div", "db-widget__details-pills db-details-pills");
      keyDetails.slice(0, 3).forEach((item) => {
        const value = item && typeof item === "object" ? item.value : item;
        if (value) pills.appendChild(element("div", "db-widget__details-pill db-details-pill", value));
      });
      if (pills.childElementCount) detailBody.appendChild(pills);
    }

    function infoCard(title, contentEl) {
      const infoCardEl = element("div", "db-widget__detail-section db-info-card");
      if (title) infoCardEl.appendChild(element("div", "db-info-card-title", title));
      infoCardEl.appendChild(contentEl);
      return infoCardEl;
    }

    const heroText = String(details.description || details.hero_description || "").trim();
    if (heroText) detailBody.appendChild(infoCard(null, element("div", "db-info-card-body", heroText)));

    const accreditations = (Array.isArray(details.accreditations) ? details.accreditations : []).filter(Boolean);
    if (accreditations.length) {
      const tags = element("div", "db-widget__accr-tags db-accr-tags");
      accreditations.forEach((item) => {
        const text = item && typeof item === "object" ? item.label || item.name || item.value : item;
        if (text) tags.appendChild(element("span", "db-widget__accr-tag db-accr-tag", text));
      });
      if (tags.childElementCount) detailBody.appendChild(infoCard("Accreditations", tags));
    }

    const admissionSteps = (Array.isArray(details.admission_steps) ? details.admission_steps : []).filter(Boolean);
    if (admissionSteps.length) {
      const steps = element("div", "db-widget__admission-steps db-admission-steps");
      admissionSteps.forEach((item, index) => {
        const text = item && typeof item === "object" ? item.text || item.label || item.description : item;
        if (!text) return;
        const num = item && typeof item === "object" && item.n ? item.n : index + 1;
        const row = element("div", "db-widget__admission-step db-admission-step");
        row.append(
          element("div", "db-widget__step-num db-step-num", String(num)),
          element("div", "db-widget__step-text db-step-text", text),
        );
        steps.appendChild(row);
      });
      if (steps.childElementCount) detailBody.appendChild(infoCard("Admission steps", steps));
    }

    const reviews = (Array.isArray(details.reviews) ? details.reviews : []).filter(Boolean);
    if (reviews.length) {
      const items = element("div", "db-widget__review-items db-review-items");
      reviews.forEach((item) => {
        const reviewerName = item && typeof item === "object" ? item.reviewer_name || item.name : "";
        const text = item && typeof item === "object" ? item.review_text || item.text : item;
        if (!text) return;
        const row = element("div", "");
        if (reviewerName) row.appendChild(element("div", "db-widget__review-name db-review-name", reviewerName));
        row.appendChild(element("div", "db-widget__review-text db-review-text", text));
        items.appendChild(row);
      });
      if (items.childElementCount) detailBody.appendChild(infoCard("What learners say", items));
    }

    const faqs = (Array.isArray(details.faqs) ? details.faqs : []).filter(Boolean);
    if (faqs.length) {
      const items = element("div", "db-widget__faq-items db-faq-items");
      faqs.forEach((item) => {
        const question = item && typeof item === "object" ? item.question || item.q : "";
        const answer = item && typeof item === "object" ? item.answer || item.a : item;
        if (!question && !answer) return;
        const row = element("div", "");
        if (question) row.appendChild(element("div", "db-widget__faq-q db-faq-q", question));
        if (answer) row.appendChild(element("div", "db-widget__faq-a db-faq-a", answer));
        items.appendChild(row);
      });
      if (items.childElementCount) detailBody.appendChild(infoCard("FAQs", items));
    }

    if (!detailBody.childElementCount) {
      detailBody.appendChild(element("p", "db-widget__picker-empty", "No additional published detail is available yet."));
    }
    const footer = element("div", "db-widget__details-footer db-details-footer");
    footer.appendChild(createButton("Ask about fees & EMI", "db-widget__details-cta db-cta-primary", closeOverlay));
    panel.append(header, detailBody, footer);
    body.appendChild(panel);
  }

  function formatInr(value) {
    const num = Number(String(value).replace(/[^0-9.]/g, ""));
    if (!Number.isFinite(num) || num <= 0) return "";
    return `₹${Math.round(num).toLocaleString("en-IN")}`;
  }

  function maskPhone(phone) {
    const digits = String(phone || "").replace(/\D/g, "").slice(-10);
    if (digits.length < 4) return "your number";
    return `+91 •••• •• ${digits.slice(-4)}`;
  }

  function endScreenData(kind, flow, components) {
    const tags = flow && flow.lead_tags && typeof flow.lead_tags === "object" ? flow.lead_tags : {};
    const full = flow && flow.result && typeof flow.result === "object" ? flow.result : {};
    const lead = state.lastLead || {};
    const programLabel = state.context && (state.context.label || contextValues(state.context).join(" · "))
      || "this programme";
    const base = {
      kind,
      name: lead.name || "",
      masked: maskPhone(lead.phone),
      program: programLabel,
      components: Array.isArray(components) ? components : [],
      message: String(full.message || flow && flow.message || "").trim(),
    };
    if (kind === "roi") {
      const months = tags.payback_months || full.payback_months;
      const firstWithEmi = components.find((c) => c && c.emi);
      return {
        ...base,
        headLabel: "Your ROI result",
        heroValue: months ? `${months} months` : "Estimate ready",
        heroSub: "estimated payback period",
        invest: formatInr(full.fee_numeric),
        avgSalary: formatInr(full.expected_post_program_salary_annual),
        currentSalary: formatInr(full.current_salary_annual),
        emi: firstWithEmi ? displayFeeAmount(firstWithEmi.emi, { stripSemester: true }) : "",
        verdict: base.message,
      };
    }
    const waiver = tags.waiver_amount || full.waiver_amount;
    return {
      ...base,
      headLabel: "Scholarship unlocked",
      heroValue: waiver ? `${formatInr(waiver)} off` : (tags.reward_band || "Waiver unlocked"),
      heroSub: "fee waiver applied to your programme",
      waiver: formatInr(waiver),
      net: formatInr(full.net_fee),
      rewardBand: tags.reward_band || full.reward_band || "",
      reasons: Array.isArray(full.reasons) ? full.reasons.filter(Boolean) : [],
      claimSteps: Array.isArray(full.claim_steps) ? full.claim_steps.filter(Boolean) : [],
    };
  }

  function closeEndScreen() {
    state.endScreen = null;
    if (state.endScreenEl && state.endScreenEl.isConnected) state.endScreenEl.remove();
    state.endScreenEl = null;
  }

  function endScreenDetail(data) {
    const card = element("div", "db-widget__info-card db-info-card");
    if (data.kind === "roi") {
      card.appendChild(element("div", "db-info-card-title", `${data.program} · the maths`));
      const stats = element("div", "db-widget__roi-stats db-roi-stats");
      [
        { label: "Investment", value: data.invest },
        { label: "Avg salary", value: data.avgSalary },
        { label: "EMI/mo", value: data.emi || data.heroValue },
      ].filter((item) => item.value).forEach((item) => {
        const stat = element("div", "db-widget__roi-stat db-roi-stat");
        stat.append(
          element("div", "db-widget__roi-stat-label db-roi-stat-label", item.label),
          element("div", "db-widget__roi-stat-value db-roi-stat-value", item.value),
        );
        stats.appendChild(stat);
      });
      if (stats.childElementCount) card.appendChild(stats);
      if (data.verdict) card.appendChild(element("div", "db-widget__roi-verdict db-roi-verdict", data.verdict));
      return [card];
    }
    const feeRow = element("div", "db-widget__schol-fee-row db-schol-fee-row");
    if (data.net) {
      const net = element("div");
      net.append(
        element("div", "db-widget__schol-net-label db-schol-net-label", "Your fee after waiver"),
        element("div", "db-widget__schol-net-value db-schol-net-value", data.net),
      );
      feeRow.appendChild(net);
    }
    if (data.waiver) {
      const off = element("div");
      off.append(
        element("div", "db-widget__schol-std-label db-schol-std-label", "Waiver applied"),
        element("div", "db-widget__schol-std-value db-schol-std-value", data.waiver),
      );
      feeRow.appendChild(off);
    }
    if (feeRow.childElementCount) card.appendChild(feeRow);
    if (data.reasons.length) {
      card.appendChild(element("div", "db-widget__schol-reasons-label db-schol-reasons-label", "Why you qualified"));
      const reasons = element("div", "db-widget__schol-reasons db-schol-reasons");
      data.reasons.forEach((reason) => {
        const tag = element("span", "db-widget__schol-reason db-schol-reason");
        tag.append(richCardIcon("", RICH_CARD_ICONS.checkGreen, "span"), document.createTextNode(` ${reason}`));
        reasons.appendChild(tag);
      });
      card.appendChild(reasons);
    }
    const cards = [card];
    if (data.claimSteps.length) {
      const claim = element("div", "db-widget__info-card db-info-card");
      claim.appendChild(element("div", "db-info-card-title", "How to claim it"));
      data.claimSteps.forEach((step, index) => {
        const text = step && typeof step === "object" ? step.text || step.label || step.description : step;
        if (!text) return;
        const num = step && typeof step === "object" && step.n ? step.n : index + 1;
        const row = element("div", "db-widget__tool-step db-tool-step");
        row.append(
          element("div", "db-widget__tool-step-num db-tool-step-num", String(num)),
          element("div", "db-widget__tool-step-text db-tool-step-text", text),
        );
        claim.appendChild(row);
      });
      const locked = element("div", "db-widget__offer-locked db-offer-locked");
      locked.append(richCardIcon("", RICH_CARD_ICONS.clock, "span"), document.createTextNode(" Offer locked for 7 days"));
      claim.appendChild(locked);
      cards.push(claim);
    }
    return cards;
  }

  function openEndScreen(kind, flow, components) {
    closeEndScreen();
    const data = endScreenData(kind, flow, components);
    state.endScreen = data;
    const firstName = data.name ? data.name.split(/\s+/)[0] : "there";
    const screen = element("div", "db-widget__end-screen db-end-screen");
    screen.id = "db-end-screen";

    const header = element("div", "db-widget__end-header db-end-header");
    const top = element("div", "db-widget__end-header-top db-end-header-top");
    const brand = element("div", "db-widget__end-brand db-end-brand");
    brand.append(
      element("div", "db-widget__end-brand-badge db-end-brand-badge", "DB"),
      element("span", "db-widget__end-brand-label db-end-brand-label",
        state.config && state.config.botName || "DegreeBaba Assistant"),
    );
    const close = createButton("", "db-widget__end-close db-end-close", closeEndScreen);
    close.innerHTML = RICH_CARD_ICONS.endClose;
    close.setAttribute("aria-label", "Close result");
    top.append(brand, close);
    const hero = element("div", "db-widget__end-hero db-end-hero");
    const ring = element("div", "db-widget__end-check-ring db-end-check-ring");
    ring.appendChild(richCardIcon("db-widget__end-check-inner db-end-check-inner", RICH_CARD_ICONS.checkWhite21));
    hero.append(
      ring,
      element("div", "db-widget__end-head-label db-end-head-label", data.headLabel),
      element("div", "db-widget__end-hero-value db-end-hero-value", data.heroValue),
      element("div", "db-widget__end-hero-sub db-end-hero-sub", data.heroSub),
    );
    header.append(top, hero);

    const bodyEl = element("div", "db-widget__end-body db-end-body");
    const confirm = element("div", "db-widget__end-confirm db-end-confirm");
    confirm.appendChild(richCardIcon("db-widget__end-confirm-icon db-end-confirm-icon", RICH_CARD_ICONS.phone));
    const confirmCopy = element("div");
    confirmCopy.appendChild(element("div", "db-widget__end-confirm-name db-end-confirm-name", `Locked in, ${firstName}.`));
    const confirmSub = element("div", "db-widget__end-confirm-sub db-end-confirm-sub");
    confirmSub.append(
      document.createTextNode("A counsellor will call "),
      element("span", "db-widget__end-confirm-phone db-end-confirm-phone", data.masked),
      document.createTextNode(" within 30 minutes to confirm this offer. No spam."),
    );
    confirmCopy.appendChild(confirmSub);
    confirm.appendChild(confirmCopy);
    bodyEl.appendChild(confirm);
    endScreenDetail(data).forEach((card) => bodyEl.appendChild(card));

    const footer = element("div", "db-widget__end-footer db-end-footer");
    footer.append(
      createButton("See matching programs", "db-widget__end-cta db-cta-primary", () => {
        const components2 = data.components;
        closeEndScreen();
        if (components2.length) {
          renderBotPayload({
            message: "Here are the programs matched to your result — lowest fee first.",
            components: components2,
          });
        } else {
          executeGuidedAction("browse_programs", "See matching programs");
        }
      }),
      createButton("Back to chat", "db-widget__end-cta-secondary db-cta-secondary", closeEndScreen),
    );

    screen.append(header, bodyEl, footer);
    state.panel.appendChild(screen);
    state.endScreenEl = screen;
    emitAnalytics("card_shown", null, { entity: { type: `${kind}_result`, id: `${kind}:end_screen` } });
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
