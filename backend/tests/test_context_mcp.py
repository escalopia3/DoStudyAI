import os
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from dovideo.agents.context import build,history_view
from dovideo.tools.registry import SPECS,discover,execute
from dovideo.mcp.client import configured, _learning_links

class ContextAndToolTests(unittest.TestCase):
    def test_learning_search_accepts_only_links_from_selected_platform(self):
        entries=[
            {'title':'课程', 'url':'https://www.icourse163.org/course/example'},
            {'title':'伪造域名', 'url':'https://icourse163.org.example/course'},
            {'title':'视频', 'url':'https://www.bilibili.com/video/example'},
        ]
        result=SimpleNamespace(structured_content={'web':{'results':entries}},
            content=[SimpleNamespace(type='text',text=json.dumps(entries))])
        self.assertEqual([x['title'] for x in _learning_links(result,'mooc')],['课程'])
        self.assertEqual([x['title'] for x in _learning_links(result,'bilibili')],['视频'])

    def test_slide_coordinates_do_not_consume_model_budget(self):
        data={'coverage':{'complete':False},'next_cursor':'page-2','evidence':[
            {'source_id':'S1','content':'复数的基本运算','locators':[{'bbox':'x'*50000}]}]}
        raw=json.dumps({'status':'ok','data':data},ensure_ascii=False)
        messages=[{'role':'user','content':'总结课件'},{'role':'tool','tool_call_id':'p1','content':raw}]
        view,_,_=build({'messages':messages},SPECS)
        projected=json.loads(view[-1]['content'])['data']
        self.assertEqual(projected['next_cursor'],'page-2')
        self.assertEqual(projected['evidence'],[{'source_id':'S1','content':'复数的基本运算'}])
        self.assertEqual(messages[-1]['content'],raw)
    def test_history_keeps_complete_turns_and_never_claims_mastery(self):
        turns=[SimpleNamespace(input_text=f'问题{i}',answer='解释'*80) for i in range(20)]
        view=history_view(turns,token_budget=1600)
        self.assertEqual(view[-2]['role'],'user')
        self.assertEqual(view[-1]['role'],'assistant')
        self.assertIn('较早对话摘录',view[0]['content'])
        self.assertNotIn('已掌握',view[0]['content'])

    def test_budget_rejects_oversize_without_dropping_tool_result(self):
        state={'loaded':['search_tools'],'messages':[{'role':'user','content':'问题'},
            {'role':'tool','tool_call_id':'x','content':'证据'*30000}]}
        with self.assertRaisesRegex(ValueError,'CONTEXT_BUDGET_EXCEEDED'):
            build(state,SPECS)
        self.assertEqual(len(state['messages']),2)

    def test_unconfigured_mcp_hidden_and_invalid_endpoint_rejected(self):
        with patch.dict(os.environ,{'DOVIDEO_MCP_TOOLS':'{}'}):
            self.assertNotIn('external_search',[x['name'] for x in discover('外部搜索',{})])
            self.assertEqual(execute('load_tools',{'names':['external_search']},['search_tools','load_tools'],{} )['code'],'TOOL_UNAVAILABLE')
        with patch.dict(os.environ,{'DOVIDEO_MCP_TOOLS':'{"external_search":{"url":"http://127.0.0.1:9999","tool":"search"}}'}):
            with self.assertRaisesRegex(ValueError,'MCP_HTTPS_REQUIRED'):configured()

if __name__=='__main__':unittest.main()
