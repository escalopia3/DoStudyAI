import unittest
from types import SimpleNamespace as Obj
from unittest.mock import patch
from dovideo.course_knowledge import query_course_knowledge
from dovideo.errors import ApiError

class CourseKnowledgeTests(unittest.TestCase):
    def test_formula_keeps_exact_page_under_default_parent_policy(self):
        resource=Obj(id='r',display_name='test.pptx')
        index=Obj(id='i',resource_version_id='v',config={'sparseModel':'Qdrant/bm25'},manifest={},collection='c')
        formula={'chunkId':'f','parentId':'p','elementType':'FORMULA','content':'$$-\\pi<\\theta\\le\\pi$$',
            'titlePath':['辐角'],'locators':[{'pageIndex':14}],'sourceElementIds':['e']}
        bundle={'children':[formula],'parents':[{'chunkId':'p','content':'父块原文',
            'locators':[{'pageIndex':13},{'pageIndex':14}],'sourceElementIds':['e']}]}
        session=Obj(execute=lambda _:Obj(all=lambda:[(resource,Obj(),None)]))
        with patch.dict('os.environ',{'DOVIDEO_DETAIL_EVIDENCE_MODE':'parent'}), \
             patch('dovideo.course_knowledge.k.authorized_indexes',return_value=[(resource,index)]), \
             patch('dovideo.course_knowledge.read',side_effect=lambda s,i,n:{'sections':[]} if n=='outline.json' else bundle), \
             patch('dovideo.course_knowledge.k.search',return_value={'evidence':[{'chunkId':'f'}]}), \
             patch('dovideo.course_knowledge.k.embeddings',return_value=[[0.]]), \
             patch('dovideo.course_knowledge.k.embedding_provider',return_value=Obj(model=Obj(tokenizer=Obj(encode=lambda t,**kw:list(t))))):
            result=query_course_knowledge(session,Obj(qdrant=Obj(query_points=lambda *a,**kw:Obj(points=[]))),
                Obj(id='u'),'course',query='主值',intent='detail')
        self.assertEqual(formula['content'],result['evidence'][0]['content'])
        self.assertEqual([{'pageIndex':14}],result['evidence'][0]['locators'])
        self.assertFalse(result['evidence'][0]['expanded'])

    def test_detail_keeps_ranked_children_instead_of_expanding_and_deduplicating_parent(self):
        resource=Obj(id='r',display_name='slides.pptx')
        index=Obj(id='i',resource_version_id='v',config={'sparseModel':'Qdrant/bm25'},manifest={},collection='test')
        session=Obj(execute=lambda _:Obj(all=lambda:[(resource,Obj(),None)]))
        children=[{'chunkId':str(n),'parentId':'parent','content':f'命中{n}。'*100,
            'titlePath':['章节'],'locators':[{'pageIndex':n}],'sourceElementIds':[str(n)]} for n in range(3)]
        bundle={'children':children,'parents':[{'chunkId':'parent','content':'无关前言。'*300,
            'locators':[{'pageIndex':9}],'sourceElementIds':[]}]}
        tokenizer=Obj(encode=lambda text,**_:list(text))
        storage=Obj(qdrant=Obj(query_points=lambda *a,**kw:Obj(points=[])))
        with patch.dict('os.environ',{'DOVIDEO_DETAIL_EVIDENCE_MODE':'child'}), \
             patch('dovideo.course_knowledge.k.authorized_indexes',return_value=[(resource,index)]), \
             patch('dovideo.course_knowledge.read',side_effect=lambda s,i,n:{'sections':[]} if n=='outline.json' else bundle), \
             patch('dovideo.course_knowledge.k.search',return_value={'evidence':[{'chunkId':str(n)} for n in range(3)]}), \
             patch('dovideo.course_knowledge.k.embeddings',return_value=[[0.]]), \
             patch('dovideo.course_knowledge.k.embedding_provider',return_value=Obj(model=Obj(tokenizer=tokenizer))):
            result=query_course_knowledge(session,storage,Obj(id='user'),'course',query='命中',intent='detail',token_budget=2048)
        self.assertEqual(['0','1','2'],[e['chunk_id'] for e in result['evidence']])
        self.assertTrue(all(not e['expanded'] for e in result['evidence']))
        self.assertEqual([{'pageIndex':0}],result['evidence'][0]['locators'])

    def test_structured_table_repeats_header_without_losing_rows(self):
        from dovideo.chunking import build_chunks
        tokenizer=Obj(encode=lambda text,**_:list(text))
        cells=[{'text':'列名','column_header':True,'start_row_offset_idx':0}]
        cells += [{'text':f'第{i}行内容'*3,'start_row_offset_idx':i} for i in range(1,12)]
        document={'resourceRevisionId':'v','name':'table','elements':[{'id':'table','type':'TABLE',
            'markdown':'原表','titlePath':['章节'],'locators':[{'pageIndex':1}],
            'data':{'table':{'num_rows':12,'table_cells':cells}}}]}
        bundle=build_chunks(document,tokenizer,64,128)
        self.assertTrue(all(c.content.startswith('表头：列名') for c in bundle.children))
        self.assertTrue(all(c.tokenCount<=64 for c in bundle.children))
        self.assertTrue(all(c.tokenCount<=2000 for c in bundle.parents))
        for i in range(1,12): self.assertIn(f'第{i}行内容',''.join(c.content for c in bundle.children))

    def test_sequential_pages_cover_every_chunk_and_reject_new_snapshot(self):
        resource=Obj(id='resource')
        index=Obj(id='index',resource_version_id='version',config={},manifest={})
        user=Obj(id='user')
        session=Obj(execute=lambda _: Obj(all=lambda:[(resource,Obj(),None)]))
        children=[{'chunkId':str(n),'parentId':'parent','content':'字'*600,
                   'titlePath':['章节'],'locators':[],'sourceElementIds':[str(n)]} for n in range(12)]
        bundle={'children':children,'parents':[{'chunkId':'parent','content':'字'*1800,'locators':[],'sourceElementIds':[]}]}
        tokenizer=Obj(encode=lambda text,**_:list(text))
        def artifacts(storage,index,name):
            return {'sections':[]} if name=='outline.json' else bundle
        with patch('dovideo.course_knowledge.k.authorized_indexes',return_value=[(resource,index)]), \
             patch('dovideo.course_knowledge.read',side_effect=artifacts), \
             patch('dovideo.course_knowledge.k.embedding_provider',return_value=Obj(model=Obj(tokenizer=tokenizer))):
            cursor=None; ids=[]; first=None
            for _ in range(10):
                result=query_course_knowledge(session,None,user,'course',intent='overview',cursor=cursor,token_budget=2048)
                self.assertLessEqual(result['token_count'],2048)
                ids.extend(e['chunk_id'] for e in result['evidence'])
                cursor=result['next_cursor']
                first=first or cursor
                if not cursor: break
            self.assertTrue(result['coverage']['complete'])
            self.assertEqual(ids,[str(n) for n in range(12)])
            index.id='replacement'
            with self.assertRaises(ApiError) as error:
                query_course_knowledge(session,None,user,'course',intent='overview',cursor=first,token_budget=2048)
            self.assertEqual(error.exception.code,'CURSOR_SCOPE_OR_SNAPSHOT_CHANGED')
