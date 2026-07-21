  /* ─────────────────────────────────────────────────────────────
     3. PRESENTATION CHROME
     Catalog facts, chips, results and tool questions are owned by the
     backend. Only non-factual presentation lives here: the tool badge
     glyph and title, which are design tokens, not business logic.
  ───────────────────────────────────────────────────────────── */
  var TOOL_CHROME = {
    roi:         { icon: '🧮', title: 'ROI Calculator' },
    quiz:        { icon: '🧭', title: 'Career-Path Quiz' },
    scholarship: { icon: '🎁', title: 'Scholarship Checker' }
  };
  function toolChrome(kind) { return TOOL_CHROME[kind] || { icon: '🧭', title: 'Assistant' }; }

  /* Copy shown when the backend has published nothing for a surface.
     The widget never substitutes invented values for missing data. */
  var UNAVAILABLE = 'That information has not been published for this option yet. A counsellor can confirm it for you.';

  function maskedPhone(phone) {
    var d = (phone || '').replace(/\D/g, '');
    return d.length >= 5 ? ('+91 ' + d.slice(0, 2) + ' ••••• ' + d.slice(-3)) : '+91 ' + d;
  }
