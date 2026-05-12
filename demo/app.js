const state = { run: null, selectedId: null, labelFilter: 'all', search: '' };
const els = {
  upload: document.getElementById('jsonUpload'), userRequest: document.getElementById('userRequest'), refinedDefinition: document.getElementById('refinedDefinition'), metricsStrip: document.getElementById('metricsStrip'), stageTrack: document.getElementById('stageTrack'), candidateSearch: document.getElementById('candidateSearch'), labelFilter: document.getElementById('labelFilter'), candidateList: document.getElementById('candidateList'), candidateDetail: document.getElementById('candidateDetail'), rubricMatrix: document.getElementById('rubricMatrix'), evidenceCards: document.getElementById('evidenceCards'), literatureMap: document.getElementById('literatureMap'), iterationTrace: document.getElementById('iterationTrace'), emptyTemplate: document.getElementById('emptyStateTemplate')
};
const labelClass = label => label === 'Confirmed' ? 'label-confirmed' : label === 'Explicit Negative Evidence' ? 'label-negative' : 'label-need';
const stateClass = value => { const s = String(value || '').toLowerCase(); return s.includes('supported') ? 'supported' : s.includes('contradicted') ? 'contradicted' : 'unresolved'; };
const fmt = value => Number(value || 0).toLocaleString();
async function loadDemo(){ const response = await fetch('sample_run.json'); if(!response.ok) throw new Error('Could not load sample_run.json'); setRun(await response.json()); }
function setRun(run){ state.run = normalizeRun(run); state.selectedId = state.run.candidates[0]?.id || null; state.search = ''; state.labelFilter = 'all'; els.candidateSearch.value = ''; els.labelFilter.value = 'all'; render(); }
function normalizeRun(run){ return { ...run, stages: Array.isArray(run.stages) ? run.stages : [], literature: Array.isArray(run.literature) ? run.literature : [], candidates: Array.isArray(run.candidates) ? run.candidates : [], summary: run.summary || {} }; }
function selectedCandidate(){ return state.run?.candidates.find(c => c.id === state.selectedId) || state.run?.candidates[0]; }
function filteredCandidates(){ if(!state.run) return []; const q = state.search.trim().toLowerCase(); return state.run.candidates.filter(c => { const labelOk = state.labelFilter === 'all' || c.label === state.labelFilter; const haystack = [c.name, c.formula, ...(c.synonyms || [])].join(' ').toLowerCase(); return labelOk && (!q || haystack.includes(q)); }); }
function render(){ if(!state.run) return; els.userRequest.textContent = state.run.user_request || state.run.topic || 'Untitled run'; els.refinedDefinition.textContent = state.run.refined_definition || 'No refined definition provided.'; renderMetrics(); renderStages(); renderCandidateList(); renderSelectedCandidate(); }
function renderMetrics(){ const s = state.run.summary || {}; const metrics = [['Literature records',s.literature_records],['Candidate mentions',s.candidate_mentions],['Normalized candidates',s.normalized_candidates],['Verification queue',s.verification_queue],['Confirmed rows',s.confirmed],['Quote-supported refs',s.quote_supported_refs]]; els.metricsStrip.innerHTML = metrics.map(([label,value]) => `<div class="metric"><strong>${fmt(value)}</strong><span>${label}</span></div>`).join(''); }
function renderStages(){ els.stageTrack.innerHTML = state.run.stages.map((stage,i) => `<article class="stage-card" data-count="${fmt(stage.count)}"><span class="state-pill ${stage.state === 'complete' ? 'complete' : 'active'}">${stage.state || 'active'}</span><p class="eyebrow">Stage ${i+1}</p><strong>${stage.name}</strong><p>${stage.note || ''}</p></article>`).join(''); }
function renderCandidateList(){ const candidates = filteredCandidates(); if(!candidates.length){ els.candidateList.innerHTML = els.emptyTemplate.innerHTML; return; } if(!candidates.some(c => c.id === state.selectedId)) state.selectedId = candidates[0].id; els.candidateList.innerHTML = candidates.map(c => `<button class="candidate-button ${c.id === state.selectedId ? 'active' : ''}" data-candidate-id="${c.id}"><strong>${c.name}</strong><div class="candidate-meta"><span class="label-pill ${labelClass(c.label)}">${c.label}</span><span>${fmt(c.mentions)} mentions</span><span>${c.iteration_count || 0} rounds</span></div></button>`).join(''); }
function renderSelectedCandidate(){ const c = selectedCandidate(); if(!c) return; const score = Math.max(0, Math.min(100, Math.round((c.confidence || 0) * 100))); els.candidateDetail.innerHTML = `<div class="detail-header"><div><p class="eyebrow">Selected candidate</p><h2>${c.name}</h2></div><span class="label-pill ${labelClass(c.label)}">${c.label}</span></div><p class="synonyms"><strong>Synonyms:</strong> ${(c.synonyms || []).join(', ') || 'none listed'}</p><p class="synonyms"><strong>Formula:</strong> ${c.formula || 'not available'} · <strong>Papers:</strong> ${(c.papers || []).join(', ') || 'none'} · <strong>Mentions:</strong> ${fmt(c.mentions)}</p><div class="score-bar" aria-label="Candidate confidence score"><span style="--score: ${score}%"></span></div>`; renderRubric(c); renderEvidence(c); renderLiterature(c); renderIterations(c); }
function renderRubric(c){ const rubric = Array.isArray(c.rubric) ? c.rubric : []; els.rubricMatrix.innerHTML = rubric.map(item => `<div class="rubric-row"><div><strong>${item.criterion}</strong><p>${item.evidence || ''}</p></div><span class="state-pill ${stateClass(item.state)}">${item.state}</span></div>`).join('') || '<div class="empty-state"><strong>No rubric states</strong><span>Load a run with predicate states.</span></div>'; }
function renderEvidence(c){ const evidence = Array.isArray(c.evidence) ? c.evidence : []; els.evidenceCards.innerHTML = evidence.map(item => `<div class="evidence-card"><div class="paper-top"><strong>${item.paper}</strong><span class="quality-pill ${item.quality === 'direct' ? 'supported' : item.quality === 'explicit_negative' ? 'contradicted' : 'unresolved'}">${item.quality || 'context'}</span></div><p>Supports: ${item.supports || 'unspecified predicate'}</p><blockquote>${item.quote || 'No quote text provided.'}</blockquote></div>`).join('') || '<div class="empty-state"><strong>No evidence cards</strong><span>This candidate may be evidence-limited.</span></div>'; }
function renderLiterature(c){ const used = new Set(c.papers || []); els.literatureMap.innerHTML = state.run.literature.map(p => `<article class="paper-card ${used.has(p.id) ? 'selected' : ''}"><div class="paper-top"><strong>${p.id}. ${p.title}</strong><span>${p.year || ''}</span></div><p>${p.source || 'unknown source'} · ${p.kind || 'paper'} · ${p.status || 'unknown status'}</p><div class="paper-tags">${(p.used_by || []).map(id => `<span>${id}</span>`).join('')}</div></article>`).join(''); }
function renderIterations(c){ const items = Array.isArray(c.iterations) ? c.iterations : []; els.iterationTrace.innerHTML = items.map(item => `<div class="timeline-item ${String(item.agent || '').toLowerCase().includes('critique') ? 'critique' : 'researcher'}" data-round="${item.round}"><span>${item.agent} · ${item.action}</span><strong>${item.result}</strong></div>`).join('') || '<div class="empty-state"><strong>No iteration trace</strong><span>Load a run with Researcher-Critique events.</span></div>'; }
els.candidateList.addEventListener('click', event => { const button = event.target.closest('[data-candidate-id]'); if(!button) return; state.selectedId = button.dataset.candidateId; renderCandidateList(); renderSelectedCandidate(); });
els.candidateSearch.addEventListener('input', event => { state.search = event.target.value; renderCandidateList(); renderSelectedCandidate(); });
els.labelFilter.addEventListener('change', event => { state.labelFilter = event.target.value; renderCandidateList(); renderSelectedCandidate(); });
els.upload.addEventListener('change', async event => { const file = event.target.files?.[0]; if(!file) return; try { setRun(JSON.parse(await file.text())); } catch(error){ alert(`Could not load JSON: ${error.message}`); } finally { event.target.value = ''; } });
loadDemo().catch(error => { document.body.innerHTML = `<main class="panel" style="margin:40px auto;max-width:720px"><h1>Demo failed to load</h1><p>${error.message}</p></main>`; });

// Browser-only branding lab. This simulates the control flow without API keys.
const lab = {
  prompt: document.getElementById('demoPrompt'),
  output: document.getElementById('labOutput'),
  flow: document.getElementById('labFlow'),
  skillBoard: document.getElementById('skillBoard'),
  full: document.getElementById('runFullPipeline'),
  reset: document.getElementById('resetLab'),
  state: { refined: null, papers: [], candidates: [], verified: [] }
};

const labSteps = [
  ['refine', 'Intent refinement', 'Convert user intent into a rubric'],
  ['search', 'Dynamic literature', 'Build a topic-conditioned paper set'],
  ['discover', 'Candidate discovery', 'Extract and rank chemical entities'],
  ['verify', 'Predicate verification', 'Audit candidates against evidence']
];

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
  lab.output.textContent = 'Click a skill or run the full pipeline.';
}

async function runRefinement() {
  renderLabFlow('refine');
  await sleep(420);
  const request = lab.prompt.value.trim() || 'Form a scientific compound database.';
  lab.state.refined = {
    user_request: request,
    refined_definition: 'A database entry must be a specific chemical entity in scope for the requested topic and supported by primary literature evidence.',
    mandatory_predicates: ['specific chemical identity', 'topic-specific context', 'direct paper evidence', 'not reagent/context-only'],
    exclusion_predicates: ['solvent role only', 'analytical standard only', 'class-level mention only']
  };
  renderLabFlow();
  writeLab('Intent refinement output', lab.state.refined);
  return lab.state.refined;
}

async function runLiteratureSearch() {
  if (!lab.state.refined) await runRefinement();
  renderLabFlow('search');
  await sleep(520);
  lab.state.papers = [
    { id: 'P1', source: 'Europe PMC', title: 'Formation of halogenated aldehydes during chlorination', status: 'full text', triggered_by: 'broad topic query' },
    { id: 'P2', source: 'Semantic Scholar', title: 'High-resolution screening of nitrogenous DBPs', status: 'abstract + metadata', triggered_by: 'candidate context query' },
    { id: 'P3', source: 'Publisher PDF', title: 'Iodo-phenolic byproducts in chloraminated water', status: 'full text', triggered_by: 'critique follow-up' },
    { id: 'P4', source: 'Local corpus', title: 'Benchmark context for regulated DBPs', status: 'metadata', triggered_by: 'identity grounding' }
  ];
  renderLabFlow();
  writeLab('Dynamic literature construction output', { retrieved_papers: lab.state.papers, key_point: 'The corpus grows from broad, candidate-specific, and critique-triggered searches.' });
  return lab.state.papers;
}

async function runCandidateDiscovery() {
  if (!lab.state.papers.length) await runLiteratureSearch();
  renderLabFlow('discover');
  await sleep(520);
  lab.state.candidates = [
    { id: 'C1', name: 'Chloroform', mentions: 67, rank_reason: 'frequent measured DBP with grounded synonym TCM' },
    { id: 'C2', name: 'Trichloroacetaldehyde', mentions: 24, rank_reason: 'specific carbonyl DBP with direct chlorination context' },
    { id: 'C3', name: '2,4,6-triiodophenol', mentions: 9, rank_reason: 'rare candidate requiring follow-up formation evidence' },
    { id: 'C4', name: 'Acetonitrile', mentions: 31, rank_reason: 'high mention count but likely solvent/context artifact' }
  ];
  renderLabFlow();
  writeLab('Candidate discovery output', { raw_mentions: 1185, normalized_candidates: 126, verification_queue: lab.state.candidates });
  return lab.state.candidates;
}

async function runPredicateVerification() {
  if (!lab.state.candidates.length) await runCandidateDiscovery();
  renderLabFlow('verify');
  await sleep(620);
  lab.state.verified = [
    { name: 'Chloroform', label: 'Confirmed', predicate_state: ['identity supported', 'formation supported', 'matrix supported'] },
    { name: 'Trichloroacetaldehyde', label: 'Confirmed', predicate_state: ['identity supported', 'formation supported', 'not reagent'] },
    { name: '2,4,6-triiodophenol', label: 'Insufficient Direct Evidence', predicate_state: ['identity supported', 'formation unresolved'] },
    { name: 'Acetonitrile', label: 'Explicit Negative Evidence', predicate_state: ['identity supported', 'solvent exclusion triggered'] }
  ];
  renderLabFlow();
  writeLab('Predicate verification output', { verified_rows: lab.state.verified, key_point: 'The decision is controlled by predicate states, not by whether the name sounds plausible.' });
  return lab.state.verified;
}

function labRunToViewer() {
  const run = {
    run_id: 'browser-lab-run',
    topic: 'Browser demo run',
    user_request: lab.state.refined.user_request,
    refined_definition: lab.state.refined.refined_definition,
    summary: { literature_records: lab.state.papers.length, candidate_mentions: 1185, normalized_candidates: 126, verification_queue: lab.state.candidates.length, confirmed: 2, evidence_limited: 1, excluded: 1, quote_supported_refs: 5 },
    stages: [
      { name: 'Intent refinement', state: 'complete', count: 4, note: 'Rubric predicates created from user request.' },
      { name: 'Dynamic literature', state: 'complete', count: lab.state.papers.length, note: 'Corpus expanded by broad and follow-up queries.' },
      { name: 'Candidate funnel', state: 'complete', count: lab.state.candidates.length, note: 'Candidates ranked for verification.' },
      { name: 'Predicate verification', state: 'complete', count: lab.state.verified.length, note: 'Rows assigned evidence-conditioned labels.' }
    ],
    literature: lab.state.papers.map((p, i) => ({ id: p.id, title: p.title, year: 2020 + i, source: p.source, kind: 'demo paper', status: p.status, used_by: ['C1', 'C2'].slice(0, i % 2 + 1) })),
    candidates: [
      { id: 'C1', name: 'Chloroform', synonyms: ['TCM'], formula: 'CHCl3', label: 'Confirmed', confidence: .94, mentions: 67, papers: ['P1','P4'], iteration_count: 2, rubric: [{ criterion: 'Specific identity', state: 'supported', evidence: 'Synonym and formula grounded.' },{ criterion: 'Formation evidence', state: 'supported', evidence: 'Chlorination context found.' }], evidence: [{ paper: 'P1', quote: 'chloroform increased after chlorination', supports: 'Formation evidence', quality: 'direct' }], iterations: [{ round: 1, agent: 'Researcher', action: 'search', result: 'Found chlorination evidence.' },{ round: 2, agent: 'Critique', action: 'approve', result: 'All predicates supported.' }] },
      { id: 'C3', name: '2,4,6-triiodophenol', synonyms: ['Triiodophenol'], formula: 'C6H3I3O', label: 'Insufficient Direct Evidence', confidence: .51, mentions: 9, papers: ['P3'], iteration_count: 4, rubric: [{ criterion: 'Specific identity', state: 'supported', evidence: 'Exact name found.' },{ criterion: 'Formation evidence', state: 'unresolved', evidence: 'Formation route remains ambiguous.' }], evidence: [{ paper: 'P3', quote: 'iodo-phenolic byproducts were observed', supports: 'Water matrix', quality: 'near_miss' }], iterations: [{ round: 1, agent: 'Researcher', action: 'retrieve', result: 'Found iodo-phenolic paper.' },{ round: 2, agent: 'Critique', action: 'request follow-up', result: 'Need direct formation evidence.' }] },
      { id: 'C4', name: 'Acetonitrile', synonyms: ['Methyl cyanide'], formula: 'C2H3N', label: 'Explicit Negative Evidence', confidence: .22, mentions: 31, papers: ['P2'], iteration_count: 1, rubric: [{ criterion: 'Specific identity', state: 'supported', evidence: 'Compound identity clear.' },{ criterion: 'Not reagent/context-only', state: 'contradicted', evidence: 'Used as solvent.' }], evidence: [{ paper: 'P2', quote: 'samples were diluted in acetonitrile', supports: 'Exclusion', quality: 'explicit_negative' }], iterations: [{ round: 1, agent: 'Critique', action: 'exclude', result: 'Solvent role triggers exclusion.' }] }
    ]
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
renderLabFlow();
