  /* ─────────────────────────────────────────────────────────────
     5. RENDER (vanilla DOM — no virtual DOM overhead)
  ───────────────────────────────────────────────────────────── */
  var shadow, root, launcher, windowEl;

  /* ── SVG helpers ── */
  var SVG = {
    chat: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.9-.9L3 21l1.9-5.6A8.5 8.5 0 0 1 12.5 3 8.38 8.38 0 0 1 21 11.5z"/></svg>',
    close: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
    chevDown: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
    check: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#3B6D11" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
    checkWhite: function(w,sw){return '<svg width="'+w+'" height="'+w+'" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="'+sw+'" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>';},
    x: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
    checkSeen: '<svg class="db-seen-tick" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
    x10: '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
    back: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>',
    currency: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#E84010" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h12M6 8h12M6 13h3m0 0c6.667 0 6.667-10 0-10M6 13l8.5 8"/></svg>',
    compare: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3h5v5M8 3H3v5m0 8v5h5m8 0h5v-5"/></svg>',
    search: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#4B5563" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></svg>',
    chevGray: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
    phone: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.9.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/></svg>',
    dash: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" stroke-width="3" stroke-linecap="round"><path d="M5 12h14"/></svg>',
    checkGreen: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#3B6D11" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
    clock: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#9A6412" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>'
  };

  function e(tag, cls, inner, attrs) {
    var s = '<' + tag + (cls ? ' class="' + cls + '"' : '') + (attrs ? ' ' + attrs : '') + '>';
    if (inner !== undefined) s += inner;
    s += '</' + tag + '>';
    return s;
  }
  function div(cls, inner, attrs) { return e('div', cls, inner, attrs); }
  function btn(cls, inner, id, extraAttrs) {
    var attrs = (id ? 'id="' + id + '" ' : '') + (extraAttrs || '');
    return e('button', cls, inner, attrs.trim());
  }
  function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

  /* ── Message renderers ── */
  function renderMsg(m) {
    if (m.kind==='user') return div('db-msg', div('db-bubble-user', esc(m.text)));
    if (m.kind==='bot') return div('db-msg', div('db-bubble-bot', esc(m.text)));
    if (m.kind==='cards') return div('db-msg', m.cards.map(function(c){ return renderCard(c,m.id); }).join(''));
    if (m.kind==='compare') return div('db-msg', renderCompare(m));
    if (m.kind==='lead') return div('db-msg', renderLead(m));
    if (m.kind==='fees') return div('db-msg', renderFees(m.fee));
    if (m.kind==='elig') return div('db-msg', renderElig(m.elig));
    if (m.kind==='career') return div('db-msg', renderCareer(m.career));
    if (m.kind==='reviews') return div('db-msg', renderReviews(m.rev));
    if (m.kind==='syllabus') return div('db-msg', renderSyllabus(m.syl, m.id));
    if (m.kind==='toolResult') return div('db-msg', renderToolResult(m.tr));
    if (m.kind==='published') return div('db-msg', renderPublished(m.info));
    return '';
  }
  function renderCard(c, mid) {
    var cardKey = c.entityId || c.title;
    var inC = !!state.compare.find(function(x){ return (x.entityId || x.title) === cardKey; });
    var cmpCls = 'db-btn-compare' + (inC ? ' db-in-compare' : '');
    var cmpLabel = inC ? '✓ Added' : '+ Compare';
    return div('db-card',
      div('db-card-head',
        div('db-card-mono', esc(c.mono), 'style="background:'+c.bg+'"') +
        div('',div('db-card-title',esc(c.title))+div('db-card-trust',esc(c.trust)))
      ) +
      div('db-pills-row', c.pills.map(function(p){return div('db-pill',esc(p));}).join('')) +
      (c.emi ? div('db-card-emi', esc(c.emi)) : '') +
      (c.job ? div('db-card-job', esc(c.job)) : '') +
      div('db-card-actions',
        btn('db-btn-primary','View details','','data-action="viewDetails" data-mid="'+mid+'" data-key="'+esc(cardKey)+'"') +
        btn(cmpCls, cmpLabel, '', 'data-action="toggleCompare" data-key="'+esc(cardKey)+'"')
      )
    );
  }
  function renderCompare(m) {
    return div('db-compare',
      div('db-compare-head',
        div('db-compare-head-empty') +
        div('db-compare-head-cell', esc(m.aName)) +
        div('db-compare-head-cell', esc(m.bName))
      ) +
      m.rows.map(function(r){
        return div('db-compare-row',
          div('db-compare-key',esc(r.k)) +
          div('db-compare-val',esc(r.a)) +
          div('db-compare-val',esc(r.b))
        );
      }).join('') +
      div('db-compare-verdict', e('span','db-verdict-label','Verdict&nbsp;') + esc(m.verdict))
    );
  }
  function renderLead(m) {
    if (m.leadDone) {
      return div('db-lead',
        div('db-lead-done',
          div('db-lead-done-icon', SVG.check) +
          div('db-lead-done-text', 'Done — a counsellor will call within 30 minutes with today\'s fee offer.')
        )
      );
    }
    return div('db-lead',
      div('db-lead-text', esc(m.text)) +
      div('db-lead-form',
        div('db-phone-wrapper',
          e('span','db-phone-prefix','+91') +
          e('input','db-phone-input','','type="tel" placeholder="Your number" data-action="leadPhoneInput" data-mid="'+m.id+'" value="'+esc(state.leadPhone)+'"')
        ) +
        btn('db-lead-send', m.leadBusy ? 'Sending…' : 'Send','','data-action="submitLead" data-mid="'+m.id+'"'+(m.leadBusy?' disabled':''))
      ) +
      div('db-lead-note', m.leadError ? esc(m.leadError) : 'No spam. One call, today\'s offer.')
    );
  }
  function renderFees(f) {
    return div('db-fees',
      div('db-fees-hero',
        div('',div('db-fees-total-label','Total programme fee')+div('db-fees-total-value',esc(f.total))) +
        div('',div('db-fees-sem-label','Per semester')+div('db-fees-sem-value',esc(f.perSem)))
      ) +
      (f.plans.length ? div('db-fees-plans', f.plans.map(function(p){
        return div('db-fees-plan-row',
          div('',div('db-fees-plan-label',esc(p.label))+div('db-fees-plan-note',esc(p.note))) +
          div('db-fees-plan-value',esc(p.value))
        );
      }).join('')) : '') +
      div('db-fees-emi', SVG.currency + e('span','',esc(f.emiNote)))
    );
  }
  function renderElig(elig) {
    return div('db-elig',
      div('db-elig-hero',
        div('db-elig-check', SVG.checkWhite(17,2.6)) +
        div('',div('db-elig-verdict',esc(elig.verdict))+div('db-elig-sub',esc(elig.sub)))
      ) +
      div('db-elig-list', elig.reqs.map(function(r){
        var icon = r.ok ? div('db-elig-icon ok', SVG.checkGreen) : div('db-elig-icon opt', SVG.dash);
        return div('db-elig-row', icon + div('',div('db-elig-req-title',esc(r.t))+(r.note?div('db-elig-req-note',esc(r.note)):'') ));
      }).join(''))
    );
  }
  function renderCareer(c) {
    return div('db-career',
      div('db-career-hero',
        div('db-career-label','Average starting salary') +
        div('',div('db-career-avg',esc(c.avg))+e('span','db-career-range',' '+esc(c.range)))
      ) +
      div('db-career-roles',
        div('db-career-roles-label','Roles you can target') +
        c.roles.map(function(r){return div('db-career-role-row',div('db-career-role-title',esc(r.t))+div('db-career-role-salary',esc(r.s)));}).join('')
      ) +
      (c.recruiters.length ? div('db-career-recruiters',
        div('db-career-recruiters-label','Top recruiters') +
        div('db-recruiter-tags', c.recruiters.map(function(r){return e('span','db-recruiter-tag',esc(r));}).join(''))
      ) : '')
    );
  }
  function renderReviews(rv) {
    return div('db-reviews',
      div('db-reviews-summary',
        div('',div('db-rating-big',esc(rv.rating))+div('db-rating-stars',esc(rv.stars))+div('db-rating-count',esc(rv.count)+' reviews')) +
        (rv.bars.length ? div('db-rating-bars', rv.bars.map(function(b){
          return div('db-bar-row', e('span','db-bar-label',esc(b.stars))+div('db-bar-track',div('db-bar-fill','','style="width:'+b.pct+'"')));
        }).join('')) : '')
      ) +
      div('db-reviews-sentiment',
        div('db-praised',div('db-praised-label','Most praised')+div('db-praised-text',esc(rv.praised))) +
        div('db-flagged',div('db-flagged-label','Most flagged')+div('db-flagged-text',esc(rv.flagged)))
      ) +
      (rv.quotes.length ? div('db-reviews-quotes', rv.quotes.map(function(q){
        return div('db-quote',div('db-quote-text',esc(q.t))+div('db-quote-name',esc(q.n)));
      }).join('')) : '')
    );
  }
  function renderSyllabus(sy, mid) {
    return div('db-syllabus',
      div('db-syllabus-head', div('db-syllabus-title',esc(sy.title))+div('db-syllabus-meta',esc(sy.meta))) +
      sy.items.map(function(it, i){
        var key = mid+':'+i;
        var open = state.acc[key] !== undefined ? state.acc[key] : (i===0);
        var numBg = open ? '#0E1F3D' : '#F3F4F6';
        var numColor = open ? '#fff' : '#0E1F3D';
        var headBg = open ? '#F7F8FA' : '#fff';
        var chevRotate = open ? 'rotate(180deg)' : 'rotate(0deg)';
        return div('db-sem-item',
          btn('db-sem-toggle', 
            div('db-sem-toggle-inner',
              div('db-sem-num',esc(it.n),'style="background:'+numBg+';color:'+numColor+'"') +
              div('db-sem-title',esc(it.title))
            ) +
            e('span','db-sem-chevron',SVG.chevGray,'style="display:inline-flex;transform:'+chevRotate+'"'),
            '',
            'data-action="toggleAcc" data-mid="'+mid+'" data-idx="'+i+'" style="background:'+headBg+'"'
          ) +
          (open ? div('db-sem-subs', it.subs.map(function(s){return div('db-sem-sub',div('db-sub-dot')+' '+esc(s));}).join('')) : '')
        );
      }).join('')
    );
  }
  function renderToolResult(tr) {
    return div('db-tool-result',
      div('db-tool-result-hero',
        div('db-tool-result-label',esc(tr.label),'style="color:'+esc(tr.labelColor||'#3B6D11')+'"') +
        div('db-tool-result-value',esc(tr.value)),
        'style="background:'+esc(tr.headBg||'#EAF3DE')+'"'
      ) +
      (tr.steps ? div('db-tool-steps',
        div('db-tool-steps-label','How to claim it') +
        tr.steps.map(function(st){
          return div('db-tool-step',div('db-tool-step-num',esc(st.n))+div('db-tool-step-text',esc(st.t)));
        }).join('')
      ) : '')
    );
  }

  /* Published facts with no bespoke card reuse the approved .db-info-card
     surface already used by the details overlay. No new classes. */
  function renderPublished(v) {
    return div('db-info-card',
      div('db-info-card-title', esc(v.title)) +
      (v.text ? div('db-info-card-body', esc(v.text)) : '') +
      ((v.tags || []).length
        ? div('db-accr-tags', v.tags.map(function (t) { return e('span','db-accr-tag',esc(t)); }).join(''))
        : '') +
      ((v.steps || []).length
        ? div('db-admission-steps', v.steps.map(function (t, i) {
            return div('db-admission-step', div('db-step-num', String(i+1)) + div('db-step-text', esc(t)));
          }).join(''))
        : '')
    );
  }

  /* ── Chips ── */
  /* §2 the action zone renders one of two shapes. A list_set is an
     enumeration the user scans and picks from; a nav_set is topic navigation.
     Truncating a list to satisfy a navigation minimum is the §1.2 bug, so the
     two paths never share sizing rules. */
  function renderChips() {
    var conv = state.conversionChip;
    if (!state.chips.length && !conv) return '';
    var listChips = state.chips.filter(function (c) { return c.chip_type === 'list_set'; });
    var isList = listChips.length > 0 && listChips.length === state.chips.length;
    return div('db-chips-area', isList ? renderListSet() : renderNavSet());
  }

  function chipAttrs(idx) {
    return 'data-action="chip" data-idx="' + idx + '"' + (state.busy ? ' disabled="disabled"' : '');
  }
  function busyCls() { return state.busy ? ' db-chip--disabled' : ''; }

  /* §8 [info][info][info] + [conversion] — the conversion slot is always
     present and always separate, so escalation never costs a nav option. */
  function renderNavSet() {
    var conv = state.conversionChip;
    return div('db-chip-grid',
      state.chips.map(function (ch, i) {
        return btn('db-chip' + busyCls(), esc(ch.label), '', chipAttrs(i));
      }).join('') +
      (conv ? btn('db-chip db-chip-conversion' + busyCls() + (conv.handler === 'cta_apply' ? ' db-chip-conversion--lead' : ''),
        esc(conv.label), '', 'data-action="conversion"' + (state.busy ? ' disabled="disabled"' : '')) : '')
    ) +
    (state.moreOpen ? renderMorePanel() : '') +
    (state.hasMore ? btn('db-more-btn' + busyCls(),
      esc(state.moreOpen ? 'Less ⌃' : 'More ⌄'), '', 'data-action="toggleMore"' + (state.busy ? ' disabled="disabled"' : '')) : '');
  }

  /* §10 demoted chips stay reachable, rendered dimmed with a check so
     re-tapping is deliberate rather than accidental. */
  function renderMorePanel() {
    return div('db-more-panel', state.moreChips.map(function (ch, i) {
      return btn('db-more-item' + (ch.seen ? ' db-chip--seen' : '') + busyCls(),
        (ch.seen ? SVG.checkSeen : '') + e('span', '', esc(ch.label)),
        '', 'data-action="moreChip" data-idx="' + i + '"' + (state.busy ? ' disabled="disabled"' : ''));
    }).join(''));
  }

  /* §2.2 show all at <=6 as a grid; at 7+ show the top 5 and hand overflow to
     the picker sheet. Never backfilled, never reordered, never truncated to
     fit a navigation minimum. */
  function renderListSet() {
    var conv = state.conversionChip;
    var all = state.chips;
    var first = all[0] || {};
    var inlineMax = first.list_inline_max || 6;
    var showTop = first.list_show_top || 5;
    var grid = all.length <= inlineMax;
    var shown = grid ? all : all.slice(0, showTop);
    var rowHtml = function (ch, i) {
      return btn('db-list-item' + (grid ? ' db-list-item--grid' : '') + (ch.seen ? ' db-chip--seen' : '') + busyCls(),
        div('db-list-mono', esc(ch.mono || initialsFor(ch.label)), 'style="background:' + (ch.bg || colorFor(ch.label)) + '"') +
        div('db-list-body',
          div('db-list-name', (ch.seen ? SVG.checkSeen : '') + esc(ch.label)) +
          (ch.meta ? div('db-list-meta', esc(ch.meta)) : '')),
        '', chipAttrs(i));
    };
    return div(grid ? 'db-list-grid' : 'db-list-column',
      shown.map(rowHtml).join('') +
      (grid ? '' : (all.length > showTop
        ? btn('db-list-showall' + busyCls(),
            e('span', '', 'Show all ' + all.length + ' ›'), '',
            'data-action="listShowAll"' + (state.busy ? ' disabled="disabled"' : ''))
        : ''))
    ) +
    /* The conversion chip sits below a divider so it never reads as list item #6. */
    (conv ? div('db-list-divider') + btn('db-chip db-chip-conversion db-chip-conversion--wide' + busyCls() + (conv.handler === 'cta_apply' ? ' db-chip-conversion--lead' : ''),
      esc(conv.label), '', 'data-action="conversion"' + (state.busy ? ' disabled="disabled"' : '')) : '');
  }

  /* §11.4 breadcrumb — each segment jumps to that entity, so the cascade is
     traversable in both directions. */
  function renderBreadcrumb() {
    var crumbs = state.breadcrumb || [];
    if (!crumbs.length) return '';
    return div('db-context-chip',
      div('db-context-dot') +
      div('db-crumbs', crumbs.map(function (c, i) {
        return (i ? e('span', 'db-crumb-sep', '›') : '') +
          btn('db-crumb' + (i === crumbs.length - 1 ? ' db-crumb--active' : ''),
            esc(c.label), '', 'data-action="crumb" data-idx="' + i + '"');
      }).join('')) +
      btn('db-context-clear', SVG.x10, '', 'data-action="clearContext" aria-label="Clear current context"')
    );
  }

  /* §11.3 recently-viewed rail — returns to any entity with its consumed
     state intact, which linear Back cannot do. */
  function renderRail() {
    var items = state.recentlyViewed || [];
    if (items.length < 2) return '';
    return div('db-rail-wrap',
      div('db-rail-label', 'Recently viewed') +
      div('db-rail', items.map(function (v, i) {
        return btn('db-rail-item', 
          div('db-rail-mono', esc(initialsFor(v.label)), 'style="background:' + colorFor(v.label) + '"') +
          e('span', 'db-rail-name', esc(v.label)),
          '', 'data-action="rail" data-idx="' + i + '"');
      }).join(''))
    );
  }

  /* §9 persistent navigation row — chrome, not content. Sits outside the
     contextual set and does not count toward the 4-chip floor, which makes a
     terminal dead end structurally impossible. */
  function renderNavRow() {
    var hasBack = (state.historyStack && state.historyStack.length > 0) || (state.breadcrumb && state.breadcrumb.length > 1);
    return div('db-nav-row',
      btn('db-nav-btn', '🏠 Main menu', '', 'data-action="mainMenu"') +
      btn('db-nav-btn' + (hasBack ? '' : ' db-nav-btn--muted'),
        '‹ Back', '', 'data-action="navBack"' + (hasBack ? '' : ' disabled="disabled"')) +
      div('db-nav-spacer') +
      btn('db-nav-btn db-nav-btn--accent', '📞 Counsellor', '', 'data-action="navCounsellor"')
    );
  }

  /* ── Tool widget ── */
  function renderToolWidget() {
    var t = state.tool;
    var def = toolChrome(t.kind);
    /* Questions, options and step counts are all backend-owned. */
    var len = Math.max(t.total || 0, t.idx + 1);
    var cur = { q: t.question || '', opts: (t.options || []).map(function (o) { return o.label; }) };
    var pct = ((t.idx+1)/len*100)+'%';
    var progress = (t.idx+1)+' of '+len;

    var header = div('db-tool-header',
      div('db-tool-header-left',
        div('db-tool-icon-badge',def.icon) +
        div('db-tool-title',esc(def.title))
      ) +
      btn('db-tool-close',SVG.x,'','data-action="closeTool" aria-label="Close tool"')
    );

    var body = '';
    if (t.phase==='entry') {
      body = div('db-tool-promise',esc(t.entryCopy || '')) +
        (t.total ? div('db-tool-step-badge', t.total + ' quick questions') : '') +
        btn('db-tool-start','Start','','data-action="toolBegin"');
    } else if (t.phase==='step') {
      var optsHtml = cur.opts.map(function(o,oi){
        var sel = t.answers[t.idx] && t.answers[t.idx].i===oi;
        return btn('db-tool-opt'+(sel?' selected':''),esc(o),'','data-action="toolAnswer" data-opt="'+esc(o)+'" data-oi="'+oi+'"');
      }).join('');
      body = div('db-tool-progress',
          div('db-progress-track',div('db-progress-fill','','style="width:'+pct+'"')) +
          e('span','db-progress-label',progress)
        ) +
        div('db-tool-question',esc(cur.q)) +
        div('db-tool-opts',optsHtml) +
        '';
    } else if (t.phase==='loading') {
      body = div('db-tool-promise','Loading…');
    } else if (t.phase==='partial') {
      body = div('db-tool-partial-box',
          div('db-tool-partial-check',SVG.checkWhite(14,2.8)) +
          div('db-tool-partial-text',esc(t.partialText || ''))
        ) +
        btn('db-tool-reveal','See my full result ›','','data-action="toolReveal"');
    } else if (t.phase==='lead') {
      body = div('db-tool-lead-text','Enter your details to see your full result.') +
        e('input','db-tool-name-input','','type="text" placeholder="Your name" data-action="toolName" value="'+esc(state.toolName)+'"') +
        div('db-tool-phone-row',
          e('span','db-tool-phone-prefix','+91') +
          e('input','db-tool-phone-input','','type="tel" placeholder="Your number" data-action="toolPhone" value="'+esc(state.toolPhone)+'"')
        ) +
        btn('db-tool-submit','Reveal my result','','data-action="toolSubmit"') +
        btn('db-tool-skip','Skip — show a general result','','data-action="toolSkip"');
    }

    return div('db-msg', '<div id="db-tool-widget">'+header+body+'</div>');
  }

  /* ── Picker ── */
  /* Shared by the full picker render and the keystroke-level list refresh. */
  function pickerListHtml() {
    var p = state.picker;
    var q = (p.query||'').toLowerCase();
    var live = Array.isArray(p.rows);
    var src = pickerRows();
    /* Server-side `q` already filtered live rows; only bundled rows need it. */
    var filtered = live ? src : src.filter(function(r){
      return !q || r.name.toLowerCase().includes(q) || (r.short||'').toLowerCase().includes(q);
    });
    var rowHtml = function(r) {
      return btn('db-picker-row',
        div('db-picker-mono',esc(r.mono),'style="background:'+r.bg+'"') +
        div('',div('db-picker-row-name',esc(r.name))+div('db-picker-row-meta',esc(r.meta))),
        '','data-action="pickItem" data-key="'+esc(r.id||r.name)+'" data-kind="'+p.kind+'"'
      );
    };

    /* Compare mode: show which option(s) are already chosen up top, using the
       same row markup, and keep them out of Popular/All below so nothing is
       listed twice. */
    var selectedHtml = '';
    if (p.compareMode && state.compare.length) {
      var chosenIds = {};
      state.compare.forEach(function (c) { chosenIds[c.entityId || c.title] = true; });
      filtered = filtered.filter(function (r) { return !chosenIds[r.id]; });
      selectedHtml = div('db-picker-section-label', '✓ Selected (' + state.compare.length + '/2)') +
        state.compare.map(function (c) {
          return rowHtml({ id: c.entityId, name: c.title, mono: c.mono, bg: c.bg, meta: 'Tap to remove' });
        }).join('');
    }

    /* Popular is a backend signal. Without it the section would just repeat
       the head of the list under a different heading. */
    var popular = filtered.filter(function(r){ return r.pop; });
    if (popular.length >= filtered.length) popular = [];

    if (p.loading && !filtered.length && !selectedHtml) return div('db-picker-empty','Loading…');
    return selectedHtml +
      (!q && popular.length ? div('db-picker-section-label','⭐ Popular') + popular.map(rowHtml).join('') : '') +
      div('db-picker-section-label','All') +
      filtered.map(rowHtml).join('') +
      (filtered.length===0 && !p.loading ? div('db-picker-empty','Nothing matched. Try a shorter search.') : '');
  }

  function renderPicker() {
    var p = state.picker;
    return '<div id="db-picker" role="dialog" aria-modal="true" aria-label="'+esc(p.title)+'">'+
      div('db-picker-scrim','','data-action="closePicker"') +
      div('db-picker-sheet',
        div('db-picker-header',
          div('db-picker-handle') +
          div('db-picker-title-row',
            div('db-picker-title',esc(p.title)) +
            btn('db-picker-close',SVG.x,'','data-action="closePicker" aria-label="Close list"')
          ) +
          div('db-picker-search',
            SVG.search +
            e('input','db-picker-input','','placeholder="'+(p.kind==='uni'?'Search universities…':(p.kind==='spec'?'Search specializations…':'Search programs…'))+'" aria-label="Search the list" data-action="pickerInput" value="'+esc(p.query||'')+'"')
          )
        ) +
        div('db-picker-list', pickerListHtml())
      ) +
      '</div>';
  }

  /* ── Details overlay ── */
  function renderDetails() {
    var d = state.details;
    /* Only render a section when it actually has published content — an
       empty .db-info-card with just a heading is a visible blank strip. */
    var sections = [];
    if (d.hero) sections.push(div('db-info-card', div('db-info-card-body',esc(d.hero))));
    if (d.accr.length) sections.push(div('db-info-card', div('db-info-card-title','Accreditations') + div('db-accr-tags', d.accr.map(function(a){return e('span','db-accr-tag',esc(a));}).join(''))));
    if (d.steps.length) sections.push(div('db-info-card', div('db-info-card-title','Admission steps') + div('db-admission-steps', d.steps.map(function(s){return div('db-admission-step',div('db-step-num',esc(s.n))+div('db-step-text',esc(s.t)));}).join(''))));
    if (d.reviews.length) sections.push(div('db-info-card', div('db-info-card-title','What learners say') + div('db-review-items', d.reviews.map(function(r){return div('',div('db-review-name',esc(r.n))+div('db-review-text',esc(r.t)));}).join(''))));
    if (d.faqs.length) sections.push(div('db-info-card', div('db-info-card-title','FAQs') + div('db-faq-items', d.faqs.map(function(f){return div('',div('db-faq-q',esc(f.q))+div('db-faq-a',esc(f.a)));}).join(''))));
    return '<div id="db-details" role="dialog" aria-modal="true" aria-label="'+esc(d.title)+' details">'+
      div('db-details-header',
        btn('db-details-back', SVG.back+'Back','','data-action="closeDetails"') +
        div('db-details-title-row',
          div('db-details-mono',esc(d.mono),'style="background:'+d.bg+'"') +
          div('',div('db-details-name',esc(d.title))+div('db-details-trust',esc(d.trust)))
        )
      ) +
      div('db-details-body',
        div('db-details-pills', d.pills.map(function(p){return div('db-details-pill',esc(p));}).join('')) +
        sections.join('')
      ) +
      div('db-details-footer', btn('db-cta-primary','Ask about fees & EMI','','data-action="detailsCtaFees"')) +
      '</div>';
  }

  /* ── End screen ── */
  function renderEndScreen() {
    var e2 = state.endScreen;
    var firstName = e2.name ? e2.name.split(' ')[0] : 'there';
    var headLabel = e2.kind==='roi' ? 'Your ROI result' : 'Scholarship unlocked';
    var heroValue = e2.kind==='roi' ? (e2.months+' months') : (e2.waiver+' off');
    var heroSub = e2.kind==='roi' ? 'estimated payback period' : 'applied to your first-semester fee';

    var detail = '';
    if (e2.kind==='roi') {
      detail = div('db-info-card',
        div('db-info-card-title', esc(e2.program)+' · the maths') +
        div('db-roi-stats',
          div('db-roi-stat',div('db-roi-stat-label','Investment')+div('db-roi-stat-value',esc(e2.invest))) +
          div('db-roi-stat',div('db-roi-stat-label','Avg salary')+div('db-roi-stat-value',esc(e2.avgSalary))) +
          div('db-roi-stat',div('db-roi-stat-label','EMI/mo')+div('db-roi-stat-value',esc(e2.emi)))
        ) +
        div('db-roi-verdict',esc(e2.verdict))
      );
    } else {
      detail = div('db-info-card',
        div('db-schol-fee-row',
          div('',div('db-schol-net-label','Your fee after waiver')+div('db-schol-net-value',esc(e2.net))) +
          div('',div('db-schol-std-label','Standard fee')+div('db-schol-std-value',esc(e2.standard || 'Not published')))
        ) +
        div('db-schol-divider') +
        div('db-schol-reasons-label','Why you qualified') +
        div('db-schol-reasons', e2.reasons.map(function(r){return e('span','db-schol-reason',SVG.checkGreen+' '+esc(r));}).join(''))
      ) +
      div('db-info-card',
        div('db-info-card-title','How to claim it') +
        e2.steps.map(function(st){ return div('db-tool-step',div('db-tool-step-num',esc(st.n))+div('db-tool-step-text',esc(st.t))); }).join('') +
        div('db-offer-locked', SVG.clock + 'Offer locked for 7 days')
      );
    }

    return '<div id="db-end-screen" role="dialog" aria-modal="true" aria-label="'+esc(headLabel)+'">'+
      div('db-end-header',
        div('db-end-header-top',
          div('db-end-brand', div('db-end-brand-badge','DB')+e('span','db-end-brand-label','DegreeBaba Assistant')) +
          btn('db-end-close',SVG.close,'','data-action="closeEnd" aria-label="Close result"')
        ) +
        div('db-end-hero',
          div('db-end-check-ring',div('db-end-check-inner',SVG.checkWhite(21,2.6))) +
          div('db-end-head-label',esc(headLabel)) +
          div('db-end-hero-value',esc(heroValue)) +
          div('db-end-hero-sub',esc(heroSub))
        )
      ) +
      div('db-end-body',
        div('db-end-confirm',
          div('db-end-confirm-icon',SVG.phone) +
          div('',
            div('db-end-confirm-name','Locked in, '+esc(firstName)+'.') +
            div('db-end-confirm-sub','A counsellor will call '+e('span','db-end-confirm-phone',esc(e2.masked))+' within 30 minutes to confirm this offer. No spam.')
          )
        ) +
        detail
      ) +
      div('db-end-footer',
        btn('db-cta-primary','See matching programs','','data-action="endPrograms"') +
        btn('db-cta-secondary','Back to chat','','data-action="closeEnd"')
      ) +
      '</div>';
  }

  /* ── Main render ── */
  function render() {
    if (!windowEl) return;

    /* Launcher icon */
    launcher.innerHTML = state.open ? SVG.close : SVG.chat;

    /* Window visibility */
    windowEl.style.display = state.open ? 'flex' : 'none';
    if (!state.open) return;

    /* Build inner HTML */
    var html = '';

    /* Header */
    html += '<div id="db-header">'+
      div('db-header-inner',
        div('db-avatar','DB') +
        div('db-header-text',
          div('db-bot-name', esc(cfg.botName)) +
          div('db-status', e('span','db-status-dot')+'Online · replies instantly')
        ) +
        btn('db-close-btn', SVG.chevDown, 'db-close-btn-el', 'aria-label="Minimise chat"')
      ) +
      '</div>';

    /* §11.4 breadcrumb + §11.3 recently-viewed rail, both server-owned. */
    var crumbHtml = renderBreadcrumb();
    var railHtml = renderRail();
    if (crumbHtml || railHtml) {
      html += '<div id="db-context-bar">' + crumbHtml + railHtml + '</div>';
    }

    /* Messages */
    var msgsHtml = state.msgs.map(renderMsg).join('');
    /* Tool widget (inline) */
    if (state.tool) msgsHtml += renderToolWidget();
    /* Chips */
    if (!state.tool) msgsHtml += renderChips();

    html += '<div id="db-messages" aria-live="polite">'+msgsHtml+'</div>';

    /* Compare bar */
    if (state.compare.length===2) {
      html += '<div id="db-compare-bar">'+
        btn('db-compare-run-btn', SVG.compare + 'Compare '+state.compare.length+' selected', '', 'data-action="runCompare"') +
        '</div>';
    }

    /* §9 persistent navigation row — always present, outside the chip set. */
    if (state.ready) html += renderNavRow();

    /* Overlays */
    if (state.picker) html += renderPicker();
    if (state.details) html += renderDetails();
    if (state.endScreen) html += renderEndScreen();

    windowEl.innerHTML = html;

    /* Re-query scroll target */
    scrollEl = windowEl.querySelector('#db-messages');

    /* Bind events */
    bindEvents();
  }
