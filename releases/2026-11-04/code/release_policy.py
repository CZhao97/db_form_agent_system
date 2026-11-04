"""Additive release checks. Native labels/acceptance remain historical endpoints.

A trusted caller supplies an explicit fixed-evidence review packet; model-reported
solved flags are never converted into directional evidence assessments here.
"""
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path


@lru_cache(maxsize=1)
def _certifier():
    path = (Path(__file__).resolve().parents[1] / 'revision_eval' /
            'criterion_certification_v2_20261017' / 'certify.py')
    spec = importlib.util.spec_from_file_location('dbcurator_release_certifier_v21', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.certify


def attach_release_check(report, candidate_name, packet=None):
    """Return a new report, preserving the native label and acceptance flag.

    None means not assessed, not scientific rejection. Explicit invalid packets
    fail closed. The contract must be frozen by the caller, not inferred from
    the subset of criteria the model chose to report.
    """
    out = dict(report)
    out.update(release_eligible=None, release_check_status='not_assessed',
               release_check_reason='No explicit fixed-evidence review packet supplied')
    if packet is None:
        return out
    try:
        if not isinstance(packet, dict):
            raise ValueError('Review packet must be an object')
        target = packet.get('candidate_name')
        if (not isinstance(target, str) or not isinstance(candidate_name, str)
                or not candidate_name.strip() or target.strip() != candidate_name.strip()):
            raise ValueError('Review packet is not bound to the exact input candidate')
        query = report.get('query')
        if query:
            query_hash = hashlib.sha256(str(query).encode()).hexdigest()
            if packet.get('input_sha256') != query_hash:
                raise ValueError('Review packet is not bound to this original input/rubric')
        if not isinstance(packet.get('contract'), dict):
            raise ValueError('Missing frozen contract')
        if not isinstance(packet.get('assessments'), list) or not isinstance(packet.get('sources'), dict):
            raise ValueError('Missing explicit assessments or source texts')
        result = _certifier()(packet['contract'], packet['assessments'], packet['sources'],
                              report.get('final_adjudicated_claim') or report.get('claim'),
                              report.get('accepted'))
        label = str(report.get('final_adjudicated_claim') or report.get('claim') or '').strip()
        runtime_ok = str(report.get('stop_reason') or '').upper() not in {'TIMEOUT', 'ERROR'}
        native_ok = report.get('accepted') is True
        eligible = label == 'Confirmed' and result['accepted_v2'] is True and runtime_ok and native_ok
        out.update(release_eligible=eligible, release_check_status='checked',
                   release_check_reason=result['reason_for_change'], release_assessment=result,
                   release_packet_sha256=hashlib.sha256(
                       json.dumps(packet, sort_keys=True).encode()).hexdigest())
        if label != 'Confirmed':
            out['release_check_reason'] = 'Native final label is not Confirmed'
        elif not runtime_ok:
            out['release_check_reason'] = 'Runtime failure blocks release'
        elif not native_ok:
            out['release_check_reason'] = 'Native workflow acceptance is not true'
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        out.update(release_eligible=False, release_check_status='invalid_input',
                   release_check_reason=str(exc))
    return out


def counts_as_confirmed(report):
    """Count a Confirmed state, never an accepted Suspected state.

    When explicit release assessment exists, use it. Without it, retain native
    acceptance behavior for Confirmed labels only. This is not an accuracy test.
    """
    if not isinstance(report, dict):
        return False
    if report.get("decision_policy_version"):
        return (report.get("claim") == "Confirmed"
                and report.get("final_adjudicated_claim") == "Confirmed"
                and report.get("accepted") is True
                and report.get("release_eligible") is True
                and report.get("all_paper_citations_verified") is True)
    label = next((str(report[k]).strip() for k in
                  ('final_adjudicated_claim', 'claim', 'researcher_claim')
                  if report.get(k)), '')
    if label.casefold() != 'confirmed':
        return False
    accepted = report.get('accepted')
    if report.get('release_check_status') in {'checked', 'invalid_input'}:
        return report.get('release_eligible') is True and accepted is True
    if accepted is None or accepted == '':
        return True
    return accepted is True or (isinstance(accepted, str) and accepted.casefold() == 'true')
