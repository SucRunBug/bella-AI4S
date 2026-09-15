#!/usr/bin/env python3
"""Audit evidence registration, not scientific truth. No network calls or mutations."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys
from urllib.parse import urlparse


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def audit(data, root):
    if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('Expected object with schema_version=1')
    sources, claims = data.get('sources'), data.get('claims')
    if not isinstance(sources, list) or not isinstance(claims, list):
        raise ValueError('sources and claims must be arrays')
    issues = []
    root = Path(root).resolve()
    source_map = {}
    invalid = set()
    if not sources or not claims:
        issues.append('Incomplete ledger: sources and claims must both contain records')
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f'sources[{index}] must be an object')
        sid = source.get('id')
        label = sid if nonempty(sid) else f'sources[{index}]'
        before = len(issues)
        if not nonempty(sid):
            issues.append(f'{label}: missing string id')
        elif sid in source_map:
            issues.append(f'{label}: duplicate source id')
        else:
            source_map[sid] = source
        if not nonempty(source.get('title')):
            issues.append(f'{label}: missing title')
        if source.get('kind') not in ('literature', 'experiment', 'dataset', 'other'):
            issues.append(f'{label}: invalid kind')
        if source.get('identity_status') not in ('verified', 'unverified', 'conflict'):
            issues.append(f'{label}: invalid identity_status')
        if source.get('access') not in ('metadata_only', 'abstract_only', 'full_text', 'local_artifact'):
            issues.append(f'{label}: invalid access')
        if source.get('identity_status') == 'verified':
            try:
                stamp = source.get('identity_checked_at')
                if not isinstance(stamp, str) or len(stamp) != 10:
                    raise ValueError()
                date.fromisoformat(stamp)
            except (ValueError, TypeError):
                issues.append(f'{label}: verified identity requires YYYY-MM-DD check date')
            if not nonempty(source.get('identity_basis')):
                issues.append(f'{label}: verified identity requires basis')
        artifact = source.get('artifact')
        if artifact is not None:
            if not nonempty(artifact):
                issues.append(f'{label}: artifact must be a nonempty relative path')
            else:
                path = (root / artifact).resolve()
                if Path(artifact).is_absolute() or not path.is_relative_to(root):
                    issues.append(f'{label}: artifact must remain inside ledger directory')
                elif not path.is_file() or path.stat().st_size == 0:
                    issues.append(f'{label}: missing or empty artifact: {artifact}')
        if source.get('access') == 'local_artifact' or source.get('kind') == 'experiment':
            if not nonempty(artifact):
                issues.append(f'{label}: local/experiment source requires artifact')
            if source.get('kind') == 'experiment' and source.get('access') != 'local_artifact':
                issues.append(f'{label}: experiment source requires local_artifact access')
        else:
            url = source.get('url')
            parsed = urlparse(url) if isinstance(url, str) else None
            if not parsed or parsed.scheme not in ('https', 'http') or not parsed.netloc:
                issues.append(f'{label}: external source requires http(s) URL')
        if len(issues) > before and nonempty(sid):
            invalid.add(sid)
    claim_ids = set()
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise ValueError(f'claims[{index}] must be an object')
        cid = claim.get('id')
        label = cid if nonempty(cid) else f'claims[{index}]'
        if not nonempty(cid):
            issues.append(f'{label}: missing string id')
        elif cid in claim_ids:
            issues.append(f'{label}: duplicate claim id')
        else:
            claim_ids.add(cid)
        if not nonempty(claim.get('text')):
            issues.append(f'{label}: missing claim text')
        status = claim.get('status')
        if status not in ('supported', 'needs_evidence', 'contradicted'):
            issues.append(f'{label}: invalid status')
        if type(claim.get('use_in_output')) is not bool:
            issues.append(f'{label}: use_in_output must be boolean')
        if claim.get('use_in_output') is True and status != 'supported':
            issues.append(f'{label}: downstream factual claim is not supported')
        evidence = claim.get('evidence')
        if not isinstance(evidence, list):
            raise ValueError(f'{label}: evidence must be an array')
        support_count, contradiction = 0, False
        for link in evidence:
            if not isinstance(link, dict):
                raise ValueError(f'{label}: evidence entries must be objects')
            sid = link.get('source_id')
            if not nonempty(sid) or sid not in source_map:
                issues.append(f'{label}: unknown source_id')
                continue
            relation = link.get('relation')
            if relation not in ('supports', 'contradicts', 'context'):
                issues.append(f'{label}: invalid evidence relation')
            if not nonempty(link.get('locator')) or not nonempty(link.get('note')):
                issues.append(f'{label}: evidence requires locator and support-scope note')
            contradiction |= relation == 'contradicts'
            if relation == 'supports':
                source = source_map[sid]
                usable = (sid not in invalid and source.get('identity_status') == 'verified'
                          and source.get('access') in ('full_text', 'local_artifact'))
                if usable and nonempty(link.get('locator')) and nonempty(link.get('note')):
                    support_count += 1
                elif status == 'supported':
                    issues.append(f'{label}: supporting source {sid} is unverified, incomplete, or access-limited')
        if status == 'supported' and support_count == 0:
            issues.append(f'{label}: supported claim has no usable registered support')
        if status == 'supported' and contradiction:
            issues.append(f'{label}: supported claim contains unresolved contradiction')
        if status == 'contradicted' and not contradiction:
            issues.append(f'{label}: contradicted status requires contradicting evidence')
    return {'status': 'gaps_found' if issues else 'registration_checks_passed',
            'scope': 'Registration and local file checks only; no citation identity or semantic verification.',
            'sources': len(sources), 'claims': len(claims), 'issues': issues}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ledger', type=Path)
    args = parser.parse_args()
    try:
        result = audit(json.loads(args.ledger.read_text(encoding='utf-8')), args.ledger.resolve().parent)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({'status': 'input_error', 'error': str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['issues'] else 0


if __name__ == '__main__':
    sys.exit(main())
