"""Developer-only retrieval export via direct database access; no HTTP route."""
import argparse
import copy
import html
import json
import os
import re
import uuid
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from dovideo.config import load_local_environment
from dovideo.models import AgentRun, AgentThread


def make_report(run, thread):
    trace=copy.deepcopy((run.checkpoint or {}).get('retrieval_debug'))
    if not trace:
        raise ValueError('此运行没有检索调试记录。请启用 DOVIDEO_RETRIEVAL_TRACE=1，重启 Agent Worker 后发起新问题。')
    cited=set(re.findall(r'\bS[0-9]+\b',run.answer or ''))
    inputs=trace.get('model_inputs',[])
    sent={e.get('source_id') for m in inputs for e in m['evidence']}
    for call in trace['calls']:
        returned=call.get('returned_evidence',[])
        for candidate in call.get('ranked_candidates',[]):
            related=[e for e in returned if e['resource_id']==candidate['resource_id'] and
                e['index_version_id']==candidate['index_version_id'] and
                (e['chunk_id']==candidate['chunk_id'] or
                 (e.get('expanded') and e['parent_id']==candidate['parent_id']))]
            ids=[e['source_id'] for e in related]
            candidate.update(source_ids=ids,sent_to_model=bool(sent.intersection(ids)),
                cited_in_final_answer=bool(cited.intersection(ids)),
                covered_by_expanded_parent=any(e.get('expanded') for e in related))
    return {'schema_version':1,'run_id':str(run.id),'thread_id':str(run.thread_id),
        'course_id':str(thread.course_id),'state':run.state,'question':run.input_text,
        'answer':run.answer,'error_code':run.error_code,'retrieval':trace,
        'notes':['detail 的 ranked_candidates 是父块补充召回后、预算筛选前的排名；默认 k=8。',
                 'global_hits 是原始全局混合检索结果，score 为 Qdrant RRF；跨集合按集合内排名融合排序。',
                 'supplement_hits 的 dense_similarity 分数与 RRF 不可直接比较；分数不是正确概率。',
                 'overview 是顺序阅读，不应当作 Top-k 召回评测。分页调用分别记录，不相加当作同一次 Top-k。',
                 'sent_to_model 表示至少一次模型调用包含该证据或覆盖它的父块；model_inputs 保留实际截取文本。',
                 'cited_in_final_answer 只表示答案出现该来源编号，不保证结论被原文支持。']}


def render_html(report):
    esc=lambda value:html.escape(str(value))
    pre=lambda value:'<pre>'+esc(json.dumps(value,ensure_ascii=False,indent=2))+'</pre>'
    parts=['<!doctype html><meta charset="utf-8"><title>开发者检索详情</title>',
        '<style>body{font:15px/1.6 system-ui;margin:32px;max-width:1300px;color:#20242b}'
        'table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}'
        'pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f5f7;padding:12px}'
        'summary{cursor:pointer}small{color:#555}</style>',
        '<h1>开发者检索详情</h1><p>Run '+esc(report['run_id'])+' · '+esc(report['state'])+'</p>',
        '<h2>问题</h2><pre>'+esc(report['question'])+'</pre>',
        '<h2>最终回答</h2><pre>'+esc(report['answer'])+'</pre>',
        '<ul>'+''.join('<li>'+esc(n)+'</li>' for n in report['notes'])+'</ul>']
    for call in report['retrieval']['calls']:
        parts+=['<h2>检索调用 '+esc(call['call_number'])+' · '+esc(call.get('mode','未完成'))+'</h2>',
            '<p>查询：'+esc(call.get('query',''))+' · k='+esc(call.get('limit','—'))+
            ' · 状态：'+esc(call.get('status',''))+'</p>',
            '<table><tr><th>排名</th><th>资料 / 页码 / 片段</th><th>筛选结果</th><th>送入模型</th><th>最终引用</th><th>原文</th></tr>']
        for c in call.get('ranked_candidates',[]):
            pages=sorted({loc['pageIndex']+1 for loc in c['locators'] if
                isinstance(loc,dict) and type(loc.get('pageIndex')) is int})
            parts.append('<tr><td>'+esc(c['rank'])+'</td><td>'+esc(c['document_name'] or c['resource_id'])+
                '<br>页码 '+esc(', '.join(map(str,pages)) or '未提供')+'<br><small>'+esc(c['chunk_id'])+
                '</small></td><td>'+esc(c['selection'])+('（父块覆盖）' if c['covered_by_expanded_parent'] else '')+
                '</td><td>'+('是' if c['sent_to_model'] else '否')+'</td><td>'+('是' if c['cited_in_final_answer'] else '否')+
                '</td><td><details><summary>展开</summary><pre>'+esc(c['content'])+'</pre></details></td></tr>')
        parts.append('</table><details><summary>分数、全局命中、补充召回、定位与返回原文</summary>'+pre(call)+'</details>')
    parts.append('<h2>实际提交给模型的证据（按模型调用）</h2>'+pre(report['retrieval'].get('model_inputs',[])))
    return '\n'.join(parts)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--list',action='store_true',help='列出最近有调试记录的运行')
    action.add_argument('--run-id',type=uuid.UUID)
    parser.add_argument('--course-id',type=uuid.UUID,help='可选课程范围')
    parser.add_argument('--limit',type=int,default=20)
    parser.add_argument('--output',type=Path,help='.json 或 .html 文件；省略时输出 JSON')
    args=parser.parse_args(argv)
    if not 1<=args.limit<=100:parser.error('--limit 必须为 1..100')
    if args.output and args.output.suffix.lower() not in ('.json','.html'):
        parser.error('--output 后缀必须为 .json 或 .html')
    load_local_environment()
    url=os.getenv('DOVIDEO_DATABASE_URL','')
    if not url:parser.error('请在开发者终端配置 DOVIDEO_DATABASE_URL；无需用户登录令牌。')
    engine=create_engine(url,pool_pre_ping=True)
    try:
        with Session(engine) as session:
            query=select(AgentRun,AgentThread).join(AgentThread,AgentRun.thread_id==AgentThread.id)
            if args.course_id:query=query.where(AgentThread.course_id==args.course_id)
            if args.list:
                query=query.where(AgentRun.checkpoint.has_key('retrieval_debug'))
                records=session.execute(query.order_by(AgentRun.created_at.desc(),AgentRun.id.desc()).limit(args.limit)).all()
                report={'runs':[{'run_id':str(r.id),'course_id':str(t.course_id),'state':r.state,
                    'question':r.input_text,'created_at':r.created_at.isoformat()} for r,t in records]}
            else:
                record=session.execute(query.where(AgentRun.id==args.run_id)).first()
                if not record:parser.error('未找到该运行或不属于指定课程')
                try:report=make_report(*record)
                except ValueError as exc:parser.error(str(exc))
        if args.output and args.output.suffix.lower()=='.html':
            if args.list:parser.error('--list 仅支持 JSON 输出')
            text=render_html(report)
        else:text=json.dumps(report,ensure_ascii=False,indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(text,encoding='utf-8')
            print(str(args.output.resolve()))
        else:print(text)
    finally:engine.dispose()


if __name__=='__main__':main()
