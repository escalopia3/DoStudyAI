"""Deterministic aggregation of explicit AI labels; never replaces missing data."""
from statistics import mean


def aggregate(cases,results,grades):
    ids=set(cases)
    if set(results)!=ids or set(grades)!=ids:raise ValueError('INCOMPLETE_EVALUATION')
    answerable=[q for q,c in cases.items() if c['answerable']]
    retrieval=[];delivery_n=delivery_d=0
    for q in answerable:
        g=grades[q];total=g['required_unit_count']
        if total<=0:raise ValueError('MISSING_SOURCE_EVIDENCE_RUBRIC')
        candidates=sorted(g['candidates'],key=lambda c:int(c['candidate_id'][1:]))[:8]
        supported=set().union(*(set(c['supported_unit_ids']) for c in candidates)) if candidates else set()
        relevant=[i for i,c in enumerate(candidates,1) if c['supported_unit_ids']]
        returned=set(g['returned_unit_ids']);sent=set(g['sent_unit_ids'])
        retrieval.append({'id':q,'hit_at_8':bool(relevant),'precision_at_8':len(relevant)/8,
            'evidence_unit_recall_at_8':len(supported)/total,'mrr_at_8':1/relevant[0] if relevant else 0,
            'full_evidence_at_8':len(supported)==total,'sent_unit_recall':len(sent)/total,
            'required_units':total,'covered_candidate_units':len(supported),
            'returned_units':len(returned),'sent_returned_units':len(sent&returned)})
        delivery_n+=len(sent&returned);delivery_d+=len(returned)
    claims=[c for g in grades.values() for c in g['claims']]
    citations=[c for g in grades.values() for c in g['citations']]
    required=[c for c in claims if c['requires_course_citation']]
    ratio=lambda a,b:a/b if b else None
    return {'questions':len(ids),'answerable_questions':len(answerable),
        'completed_runs':sum(r['status']=='SUCCEEDED' for r in results.values()),
        'answer_complete_count':sum(g['answer_score']==2 for g in grades.values()),
        'answer_complete_rate':mean(g['answer_score']==2 for g in grades.values()),
        'answer_score_sum':sum(g['answer_score'] for g in grades.values()),'answer_max_score':len(ids)*2,
        'boundary_correct_count':sum(grades[q]['answer_score']==2 for q in ids if not cases[q]['answerable']),
        **{key:mean(r[key] for r in retrieval) for key in ('hit_at_8','precision_at_8','evidence_unit_recall_at_8','mrr_at_8','full_evidence_at_8','sent_unit_recall')},
        'evidence_delivery_rate':ratio(delivery_n,delivery_d),'delivered_units':delivery_n,'returned_units':delivery_d,
        'faithfulness':ratio(sum(c['status']=='supported' for c in claims),len(claims)),
        'supported_claims':sum(c['status']=='supported' for c in claims),'total_claims':len(claims),
        'citation_validated_rate':ratio(sum(c['verdict']=='valid' for c in citations),len(citations)),
        'valid_citations':sum(c['verdict']=='valid' for c in citations),'total_citations':len(citations),
        'unverifiable_citations':sum(c['verdict']=='unverifiable' for c in citations),
        'citation_coverage':ratio(sum(bool(c['cited']) for c in required),len(required)),
        'required_citation_claims':len(required),'cited_required_claims':sum(bool(c['cited']) for c in required),
        'mean_elapsed_seconds':mean(r['elapsed_seconds'] for r in results.values()),
        'mean_prompt_tokens':mean(r.get('usage',{}).get('prompt_tokens',0) for r in results.values()),
        'mean_completion_tokens':mean(r.get('usage',{}).get('completion_tokens',0) for r in results.values()),
        'retrieval_per_question':retrieval}
