const state = { run: null, selectedId: null, labelFilter: 'all', search: '' };
const els = {
  upload: document.getElementById('jsonUpload'), downloadRun: document.getElementById('downloadRun'), userRequest: document.getElementById('userRequest'), runNotice: document.getElementById('runNotice'), refinedDefinition: document.getElementById('refinedDefinition'), mandatoryPredicates: document.getElementById('mandatoryPredicates'), exclusionPredicates: document.getElementById('exclusionPredicates'), candidateFunnel: document.getElementById('candidateFunnel'), metricsStrip: document.getElementById('metricsStrip'), stageTrack: document.getElementById('stageTrack'), candidateSearch: document.getElementById('candidateSearch'), labelFilter: document.getElementById('labelFilter'), candidateList: document.getElementById('candidateList'), candidateDetail: document.getElementById('candidateDetail'), whyPanel: document.getElementById('whyPanel'), rowJson: document.getElementById('rowJson'), rubricMatrix: document.getElementById('rubricMatrix'), evidenceCards: document.getElementById('evidenceCards'), literatureMap: document.getElementById('literatureMap'), iterationTrace: document.getElementById('iterationTrace'), emptyTemplate: document.getElementById('emptyStateTemplate')
};

const esc = value => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#039;');
const labelText = label => label === 'Insufficient Direct Evidence' ? 'Evidence-limited' : label === 'Explicit Negative Evidence' ? 'Explicit negative' : (label || 'Unlabeled');
const qualityText = quality => quality === 'explicit_negative' ? 'explicit negative' : quality === 'near_miss' ? 'near miss' : (quality || 'context');
const safeId = value => String(value ?? '').replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 64);
const labelClass = label => label === 'Confirmed' ? 'label-confirmed' : label === 'Explicit Negative Evidence' ? 'label-negative' : 'label-need';
const stateClass = value => { const s = String(value || '').toLowerCase(); return s.includes('supported') ? 'supported' : s.includes('contradicted') ? 'contradicted' : 'unresolved'; };
const fmt = value => Number(value || 0).toLocaleString();
async function loadDemo(){ const response = await fetch('sample_run.json'); if(!response.ok) throw new Error('Could not load sample_run.json'); setRun(await response.json()); }
function setRun(run){ state.run = normalizeRun(run); state.selectedId = state.run.candidates[0]?._safe_id || null; state.search = ''; state.labelFilter = 'all'; els.candidateSearch.value = ''; els.labelFilter.value = 'all'; render(); }
function normalizeRun(run){ const seen = new Map(); const candidates = (Array.isArray(run.candidates) ? run.candidates : []).map((c,i) => { const base = safeId(c.id || c.name || `candidate-${i}`) || `candidate-${i}`; const count = seen.get(base) || 0; seen.set(base, count + 1); return { ...c, _safe_id: count ? `${base}-${count}` : base }; }); const literature = (Array.isArray(run.literature) ? run.literature : []).map((p,i) => ({ ...p, _safe_id: safeId(p.id || p.title || `paper-${i}`) || `paper-${i}` })); return { ...run, stages: Array.isArray(run.stages) ? run.stages : [], literature, candidates, summary: run.summary || {} }; }
function selectedCandidate(){ return state.run?.candidates.find(c => c._safe_id === state.selectedId) || state.run?.candidates[0]; }
function filteredCandidates(){ if(!state.run) return []; const q = state.search.trim().toLowerCase(); return state.run.candidates.filter(c => { const labelOk = state.labelFilter === 'all' || c.label === state.labelFilter; const haystack = [c.name, c.formula, ...(c.synonyms || [])].join(' ').toLowerCase(); return labelOk && (!q || haystack.includes(q)); }); }
function render(){ if(!state.run) return; els.userRequest.textContent = state.run.user_request || state.run.topic || 'Untitled run'; els.runNotice.textContent = state.run.data_notice || ''; els.refinedDefinition.textContent = state.run.refined_definition || 'No refined definition provided.'; renderPredicates(); renderMetrics(); renderFunnel(); renderStages(); renderCandidateList(); renderSelectedCandidate(); }
function renderMetrics(){ const s = state.run.summary || {}; const metrics = [['Literature records',s.literature_records],['Candidate mentions',s.candidate_mentions],['Normalized candidates',s.normalized_candidates],['Verification queue',s.verification_queue],['Confirmed rows',s.confirmed],['Quote-supported refs',s.quote_supported_refs]]; els.metricsStrip.innerHTML = metrics.map(([label,value]) => `<div class="metric"><strong>${fmt(value)}</strong><span>${label}</span></div>`).join(''); }
function renderPredicates(){ const mand = state.run.mandatory_predicates || []; const excl = state.run.exclusion_predicates || []; els.mandatoryPredicates.innerHTML = mand.map(item => `<span>${esc(item)}</span>`).join('') || '<span>No inclusion predicates in this export</span>'; els.exclusionPredicates.innerHTML = excl.map(item => `<span>${esc(item)}</span>`).join('') || '<span>No exclusion predicates in this export</span>'; }
function renderFunnel(){ const f = state.run.candidate_funnel; if(!f){ els.candidateFunnel.innerHTML = ''; return; } const steps = [['Raw mentions', f.raw_mentions], ['Normalized', f.normalized_candidates], ['Grounded', f.after_grounding], ['Ranked', f.after_topic_ranking], ['Verification queue', f.verification_queue]]; els.candidateFunnel.innerHTML = `<p class="eyebrow">Candidate discovery funnel</p><div class="funnel-steps">${steps.map(([label,value]) => `<div><strong>${fmt(value)}</strong><span>${esc(label)}</span></div>`).join('')}</div>`; }
function renderStages(){ els.stageTrack.innerHTML = state.run.stages.map((stage,i) => `<article class="stage-card" data-count="${fmt(stage.count)}"><span class="state-pill ${stage.state === 'complete' ? 'complete' : 'active'}">${esc(stage.state || 'active')}</span><p class="eyebrow">Stage ${i+1}</p><strong>${esc(stage.name)}</strong><p>${esc(stage.note || '')}</p></article>`).join(''); }
function renderCandidateList(){ const candidates = filteredCandidates(); if(!candidates.length){ els.candidateList.innerHTML = els.emptyTemplate.innerHTML; return; } if(!candidates.some(c => c._safe_id === state.selectedId)) state.selectedId = candidates[0]._safe_id; els.candidateList.innerHTML = candidates.map(c => `<button class="candidate-button ${c.id === state.selectedId ? 'active' : ''}" data-candidate-id="${c._safe_id}"><strong>${esc(c.name)}</strong><div class="candidate-meta"><span class="label-pill ${labelClass(c.label)}">${esc(labelText(c.label))}</span><span>${fmt(c.mentions)} mentions</span><span>${fmt(c.iteration_count || 0)} rounds</span></div></button>`).join(''); }
function renderSelectedCandidate(){ const c = selectedCandidate(); if(!c) return; const score = Math.max(0, Math.min(100, Math.round((c.confidence || 0) * 100))); const synonyms = (c.synonyms || []).map(esc).join(', ') || 'none listed'; const papers = (c.papers || []).map(esc).join(', ') || 'none'; const chips = [c.benchmark_status, c.discovery_type, c.human_release_audit].filter(Boolean).map(v => `<span>${esc(String(v).replaceAll('_',' '))}</span>`).join(''); els.candidateDetail.innerHTML = `<div class="detail-header"><div><p class="eyebrow">Selected candidate</p><h2>${esc(c.name)}</h2></div><span class="label-pill ${labelClass(c.label)}">${esc(labelText(c.label))}</span></div><div class="candidate-chips">${chips}</div><p class="synonyms"><strong>Synonyms:</strong> ${synonyms}</p><p class="synonyms"><strong>Formula:</strong> ${esc(c.formula || 'not available')} · <strong>Papers:</strong> ${papers} · <strong>Mentions:</strong> ${fmt(c.mentions)}</p><p class="synonyms"><strong>Triage:</strong> ${esc(c.triage_reason || 'No triage reason provided.')} <strong>Grounding:</strong> ${esc(c.grounding_status || 'not specified')}</p><meter class="score-meter" min="0" max="100" value="${score}" aria-label="Candidate confidence score"></meter>`; renderWhy(c); renderRubric(c); renderEvidence(c); renderLiterature(c); renderIterations(c); renderRowJson(c); }
function renderWhy(c){ els.whyPanel.innerHTML = `<p class="eyebrow">Why this label?</p><h2>${esc(labelText(c.label))}</h2><p>${esc(c.why_label || 'No label explanation provided in this export.')}</p>`; }
function renderRubric(c){ const rubric = Array.isArray(c.rubric) ? c.rubric : []; els.rubricMatrix.innerHTML = rubric.map(item => `<div class="rubric-row"><div><strong>${esc(item.criterion)}</strong><p>${esc(item.evidence || '')}</p></div><span class="state-pill ${stateClass(item.state)}">${esc(item.state)}</span></div>`).join('') || '<div class="empty-state"><strong>No rubric states</strong><span>Load a run with predicate states.</span></div>'; }
function renderEvidence(c){ const evidence = Array.isArray(c.evidence) ? c.evidence : []; els.evidenceCards.innerHTML = evidence.map(item => `<div class="evidence-card"><div class="paper-top"><strong>${esc(item.paper)}</strong><span class="quality-pill ${item.quality === 'direct' ? 'supported' : item.quality === 'explicit_negative' ? 'contradicted' : 'unresolved'}">${esc(qualityText(item.quality))}</span></div><p>Supports: ${esc(item.supports || 'unspecified predicate')}</p><blockquote>${esc(item.quote || 'No quote text provided.')}</blockquote></div>`).join('') || '<div class="empty-state"><strong>No evidence cards</strong><span>This candidate may be evidence-limited.</span></div>'; }
function renderLiterature(c){ const used = new Set(c.papers || []); els.literatureMap.innerHTML = state.run.literature.map(p => `<article class="paper-card ${used.has(p.id) ? 'selected' : ''}"><div class="paper-top"><strong>${esc(p.id)}. ${esc(p.title)}</strong><span>${esc(p.year || '')}</span></div><p>${esc(p.source || 'unknown source')} · ${esc(p.kind || 'paper')} · ${esc(p.status || 'unknown status')}</p><p><strong>Query:</strong> ${esc(p.query || 'not included')}<br><strong>Triggered by:</strong> ${esc(p.triggered_by || 'not included')}</p><div class="paper-tags">${(p.used_by || []).map(id => `<span>${esc(id)}</span>`).join('')}</div></article>`).join(''); }
function renderRowJson(c){ const row = c.final_row || { compound_name: c.name, label: c.label, papers: c.papers || [], why_label: c.why_label || '' }; els.rowJson.textContent = JSON.stringify(row, null, 2); }
function renderIterations(c){ const items = Array.isArray(c.iterations) ? c.iterations : []; els.iterationTrace.innerHTML = items.map(item => `<div class="timeline-item ${String(item.agent || '').toLowerCase().includes('critique') ? 'critique' : 'researcher'}" data-round="${fmt(item.round)}"><span>${esc(item.agent)} · ${esc(item.action)}</span><strong>${esc(item.result)}</strong></div>`).join('') || '<div class="empty-state"><strong>No iteration trace</strong><span>Load a run with Researcher-Critique events.</span></div>'; }
els.candidateList.addEventListener('click', event => { const button = event.target.closest('[data-candidate-id]'); if(!button) return; state.selectedId = button.dataset.candidateId; renderCandidateList(); renderSelectedCandidate(); });
els.candidateSearch.addEventListener('input', event => { state.search = event.target.value; renderCandidateList(); renderSelectedCandidate(); });
els.labelFilter.addEventListener('change', event => { state.labelFilter = event.target.value; renderCandidateList(); renderSelectedCandidate(); });
els.upload.addEventListener('change', async event => { const file = event.target.files?.[0]; if(!file) return; try { setRun(JSON.parse(await file.text())); } catch(error){ alert(`Could not load JSON: ${error.message}`); } finally { event.target.value = ''; } });
els.downloadRun?.addEventListener('click', () => { if(!state.run) return; const blob = new Blob([JSON.stringify(state.run, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `${String(state.run.run_id || 'db-curator-run').replace(/[^a-z0-9_.-]+/gi, '-')}.json`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url); });
loadDemo().catch(error => { document.body.innerHTML = `<main class="panel load-error"><h1>Demo failed to load</h1><p>${esc(error.message)}</p></main>`; });

// Browser-only branding lab. This simulates the control flow without API keys.
const lab = {
  prompt: document.getElementById('demoPrompt'),
  output: document.getElementById('labOutput'),
  flow: document.getElementById('labFlow'),
  skillBoard: document.getElementById('skillBoard'),
  full: document.getElementById('runFullPipeline'),
  reset: document.getElementById('resetLab'),
  precomputed: document.getElementById('loadPrecomputedRun'),
  state: { refined: null, papers: [], candidates: [], verified: [] }
};

const labSteps = [
  ['refine', 'Intent refinement', 'Convert user intent into a rubric'],
  ['search', 'Dynamic literature construction', 'Build a topic-conditioned paper set'],
  ['discover', 'Candidate discovery', 'Extract and rank chemical entities'],
  ['verify', 'Predicate-state verification', 'Audit candidates against evidence']
];

const demoPresets = {
  dbp: 'Form a database of disinfection byproducts supported by primary literature.',
  blood: 'Form a database of human blood exposome chemicals reported in blood or systemic circulation and linked to external exposure.',
  microbial: 'Form a database of microbial natural products with organism context and primary literature evidence.'
};

function activeScenario() {
  const text = (lab.prompt?.value || '').toLowerCase();
  if (text.includes('blood') || text.includes('exposome')) return 'blood';
  if (text.includes('microbial') || text.includes('natural product')) return 'microbial';
  return 'dbp';
}

const scenarioText = {
  dbp: {
    definition: 'A database entry must be a specific chemical entity formed during water disinfection and supported by primary literature evidence in a water-treatment or drinking-water context.',
    mandatory: ['specific chemical identity', 'water disinfection context', 'formation or occurrence evidence', 'not reagent/context-only'],
    exclusions: ['solvent role only', 'analytical standard only', 'precursor but not DBP'],
    papers: [
      ['P1', 'Europe PMC', 'Formation of halogenated aldehydes during chlorination', 'full text', 'broad topic query'],
      ['P2', 'Semantic Scholar', 'High-resolution screening of nitrogenous DBPs', 'abstract + metadata', 'candidate context query'],
      ['P3', 'Publisher PDF', 'Iodo-phenolic byproducts in chloraminated water', 'full text', 'critique follow-up'],
      ['P4', 'Local corpus', 'Benchmark context for regulated DBPs', 'metadata', 'identity grounding']
    ],
    candidates: [
      ['C1', 'Chloroform', 67, 'frequent measured DBP with grounded synonym TCM'],
      ['C2', 'Trichloroacetaldehyde', 24, 'specific carbonyl DBP with direct chlorination context'],
      ['C3', '2,4,6-triiodophenol', 9, 'rare candidate requiring follow-up formation evidence'],
      ['C4', 'Acetonitrile', 31, 'high mention count but likely solvent/context artifact']
    ]
  },
  blood: {
    definition: 'A database entry must be a specific chemical entity reported in human blood or systemic circulation and linked to external exposure, exposure response, or exposome literature.',
    mandatory: ['specific chemical identity', 'human blood/systemic matrix', 'exposure-linked context', 'primary literature or biomonitoring evidence'],
    exclusions: ['method contaminant only', 'non-human matrix only', 'class-level mention only'],
    papers: [
      ['P1', 'Europe PMC', 'Human biomonitoring of perfluoroalkyl substances in serum', 'full text', 'broad topic query'],
      ['P2', 'OpenAlex', 'Blood exposome signatures after dietary exposure', 'metadata', 'topic expansion'],
      ['P3', 'Publisher PDF', 'Serum detection of organophosphate metabolites', 'full text', 'candidate follow-up'],
      ['P4', 'Local corpus', 'Population-scale plasma exposomics', 'full text', 'rubric follow-up']
    ],
    candidates: [
      ['C1', 'Perfluorooctanoic acid', 54, 'measured in human serum with exposure context'],
      ['C2', 'Bisphenol A glucuronide', 18, 'specific metabolite in blood/plasma exposure studies'],
      ['C3', 'Diethyl phosphate', 11, 'possible exposure metabolite requiring matrix-specific evidence'],
      ['C4', 'Methanol', 22, 'common reagent/context term likely not releaseable']
    ]
  },
  microbial: {
    definition: 'A database entry must be a specific natural product produced by a microorganism and supported by organism-linked primary literature evidence.',
    mandatory: ['specific chemical identity', 'microbial producer context', 'natural product evidence', 'not synthetic analog only'],
    exclusions: ['plant-only source', 'synthetic intermediate only', 'class-level mention only'],
    papers: [
      ['P1', 'Semantic Scholar', 'Genome-guided discovery of bacterial polyketides', 'abstract + metadata', 'broad topic query'],
      ['P2', 'Europe PMC', 'Isolation of cyclic peptides from Streptomyces species', 'full text', 'organism query'],
      ['P3', 'Publisher PDF', 'Marine actinomycete metabolites with antimicrobial activity', 'full text', 'candidate follow-up'],
      ['P4', 'Local corpus', 'Natural product atlas cross-reference context', 'metadata', 'identity grounding']
    ],
    candidates: [
      ['C1', 'Surfactin', 45, 'specific bacterial lipopeptide with producer context'],
      ['C2', 'Actinomycin D', 32, 'microbial natural product with organism-linked evidence'],
      ['C3', 'Marinopyrrole A', 8, 'rare marine candidate requiring source verification'],
      ['C4', 'Palmitic acid', 29, 'common lipid likely contextual rather than topic-specific']
    ]
  }
};

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const writeLab = (title, payload) => { lab.output.textContent = `${title}\n${JSON.stringify(payload, null, 2)}`; };

function renderLabFlow(active = null) {
  lab.flow.innerHTML = labSteps.map(([id, title, note], i) => {
    const done = Boolean(lab.state.refined && id === 'refine') || Boolean(lab.state.papers.length && id === 'search') || Boolean(lab.state.candidates.length && id === 'discover') || Boolean(lab.state.verified.length && id === 'verify');
    const cls = active === id ? 'running' : done ? 'done' : '';
    return `<div class="lab-step ${cls}"><span>${i + 1}</span><strong>${title}</strong><p>${note}</p></div>`;
  }).join('');
  [...document.querySelectorAll('.skill-card')].forEach(btn => btn.classList.toggle('active', btn.dataset.skill === active));
}

function resetLabState() {
  lab.state = { refined: null, papers: [], candidates: [], verified: [] };
  renderLabFlow();
  lab.output.textContent = 'Click a workflow stage or run the full pipeline.';
}

async function runRefinement() {
  renderLabFlow('refine');
  await sleep(420);
  const request = lab.prompt.value.trim() || 'Form a scientific compound database.';
  const scenario = scenarioText[activeScenario()];
  lab.state.refined = {
    user_request: request,
    refined_definition: scenario.definition,
    mandatory_predicates: scenario.mandatory,
    exclusion_predicates: scenario.exclusions
  };
  renderLabFlow();
  writeLab('Intent refinement output', lab.state.refined);
  return lab.state.refined;
}

async function runLiteratureSearch() {
  if (!lab.state.refined) await runRefinement();
  renderLabFlow('search');
  await sleep(520);
  lab.state.papers = scenarioText[activeScenario()].papers.map(([id, source, title, status, triggered_by]) => ({ id, source, title, status, triggered_by }));
  renderLabFlow();
  writeLab('Dynamic literature construction output', { retrieved_papers: lab.state.papers, key_point: 'The corpus grows from broad, candidate-specific, and critique-triggered searches.' });
  return lab.state.papers;
}

async function runCandidateDiscovery() {
  if (!lab.state.papers.length) await runLiteratureSearch();
  renderLabFlow('discover');
  await sleep(520);
  lab.state.candidates = scenarioText[activeScenario()].candidates.map(([id, name, mentions, rank_reason]) => ({ id, name, mentions, rank_reason }));
  renderLabFlow();
  writeLab('Candidate discovery output', { raw_mentions: 1185, normalized_candidates: 126, verification_queue: lab.state.candidates });
  return lab.state.candidates;
}

async function runPredicateVerification() {
  if (!lab.state.candidates.length) await runCandidateDiscovery();
  renderLabFlow('verify');
  await sleep(620);
  const names = lab.state.candidates.map(c => c.name);
  lab.state.verified = [
    { name: names[0], label: 'Confirmed', predicate_state: ['identity supported', 'topic context supported', 'paper evidence supported'] },
    { name: names[1], label: 'Confirmed', predicate_state: ['identity supported', 'topic context supported', 'not exclusion-only'] },
    { name: names[2], label: 'Insufficient Direct Evidence', predicate_state: ['identity supported', 'one mandatory predicate unresolved'] },
    { name: names[3], label: 'Explicit Negative Evidence', predicate_state: ['identity supported', 'exclusion predicate triggered'] }
  ];
  renderLabFlow();
  writeLab('Predicate verification output', { verified_rows: lab.state.verified, key_point: 'The decision is controlled by predicate states, not by whether the name sounds plausible.' });
  return lab.state.verified;
}

function demoCandidateDetails(candidate, verified, index) {
  const isConfirmed = verified.label === 'Confirmed';
  const isNegative = verified.label === 'Explicit Negative Evidence';
  const paperId = lab.state.papers[index % Math.max(1, lab.state.papers.length)]?.id || 'P1';
  const benchmarkStatus = index === 0 ? 'benchmark_overlap' : index === 1 ? 'benchmark_missing' : index === 2 ? 'benchmark_overlap' : 'out_of_scope';
  const discoveryType = index === 1 ? 'benchmark-missing literature-supported entry' : index === 2 ? 'benchmark-overlap but evidence-limited under stricter scope' : isNegative ? 'context-only chemical mention' : 'benchmark-overlap confirmed entry';
  const why = isConfirmed
    ? `${candidate.name} is Confirmed because identity, topic context, and direct evidence predicates are supported in the toy run.`
    : isNegative
      ? `${candidate.name} is Explicit negative because its strongest context triggers an exclusion predicate.`
      : `${candidate.name} is Evidence-limited because at least one mandatory predicate remains unresolved.`;
  const finalRow = {
    compound_name: candidate.name,
    label: verified.label,
    benchmark_status: benchmarkStatus,
    supporting_papers: [paperId],
    why_label: why
  };
  return {
    id: candidate.id,
    name: candidate.name,
    synonyms: index === 0 ? ['grounded synonym'] : [],
    formula: 'demo-only',
    label: verified.label,
    confidence: isConfirmed ? .91 - index * .04 : isNegative ? .24 : .55,
    mentions: candidate.mentions,
    papers: [paperId],
    iteration_count: isConfirmed ? 2 : isNegative ? 1 : 4,
    benchmark_status: benchmarkStatus,
    discovery_type: discoveryType,
    benchmark_overlap: benchmarkStatus === 'benchmark_overlap',
    human_release_audit: isNegative ? 'rejected' : isConfirmed ? 'accepted' : 'needs_more_evidence',
    triage_reason: candidate.rank_reason,
    grounding_status: 'normalized identity available',
    why_label: why,
    final_row: finalRow,
    rubric: [
      { criterion: 'Specific chemical identity', state: 'supported', evidence: `${candidate.name} was normalized as a candidate entity.` },
      { criterion: 'Topic-specific context', state: isNegative ? 'contradicted' : 'supported', evidence: isNegative ? 'The strongest context triggers an exclusion predicate.' : 'The retrieved context is aligned with the requested topic.' },
      { criterion: 'Direct evidence requirement', state: isConfirmed ? 'supported' : 'unresolved', evidence: isConfirmed ? 'A supporting paper context is available in the toy run.' : 'The toy run leaves this item below the Confirmed threshold.' }
    ],
    evidence: [
      { paper: paperId, quote: isNegative ? `${candidate.name} appears as a contextual or exclusion-triggering term.` : `${candidate.name} is discussed in topic-specific scientific context.`, supports: isNegative ? 'Exclusion predicate' : 'Topic and evidence predicates', quality: isNegative ? 'explicit_negative' : isConfirmed ? 'direct' : 'near_miss' }
    ],
    iterations: [
      { round: 1, agent: 'Researcher', action: 'retrieve', result: `Collected evidence context for ${candidate.name}.` },
      { round: 2, agent: 'Critique', action: isConfirmed ? 'approve' : isNegative ? 'exclude' : 'request follow-up', result: isConfirmed ? 'Required predicates are supported.' : isNegative ? 'An exclusion predicate is triggered.' : 'One mandatory predicate remains unresolved.' }
    ]
  };
}

function labRunToViewer() {
  const confirmed = lab.state.verified.filter(v => v.label === 'Confirmed').length;
  const evidenceLimited = lab.state.verified.filter(v => v.label === 'Insufficient Direct Evidence').length;
  const excluded = lab.state.verified.filter(v => v.label === 'Explicit Negative Evidence').length;
  const run = {
    run_id: 'browser-lab-run',
    topic: 'Browser demo run',
    user_request: lab.state.refined.user_request,
    refined_definition: lab.state.refined.refined_definition,
    demo_mode: 'browser_simulation',
    data_notice: 'Synthetic browser simulation data; no live literature search or LLM calls were made.',
    mandatory_predicates: lab.state.refined.mandatory_predicates,
    exclusion_predicates: lab.state.refined.exclusion_predicates,
    candidate_funnel: { raw_mentions: 1185, normalized_candidates: 126, after_grounding: 74, after_topic_ranking: 32, verification_queue: lab.state.candidates.length },
    summary: { literature_records: lab.state.papers.length, candidate_mentions: 1185, normalized_candidates: 126, verification_queue: lab.state.candidates.length, confirmed, evidence_limited: evidenceLimited, excluded, quote_supported_refs: confirmed * 2 + evidenceLimited },
    stages: [
      { name: 'Intent refinement', state: 'complete', count: lab.state.refined.mandatory_predicates.length, note: 'Rubric predicates created from user request.' },
      { name: 'Dynamic literature construction', state: 'complete', count: lab.state.papers.length, note: 'Corpus expanded by broad and follow-up queries.' },
      { name: 'Candidate funnel', state: 'complete', count: lab.state.candidates.length, note: 'Candidates ranked for verification.' },
      { name: 'Predicate-state verification', state: 'complete', count: lab.state.verified.length, note: 'Rows assigned evidence-conditioned labels.' }
    ],
    literature: lab.state.papers.map((p, i) => ({ id: p.id, title: p.title, year: 2020 + i, source: p.source, kind: 'toy paper record', status: p.status, used_by: lab.state.candidates.slice(0, Math.min(2, lab.state.candidates.length)).map(c => c.id) })),
    candidates: lab.state.candidates.map((candidate, index) => demoCandidateDetails(candidate, lab.state.verified[index], index))
  };
  setRun(run);
}

lab.skillBoard?.addEventListener('click', async event => {
  const button = event.target.closest('[data-skill]');
  if (!button) return;
  const skill = button.dataset.skill;
  if (skill === 'refine') await runRefinement();
  if (skill === 'search') await runLiteratureSearch();
  if (skill === 'discover') await runCandidateDiscovery();
  if (skill === 'verify') await runPredicateVerification();
});
lab.full?.addEventListener('click', async () => { resetLabState(); await runRefinement(); await runLiteratureSearch(); await runCandidateDiscovery(); await runPredicateVerification(); labRunToViewer(); lab.output.textContent += '\n\nLoaded the generated toy run into the result viewer below.'; });
lab.reset?.addEventListener('click', resetLabState);
lab.precomputed?.addEventListener('click', async () => { resetLabState(); await loadDemo(); lab.output.textContent = 'Loaded the precomputed walkthrough into the result viewer below. The walkthrough is saved demo data, not a live literature or LLM run.'; });
renderLabFlow();


document.querySelectorAll('[data-preset]').forEach(button => {
  button.addEventListener('click', () => {
    const value = demoPresets[button.dataset.preset];
    if (!value) return;
    lab.prompt.value = value;
    resetLabState();
  });
});
