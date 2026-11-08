import copy
import json
import unittest
from types import SimpleNamespace as Obj
from unittest.mock import patch
from dovideo.agents.evidence import select
from dovideo.agents.context import model_messages, visible_evidence, build
from dovideo.agents.loop import make_loop
from dovideo.routers.agents import public_references
from dovideo.chunking import build_chunks


class EvidenceSelectionTests(unittest.TestCase):
    def test_relevant_tail_keeps_exact_page_and_checkpoint(self):
        parts=[{'text':'介绍背景。'*120,'locators':[{'pageIndex':0}]},
               {'text':'辐角主值满足 $-\\pi<\\theta_0\\leq\\pi$。','locators':[{'pageIndex':14}]}]
        item={'source_id':'S1','content':'\n\n'.join(p['text'] for p in parts),
            'source_segments':parts,'locators':[{'pageIndex':0},{'pageIndex':14}]}
        raw={'role':'tool','content':json.dumps({'status':'ok','data':{'coverage':{'mode':'detail'},'evidence':[item]}})}
        original=copy.deepcopy(raw)
        messages=model_messages([raw],100,'辐角主值范围')
        projected=json.loads(messages[0]['content'])['data']['evidence'][0]
        self.assertIn('theta_0',projected['content'])
        self.assertEqual([15],projected['pages'])
        self.assertEqual([15],visible_evidence(messages)['S1']['pages'])
        self.assertEqual(original,raw)

    def test_legacy_or_invalid_segments_keep_conservative_chunk_pages(self):
        for spans in ([],[{'text':'假的替换内容','locators':[{'pageIndex':99}]}]):
            item={'content':'背景。'*100+'辐角主值范围是约定。','source_segments':spans,
                  'locators':[{'pageIndex':1},{'pageIndex':14}]}
            text,loc,shortened,precise=select(item,'辐角主值',50)
            self.assertIn('主值',text)
            self.assertEqual(item['locators'],loc)
            self.assertTrue(shortened);self.assertFalse(precise)

    def test_never_splits_display_formula_or_adjacent_conditions(self):
        text='其他背景。'*60+'\n条件为 $z\\ne0$。\n$$\\operatorname{Arg}z=\\arg z+2k\\pi$$\n其中 $k\\in\\mathbb Z$。\n其他结论。'
        selected,_,_,_=select({'content':text},'Arg 辐角',125)
        self.assertIn('条件为',selected)
        self.assertIn('其中',selected)
        self.assertIn('$$\\operatorname{Arg}z=\\arg z+2k\\pi$$',selected)
        self.assertLessEqual(len(selected),125)
        oversized='条件。\n$$'+('x+'*100)+'x$$\n限制。'
        selected,_,_,_=select({'content':oversized},'x',30)
        self.assertNotIn('$$',selected)

    def test_final_selection_recovers_relevant_middle_source(self):
        refs={f'S{i}':{'source_id':f'S{i}','content':'其他背景。'*20} for i in range(1,17)}
        refs['S10']['content']='辐角主值的定义和范围。'
        messages,_,_=build({'messages':[{'role':'user','content':'辐角主值范围？'}], 'references':refs},{},finalize=True)
        self.assertIn('S10',visible_evidence(messages))

    def test_public_citations_use_visible_pages_without_exposing_trace(self):
        run=Obj(answer='结论 [S1] [S2]',checkpoint={'references':{
            'S1':{'resource_id':'r','locators':[{'pageIndex':0},{'pageIndex':14}]},
            'S2':{'resource_id':'r','locators':[{'pageIndex':9}]}},
            'citation_evidence':{'S1':{'pages':[15]}}})
        self.assertEqual([{'id':'S1','resource_id':'r','title_path':[],'pages':[15]}],public_references(run))

    def test_visible_citations_are_recorded_even_with_tracing_disabled(self):
        def model(messages,tools):return {'role':'assistant','content':'结论 [S1]'},{}
        state=make_loop(model,{}).invoke({'messages':[{'role':'user','content':'问题'}],
            'references':{'S1':{'source_id':'S1','content':'原文','locators':[{'pageIndex':14}]}},'detail_rounds':3})
        self.assertEqual({'S1':{'pages':[15]}},state['citation_evidence'])
        self.assertNotIn('retrieval_debug',state)

    def test_new_chunk_spans_reconstruct_text_and_keep_page(self):
        document={'resourceRevisionId':'v','name':'test','elements':[
            {'id':'a','type':'PARAGRAPH','markdown':'  引言。','titlePath':['章节'],'locators':[{'pageIndex':0}]},
            {'id':'b','type':'PARAGRAPH','markdown':'辐角主值。','titlePath':['章节'],'locators':[{'pageIndex':14}]}]}
        bundle=build_chunks(document,Obj(encode=lambda text,**_:list(text)),64,128)
        child=bundle.children[0]
        self.assertEqual(child.content,'\n\n'.join(s['text'] for s in child.sourceSpans))
        text,loc,_,precise=select({'content':child.content,'source_segments':child.sourceSpans,'locators':child.locators},'辐角主值',6)
        self.assertEqual('辐角主值。',text)
        self.assertEqual([{'pageIndex':14}],loc);self.assertTrue(precise)

    def test_oversized_formula_requires_review_instead_of_silent_splitting(self):
        document={'resourceRevisionId':'v','elements':[{'id':'f','type':'FORMULA','markdown':'$$'+'x'*200+'$$'}]}
        with self.assertRaisesRegex(ValueError,'FORMULA_EXCEEDS_TOKEN_LIMIT'):
            build_chunks(document,Obj(encode=lambda text,**_:list(text)),64,128)


if __name__=='__main__':unittest.main()
