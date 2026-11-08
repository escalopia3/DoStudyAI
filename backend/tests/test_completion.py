import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from dovideo.agents.grading import grade
from dovideo.agents.provider import ChatModel
from app.legacy_courses import import_courses,legacy_id
import httpx

class CompletionTests(unittest.TestCase):
    def test_stream_reassembles_split_tool_calls(self):
        events=[
            {'choices':[{'delta':{'content':'先查'}}]},
            {'choices':[{'delta':{'tool_calls':[{'index':0,'id':'call-1',
                'function':{'name':'search_tools','arguments':'{"query":'}}]}}]},
            {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':'"课件"}'}}]}}]},
            {'choices':[],'usage':{'total_tokens':42}},
        ]
        stream=''.join('data: '+json.dumps(event)+'\n\n' for event in events)+'data: [DONE]\n\n'
        client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,text=stream)))
        model=object.__new__(ChatModel)
        model.model,model.url,model.key='fixture','https://example.invalid','fixture'
        seen=[]
        with patch('dovideo.agents.provider.httpx.Client',return_value=client):
            reply,usage=model.stream([],[],seen.append,lambda:None)
        self.assertEqual(seen,['先查'])
        self.assertEqual(json.loads(reply['tool_calls'][0]['function']['arguments']),{'query':'课件'})
        self.assertEqual(usage['total_tokens'],42)

    def test_review_rejects_invalid_model_grades(self):
        question=SimpleNamespace(question='解释递归',expected_answer='基例和递推',rubric=['说明基例','说明递推'])
        with self.assertRaisesRegex(ValueError,'INVALID_RUBRIC_RESPONSE'):
            grade(lambda *_:({'content':'{"met":[true],"feedback":"好"}'},{}),question,'基例')

    def test_import_rejects_unmapped_course_owner(self):
        manifest={'source':'old','owner_map':{},'courses':[{'id':1,'user_id':99,'name':'课'}],
                  'course_chapters':[]}
        with self.assertRaisesRegex(ValueError,'unmapped course owner'):
            import_courses(None,manifest)
        self.assertNotEqual(legacy_id('old','course',1),legacy_id('another','course',1))
