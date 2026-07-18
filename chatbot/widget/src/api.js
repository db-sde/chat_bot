  function safeHttpUrl(value) {
    if (!value) return "";
    try {
      const resolved = new URL(String(value), apiBase);
      return ["http:", "https:"].includes(resolved.protocol) ? resolved.href : "";
    } catch (_error) {
      return "";
    }
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

  async function requestChat(body, signal) {
    const response = await fetch(`${apiBase}/chat`, {
      method: "POST",
      mode: "cors",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
    if (!response.ok) throw new Error(`Chat request failed (${response.status})`);
    return response;
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
