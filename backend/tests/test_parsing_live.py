"""Opt-in real offline parsers, no dependency/model downloads."""
import os
import json
import tempfile
import unittest
from pathlib import Path
from dovideo.config import load_local_environment

@unittest.skipUnless(os.getenv('DOVIDEO_PARSING_LIVE') == '1', 'opt-in local model test')
class LiveParsers(unittest.TestCase):
    def test_audio_video(self):
        import subprocess
        from PIL import Image, ImageDraw, ImageFont
        from dovideo.media_parsing import parse_media
        load_local_environment()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wav = root/'speech.wav'
            command = "Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.SetOutputToWaveFile('" + str(wav).replace("'","''") + "'); $s.Speak('Computer networks provide reliable communication. TCP is a reliable transport protocol.'); $s.Dispose()"
            subprocess.run(['powershell','-NoProfile','-Command',command],check=True,timeout=30)
            parse_media(wav,'audio-test',root/'audio')
            audio=json.loads((root/'audio'/'document.json').read_text(encoding='utf-8'))
            self.assertEqual(audio['sourceType'],'AUDIO')
            self.assertTrue(audio['elements'])
            image=Image.new('RGB',(1200,300),'white')
            ImageDraw.Draw(image).text((30,80),'NETWORK TCP TRANSPORT',font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',40),fill='black')
            image.save(root/'frame.png')
            video=root/'lecture.mp4'
            subprocess.run([os.environ['DOVIDEO_FFMPEG'],'-y','-loop','1','-i',str(root/'frame.png'),'-i',str(wav),
                '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(video)],
                check=True,timeout=60,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            parse_media(video,'video-test',root/'video')
            result=json.loads((root/'video'/'document.json').read_text(encoding='utf-8'))
            self.assertTrue(any(x['type']=='VIDEO_FRAME' for x in result['elements']))
            self.assertTrue(any(x['type']=='VIDEO_SEGMENT' for x in result['elements']))

    def test_document_and_image(self):
        load_local_environment()
        from docx import Document
        from pptx import Presentation
        from PIL import Image, ImageDraw, ImageFont
        from knowledge_service.parsing.convert import parse
        from dovideo.media_parsing import parse_image
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            doc = Document()
            doc.add_heading('Network fundamentals',0)
            doc.add_paragraph('TCP provides reliable transport.')
            doc.save(root/'sample.docx')
            deck = Presentation()
            slide = deck.slides.add_slide(deck.slide_layouts[1])
            slide.shapes.title.text = 'Network fundamentals'
            slide.placeholders[1].text = 'TCP provides reliable transport.'
            deck.save(root/'sample.pptx')
            image = Image.new('RGB',(1200,300),'white')
            ImageDraw.Draw(image).text((30,80),'NETWORK TCP RELIABLE TRANSPORT',font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',40),fill='black')
            image.save(root/'sample.png')
            image.save(root/'sample.pdf','PDF')
            for suffix in ('docx','pptx','pdf'):
                parse(root/f'sample.{suffix}',f'test-{suffix}',root/suffix,
                      artifacts_path=os.environ['DOCLING_ARTIFACTS_PATH'])
                result=json.loads((root/suffix/'document.json').read_text(encoding='utf-8'))
                self.assertTrue(result['elements'], suffix)
            parse_image(root/'sample.png','test-image',root/'image')
            text=(root/'image'/'content.md').read_text(encoding='utf-8')
            self.assertIn('TCP',text.upper())
