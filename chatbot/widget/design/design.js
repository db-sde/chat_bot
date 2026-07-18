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

  /* ─────────────────────────────────────────────────────────────
     2. STATE
  ───────────────────────────────────────────────────────────── */
  var state = {
    open: false,
    msgs: [],
    chips: [],
    hasMore: false,
    compare: [],
    acc: {},             // accordion state { "msgId:idx": bool }
    context: null,
    picker: null,
    finder: null,
    details: null,
    tool: null,
    endScreen: null,
    input: '',
    inputFocused: false,
    leadPhone: '',
    toolName: '',
    toolPhone: '',
    started: false,
    uid: 0
  };
  var cfg = {
    botName: 'DegreeBaba Assistant',
    primaryColor: '#E84010',
    position: 'right',
    page: 'course',
    apiUrl: null,
    widgetId: null
  };

  function nextId() { return 'm' + (++state.uid); }

  /* ─────────────────────────────────────────────────────────────
     3. DATA
  ───────────────────────────────────────────────────────────── */
  var UNIS = [
    { mono:'NM', bg:'#0E1F3D', name:'NMIMS Global Access', short:'NMIMS', meta:'NAAC A+ · UGC Entitled · 12 programs', pop:true },
    { mono:'MU', bg:'#7A1E1E', name:'Manipal University Online', short:'Manipal', meta:'NAAC A+ · UGC-DEB · 8 programs', pop:true },
    { mono:'AM', bg:'#1E4620', name:'Amity University Online', short:'Amity', meta:'NAAC A+ · UGC-DEB · 14 programs', pop:true },
    { mono:'LP', bg:'#5A3B00', name:'Lovely Professional University', short:'LPU', meta:'NAAC A++ · UGC-DEB · 10 programs', pop:true },
    { mono:'JA', bg:'#3A2560', name:'Jain University Online', short:'Jain', meta:'NAAC A+ · UGC-DEB · 9 programs', pop:true },
    { mono:'DY', bg:'#0B3B4A', name:'DY Patil University', short:'DY Patil', meta:'NAAC A++ · UGC-DEB · 6 programs', pop:true },
    { mono:'CU', bg:'#5A1030', name:'Chandigarh University', short:'Chandigarh', meta:'NAAC A+ · UGC-DEB · 11 programs', pop:true },
    { mono:'UP', bg:'#153E2E', name:'UPES Online', short:'UPES', meta:'NAAC A · UGC-DEB · 7 programs', pop:true },
    { mono:'AN', bg:'#334155', name:'Andhra University Online', short:'Andhra', meta:'NAAC A+ · UGC-DEB · 5 programs' },
    { mono:'BH', bg:'#334155', name:'Bharathidasan University', short:'Bharathidasan', meta:'NAAC A+ · UGC-DEB · 4 programs' },
    { mono:'GL', bg:'#334155', name:'GLA University Online', short:'GLA', meta:'NAAC A+ · UGC-DEB · 6 programs' },
    { mono:'IG', bg:'#334155', name:'IGNOU', short:'IGNOU', meta:'NAAC A++ · UGC-DEB · 20 programs' },
    { mono:'OP', bg:'#334155', name:'O.P. Jindal Global', short:'Jindal', meta:'NAAC A+ · UGC-DEB · 7 programs' },
    { mono:'SM', bg:'#334155', name:'Sikkim Manipal University', short:'Sikkim Manipal', meta:'NAAC A+ · UGC-DEB · 6 programs' }
  ];
  var SPECS = [
    { mono:'FA', bg:'#0E1F3D', name:'Finance', short:'Finance', meta:'Corporate finance, valuation, markets' },
    { mono:'MK', bg:'#7A1E1E', name:'Marketing', short:'Marketing', meta:'Brand, digital, consumer behaviour' },
    { mono:'BA', bg:'#1E4620', name:'Business Analytics', short:'Business Analytics', meta:'Data, Python, predictive modelling' },
    { mono:'HR', bg:'#5A3B00', name:'Human Resources', short:'HR', meta:'Talent, org design, labour law' },
    { mono:'OP', bg:'#3A2560', name:'Operations', short:'Operations', meta:'Supply chain, lean, logistics' },
    { mono:'IB', bg:'#0B3B4A', name:'International Business', short:'International Business', meta:'Trade, cross-border strategy' },
    { mono:'IT', bg:'#5A1030', name:'IT & Systems', short:'IT & Systems', meta:'ERP, cloud, project management' },
    { mono:'EN', bg:'#153E2E', name:'Entrepreneurship', short:'Entrepreneurship', meta:'Ventures, funding, growth' },
    { mono:'HC', bg:'#334155', name:'Healthcare Management', short:'Healthcare', meta:'Hospital ops, pharma, policy' },
    { mono:'SC', bg:'#334155', name:'Supply Chain', short:'Supply Chain', meta:'Procurement, distribution, SCM' }
  ];

  function jobFor(s) {
    var m = { 'Finance':'💼 Financial Analyst · ₹7.2 LPA avg','Marketing':'💼 Brand Manager · ₹8.0 LPA avg','Business Analytics':'💼 Data Analyst · ₹6.5 LPA avg','HR':'💼 HR Manager · ₹6.8 LPA avg','Operations':'💼 Operations Manager · ₹7.5 LPA avg','International Business':'💼 Trade Manager · ₹7.4 LPA avg' };
    return m[s] || '💼 Manager · ₹7.0 LPA avg';
  }
  function resultCards() {
    return [
      { mono:'MU', bg:'#7A1E1E', title:'Manipal Online MBA', trust:'UGC-DEB · NAAC A+', pills:['₹1.50L','24 months','6 specs'], emi:'EMI from ₹4,166/mo' },
      { mono:'NM', bg:'#0E1F3D', title:'NMIMS Online MBA', trust:'UGC Entitled · NAAC A+', pills:['₹1.71L','24 months','9 specs'], emi:'EMI from ₹4,750/mo' },
      { mono:'AM', bg:'#1E4620', title:'Amity Online MBA', trust:'UGC-DEB · NAAC A+', pills:['₹1.99L','24 months','11 specs'], emi:'EMI from ₹5,527/mo' }
    ];
  }
  function specCard(name) {
    return { mono:'NM', bg:'#0E1F3D', title:'NMIMS Online MBA · '+name, trust:'UGC Entitled · NAAC A+', pills:['₹1.71L','24 months','Online'], job:jobFor(name) };
  }
  function feesData() {
    return { total:'₹1,71,000', perSem:'₹42,750', plans:[
      { label:'Pay in full', value:'₹1,63,000', note:'Save ₹8,000 upfront' },
      { label:'Semester-wise', value:'₹42,750 × 4', note:'Most popular' },
      { label:'Monthly EMI', value:'₹4,750 × 36', note:'0% interest on select cards' }
    ], emiNote:'EMI from ₹4,750/month · 0% interest on select cards' };
  }
  function eligData() {
    return { verdict:'You qualify', sub:'Based on the standard NMIMS Online MBA criteria', reqs:[
      { ok:true, t:"Bachelor's degree in any discipline" },
      { ok:true, t:'Minimum 50% aggregate marks' },
      { ok:true, t:'No entrance exam required' },
      { optional:true, t:'Work experience', note:'Optional — not mandatory for admission' }
    ]};
  }
  function careerData() {
    return { avg:'₹6.5 LPA', range:'up to ₹12 LPA with 3+ yrs',
      roles:[{t:'Data Analyst',s:'₹6.5 LPA'},{t:'Business Analyst',s:'₹7.2 LPA'},{t:'Analytics Manager',s:'₹11 LPA'}],
      recruiters:['Deloitte','TCS','Flipkart','Accenture'] };
  }
  function reviewsData() {
    return { rating:'4.3', stars:'★★★★☆', count:'1,240',
      bars:[{stars:'5',pct:'62%'},{stars:'4',pct:'24%'},{stars:'3',pct:'9%'},{stars:'2',pct:'3%'},{stars:'1',pct:'2%'}],
      praised:'Live faculty sessions & placement support', flagged:'The LMS app can occasionally lag',
      quotes:[
        {n:'Ankit S. · Class of 2024',t:'\u201CLive faculty sessions made all the difference — it never felt like just watching a recording.\u201D'},
        {n:'Priya M. · Class of 2023',t:'\u201CFees were transparent and the EMI was easy to set up. Got a raise within a year.\u201D'}
      ]};
  }
  function syllabusData() {
    return { title:'Business Analytics · Syllabus', meta:'4 sems · 24 credits', items:[
      {n:'S1',title:'Semester 1 · Foundations',subs:['Managerial Economics','Statistics for Business','Financial Accounting','Organisational Behaviour']},
      {n:'S2',title:'Semester 2 · Core',subs:['Python for Business','Marketing Management','Operations Management','Business Research Methods']},
      {n:'S3',title:'Semester 3 · Specialisation',subs:['Predictive Modelling','Data Visualisation','Machine Learning Basics','Elective I']},
      {n:'S4',title:'Semester 4 · Capstone',subs:['Big Data Analytics','Industry Capstone Project','Elective II','Internship']}
    ]};
  }

  function programChips(uni) {
    var p = uni || '';
    return [
      {label:'Online MBA',action:'pickProgram',payload:{uni:p,prog:'Online MBA'}},
      {label:'Online BBA',action:'pickProgram',payload:{uni:p,prog:'Online BBA'}},
      {label:'Online MCA',action:'pickProgram',payload:{uni:p,prog:'Online MCA'}},
      {label:'Online MSc',action:'pickProgram',payload:{uni:p,prog:'Online MSc'}}
    ];
  }
  function specChips4() {
    return [
      {label:'Finance',action:'pickSpec',payload:'Finance'},
      {label:'Marketing',action:'pickSpec',payload:'Marketing'},
      {label:'HR',action:'pickSpec',payload:'HR'},
      {label:'Operations',action:'pickSpec',payload:'Operations'},
      {label:'Show all 9',action:'showAll'},
      {label:'Not sure yet',action:'widen'}
    ];
  }
  function specChipsAll() {
    return SPECS.slice(0,9).map(function(s){return {label:s.name,action:'pickSpec',payload:s.short};})
      .concat([{label:'Not sure yet',action:'widen'}]);
  }
  function openingChips(page) {
    if (page==='homepage') return [
      {label:'🎓 Browse universities',action:'browseUni'},{label:'📚 Browse programs',action:'browsePrograms'},
      {label:'🎯 Help me choose',action:'finder'},{label:'🛡️ Is an online degree valid?',action:'validity'},
      {label:'🧭 Career-path quiz',action:'toolQuiz'},{label:'🎁 Scholarship check',action:'toolScholarship'}
    ];
    if (page==='university') return [
      {label:'📚 Programs offered here',action:'browsePrograms'},{label:'⭐ Student reviews',action:'reviews'},
      {label:'🏅 Accreditations',action:'accreditations'},{label:'⚖️ Compare with others',action:'compare'}
    ];
    if (page==='specialization') return [
      {label:'💼 Career & salary',action:'career'},{label:'📖 Syllabus',action:'syllabus'},
      {label:'💰 Fees',action:'fees'},{label:'🔄 Other specializations',action:'otherSpecs'}
    ];
    return [
      {label:'💰 Fees & EMI',action:'fees'},{label:'🎯 Specializations',action:'specs'},
      {label:'✅ Eligibility',action:'eligibility'},{label:'⚖️ Compare universities',action:'compare'},
      {label:'🧮 ROI calculator',action:'toolRoi'},{label:'🎁 Scholarship check',action:'toolScholarship'}
    ];
  }
  function moreSet() {
    return [
      {label:'🧮 ROI calculator',action:'toolRoi'},{label:'🧭 Career-path quiz',action:'toolQuiz'},
      {label:'🎁 Scholarship check',action:'toolScholarship'},{label:'⚖️ Compare',action:'compare'},
      {label:'💰 Fees & EMI',action:'fees'},{label:'📞 Talk to a counsellor',action:'counsellor'}
    ];
  }
  function greet(page) {
    if (page==='homepage') return "Hi — I can help you find the right online degree. Where should we start?";
    if (page==='university') return "You're viewing NMIMS Global. Ask me anything, or pick a shortcut below.";
    if (page==='specialization') return "You're viewing the Business Analytics specialization. What would you like to know?";
    return "You're viewing the NMIMS Online MBA. What would you like to know?";
  }
  function presetContext(page) {
    if (page==='university') return {label:'NMIMS'};
    if (page==='course') return {label:'NMIMS · Online MBA'};
    if (page==='specialization') return {label:'NMIMS · MBA · Business Analytics'};
    return null;
  }
  function followSet(kind) {
    if (kind==='uni') return [{label:'📚 Programs offered',action:'browsePrograms'},{label:'🏅 Accreditations',action:'accreditations'},{label:'⭐ Student reviews',action:'reviews'}];
    if (kind==='course') return [{label:'💰 Fee plans & EMI',action:'fees'},{label:'✅ Eligibility',action:'eligibility'},{label:'🎯 Specializations',action:'specs'}];
    if (kind==='spec') return [{label:'💼 Career & salary',action:'career'},{label:'📖 Syllabus',action:'syllabus'},{label:'🔄 Other specializations',action:'otherSpecs'}];
    return [];
  }
  function toolCtas() {
    return [{label:'📞 Talk to a counsellor',action:'counsellor'},{label:'⚖️ Compare these',action:'compare'},{label:'🔍 Browse more',action:'browsePrograms'}];
  }

  /* Tool definitions */
  function toolDef(kind) {
    if (kind==='roi') return {icon:'🧮',title:'ROI Calculator',promise:'See how fast this program pays for itself.',stepLabel:'2 quick questions',steps:[
      {q:'Which program are you considering?',opts:['Online MBA','Online MCA','Online BBA','Online MSc']},
      {q:'What do you earn right now?',opts:['Under ₹3L','₹3–6L','₹6–10L','₹10L+']}
    ]};
    if (kind==='quiz') return {icon:'🧭',title:'Career-Path Quiz',promise:"Answer 5 quick questions and we'll point you to your best-fit field.",stepLabel:'5 quick questions',steps:[
      {q:'What kind of work energises you most?',opts:['Working with numbers & data','Persuading & connecting with people','Building & streamlining systems','Leading and developing people']},
      {q:"Pick a project you'd enjoy:",opts:['Analysing a sales dataset','Launching a campaign','Fixing a supply bottleneck','Building a hiring plan']},
      {q:'What matters most to you in a role?',opts:['Sharp problem-solving','Creativity & visibility','Structure & efficiency','Impact on people']},
      {q:'How do you like to spend a workday?',opts:['With dashboards & tools','With clients & pitches','With processes & plans','With teams & 1:1s']},
      {q:'Where do you want to be in 5 years?',opts:['Analytics lead','Marketing head','Operations director','HR business partner']}
    ]};
    return {icon:'🎁',title:'Scholarship Checker',promise:'Check which fee waivers you qualify for — takes under a minute.',stepLabel:'7 quick questions',steps:[
      {q:'Your highest qualification?',opts:['12th pass','Graduate','Postgraduate']},
      {q:'Your graduation aggregate?',opts:['Below 50%','50–60%','60–75%','Above 75%']},
      {q:'Work experience so far?',opts:['None','0–2 yrs','2–5 yrs','5+ yrs']},
      {q:'Which category do you belong to?',opts:['General','OBC','SC / ST','EWS']},
      {q:'Are you a woman applicant?',opts:['Yes','No']},
      {q:'From a defence / ex-servicemen family?',opts:['Yes','No']},
      {q:'When do you want to start?',opts:['This month','Next 3 months','Later']}
    ]};
  }
  function roiMonths(b) { return ({'Under ₹3L':7,'₹3–6L':9,'₹6–10L':11,'₹10L+':14})[b]||9; }
  function quizArea(answers) {
    var areas=['Business Analytics','Marketing','Operations','HR'], tally=[0,0,0,0];
    Object.values(answers).forEach(function(a){if(a&&a.i!=null&&a.i<4)tally[a.i]++;});
    var mi=0; tally.forEach(function(v,i){if(v>tally[mi])mi=i;}); return areas[mi];
  }
  function quizCards(area) {
    return [
      {mono:'NM',bg:'#0E1F3D',title:'NMIMS Online MBA · '+area,trust:'UGC Entitled · NAAC A+',pills:['₹1.71L','24 months','Online'],job:jobFor(area)},
      {mono:'MU',bg:'#7A1E1E',title:'Manipal Online MBA · '+area,trust:'UGC-DEB · NAAC A+',pills:['₹1.50L','24 months','Online'],job:jobFor(area)},
      {mono:'AM',bg:'#1E4620',title:'Amity Online MBA · '+area,trust:'UGC-DEB · NAAC A+',pills:['₹1.99L','24 months','Online'],job:jobFor(area)}
    ];
  }
  function scholarshipWaiver(a) {
    var w=10000;
    var m=(a[1]||{}).l;
    if(m==='60–75%')w+=5000; if(m==='Above 75%')w+=12000;
    if((a[3]||{}).l&&a[3].l!=='General')w+=10000;
    if((a[4]||{}).l==='Yes')w+=6000; if((a[5]||{}).l==='Yes')w+=10000;
    if((a[6]||{}).l==='This month')w+=5000;
    return '₹'+w.toLocaleString('en-IN');
  }
  function scholarshipReasons(a) {
    var r=['Base programme waiver'];
    var m=(a[1]||{}).l;
    if(m==='60–75%')r.push('Merit — 60–75% aggregate');
    if(m==='Above 75%')r.push('Merit — 75%+ aggregate');
    if((a[3]||{}).l&&a[3].l!=='General')r.push('Reserved-category benefit');
    if((a[4]||{}).l==='Yes')r.push('Women applicant grant');
    if((a[5]||{}).l==='Yes')r.push('Defence-family concession');
    if((a[6]||{}).l==='This month')r.push('Early-bird — joining this month');
    return r;
  }
  function toolPartialText(t) {
    if(t.kind==='roi'){var m=roiMonths((t.answers[1]||{}).l);return m<12?'Your payback period is excellent — under a year.':'Your payback period is strong — just over a year.';}
    if(t.kind==='quiz')return 'Your best-fit area looks like '+quizArea(t.answers)+'.';
    return 'You\'ve qualified for a fee waiver.';
  }
  function maskedPhone(phone) {
    var d=(phone||'').replace(/\D/g,'');
    return d.length>=5?('+91 '+d.slice(0,2)+' ••••• '+d.slice(-3)):'+91 '+d;
  }
  function toolFull(t) {
    if(t.kind==='roi'){var m=roiMonths((t.answers[1]||{}).l);return {
      msgs:[{kind:'bot',text:'On a ₹1.71L investment, at your current salary you\'ll typically recover the full cost in about '+m+' months. Here are the 3 best-value programs:'},
        {kind:'toolResult',tr:{label:'Estimated payback period',value:m+' months',headBg:'#EAF3DE',labelColor:'#3B6D11'}},
        {kind:'cards',cards:resultCards()}],chips:toolCtas()};}
    if(t.kind==='quiz'){var area=quizArea(t.answers);return {
      msgs:[{kind:'bot',text:'Based on your answers, '+area+' is your strongest fit. Three programs to explore:'},
        {kind:'cards',cards:quizCards(area)}],chips:toolCtas()};}
    var amt=scholarshipWaiver(t.answers);return {
      msgs:[{kind:'bot',text:"You qualify. Here's your fee-waiver offer:"},
        {kind:'toolResult',tr:{label:'Fee waiver unlocked',value:amt+' off',headBg:'#EAF3DE',labelColor:'#3B6D11',steps:[
          {n:1,t:'A counsellor verifies your details on a quick call'},
          {n:2,t:'Submit your marksheet & photo ID'},
          {n:3,t:'Waiver applied to your first-semester fee'}]}}],chips:toolCtas()};
  }
  function toolGeneric(t) {
    var soft=[{label:'📞 Talk to a counsellor',action:'counsellor'},{label:'🔍 Browse more',action:'browsePrograms'}];
    if(t.kind==='roi')return {msgs:[{kind:'bot',text:'No problem — here are 3 programs with the strongest ROI, no details needed:'},{kind:'cards',cards:resultCards()}],chips:soft};
    if(t.kind==='quiz'){var area=quizArea(t.answers);return {msgs:[{kind:'bot',text:'Here are 3 programs in the '+area+' area to explore:'},{kind:'cards',cards:quizCards(area)}],chips:soft};}
    return {msgs:[{kind:'bot',text:'Fee waivers are available on most programs. A counsellor can confirm the exact amount you qualify for.'}],chips:soft};
  }
  function buildEnd(t) {
    var name=(state.toolName||'').trim(), masked=maskedPhone(state.toolPhone);
    if(t.kind==='roi'){var months=roiMonths((t.answers[1]||{}).l);return {kind:'roi',name,masked,program:(t.answers[0]||{}).l||'Online MBA',months,invest:'₹1,71,000',avgSalary:'₹8.4 LPA',emi:'₹4,750',verdict:months<12?'You recover the full programme cost in under a year — one of the strongest returns on our shelf.':'You recover the full programme cost in just over a year — a strong, low-risk return.'};}
    var waiver=scholarshipWaiver(t.answers);
    var waiverNum=parseInt(waiver.replace(/[^\d]/g,''),10)||0;
    var net='₹'+(171000-waiverNum).toLocaleString('en-IN');
    return {kind:'scholarship',name,masked,waiver,net,reasons:scholarshipReasons(t.answers),steps:[{n:1,t:'A counsellor verifies your details on a quick call'},{n:2,t:'Submit your marksheet & photo ID'},{n:3,t:'Waiver is applied to your first-semester fee'}]};
  }

  /* ─────────────────────────────────────────────────────────────
     4. FLOW
  ───────────────────────────────────────────────────────────── */
  function getUni() { return state.context && state.context.label ? state.context.label.split(' · ')[0] : 'NMIMS'; }

  var scrollEl; // set after render
  function scrollToBottom() {
    if (scrollEl) setTimeout(function(){ scrollEl.scrollTop = scrollEl.scrollHeight; }, 30);
  }

  function respond(userLabel, msgSpecs, chips, ctx, echo) {
    var items = [];
    if (echo !== false && userLabel) items.push({ kind:'user', text:userLabel, id:nextId() });
    var tid = nextId();
    items.push({ kind:'typing', id:tid });
    state.started = true;
    state.chips = [];
    state.input = '';
    state.inputFocused = false;
    state.msgs = state.msgs.concat(items);
    render();
    scrollToBottom();
    setTimeout(function() {
      var withIds = msgSpecs.map(function(m){ return Object.assign({}, m, {id:nextId()}); });
      state.msgs = state.msgs.filter(function(m){ return m.id !== tid; }).concat(withIds);
      state.chips = chips || [];
      if (ctx !== undefined) state.context = ctx;
      render();
      scrollToBottom();
    }, 700);
  }

  function onChip(ch) {
    var a = ch.action, L = ch.label, pl = ch.payload;
    switch (a) {
      case 'browseUni': state.picker = {title:'Browse universities',kind:'uni',query:''}; render(); return;
      case 'browseSpec': state.picker = {title:'Browse by specialization',kind:'spec',query:''}; render(); return;
      case 'browsePrograms': respond(L,[{kind:'bot',text:'We partner with 4 online programs. Which one?'}],programChips(getUni())); return;
      case 'finder': startFinder(); return;
      case 'more': {
        var have = new Set(state.chips.map(function(c){return c.action;}));
        state.chips = state.chips.concat(moreSet().filter(function(c){return !have.has(c.action);}));
        state.hasMore = false;
        render(); return;
      }
      case 'toolRoi': startTool('roi'); return;
      case 'toolQuiz': startTool('quiz'); return;
      case 'toolScholarship': startTool('scholarship'); return;
      case 'showAll': state.chips = specChipsAll(); render(); return;
      case 'pickProgram':
        respond(L,[{kind:'bot',text:pl.uni+' '+pl.prog+' has 9 specializations. Which area interests you?'}],specChips4(),{label:pl.uni+' · '+pl.prog});
        return;
      case 'pickSpec':
        respond(L,[{kind:'bot',text:pl+' — here\u2019s the strongest match:'},{kind:'cards',cards:[specCard(pl)]}],followSet('spec'));
        return;
      case 'specs': case 'otherSpecs':
        respond(L,[{kind:'bot',text:'NMIMS Online MBA has 9 specializations. Which area interests you?'}],specChips4());
        return;
      case 'widen': doResults(L); return;
      case 'compare': case 'compareTop': doCompare(L); return;
      case 'validity':
        respond(L,[{kind:'bot',text:"Yes — an NMIMS Online MBA is UGC-entitled and legally equal to an on-campus degree for jobs, promotions and PhD. The certificate does not say \u2018online\u2019."}],
          [{label:'🎓 Show me the proof',action:'proof'},{label:'🎓 Browse universities',action:'browseUni'},{label:'📞 Talk to a counsellor',action:'counsellor'}]);
        return;
      case 'proof': case 'certificate':
        respond(L,[{kind:'bot',text:"The certificate reads \u2018Master of Business Administration\u2019 — identical to the on-campus degree. It carries the UGC-DEB entitlement number and never mentions \u2018online\u2019."}],
          [{label:'💰 Fee plans & EMI',action:'fees'},{label:'📚 Browse programs',action:'browsePrograms'},{label:'📞 Talk to a counsellor',action:'counsellor'}]);
        return;
      case 'fees': case 'feePlans': case 'seeFees':
        respond(L,[{kind:'fees',fee:feesData()},{kind:'lead',text:"Want me to check today's fee offer and seat availability? Just your number — no spam."}],
          [{label:'📝 Admission steps',action:'admissionSteps'},{label:'⚖️ Compare',action:'compare'},{label:'📞 Talk to a counsellor',action:'counsellor'}]);
        return;
      case 'eligibility':
        respond(L,[{kind:'elig',elig:eligData()},{kind:'lead',text:"Want me to confirm your eligibility and today's seat availability? Just your number — no spam."}],
          [{label:'📝 How to apply',action:'admissionSteps'},{label:'💰 See fees',action:'fees'},{label:'📞 Talk to a counsellor',action:'counsellor'}]);
        return;
      case 'admissionSteps': case 'howToApply':
        respond(L,[{kind:'bot',text:"1) Fill the application form  2) Upload marksheet & photo ID  3) Pay ₹1,000 registration  4) Enrolment confirmed in 48 hours."}],
          [{label:'💰 See fees',action:'fees'},{label:'✅ Eligibility',action:'eligibility'},{label:'📞 Talk to a counsellor',action:'counsellor'}]);
        return;
      case 'reviews':
        respond(L,[{kind:'bot',text:"Verified learner feedback for NMIMS Online MBA:"},{kind:'reviews',rev:reviewsData()}],followSet('course'));
        return;
      case 'accreditations':
        respond(L,[{kind:'bot',text:"UGC Entitled · NAAC A+ · AICTE approved · AIU member. The MBA is also NBA-accredited."}],
          [{label:'💰 Fee plans & EMI',action:'fees'},{label:'⚖️ Compare',action:'compare'},{label:'📞 Talk to a counsellor',action:'counsellor'}]);
        return;
      case 'career':
        respond(L,[{kind:'bot',text:"Here\u2019s the career outlook for a Business Analytics MBA:"},{kind:'career',career:careerData()}],
          [{label:'📖 Syllabus',action:'syllabus'},{label:'💰 Fees',action:'fees'},{label:'📞 Talk to a counsellor',action:'counsellor'}]);
        return;
      case 'syllabus':
        respond(L,[{kind:'bot',text:"The Business Analytics syllabus runs over 4 semesters — tap any to expand:"},{kind:'syllabus',syl:syllabusData()}],
          [{label:'💼 Career & salary',action:'career'},{label:'💰 Fees',action:'fees'},{label:'📞 Talk to a counsellor',action:'counsellor'}]);
        return;
      case 'counsellor':
        respond(L,[{kind:'lead',text:"Happy to connect you. Just your number and a counsellor will call within 30 minutes — no spam."}],[]);
        return;
      default:
        respond(L,[{kind:'bot',text:"I don't have that confirmed — I'd rather not guess on something this important."}],
          [{label:'📞 Get it confirmed',action:'counsellor'},{label:'🔍 Browse programs',action:'browsePrograms'},{label:'⚖️ Compare',action:'compare'}]);
        return;
    }
  }

  function doResults(userLabel) {
    respond(userLabel,[{kind:'bot',text:'Here are your top 3 matches — cheapest first.'},{kind:'cards',cards:resultCards()}],
      [{label:'⚖️ Compare top 2',action:'compareTop'},{label:'💰 Fee plans & EMI',action:'fees'},{label:'📞 Talk to a counsellor',action:'counsellor'}],undefined,!!userLabel);
  }
  function doCompare(userLabel) {
    var sel = state.compare, aName='Manipal', bName='NMIMS', rows, verdict;
    if (sel.length===2) {
      var x=sel[0], y=sel[1];
      aName=x.title.split(' Online')[0].split(' MBA')[0].trim();
      bName=y.title.split(' Online')[0].split(' MBA')[0].trim();
      rows=[{k:'Fees',a:x.pills[0],b:y.pills[0]},{k:'Duration',a:x.pills[1],b:y.pills[1]},{k:'Mode',a:'Online',b:'Online'},{k:'Approval',a:x.trust,b:y.trust},{k:'Specializations',a:x.pills[2]||'—',b:y.pills[2]||'—'},{k:'EMI',a:x.emi?x.emi.replace('EMI from ',''):'—',b:y.emi?y.emi.replace('EMI from ',''):'—'}];
      verdict='Pick '+aName+' if fees matter most; '+bName+' for wider specialisations and brand recall.';
    } else {
      rows=[{k:'Fees',a:'₹1.50L',b:'₹1.71L'},{k:'Duration',a:'24 mo',b:'24 mo'},{k:'Mode',a:'Online',b:'Online'},{k:'NAAC',a:'A+',b:'A+'},{k:'UGC',a:'UGC-DEB',b:'Entitled'},{k:'Specs',a:'6',b:'9'},{k:'EMI',a:'₹4,166/mo',b:'₹4,750/mo'},{k:'Eligibility',a:'50% grad',b:'50% grad'}];
      verdict='Pick Manipal if fees matter most; NMIMS if brand recall and specialisation range matter more.';
    }
    state.compare = [];
    respond(userLabel||'Compare',[{kind:'bot',text:aName+' vs '+bName+', side by side:'},{kind:'compare',rows:rows,verdict:verdict,aName:aName,bName:bName}],
      [{label:'💰 Fee plans & EMI',action:'fees'},{label:'✅ Eligibility',action:'eligibility'},{label:'📞 Talk to a counsellor',action:'counsellor'}]);
  }
  function toggleCompare(card) {
    var has = state.compare.find(function(c){return c.title===card.title;});
    if (has) { state.compare = state.compare.filter(function(c){return c.title!==card.title;}); }
    else if (state.compare.length>=2) { state.compare = [state.compare[1],card]; }
    else { state.compare = state.compare.concat([card]); }
    render();
  }
  function toggleAcc(mid, i) {
    var key = mid+':'+i;
    var cur = state.acc[key] !== undefined ? state.acc[key] : (i===0);
    state.acc[key] = !cur;
    render();
  }
  function submitLead(id) {
    if ((state.leadPhone||'').replace(/\D/g,'').length < 10) return;
    state.msgs = state.msgs.map(function(m){ return m.id===id ? Object.assign({},m,{leadDone:true}) : m; });
    render();
  }
  function openDetails(card) {
    state.details = {
      mono:card.mono, bg:card.bg, title:card.title, trust:card.trust, pills:card.pills,
      hero:card.title+' is delivered fully online with live and recorded sessions, industry projects and dedicated placement support — built for working professionals who can\u2019t pause their careers.',
      accr:['UGC Entitled','NAAC A+','AICTE Approved','AIU Member'],
      steps:[{n:1,t:'Fill the application form (5 minutes)'},{n:2,t:'Upload marksheet & photo ID'},{n:3,t:'Pay ₹1,000 registration fee'},{n:4,t:'Enrolment confirmed within 48 hours'}],
      reviews:[{n:'Ankit S. · Class of 2024',t:'Live faculty sessions made all the difference — it never felt like a recording.'},{n:'Priya M. · Class of 2023',t:'Fees were transparent and the EMI was easy to set up. Got a raise within a year.'}],
      faqs:[{q:'Is this valid for government jobs?',a:'Yes — UGC-entitled degrees are accepted for government roles, promotions and PhD.'},{q:'Do I need to visit campus?',a:'No — coursework and exams are fully online.'},{q:'Can I pay in instalments?',a:'Yes — EMI from ₹4,750/month with 0% interest on select cards.'}]
    };
    render();
  }
  /* Picker */
  function pickItem(row) {
    var p = state.picker;
    state.picker = null;
    if (p.kind==='uni') {
      respond(row.name,[{kind:'bot',text:row.short+' offers 4 online programs. Which one?'}],programChips(row.short),{label:row.short});
    } else {
      respond(row.name,[{kind:'bot',text:'Top matches for '+row.name+', cheapest first:'},{kind:'cards',cards:[specCard(row.short)]}],followSet('spec'),{label:'NMIMS · MBA · '+row.short});
    }
  }
  /* Finder */
  var FINDER_QS = [
    {q:'Which program?',opts:['Online MBA','Online MCA','Online Executive MBA','Online MSc']},
    {q:'Which area interests you?',opts:['Finance','Marketing','Business Analytics','HR','Show all','Not sure']},
    {q:'Approval priority?',opts:['UGC-DEB only','NAAC A+','No preference']},
    {q:'Your budget?',opts:['Under ₹1L','₹1–2L','₹2–3L','₹3L+','No preference']}
  ];
  function startFinder() {
    var page = cfg.page;
    var pre = (page==='course'||page==='specialization');
    state.finder = {answers:pre?{0:'Online MBA'}:{},idx:pre?1:0,prefill:pre};
    state.chips = []; state.hasMore = false;
    render(); scrollToBottom();
  }
  function finderAnswer(opt) {
    var f = state.finder, idx = f.idx, nidx = idx+1;
    var answers = Object.assign({}, f.answers, {[idx]:opt});
    if (nidx>3) { state.finder = null; doResults(null); }
    else { state.finder = Object.assign({}, f, {answers:answers, idx:nidx}); render(); scrollToBottom(); }
  }
  /* Tool */
  function startTool(kind) {
    state.tool = {kind:kind,phase:'entry',idx:0,answers:{}};
    state.toolName = ''; state.toolPhone = ''; state.chips = []; state.hasMore = false; state.started = true;
    render(); scrollToBottom();
  }
  function toolAnswer(opt, oi) {
    var t = state.tool;
    var answers = Object.assign({}, t.answers, {[t.idx]:{l:opt,i:oi}});
    var len = toolDef(t.kind).steps.length;
    if (t.idx+1 >= len) { state.tool = Object.assign({}, t, {answers:answers, phase:'partial'}); }
    else { state.tool = Object.assign({}, t, {answers:answers, idx:t.idx+1}); }
    render(); scrollToBottom();
  }
  function toolSubmit() {
    if (!(state.toolName||'').trim()) return;
    if ((state.toolPhone||'').replace(/\D/g,'').length < 10) return;
    var t = state.tool;
    if (t.kind==='quiz') {
      var r = toolFull(t);
      state.tool = null; state.toolName = ''; state.toolPhone = '';
      respond(null,r.msgs,r.chips,undefined,false);
      return;
    }
    var end = buildEnd(t);
    state.tool = null; state.endScreen = end;
    render();
  }
  function toolSkip() {
    var r = toolGeneric(state.tool);
    state.tool = null;
    respond(null,r.msgs,r.chips,undefined,false);
  }
  function onEndPrograms() {
    var e = state.endScreen;
    var text = e&&e.kind==='scholarship'
      ? 'Here are 3 programs where your '+e.waiver+' waiver applies — cheapest first:'
      : 'Here are the 3 best-value programs for your payback goal — cheapest first:';
    state.endScreen = null;
    respond(null,[{kind:'bot',text:text},{kind:'cards',cards:resultCards()}],toolCtas(),undefined,false);
  }
  function onSendText() {
    var t = (state.input||'').trim(); if (!t) return;
    var action = 'fallback';
    var low = t.toLowerCase();
    if (/fee|emi|cost|price|₹/.test(low)) action='fees';
    else if (/elig|qualif|require/.test(low)) action='eligibility';
    else if (/valid|recogn|worth|legit/.test(low)) action='validity';
    else if (/compar|vs|versus|better/.test(low)) action='compare';
    else if (/special|stream|branch/.test(low)) action='specs';
    onChip({action:action, label:t});
  }
  function resetChat() {
    var page = cfg.page;
    state.uid = 0;
    state.msgs = [{kind:'bot',text:greet(page),id:nextId()}];
    state.chips = openingChips(page);
    state.hasMore = true;
    state.compare = []; state.acc = {};
    state.context = presetContext(page);
    state.picker = null; state.finder = null; state.details = null; state.tool = null; state.endScreen = null;
    state.input = ''; state.inputFocused = false; state.leadPhone = ''; state.toolName = ''; state.toolPhone = ''; state.started = false;
    render(); scrollToBottom();
  }

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
    x10: '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
    send: '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>',
    back: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>',
    dollar: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#E84010" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>',
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
    if (m.kind==='typing') return div('db-msg', div('db-typing', div('db-dot')+''+div('db-dot')+''+div('db-dot')));
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
    return '';
  }
  function renderCard(c, mid) {
    var inC = !!state.compare.find(function(x){return x.title===c.title;});
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
        btn('db-btn-primary','View details','','data-action="viewDetails" data-mid="'+mid+'" data-title="'+esc(c.title)+'"') +
        btn(cmpCls, cmpLabel, '', 'data-action="toggleCompare" data-title="'+esc(c.title)+'"')
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
        btn('db-lead-send','Send','','data-action="submitLead" data-mid="'+m.id+'"')
      ) +
      div('db-lead-note','No spam. One call, today\'s offer.')
    );
  }
  function renderFees(f) {
    return div('db-fees',
      div('db-fees-hero',
        div('',div('db-fees-total-label','Total programme fee')+div('db-fees-total-value',esc(f.total))) +
        div('',div('db-fees-sem-label','Per semester')+div('db-fees-sem-value',esc(f.perSem)))
      ) +
      div('db-fees-plans', f.plans.map(function(p){
        return div('db-fees-plan-row',
          div('',div('db-fees-plan-label',esc(p.label))+div('db-fees-plan-note',esc(p.note))) +
          div('db-fees-plan-value',esc(p.value))
        );
      }).join('')) +
      div('db-fees-emi', SVG.dollar + e('span','',esc(f.emiNote)))
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
      div('db-career-recruiters',
        div('db-career-recruiters-label','Top recruiters') +
        div('db-recruiter-tags', c.recruiters.map(function(r){return e('span','db-recruiter-tag',esc(r));}).join(''))
      )
    );
  }
  function renderReviews(rv) {
    return div('db-reviews',
      div('db-reviews-summary',
        div('',div('db-rating-big',esc(rv.rating))+div('db-rating-stars',esc(rv.stars))+div('db-rating-count',esc(rv.count)+' reviews')) +
        div('db-rating-bars', rv.bars.map(function(b){
          return div('db-bar-row', e('span','db-bar-label',esc(b.stars))+div('db-bar-track',div('db-bar-fill','','style="width:'+b.pct+'"')));
        }).join(''))
      ) +
      div('db-reviews-sentiment',
        div('db-praised',div('db-praised-label','Most praised')+div('db-praised-text',esc(rv.praised))) +
        div('db-flagged',div('db-flagged-label','Most flagged')+div('db-flagged-text',esc(rv.flagged)))
      ) +
      div('db-reviews-quotes', rv.quotes.map(function(q){
        return div('db-quote',div('db-quote-text',esc(q.t))+div('db-quote-name',esc(q.n)));
      }).join(''))
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

  /* ── Chips ── */
  function renderChips() {
    if (!state.chips.length) return '';
    return div('db-chips-area',
      (!state.started ? div('db-chips-hint','Or type your question below.') : '') +
      div('db-chip-grid', state.chips.map(function(ch,i){
        return btn('db-chip',esc(ch.label),'','data-action="chip" data-idx="'+i+'"');
      }).join('')) +
      (state.hasMore ? btn('db-more-btn','More ⌄','','data-action="chip" data-idx="-1"') : '')
    );
  }

  /* ── Tool widget ── */
  function renderToolWidget() {
    var t = state.tool;
    var def = toolDef(t.kind);
    var len = def.steps.length;
    var cur = def.steps[t.idx] || {q:'',opts:[]};
    var pct = ((t.idx+1)/len*100)+'%';
    var progress = (t.idx+1)+' of '+len;

    var header = div('db-tool-header',
      div('db-tool-header-left',
        div('db-tool-icon-badge',def.icon) +
        div('db-tool-title',esc(def.title))
      ) +
      btn('db-tool-close',SVG.x,'','data-action="closeTool"')
    );

    var body = '';
    if (t.phase==='entry') {
      body = div('db-tool-promise',esc(def.promise)) +
        div('db-tool-step-badge',esc(def.stepLabel)) +
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
        (t.idx>0 ? btn('db-tool-back','‹ Back','','data-action="toolBack"') : '');
    } else if (t.phase==='partial') {
      body = div('db-tool-partial-box',
          div('db-tool-partial-check',SVG.checkWhite(14,2.8)) +
          div('db-tool-partial-text',esc(toolPartialText(t)))
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

    return div('db-msg', div('db-msg','',''+'id="db-tool-widget"') +
      '<div id="db-tool-widget">'+header+body+'</div>');
  }

  /* ── Finder widget ── */
  function renderFinderWidget() {
    var f = state.finder;
    var cur = FINDER_QS[f.idx] || {q:'',opts:[]};
    var pct = (f.idx/4*100)+'%';
    var progress = (f.idx+1)+' of 4';
    return '<div id="db-finder-widget">'+
      div('db-finder-title-row',
        div('db-finder-title','Help me choose') +
        btn('db-finder-close',SVG.x,'','data-action="closeFinder"')
      ) +
      div('db-tool-progress',
        div('db-progress-track',div('db-progress-fill','','style="width:'+pct+'"')) +
        e('span','db-progress-label',progress)
      ) +
      (f.prefill ? div('db-prefill-note','Program pre-filled from this page ✓') : '') +
      div('db-finder-question',esc(cur.q)) +
      div('db-finder-opts', cur.opts.map(function(o){
        return btn('db-finder-opt',esc(o),'','data-action="finderAnswer" data-opt="'+esc(o)+'"');
      }).join('')) +
      btn('db-finder-skip','Skip → show results now','','data-action="finderSkip"') +
      '</div>';
  }

  /* ── Picker ── */
  function renderPicker() {
    var p = state.picker;
    var q = (p.query||'').toLowerCase();
    var src = p.kind==='uni' ? UNIS : SPECS;
    var filtered = src.filter(function(r){ return !q || r.name.toLowerCase().includes(q) || (r.short||'').toLowerCase().includes(q); });
    var popular = p.kind==='uni' ? filtered.filter(function(r){return r.pop;}) : filtered.slice(0,4);
    var rowHtml = function(r) {
      return btn('db-picker-row',
        div('db-picker-mono',esc(r.mono),'style="background:'+r.bg+'"') +
        div('',div('db-picker-row-name',esc(r.name))+div('db-picker-row-meta',esc(r.meta))),
        '','data-action="pickItem" data-key="'+esc(r.name)+'" data-kind="'+p.kind+'"'
      );
    };
    return '<div id="db-picker">'+
      div('db-picker-scrim','','data-action="closePicker"') +
      div('db-picker-sheet',
        div('db-picker-header',
          div('db-picker-handle') +
          div('db-picker-title-row',
            div('db-picker-title',esc(p.title)) +
            btn('db-picker-close',SVG.x,'','data-action="closePicker"')
          ) +
          div('db-picker-search',
            SVG.search +
            e('input','db-picker-input','','placeholder="'+(p.kind==='uni'?'Search 56 universities…':'Search 40 disciplines…')+'" data-action="pickerInput" value="'+esc(p.query||'')+'"')
          )
        ) +
        div('db-picker-list',
          (!q && popular.length ? div('db-picker-section-label','⭐ Popular') + popular.map(rowHtml).join('') : '') +
          div('db-picker-section-label','All') +
          filtered.map(rowHtml).join('') +
          (filtered.length===0 ? div('db-picker-empty','Nothing matched. Try a shorter search.') : '')
        )
      ) +
      '</div>';
  }

  /* ── Details overlay ── */
  function renderDetails() {
    var d = state.details;
    return '<div id="db-details">'+
      div('db-details-header',
        btn('db-details-back', SVG.back+'Back','','data-action="closeDetails"') +
        div('db-details-title-row',
          div('db-details-mono',esc(d.mono),'style="background:'+d.bg+'"') +
          div('',div('db-details-name',esc(d.title))+div('db-details-trust',esc(d.trust)))
        )
      ) +
      div('db-details-body',
        div('db-details-pills', d.pills.map(function(p){return div('db-details-pill',esc(p));}).join('')) +
        div('db-info-card', div('db-info-card-body',esc(d.hero))) +
        div('db-info-card', div('db-info-card-title','Accreditations') + div('db-accr-tags', d.accr.map(function(a){return e('span','db-accr-tag',esc(a));}).join(''))) +
        div('db-info-card', div('db-info-card-title','Admission steps') + div('db-admission-steps', d.steps.map(function(s){return div('db-admission-step',div('db-step-num',esc(s.n))+div('db-step-text',esc(s.t)));}).join(''))) +
        div('db-info-card', div('db-info-card-title','What learners say') + div('db-review-items', d.reviews.map(function(r){return div('',div('db-review-name',esc(r.n))+div('db-review-text',esc(r.t)));}).join(''))) +
        div('db-info-card', div('db-info-card-title','FAQs') + div('db-faq-items', d.faqs.map(function(f){return div('',div('db-faq-q',esc(f.q))+div('db-faq-a',esc(f.a)));}).join('')))
      ) +
      div('db-details-footer', btn('db-cta-primary','Ask about fees & EMI','','data-action="closeDetails"')) +
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
          div('',div('db-schol-std-label','Standard fee')+div('db-schol-std-value','₹1,71,000'))
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

    return '<div id="db-end-screen">'+
      div('db-end-header',
        div('db-end-header-top',
          div('db-end-brand', div('db-end-brand-badge','DB')+e('span','db-end-brand-label','DegreeBaba Assistant')) +
          btn('db-end-close',SVG.close.replace('stroke="#fff"','stroke="#fff"'),'','data-action="closeEnd"')
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
        btn('db-close-btn', SVG.chevDown, 'db-close-btn-el')
      ) +
      '</div>';

    /* Context chip */
    if (state.context) {
      html += '<div id="db-context-bar">'+
        div('db-context-chip',
          div('db-context-dot') +
          esc(state.context.label) +
          btn('db-context-clear', SVG.x10, '', 'data-action="clearContext"')
        ) +
        '</div>';
    }

    /* Messages */
    var msgsHtml = state.msgs.map(renderMsg).join('');
    /* Finder widget (inline in message stream) */
    if (state.finder) msgsHtml += renderFinderWidget();
    /* Tool widget (inline) */
    if (state.tool) msgsHtml += renderToolWidget();
    /* Chips */
    if (state.chips.length && !state.finder && !state.tool) msgsHtml += renderChips();

    html += '<div id="db-messages">'+msgsHtml+'</div>';

    /* Compare bar */
    if (state.compare.length===2) {
      html += '<div id="db-compare-bar">'+
        btn('db-compare-run-btn', SVG.compare + 'Compare '+state.compare.length+' selected', '', 'data-action="runCompare"') +
        '</div>';
    }

    /* Input bar */
    var sendActive = (state.input||'').trim().length>0;
    var inputBorder = state.inputFocused ? '#0E1F3D' : '#E5E7EB';
    html += '<div id="db-input-bar">'+
      div('db-input-wrapper'+(state.inputFocused?' focused':''),
        e('input','db-input','','placeholder="Type your question…" id="db-input-el" value="'+esc(state.input)+'" autocomplete="off"'),
        'style="border-color:'+inputBorder+'"'
      ) +
      btn('db-send-btn'+(sendActive?' active':''), SVG.send, 'db-send-btn-el') +
      '</div>';

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

  /* ─────────────────────────────────────────────────────────────
     6. EVENT DELEGATION
  ───────────────────────────────────────────────────────────── */
  function bindEvents() {
    /* Close button */
    var closeBtn = windowEl.querySelector('#db-close-btn-el');
    if (closeBtn) closeBtn.addEventListener('click', function(){ state.open = false; render(); });

    /* Clear context */
    delegate('[data-action="clearContext"]', function(){ state.context = null; render(); });

    /* Chip clicks */
    delegate('[data-action="chip"]', function(el){
      var idx = parseInt(el.getAttribute('data-idx'));
      if (idx===-1) { onChip({action:'more',label:'More ⌄'}); return; }
      var ch = state.chips[idx];
      if (ch) onChip(ch);
    });

    /* View details */
    delegate('[data-action="viewDetails"]', function(el){
      var title = el.getAttribute('data-title');
      var mid = el.getAttribute('data-mid');
      var msg = state.msgs.find(function(m){return m.id===mid;});
      if (msg && msg.cards) {
        var card = msg.cards.find(function(c){return c.title===title;});
        if (card) openDetails(card);
      }
    });

    /* Toggle compare */
    delegate('[data-action="toggleCompare"]', function(el){
      var title = el.getAttribute('data-title');
      var card = null;
      state.msgs.forEach(function(m){ if(m.cards) m.cards.forEach(function(c){ if(c.title===title) card=c; }); });
      if (card) toggleCompare(card);
    });

    /* Lead submit */
    delegate('[data-action="submitLead"]', function(el){
      submitLead(el.getAttribute('data-mid'));
    });
    delegate('[data-action="leadPhoneInput"]', function(el){
      state.leadPhone = el.value;
    }, 'input');

    /* Syllabus accordion */
    delegate('[data-action="toggleAcc"]', function(el){
      toggleAcc(el.getAttribute('data-mid'), parseInt(el.getAttribute('data-idx')));
    });

    /* Run compare bar */
    delegate('[data-action="runCompare"]', function(){ doCompare('Compare'); });

    /* Input field */
    var inputEl = windowEl.querySelector('#db-input-el');
    if (inputEl) {
      inputEl.addEventListener('focus', function(){ state.inputFocused = true; updateInputBorder(); });
      inputEl.addEventListener('blur', function(){ state.inputFocused = false; updateInputBorder(); });
      inputEl.addEventListener('input', function(){ state.input = inputEl.value; updateSendBtn(); });
      inputEl.addEventListener('keydown', function(ev){ if(ev.key==='Enter') onSendText(); });
    }
    /* Send btn */
    var sendBtn = windowEl.querySelector('#db-send-btn-el');
    if (sendBtn) sendBtn.addEventListener('click', onSendText);

    /* Picker */
    delegate('[data-action="closePicker"]', function(){ state.picker = null; render(); });
    delegate('[data-action="pickerInput"]', function(el){ state.picker = Object.assign({},state.picker,{query:el.value}); renderPickerList(); }, 'input');
    delegate('[data-action="pickItem"]', function(el){
      var name = el.getAttribute('data-key');
      var kind = el.getAttribute('data-kind');
      var src = kind==='uni' ? UNIS : SPECS;
      var row = src.find(function(r){return r.name===name;});
      if (row) pickItem(row);
    });

    /* Finder */
    delegate('[data-action="closeFinder"]', function(){ state.finder = null; render(); });
    delegate('[data-action="finderAnswer"]', function(el){ finderAnswer(el.getAttribute('data-opt')); });
    delegate('[data-action="finderSkip"]', function(){ state.finder = null; doResults(null); });

    /* Tool */
    delegate('[data-action="closeTool"]', function(){ state.tool = null; render(); });
    delegate('[data-action="toolBegin"]', function(){ state.tool = Object.assign({},state.tool,{phase:'step'}); render(); scrollToBottom(); });
    delegate('[data-action="toolAnswer"]', function(el){ toolAnswer(el.getAttribute('data-opt'), parseInt(el.getAttribute('data-oi'))); });
    delegate('[data-action="toolBack"]', function(){
      var t = state.tool;
      if(t.idx>0) state.tool = Object.assign({},t,{idx:t.idx-1});
      else state.tool = Object.assign({},t,{phase:'entry'});
      render();
    });
    delegate('[data-action="toolReveal"]', function(){ state.tool = Object.assign({},state.tool,{phase:'lead'}); render(); scrollToBottom(); });
    delegate('[data-action="toolName"]', function(el){ state.toolName = el.value; }, 'input');
    delegate('[data-action="toolPhone"]', function(el){ state.toolPhone = el.value; }, 'input');
    delegate('[data-action="toolSubmit"]', function(){ toolSubmit(); });
    delegate('[data-action="toolSkip"]', function(){ toolSkip(); });

    /* Details */
    delegate('[data-action="closeDetails"]', function(){ state.details = null; render(); });

    /* End screen */
    delegate('[data-action="closeEnd"]', function(){ state.endScreen = null; render(); });
    delegate('[data-action="endPrograms"]', function(){ onEndPrograms(); });
  }

  function delegate(selector, handler, eventType) {
    var evt = eventType || 'click';
    windowEl.addEventListener(evt, function(ev) {
      var el = ev.target.closest(selector);
      if (el) handler(el, ev);
    }, true);
  }

  function updateInputBorder() {
    var wrap = windowEl && windowEl.querySelector('.db-input-wrapper');
    if (!wrap) return;
    if (state.inputFocused) { wrap.classList.add('focused'); wrap.style.borderColor = '#0E1F3D'; }
    else { wrap.classList.remove('focused'); wrap.style.borderColor = '#E5E7EB'; }
  }
  function updateSendBtn() {
    var btn2 = windowEl && windowEl.querySelector('#db-send-btn-el');
    if (!btn2) return;
    if ((state.input||'').trim().length > 0) { btn2.classList.add('active'); }
    else { btn2.classList.remove('active'); }
  }
  function renderPickerList() {
    /* lightweight re-render of just the list (avoids full re-render on each keypress) */
    var p = state.picker;
    var q = (p.query||'').toLowerCase();
    var src = p.kind==='uni' ? UNIS : SPECS;
    var filtered = src.filter(function(r){ return !q || r.name.toLowerCase().includes(q) || (r.short||'').toLowerCase().includes(q); });
    var popular = p.kind==='uni' ? filtered.filter(function(r){return r.pop;}) : filtered.slice(0,4);
    var rowHtml = function(r) {
      return btn('db-picker-row',
        div('db-picker-mono',esc(r.mono),'style="background:'+r.bg+'"') +
        div('',div('db-picker-row-name',esc(r.name))+div('db-picker-row-meta',esc(r.meta))),
        '','data-action="pickItem" data-key="'+esc(r.name)+'" data-kind="'+p.kind+'"'
      );
    };
    var listEl = windowEl.querySelector('.db-picker-list');
    if (listEl) {
      listEl.innerHTML =
        (!q && popular.length ? div('db-picker-section-label','⭐ Popular') + popular.map(rowHtml).join('') : '') +
        div('db-picker-section-label','All') +
        filtered.map(rowHtml).join('') +
        (filtered.length===0 ? div('db-picker-empty','Nothing matched. Try a shorter search.') : '');
    }
  }

  /* ─────────────────────────────────────────────────────────────
     7. DOM MOUNT  (Shadow DOM for style isolation)
  ───────────────────────────────────────────────────────────── */
  function mount() {
    /* Host element */
    var host = document.createElement('div');
    host.id = 'db-widget-host';
    host.style.cssText = 'position:fixed;z-index:2147483647;inset:auto;pointer-events:none;';
    document.body.appendChild(host);

    /* Shadow root */
    shadow = host.attachShadow({ mode: 'open' });

    /* Inject font link into shadow */
    var fontLink = document.createElement('link');
    fontLink.rel = 'stylesheet';
    fontLink.href = 'https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap';
    shadow.appendChild(fontLink);

    /* Inject widget CSS */
    var styleLink = document.createElement('link');
    styleLink.rel = 'stylesheet';
    /* Use inline CSS if widget.css URL not available, or resolve relative to this script */
    var scriptSrc = (document.currentScript || {}).src || '';
    var base = scriptSrc ? scriptSrc.replace(/\/[^/]+$/, '/') : '';
    styleLink.href = base + 'widget.css';
    shadow.appendChild(styleLink);

    /* Inline CSS fallback — critical styles to avoid FOUC */
    var criticalStyle = document.createElement('style');
    criticalStyle.textContent = CRITICAL_CSS;
    shadow.appendChild(criticalStyle);

    /* Widget root */
    root = document.createElement('div');
    root.id = 'db-widget-root';
    shadow.appendChild(root);

    /* Launcher button */
    launcher = document.createElement('button');
    launcher.id = 'db-launcher';
    launcher.setAttribute('aria-label', 'Open chat');
    launcher.style.pointerEvents = 'auto';
    launcher.innerHTML = SVG.chat;
    launcher.addEventListener('click', function() {
      state.open = !state.open;
      launcher.setAttribute('aria-label', state.open ? 'Close chat' : 'Open chat');
      if (state.open && !state.started) {
        resetChat();
        return; // resetChat calls render()
      }
      if (!state.open) {
        windowEl.classList.add('db-closing');
        setTimeout(function(){ windowEl.classList.remove('db-closing'); render(); }, 200);
        return;
      }
      render();
    });
    root.appendChild(launcher);

    /* Chat window */
    windowEl = document.createElement('div');
    windowEl.id = 'db-window';
    windowEl.style.display = 'none';
    windowEl.style.pointerEvents = 'auto';
    root.appendChild(windowEl);

    /* Apply position */
    if (cfg.position === 'left') {
      launcher.style.right = 'auto';
      launcher.style.left = '24px';
      windowEl.style.right = 'auto';
      windowEl.style.left = '24px';
    }
  }

  /* Critical inline CSS (subset) to avoid FOUC before widget.css loads */
  var CRITICAL_CSS = [
    '#db-launcher{position:fixed;right:24px;bottom:24px;width:60px;height:60px;border-radius:50%;border:none;background:#E84010;cursor:pointer;display:flex;align-items:center;justify-content:center;z-index:2147483640;box-shadow:0 8px 22px rgba(232,64,16,.4);}',
    '#db-window{position:fixed;right:24px;bottom:96px;width:382px;border-radius:20px;overflow:hidden;display:flex;flex-direction:column;background:#F7F8FA;box-shadow:0 24px 64px rgba(0,0,0,.18),0 0 0 1px rgba(0,0,0,.06);z-index:2147483639;}',
    '@media(max-width:480px){#db-window{right:0;bottom:0;width:100%;height:100dvh;border-radius:0;}#db-launcher{right:16px;bottom:16px;}}'
  ].join('');

  /* ─────────────────────────────────────────────────────────────
     8. PUBLIC API
  ───────────────────────────────────────────────────────────── */
  function init(options) {
    if (options) {
      if (options.botName)      cfg.botName = options.botName;
      if (options.primaryColor) cfg.primaryColor = options.primaryColor;
      if (options.position)     cfg.position = options.position;
      if (options.page)         cfg.page = options.page;
      if (options.apiUrl)       cfg.apiUrl = options.apiUrl;
      if (options.widgetId)     cfg.widgetId = options.widgetId;
    }
  }

  /* ─────────────────────────────────────────────────────────────
     9. AUTO-INIT
  ───────────────────────────────────────────────────────────── */
  function bootstrap() {
    injectGoogleFonts();

    /* Read data-* from script tag */
    var scriptTag = document.currentScript;
    if (scriptTag) {
      var wid = scriptTag.getAttribute('data-widget-id');
      if (wid) cfg.widgetId = wid;
      var pos = scriptTag.getAttribute('data-position');
      if (pos) cfg.position = pos;
      var pg = scriptTag.getAttribute('data-page');
      if (pg) cfg.page = pg;
    }

    mount();
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
