import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from knowledge_service.parsing.convert import validate_file, parse


class ParsingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def test_reject_invalid_zip(self):
        p=self.root/'bad.docx';p.write_bytes(b'not a zip')
        with self.assertRaisesRegex(ValueError,'INVALID_OFFICE'): validate_file(p)
    def test_reject_zip_expansion(self):
        p=self.root/'bad.pptx'
        with ZipFile(p,'w') as z: z.writestr('large.xml','x'*100)
        with self.assertRaisesRegex(ValueError,'ARCHIVE_SIZE'): validate_file(p,max_expanded=50)
    def test_reject_unsupported_or_empty(self):
        p=self.root/'a.doc';p.write_text('x')
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED'): validate_file(p)
        p=self.root/'empty.pdf';p.write_bytes(b'')
        with self.assertRaisesRegex(ValueError,'FILE_SIZE'): validate_file(p)
    def test_video_adapter_preserves_time_and_artifacts(self):
        source=self.root/'video.json'
        source.write_text(json.dumps({'source':'video','segments':[{'startMs':1000,'endMs':3000,
            'transcript':'链式法则','ocrTexts':[],'evidenceFrames':[]}]}),encoding='utf-8')
        destination=self.root/'artifacts'
        parse(source,'rev1',destination)
        self.assertEqual({p.name for p in destination.iterdir()},
                         {'document.json','content.md','manifest.json'})
        doc=json.loads((destination/'document.json').read_text(encoding='utf-8'))
        self.assertIn('链式法则',(destination/'content.md').read_text(encoding='utf-8'))
        self.assertEqual(doc['resourceRevisionId'],'rev1')
        self.assertIn('1000',json.dumps(doc['elements'][0]['locators']))
    def test_pdf_fails_closed_without_local_models(self):
        source=self.root/'text.pdf';source.write_bytes(b'%PDF-1.7\n')
        with self.assertRaisesRegex(ValueError,'MODEL_DIRECTORY_MISSING'):
            parse(source,'rev1',self.root/'out')


if __name__=='__main__': unittest.main()
