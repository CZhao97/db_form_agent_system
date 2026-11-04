"""Versioned, candidate-local evidence memory. Never infer scientific support."""
import copy
import hashlib
import json
from typing import TypedDict


POLICY = """The evidence memory contains previously reported records, not verified facts.
Keep the exact requested entity and topic definition. A related compound, a
class member, a congener without the requested suffix, or a different species
does not by itself establish the target criterion. Resolve any identity or
context bridge using an attributable source, or leave that criterion unresolved.
Do not invent identifiers. Distinguish proposed mechanisms from demonstrated
findings and primary experiments from definitions or background discussion.
Review previous records even if they were omitted from the latest report. Cite
records you use and explain contradictions or exclusions. Do not combine old
solved flags with new flags automatically. Make the current assessment from the
actual evidence and rubric. Stored records may be wrong or superseded.
Return the existing report schema. Record evidence-memory items considered but
not used in memory_dispositions with memory_id and reason. Never interpret
presence in this memory as approval or independent scientific validation."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def parse_report(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    return value if isinstance(value, dict) and isinstance(value.get('synthesis'), dict) else None


def update_memory(memory, task, report):
    """Append immutable record versions; omissions never delete prior evidence."""
    fingerprint = digest(task)
    if memory and memory.get('task_sha256') != fingerprint:
        raise ValueError('Evidence memory belongs to a different task or rubric')
    out = copy.deepcopy(memory) if memory else {
        'version': 1, 'task_sha256': fingerprint, 'records': [], 'reports': []}
    report = parse_report(report)
    if report is None:
        return out
    report_hash = digest(report)
    if any(r['report_sha256'] == report_hash for r in out['reports']):
        return out
    report_index = len(out['reports']) + 1
    records = {r['memory_id']: r for r in out['records']}
    current_ids = []
    for field in ('identity_records', 'evidence'):
        for item in report.get(field) or []:
            if not isinstance(item, dict):
                continue
            memory_id = digest({'kind': field, 'record': item})
            current_ids.append(memory_id)
            if memory_id not in records:
                record = {'memory_id': memory_id, 'kind': field, 'record': copy.deepcopy(item),
                          'first_report_index': report_index, 'report_hashes': [],
                          'scientific_validation': 'not_established_by_storage'}
                out['records'].append(record)
                records[memory_id] = record
            records[memory_id]['report_hashes'].append(report_hash)
    out['reports'].append({
        'report_index': report_index, 'report_sha256': report_hash,
        'record_ids': current_ids,
        'criteria_assessment': copy.deepcopy(report.get('criteria_assessment')),
        'memory_dispositions': copy.deepcopy(report.get('memory_dispositions') or []),
        'claim': (report.get('synthesis') or {}).get('claim'),
    })
    return out


def memory_payload(memory):
    """Retain context and provenance without manufacturing a merged verdict."""
    return {'policy': POLICY, 'records': copy.deepcopy(memory['records']),
            'previous_assessments': copy.deepcopy(memory['reports']),
            'task_sha256': memory['task_sha256']}


def install_evidence_memory(native):
    """Opt in before graph construction, in an isolated native namespace.

    The caller owns the checkpoint saver. Memory is a graph state channel, not
    process-global state. Historical code and saved report JSON remain unchanged.
    """
    if native.get('_evidence_memory_installed'):
        raise ValueError('Evidence memory already installed')
    if not native.get('_repair_installed'):
        raise ValueError('Install the latest-report/binding repair before evidence memory')
    native['_evidence_memory_installed'] = True
    annotations = dict(native['DownAgentState'].__annotations__)
    annotations['evidence_memory'] = dict
    native['DownAgentState'] = TypedDict('EvidenceMemoryState', annotations, total=False)
    original_researcher = native['researcher_node']
    original_critique = native['critique_node']
    original_builder = native['build_critique_request_payload']

    def prepare(state):
        task = state['original_query']
        try:
            parsed = json.loads(task) if isinstance(task, str) else copy.deepcopy(task)
        except ValueError as exc:
            raise ValueError('Evidence memory requires a structured task') from exc
        if not isinstance(parsed, dict) or 'cumulative_evidence_memory' in parsed:
            raise ValueError('Task must be an original structured input without injected memory')
        memory = update_memory(state.get('evidence_memory'), parsed, state.get('last_researcher_json'))
        augmented = copy.deepcopy(state)
        augmented['original_query'] = json.dumps({**parsed, 'cumulative_evidence_memory': memory_payload(memory)}, ensure_ascii=False)
        return task, parsed, memory, augmented

    def researcher(state, config):
        original, task, memory, augmented = prepare(state)
        result = original_researcher(augmented, config)
        # Select the output just generated, not an older highest-score report.
        messages = result.get('messages') or []
        latest = parse_report(getattr(messages[-1], 'content', None)) if messages else None
        result['original_query'] = original
        result['evidence_memory'] = update_memory(memory, task, latest)
        return result

    def critique(state, config):
        original, task, memory, augmented = prepare(state)
        result = original_critique(augmented, config)
        result['original_query'] = original
        result['evidence_memory'] = memory
        return result

    def builder(**kwargs):
        result = json.loads(original_builder(**kwargs))
        current_task = kwargs.get('current_task')
        if isinstance(current_task, str):
            current_task = json.loads(current_task)
        if isinstance(current_task, dict) and 'cumulative_evidence_memory' in current_task:
            result['cumulative_evidence_memory'] = copy.deepcopy(current_task['cumulative_evidence_memory'])
        return json.dumps(result, ensure_ascii=False)

    native['researcher_node'] = researcher
    native['critique_node'] = critique
    native['build_critique_request_payload'] = builder
    return native
