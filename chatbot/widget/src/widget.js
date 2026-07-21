/*!
 * DegreeBaba Chatbot Widget  v1.0.0
 * Pixel-perfect embeddable widget.
 * Install: <script src="widget.js"></script>
 *
 * Config (optional):
 *   window.DegreeBabaWidget.init({
 *     apiUrl:       "https://your-api.com/chat",
 *     botName:      "DegreeBaba Assistant",
 *     primaryColor: "#E84010",
 *     position:     "right",   // "right" | "left"
 *     page:         "course",  // "homepage" | "university" | "course" | "specialization"
 *     widgetId:     "CLIENT_ID"
 *   });
 */
(function () {
  'use strict';

  /* document.currentScript is null once we defer to DOMContentLoaded. */
  var bootScript = document.currentScript;

  /* ─────────────────────────────────────────────────────────────
     1. BOOTSTRAP — font injection + style mount
  ───────────────────────────────────────────────────────────── */
  function injectGoogleFonts() {
    if (document.getElementById('db-fonts')) return;
    var link = document.createElement('link');
    link.id = 'db-fonts';
    link.rel = 'stylesheet';
    link.href = 'https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap';
    document.head.appendChild(link);
  }


  // @include state.js
  // @include config.js
  // @include api.js
  // @include actions.js
  // @include tools.js
  // @include renderer.js
  // @include ui.js

  /* ─────────────────────────────────────────────────────────────
     8. PUBLIC API
  ───────────────────────────────────────────────────────────── */
  function init(options) {
    if (options) {
      if (options.botName)        cfg.botName = options.botName;
      if (options.primaryColor)   cfg.primaryColor = options.primaryColor;
      if (options.position)       cfg.position = options.position;
      if (options.page)           cfg.page = options.page;
      if (options.apiUrl)         cfg.apiUrl = options.apiUrl;
      if (options.apiBase)        cfg.apiBase = options.apiBase;
      if (options.siteKey)        cfg.siteKey = options.siteKey;
      if (options.widgetId)     { cfg.widgetId = options.widgetId; cfg.siteKey = options.widgetId; }
      if (options.entitySlug)     cfg.entitySlug = options.entitySlug;
      if (options.universitySlug) cfg.universitySlug = options.universitySlug;
    }
    /* apiUrl may point at the /chat endpoint; the API base is its origin. */
    if (!cfg.apiBase && cfg.apiUrl) {
      try { cfg.apiBase = new URL(cfg.apiUrl, window.location.href).origin; }
      catch (err) { cfg.apiBase = ''; }
    }
    applyTheme(cfg.primaryColor);
  }

  /* ─────────────────────────────────────────────────────────────
     9. AUTO-INIT
  ───────────────────────────────────────────────────────────── */
  function bootstrap() {
    injectGoogleFonts();

    /* Documented public embed contract — see README.md. Do not rename these:
       host pages in production already ship them. */
    var scriptTag = document.currentScript || bootScript;
    if (scriptTag) {
      var key = scriptTag.getAttribute('data-site-key');
      if (key) cfg.siteKey = key;
      var pageType = scriptTag.getAttribute('data-page-type');
      if (pageType) cfg.page = pageType;
      var ent = scriptTag.getAttribute('data-page-entity-slug');
      if (ent) cfg.entitySlug = ent;
      var uni = scriptTag.getAttribute('data-page-university-slug');
      if (uni) cfg.universitySlug = uni;
      if (scriptTag.getAttribute('data-auto-open') === 'true') { cfg.autoOpen = true; cfg.autoOpenPinned = true; }
      var pos = scriptTag.getAttribute('data-position');
      if (pos) cfg.position = pos;
      var api = scriptTag.getAttribute('data-api-base');
      if (api) cfg.apiBase = api;
      /* Default the API to the origin the widget was served from. */
      if (!cfg.apiBase && scriptTag.src) {
        try { cfg.apiBase = new URL(scriptTag.src, window.location.href).origin; }
        catch (err) { cfg.apiBase = ''; }
      }
    }
    if (!cfg.apiBase && cfg.apiUrl) {
      try { cfg.apiBase = new URL(cfg.apiUrl, window.location.href).origin; }
      catch (err) { cfg.apiBase = ''; }
    }

    mount();

    if (cfg.apiBase) {
      loadConfig().then(function () {
        /* Branding lands before first paint of the header in most cases. */
        if (state.open) render();
        if (cfg.autoOpen && !state.open) {
          state.open = true;
          launcher.setAttribute('aria-label', 'Close chat');
          resetChat();
        }
      }).catch(function (err) {
        console.warn('DegreeBaba widget config unavailable; using defaults', err);
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrap);
  } else {
    bootstrap();
  }

  /* Expose public API */
  window.DegreeBabaWidget = {
    init: init,
    reset: function(options) {
      init(options);
      resetChat();
    }
  };
  /* Legacy alias */
  window.ChatWidget = window.DegreeBabaWidget;

})();
