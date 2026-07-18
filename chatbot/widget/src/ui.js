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
      avatar.textContent = "DB";
      avatar.style.fontWeight = "700";
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
    return createButton(normalized.label, `${className} db-chip`, () => handleAction(normalized));
  }

  function refreshResponsiveActionLayouts() {
    window.requestAnimationFrame(() => {
      responsiveActionLayouts.forEach((layout) => layout.fit());
    });
  }

  function responsiveActionGrid(actions, buttons, options = {}) {
    const row = element(
      "div",
      `${options.className || "db-widget__quick-actions db-widget__follow-up-actions"} db-chip-grid`,
    );
    row.style.visibility = "hidden";
    const usableActions = actions.slice(0, buttons.length);
    const usableButtons = buttons.slice(0, usableActions.length);
    usableButtons.forEach((button) => row.appendChild(button));
    let expanded = false;
    let mounted = false;
    let visibleCount = usableActions.length;
    const toggle = createButton("More", "db-widget__more-toggle db-more-btn", () => {
      if (expanded) {
        expanded = false;
        layout.fit();
        return;
      }
      expanded = true;
      usableButtons.forEach((button) => { button.hidden = false; });
      visibleCount = usableActions.length;
      toggle.textContent = "Less";
      toggle.setAttribute("aria-expanded", "true");
      if (!toggle.isConnected) row.appendChild(toggle);
      if (typeof options.onVisible === "function") options.onVisible(usableActions);
    });
    toggle.setAttribute("aria-expanded", "false");

    function setVisibleCount(count) {
      visibleCount = Math.max(0, Math.min(count, usableButtons.length));
      usableButtons.forEach((button, index) => { button.hidden = index >= visibleCount; });
    }

    function gridColumns() {
      const columns = window.getComputedStyle(row).gridTemplateColumns
        .split(/\s+/)
        .filter(Boolean).length;
      return Math.max(1, columns || 1);
    }

    function fitsViewport() {
      if (!state.messages || !row.isConnected) return true;
      const messagesRect = state.messages.getBoundingClientRect();
      const messagesStyle = window.getComputedStyle(state.messages);
      const bottomPadding = Number.parseFloat(messagesStyle.paddingBottom) || 0;
      return row.getBoundingClientRect().bottom <= messagesRect.bottom - bottomPadding + 1;
    }

    const layout = {
      fit() {
        if (!row.isConnected) {
          if (mounted) responsiveActionLayouts.delete(layout);
          return;
        }
        mounted = true;
        if (expanded) return;
        toggle.remove();
        setVisibleCount(usableActions.length);
        if (fitsViewport()) {
          row.style.visibility = "";
          if (typeof options.onVisible === "function") options.onVisible(usableActions);
          return;
        }

        row.appendChild(toggle);
        toggle.textContent = "More";
        toggle.setAttribute("aria-expanded", "false");
        const columns = gridColumns();
        const largestCollapsibleRow = Math.floor((usableActions.length - 1) / columns);
        let fittingCount = Math.min(usableActions.length, columns);
        for (let rows = largestCollapsibleRow; rows >= 1; rows -= 1) {
          const candidateCount = rows * columns;
          setVisibleCount(candidateCount);
          if (fitsViewport()) {
            fittingCount = candidateCount;
            break;
          }
        }
        setVisibleCount(fittingCount);
        if (visibleCount >= usableActions.length) toggle.remove();
        row.style.visibility = "";
        if (typeof options.onVisible === "function") {
          options.onVisible(usableActions.slice(0, visibleCount));
        }
      },
    };
    responsiveActionLayouts.add(layout);
    window.requestAnimationFrame(() => layout.fit());
    return row;
  }
