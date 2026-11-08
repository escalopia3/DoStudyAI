import unittest
from dovideo.agents.loop import make_loop

class AgentLoopTests(unittest.TestCase):
    def test_discover_load_execute_and_answer(self):
        seen=[]
        def model(messages,tools):
            names=[x['function']['name'] for x in tools]
            seen.append(names)
            step=len(seen)
            if step==1:return {'role':'assistant','tool_calls':[{'id':'a','function':{'name':'search_tools','arguments':'{"query":"课程"}'}}]},{}
            if step==2:return {'role':'assistant','tool_calls':[{'id':'b','function':{'name':'load_tools','arguments':'{"names":["query_course_knowledge"]}'}}]},{}
            if step==3:return {'role':'assistant','tool_calls':[{'id':'c','function':{'name':'query_course_knowledge','arguments':'{"query":"TCP","intent":"detail"}'}}]},{}
            self.assertIn('S1',messages[-1]['content'])
            return {'role':'assistant','content':'课件证据见 S1'}, {'total_tokens':20}
        import dovideo.agents.loop as module
        original=module.execute
        def execute(name,args,loaded,context):
            if name=='query_course_knowledge':return {'status':'ok','data':{'evidence':[{'content':'TCP可靠传输'}],'coverage':{'mode':'detail'}}}
            return original(name,args,loaded,context)
        module.execute=execute
        try:
            state=make_loop(model,{},save=lambda s:None).invoke({'messages':[{'role':'user','content':'TCP是什么'}]})
        finally:module.execute=original
        self.assertEqual(state['answer'],'课件证据见 S1')
        self.assertIn('query_course_knowledge',seen[0])
        self.assertNotIn('create_practice_question',seen[0])
        self.assertIn('query_course_knowledge',seen[2])
        self.assertEqual(state['usage']['total_tokens'],20)
