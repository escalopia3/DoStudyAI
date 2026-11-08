import unittest
from dovideo.knowledge import collection_name, scope_filter
from dovideo.evaluate import metrics
from dovideo.routers.knowledge import SearchInput
from pydantic import ValidationError

class KnowledgeTests(unittest.TestCase):
    def test_missing_configuration_fails_before_external_io(self):
        from dovideo.knowledge import build
        from dovideo.validation import InvalidResource
        with self.assertRaisesRegex(InvalidResource,'INDEX_CONFIGURATION_MISSING'):
            build(None,{'config':{'configurationError':'missing revision'}})

    def test_long_table_is_bounded_and_keeps_locator(self):
        from dovideo.chunking import build_chunks
        class Tokenizer:
            def encode(self,text,**kwargs): return list(text)
        document = {'resourceRevisionId':'rev','name':'table','elements':[
            {'id':'table1','type':'TABLE','markdown':'表格内容'*1000,'titlePath':['第一章'],
             'locators':[{'type':'PAGE','pageIndex':2}]}]}
        bundle = build_chunks(document,Tokenizer(),64,128)
        self.assertGreater(len(bundle.children),1)
        self.assertEqual(len({c.chunkId for c in bundle.children}),len(bundle.children))
        self.assertTrue(all(c.tokenCount<=64 for c in bundle.children))
        self.assertTrue(all(c.sourceElementIds==['table1'] for c in bundle.children))
        self.assertTrue(all(c.locators[0]['pageIndex']==2 for c in bundle.children))
        self.assertEqual(''.join(c.content for c in bundle.children),'表格内容'*1000)

    def test_collection_changes_with_configuration(self):
        self.assertEqual(collection_name({'b':2,'a':1}),collection_name({'a':1,'b':2}))
        self.assertNotEqual(collection_name({'model':'a'}),collection_name({'model':'b'}))

    def test_scope_rejects_unrestricted_query(self):
        with self.assertRaises(ValueError): scope_filter()
        with self.assertRaises(ValueError): scope_filter(owner_id='owner',pairs=[])
        query = scope_filter(owner_id='owner',pairs=[('r','i')],chunk_type='CHILD').model_dump()
        self.assertIn('ownerId',str(query))
        self.assertIn('indexRevision',str(query))

    def test_recall_and_rr_ignore_duplicate_chunks_for_resource_labels(self):
        evidence = [{'resourceId':'a','chunkId':'a1'}, {'resourceId':'a','chunkId':'a2'},
                    {'resourceId':'b','chunkId':'b1'}]
        self.assertEqual(metrics(evidence,['b','c']),{'recall':0.5,'reciprocalRank':0.5})
        self.assertEqual(metrics(evidence,[],['b1']),{'recall':1.0,'reciprocalRank':1/3})

    def test_question_limits(self):
        for payload in ({'question':' '},{'question':'x','limit':31}):
            with self.assertRaises(ValidationError): SearchInput(**payload)
