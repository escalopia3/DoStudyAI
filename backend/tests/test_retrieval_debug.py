import copy
import json
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import patch

from dovideo.agents.context import model_messages
from dovideo.agents.loop import make_loop
from dovideo.agents.retrieval_debug import record_model_input
from dovideo.agents.service import view
from dovideo.course_knowledge import query_course_knowledge
from dovideo.retrieval_debug import main, make_report, render_html
from dovideo.routers.agents import public_references


class RetrievalDebugTests(unittest.TestCase):
    def query_fixture(self):
        resource=Obj(id='r',display_name='<课件>.pptx')
        index=Obj(id='i',resource_version_id='v',config={'sparseModel':'Qdrant/bm25'},manifest={},collection='col')
        children=[{'chunkId':str(n),'parentId':'p'+str(n//2),'content':'原文'+str(n),
            'titlePath':['第一章'],'locators':[{'pageIndex':n}], 'sourceElementIds':[str(n)]} for n in range(6)]
        parents=[{'chunkId':'p'+str(n),'content':'父块'+str(n),'locators':[{'pageIndex':n*2}],
                  'sourceElementIds':[]} for n in range(3)]
        hits=[{'chunkId':str(n),'score':0.6-n/100,'content':children[n]['content']} for n in range(6)]
        storage=Obj(qdrant=Obj(query_points=lambda *a,**k:Obj(points=[])))
        session=Obj(execute=lambda _:Obj(all=lambda:[(resource,Obj(),None)]))
        bundle={'children':children,'parents':parents}
        return resource,index,hits,storage,session,bundle

    def test_debug_preserves_rank_and_result_and_records_parent_dedup_and_page_limit(self):
        resource,index,hits,storage,session,bundle=self.query_fixture()
        debug={}
        with patch('dovideo.course_knowledge.k.authorized_indexes',return_value=[(resource,index)]), \
             patch('dovideo.course_knowledge.read',side_effect=lambda s,i,n: {'sections':[]} if n=='outline.json' else bundle), \
             patch('dovideo.course_knowledge.k.search',return_value={'evidence':hits}), \
             patch('dovideo.course_knowledge.k.embeddings',return_value=[[0.1]]), \
             patch('dovideo.course_knowledge.k.embedding_provider',return_value=Obj(model=Obj(tokenizer=Obj(encode=lambda text,**_:list(text))))):
            kwargs=dict(query='问题',intent='detail',limit=6,page_units=2)
            normal=query_course_knowledge(session,storage,Obj(id='u'),'course',**kwargs)
            traced=query_course_knowledge(session,storage,Obj(id='u'),'course',debug=debug,**kwargs)
        self.assertEqual(normal,traced)
        self.assertNotIn('ranked_candidates',traced)
        self.assertEqual(['0','1','2','3','4','5'],[c['chunk_id'] for c in debug['ranked_candidates']])
        self.assertEqual(['returned_to_tool','deduplicated','returned_to_tool','page_limit','page_limit','page_limit'],
            [c['selection'] for c in debug['ranked_candidates']])
        self.assertEqual(['0','2'],[e['chunk_id'] for e in traced['evidence']])
        self.assertTrue(all(e['expanded'] for e in traced['evidence']))
        self.assertEqual('qdrant_rrf',debug['global_hits'][0]['score_type'])
        self.assertEqual('<课件>.pptx',debug['ranked_candidates'][0]['document_name'])

    def test_token_budget_decision_is_recorded(self):
        resource,index,hits,storage,session,bundle=self.query_fixture()
        bundle['parents'][0]['content']='字'*3000
        bundle['children'][0]['content']='字'*2500
        debug={}
        with patch('dovideo.course_knowledge.k.authorized_indexes',return_value=[(resource,index)]), \
             patch('dovideo.course_knowledge.read',side_effect=lambda s,i,n: {'sections':[]} if n=='outline.json' else bundle), \
             patch('dovideo.course_knowledge.k.search',return_value={'evidence':hits}), \
             patch('dovideo.course_knowledge.k.embeddings',return_value=[[0.1]]), \
             patch('dovideo.course_knowledge.k.embedding_provider',return_value=Obj(model=Obj(tokenizer=Obj(encode=lambda text,**_:list(text))))):
            result=query_course_knowledge(session,storage,Obj(id='u'),'course',query='问题',intent='detail',token_budget=2048,debug=debug)
        self.assertEqual([],result['evidence'])
        self.assertTrue(all(c['selection']=='token_budget' for c in debug['ranked_candidates']))

    def test_trace_stays_out_of_model_tool_response_and_sse_and_is_opt_in(self):
        for enabled in (False,True):
            calls=[];events=[];saved=[]
            def model(messages,tools):
                self.assertNotIn('ranked_candidates',json.dumps(messages))
                self.assertNotIn('private-ranking-marker',json.dumps(messages))
                calls.append(messages)
                if len(calls)==1:
                    return {'role':'assistant','tool_calls':[{'id':'lookup','function':{
                        'name':'query_course_knowledge','arguments':'{"query":"概念"}'}}]},{}
                return {'role':'assistant','content':'答案 [S1]'},{}
            def execute(name,args,loaded,context):
                evidence=[{'source_id':'S1','resource_id':'r','index_version_id':'i','chunk_id':'c',
                    'parent_id':'p','content':'课件原文','title_path':['章'],'locators':[{'pageIndex':0}],'expanded':False}]
                if 'retrieval_trace' in context:
                    context['retrieval_trace'].update(query=args['query'],mode='detail',limit=8,
                        ranked_candidates=[{'content':'private-ranking-marker'}],returned_evidence=evidence)
                return {'status':'ok','data':{'evidence':evidence,'coverage':{},'outline':[]}}
            with patch('dovideo.agents.loop.execute',side_effect=execute):
                state=make_loop(model,{'retrieval_debug':enabled},lambda s:saved.append(copy.deepcopy(s)),
                    lambda k,d:events.append((k,d))).invoke({'messages':[{'role':'user','content':'问题'}],'loaded':['query_course_knowledge']})
            self.assertEqual('答案 [S1]',state['answer'])
            self.assertNotIn('private-ranking-marker',json.dumps(events))
            self.assertEqual(enabled,'retrieval_debug' in state)
            if enabled:
                self.assertEqual('课件原文',state['retrieval_debug']['model_inputs'][-1]['evidence'][0]['content'])
                self.assertEqual('lookup',state['retrieval_debug']['calls'][0]['tool_call_id'])
                self.assertTrue(any(s.get('retrieval_debug',{}).get('model_inputs') for s in saved))

    def test_model_input_records_actual_excerpt_without_changing_messages(self):
        raw=[{'role':'tool','tool_call_id':'t','content':json.dumps({'status':'ok','data':{
            'evidence':[{'source_id':'S1','content':'字'*1000,'title_path':['章']}],'coverage':{},'outline':[]}})}]
        projected=model_messages(raw,220)
        state={}
        record_model_input(state,projected,{'input_budget':2000})
        item=state['retrieval_debug']['model_inputs'][0]['evidence'][0]
        self.assertEqual(220,len(item['content']))
        self.assertTrue(item['excerpt'])
        self.assertEqual(1000,len(json.loads(raw[0]['content'])['data']['evidence'][0]['content']))

    def test_report_distinguishes_parent_coverage_model_input_and_citation_and_escapes_html(self):
        candidate={'rank':1,'resource_id':'r','index_version_id':'i','chunk_id':'c',
            'parent_id':'p','content':'<script>alert(1)</script>','document_name':'<课件>',
            'locators':[{'pageIndex':0}],'selection':'returned_to_tool'}
        returned={'resource_id':'r','index_version_id':'i','chunk_id':'c','parent_id':'p','expanded':True,'source_id':'S2'}
        debug={'calls':[{'call_number':1,'ranked_candidates':[candidate], 'returned_evidence':[returned]}],
            'model_inputs':[{'model_call':2,'evidence':[{'source_id':'S2','content':'实际文本'}]}]}
        run=Obj(id='run',thread_id='thread',state='SUCCEEDED',model_id=None,input_text='问题',answer='答案 [S2]',
            error_code=None,usage={},checkpoint={'retrieval_debug':debug,'references':{'S2':returned}})
        report=make_report(run,Obj(course_id='course'))
        enriched=report['retrieval']['calls'][0]['ranked_candidates'][0]
        self.assertTrue(enriched['sent_to_model'])
        self.assertTrue(enriched['cited_in_final_answer'])
        self.assertTrue(enriched['covered_by_expanded_parent'])
        self.assertNotIn('sent_to_model',candidate)
        self.assertNotIn('<script>',render_html(report))
        self.assertIn('&lt;script&gt;',render_html(report))
        self.assertNotIn('retrieval_debug',view(run))
        self.assertNotIn('retrieval_debug',json.dumps(public_references(run)))

    def test_old_run_cannot_be_mistaken_for_empty_retrieval(self):
        with self.assertRaisesRegex(ValueError,'没有检索调试记录'):
            make_report(Obj(checkpoint={}),Obj())

    def test_cli_exports_without_storage_models_or_llm(self):
        from unittest.mock import MagicMock
        run=Obj(id='run',thread_id='thread',state='SUCCEEDED',input_text='问题',answer='答案',error_code=None,
            checkpoint={'retrieval_debug':{'calls':[],'model_inputs':[]}})
        session=MagicMock()
        session.execute.return_value.first.return_value=(run,Obj(course_id='course'))
        engine=MagicMock()
        with tempfile.TemporaryDirectory() as tmp, \
             patch('dovideo.retrieval_debug.load_local_environment'), \
             patch.dict('os.environ',{'DOVIDEO_DATABASE_URL':'postgresql+psycopg://developer@localhost/test'}), \
             patch('dovideo.retrieval_debug.create_engine',return_value=engine), \
             patch('dovideo.retrieval_debug.Session') as session_type, \
             patch('builtins.print'):
            session_type.return_value.__enter__.return_value=session
            output=Path(tmp)/'report.html'
            main(['--run-id','11111111-1111-1111-1111-111111111111','--output',str(output)])
            self.assertIn('开发者检索详情',output.read_text(encoding='utf-8'))
            self.assertNotIn('developer@localhost',output.read_text(encoding='utf-8'))
        engine.dispose.assert_called_once()

    def test_multiple_queries_keep_separate_ranks_and_global_source_ids(self):
        count=0
        def model(messages,tools):
            nonlocal count
            count+=1
            if count<=2:
                return {'role':'assistant','tool_calls':[{'id':'q'+str(count),'function':{
                    'name':'query_course_knowledge','arguments':json.dumps({'query':'问题'+str(count)})}}]},{}
            return {'role':'assistant','content':'综合答案 S1、S2'},{}
        def execute(name,args,loaded,context):
            evidence=[{'source_id':'S1','resource_id':'r','index_version_id':'i',
                'chunk_id':context['tool_call_id'],'parent_id':'p','content':'证据','title_path':[],
                'locators':[],'expanded':False}]
            context['retrieval_trace'].update(query=args['query'],returned_evidence=evidence,
                ranked_candidates=[{'rank':1,'resource_id':'r','index_version_id':'i',
                    'chunk_id':context['tool_call_id'],'parent_id':'p'}])
            return {'status':'ok','data':{'evidence':evidence,'coverage':{}}}
        with patch('dovideo.agents.loop.execute',side_effect=execute):
            state=make_loop(model,{'retrieval_debug':True}).invoke({
                'messages':[{'role':'user','content':'问题'}],'loaded':['query_course_knowledge']})
        report=make_report(Obj(checkpoint=state,id='run',thread_id='t',state='SUCCEEDED',
            input_text='问题',answer=state['answer'],error_code=None),Obj(course_id='course'))
        calls=report['retrieval']['calls']
        self.assertEqual(['问题1','问题2'],[c['query'] for c in calls])
        self.assertEqual(['S1','S2'],[c['returned_evidence'][0]['source_id'] for c in calls])
        self.assertTrue(all(c['ranked_candidates'][0]['sent_to_model'] for c in calls))
        self.assertTrue(all(c['ranked_candidates'][0]['cited_in_final_answer'] for c in calls))


if __name__=='__main__':unittest.main()
