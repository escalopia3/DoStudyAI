import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from knowledge_service.models import NormalizedDocument,DocumentElement
from knowledge_service.parsing.formulas import audit,enrich,FLAG


class FormulaReviewTests(unittest.TestCase):
    def test_offline_detection_deduplicates_fallback_and_enforces_review_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'test.pptx'
            with ZipFile(source,'w') as z:
                z.writestr('ppt/slides/slide1.xml','''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:oleObj progId="Equation.KSEE3" r:id="rId1"/><p:oleObj progId="Equation.KSEE3" r:id="rId1"/></p:sld>''')
            result=audit(source)
            self.assertEqual(1,result['pages'][0]['equation_objects'])
            def doc():return NormalizedDocument('v','test','PPTX',{},[
                DocumentElement('a','PARAGRAPH','正文',[],[],[{'pageIndex':0}])])
            original=enrich(doc(),source)
            self.assertIn(FLAG,original.qualityFlags)
            self.assertEqual(1,len(original.elements))
            review={'schema_version':1,'source_sha256':result['source_sha256'],'records':[
                {'id':'f','page':1,'markdown':'条件 $z\\ne0$，公式 $$r=|z|$$。','status':'verified','reviewer':'assistant_visual'}]}
            path=root/(result['source_sha256']+'.json');path.write_text(json.dumps(review),encoding='utf-8')
            enriched=enrich(doc(),source,str(root))
            self.assertEqual('FORMULA',enriched.elements[-1].type)
            self.assertEqual([{'pageIndex':0}],enriched.elements[-1].locators)
            self.assertIn(FLAG,enriched.qualityFlags)  # Partial review is not full coverage.
            review['records'][0]['status']='draft';path.write_text(json.dumps(review),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'NOT_VERIFIED'):enrich(doc(),source,str(root))
            review['source_sha256']='wrong';path.write_text(json.dumps(review),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'SOURCE_MISMATCH'):enrich(doc(),source,str(root))


if __name__=='__main__':unittest.main()
