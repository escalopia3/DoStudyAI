import copy
import json
import unittest
import httpx
from unittest.mock import patch

from dovideo.agents.context import build,model_messages,FINAL_EVIDENCE_PREFIX
from dovideo.agents.loop import make_loop
from dovideo.agents.retrieval_debug import record_model_input
from dovideo.agents.provider import ChatModel
from dovideo.tools.registry import SPECS


def evidence():
    return {'source_id':'S1','resource_id':'r','index_version_id':'i','chunk_id':'c','parent_id':'p',
        'document_name':'课件.pptx','title_path':['定义'],'content':'两个复数相等当且仅当实部和虚部分别相等。',
        'expanded':False,'locators':[{'pageIndex':4,'bbox':'坐标'*10000}]}


def tool_message(item):
    return {'role':'tool','tool_call_id':'lookup','content':json.dumps({'status':'ok','data':{
        'evidence':[item],'coverage':{'mode':'detail','complete':False},
        'outline':[{'title_path':['不相关目录']}]}})}


class QaRecoveryTests(unittest.TestCase):
    def test_deepseek_final_answer_disables_thinking_without_changing_regular_model(self):
        model=ChatModel.__new__(ChatModel)
        model.model,model.url,model.key='deepseek-flash','https://api.deepseek.com','fixture'
        with patch.dict('os.environ',{'DOVIDEO_CHAT_THINKING':'auto','DOVIDEO_CHAT_FINAL_THINKING':'disabled'}):
            self.assertEqual({},model.thinking_options())
            self.assertEqual({'thinking':{'type':'disabled'}},model.final_answer_model().thinking_options())
            self.assertEqual({},model.thinking_options())
            model.url='https://other.example.invalid'
            self.assertEqual({},model.final_answer_model().thinking_options())

    def test_stream_keeps_provider_reasoning_for_tool_protocol_but_never_emits_it(self):
        events=[{'choices':[{'index':0,'delta':{'reasoning_content':'fixture-private-protocol-state'}}]},
                {'choices':[{'index':0,'delta':{'content':'可见答案'}}]}]
        wire=''.join('data: '+json.dumps(e)+'\n\n' for e in events)+'data: [DONE]\n\n'
        client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,text=wire)))
        model=ChatModel.__new__(ChatModel)
        model.model,model.url,model.key='fixture','https://other.example.invalid','fixture'
        emitted=[]
        with patch('dovideo.agents.provider.httpx.Client',return_value=client):
            message,_=model.stream([],[],emitted.append,lambda:None)
        self.assertEqual(['可见答案'],emitted)
        self.assertEqual('fixture-private-protocol-state',message['reasoning_content'])

    def test_keeps_filename_and_one_based_pages_without_coordinates_or_detail_outline(self):
        raw=tool_message(evidence())
        data=json.loads(model_messages([raw])[0]['content'])['data']
        item=data['evidence'][0]
        self.assertEqual('课件.pptx',item['document_name'])
        self.assertEqual([5],item['pages'])
        self.assertNotIn('locators',item)
        self.assertEqual([],data['outline'])
        self.assertEqual('坐标'*10000,json.loads(raw['content'])['data']['evidence'][0]['locators'][0]['bbox'])

    def test_duplicate_evidence_is_compacted_but_tool_replies_are_retained(self):
        original=[tool_message(evidence()),tool_message(evidence())]
        before=copy.deepcopy(original)
        projected=model_messages(original)
        self.assertEqual(2,len(projected))
        self.assertEqual([],json.loads(projected[1]['content'])['data']['evidence'])
        self.assertEqual(['S1'],json.loads(projected[1]['content'])['data']['reused_source_ids'])
        self.assertEqual(before,original)

    def test_final_view_survives_huge_old_tool_results_and_is_logged(self):
        state={'messages':[{'role':'user','content':'复数相等的条件？'},
            {'role':'tool','tool_call_id':'huge','content':'无关数据'*30000}],
            'references':{'S1':evidence()},'loaded':list(SPECS)}
        before=copy.deepcopy(state)
        with self.assertRaisesRegex(ValueError,'CONTEXT_BUDGET_EXCEEDED'):build(state,SPECS)
        messages,tools,budget=build(state,SPECS,finalize=True)
        self.assertEqual([],tools)
        self.assertLessEqual(budget['estimated_input_tokens'],budget['input_budget'])
        self.assertTrue(messages[-1]['content'].startswith(FINAL_EVIDENCE_PREFIX))
        self.assertIn('实部和虚部',messages[-1]['content'])
        self.assertEqual(before,state)
        record_model_input(state,messages,budget)
        self.assertEqual('S1',state['retrieval_debug']['model_inputs'][0]['evidence'][0]['source_id'])

    def test_repeated_queries_keep_stable_source_id_then_finalize(self):
        calls=[]
        def model(messages,tools):
            calls.append(tools)
            if not tools:return {'role':'assistant','content':'实部和虚部分别相等 [S1]。'},{}
            return {'role':'assistant','tool_calls':[{'id':'q'+str(len(calls)),'function':{
                'name':'query_course_knowledge','arguments':'{"query":"相等"}'}}]},{}
        def execute(*args,**kwargs):
            return {'status':'ok','data':{'evidence':[evidence()],'coverage':{'mode':'detail'},'outline':[]}}
        with patch('dovideo.agents.loop.execute',side_effect=execute):
            state=make_loop(model,{}).invoke({'messages':[{'role':'user','content':'问题'}]})
        self.assertEqual(4,len(calls))
        self.assertEqual(['S1'],list(state['references']))
        self.assertEqual('RETRIEVAL_ROUND_LIMIT',state['finalize_reason'])
        self.assertIn('分别相等',state['answer'])
        self.assertEqual(3,state['detail_rounds'])

    def test_budget_recovery_produces_answer_instead_of_generic_stop(self):
        seen=[]
        def model(messages,tools):
            seen.append(tools)
            return {'role':'assistant','content':'由课件第5页，实部和虚部分别相等 [S1]。'},{}
        state=make_loop(model,{}).invoke({'messages':[{'role':'user','content':'问题'},
            {'role':'tool','tool_call_id':'large','content':'重复内容'*30000}],
            'references':{'S1':evidence()}})
        self.assertEqual([[]],seen)
        self.assertEqual('CONTEXT_BUDGET',state['finalize_reason'])
        self.assertIn('第5页',state['answer'])

    def test_declared_lookup_without_tool_call_gets_one_correction(self):
        count=0
        def model(messages,tools):
            nonlocal count
            count+=1
            if count==1:return {'role':'assistant','content':'我先查一下资料。'},{}
            return {'role':'assistant','content':'目前没有足够依据，无法确认。'},{}
        state=make_loop(model,{}).invoke({'messages':[{'role':'user','content':'考试时间？'}]})
        self.assertEqual(2,count)
        self.assertTrue(state['tool_intent_retry'])
        self.assertIn('无法确认',state['answer'])

    def test_overview_pagination_is_not_cut_off_after_three_rounds(self):
        count=0
        def model(messages,tools):
            nonlocal count
            count+=1
            if count==5:return {'role':'assistant','content':'已完成读取 [S1]。'},{}
            self.assertTrue(tools)
            return {'role':'assistant','tool_calls':[{'id':str(count),'function':{
                'name':'query_course_knowledge','arguments':'{"intent":"overview"}'}}]},{}
        def execute(*args,**kwargs):
            return {'status':'ok','data':{'evidence':[evidence()],'coverage':{'mode':'overview'},'next_cursor':'next'}}
        with patch('dovideo.agents.loop.execute',side_effect=execute):
            state=make_loop(model,{}).invoke({'messages':[{'role':'user','content':'通读课件'}]})
        self.assertEqual(5,count)
        self.assertNotIn('finalize_reason',state)

    def test_empty_answer_is_retried_with_evidence_instead_of_accepted(self):
        count=0
        def model(messages,tools):
            nonlocal count
            count+=1
            if count==1:return {'role':'assistant','content':''},{}
            self.assertFalse(tools)
            return {'role':'assistant','content':'实部和虚部分别相等 [S1]。'},{}
        state=make_loop(model,{}).invoke({'messages':[{'role':'user','content':'问题'}],
            'references':{'S1':evidence()}})
        self.assertEqual(2,count)
        self.assertIn('分别相等',state['answer'])

    def test_missing_source_number_gets_a_bounded_citation_retry(self):
        count=0
        def model(messages,tools):
            nonlocal count
            count+=1
            return {'role':'assistant','content':'实部和虚部分别相等。'+(' [S1]' if count>1 else '')},{}
        state=make_loop(model,{}).invoke({'messages':[{'role':'user','content':'问题'}],
            'references':{'S1':evidence()}})
        self.assertEqual(2,count)
        self.assertTrue(state['citation_retry'])
        self.assertIn('[S1]',state['answer'])


if __name__=='__main__':unittest.main()
