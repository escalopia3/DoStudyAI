"""Local-only media adapters. Model paths must exist before initialization."""
import os
import shutil
import subprocess
from pathlib import Path
from knowledge_service.models import DocumentElement, NormalizedDocument
from knowledge_service.modules.document_parser import normalize_video, save_artifacts

def parse_image(source, revision, destination):
    from rapidocr import RapidOCR
    root = Path(os.environ.get('DOVIDEO_OCR_MODEL_PATH', '.learning-models/RapidOcr')).resolve()
    names = ['PP-OCRv6_det_small.onnx', 'ch_ppocr_mobile_v2.0_cls_mobile.onnx', 'PP-OCRv6_rec_small.onnx']
    if not all((root / name).is_file() for name in names):
        raise ValueError('OCR_LOCAL_MODELS_MISSING')
    engine = RapidOCR(params={f'{kind}.model_path':str(root / name)
                              for kind, name in zip(('Det','Cls','Rec'), names)})
    result = engine(str(source))
    texts = list(result.txts) if result.txts is not None else []
    boxes = result.boxes.tolist() if result.boxes is not None else []
    elements = [DocumentElement(f'{revision}-ocr-{i}', 'PARAGRAPH', text, [], [f'ocr/{i}'],
                 [{'type':'IMAGE', 'polygon':boxes[i] if i < len(boxes) else []}], 'OCR')
                for i, text in enumerate(texts)]
    document = NormalizedDocument(revision, source.name, 'IMAGE', {'name':'rapidocr','schemaVersion':'1'}, elements)
    if not elements:
        raise ValueError('EMPTY_DOCUMENT')
    return save_artifacts(document, destination)

def parse_media(source, revision, destination):
    ffmpeg = os.getenv('DOVIDEO_FFMPEG') or shutil.which('ffmpeg')
    model = Path(os.getenv('DOVIDEO_ASR_MODEL_PATH', 'missing-asr-model'))
    if not ffmpeg:
        raise ValueError('FFMPEG_MISSING')
    if not model.is_dir():
        raise ValueError('ASR_LOCAL_MODEL_MISSING')
    import json
    probe = str(Path(ffmpeg).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe'))
    if not Path(probe).is_file():
        raise ValueError('FFPROBE_MISSING')
    metadata = json.loads(subprocess.run([probe,'-v','error','-show_format','-of','json',str(source)],
                          check=True,capture_output=True,text=True,timeout=30).stdout)
    duration = float(metadata['format']['duration'])
    if not 0 < duration <= 7200:
        raise ValueError('MEDIA_DURATION_LIMIT_2_HOURS')
    from faster_whisper import WhisperModel
    audio = source.with_suffix('.asr.wav')
    conversion = subprocess.run([ffmpeg, '-nostdin', '-y', '-i', str(source), '-vn', '-ac', '1', '-ar', '16000', str(audio)],
                   timeout=300, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    is_audio = source.suffix.lower() in ('.wav','.mp3')
    if conversion.returncode and is_audio:
        raise ValueError('AUDIO_DECODE_FAILED')
    engine = WhisperModel(str(model), device='cpu', compute_type='int8', local_files_only=True)
    # FFmpeg already produced PCM WAV. Pass samples directly to avoid a second
    # decoder and PyAV-version-specific keyword differences.
    import wave
    import numpy as np
    segments = []
    if conversion.returncode == 0:
        with wave.open(str(audio), 'rb') as pcm:
            if pcm.getnchannels() != 1 or pcm.getsampwidth() != 2 or pcm.getframerate() != 16000:
                raise ValueError('INVALID_ASR_PCM')
            if pcm.getnframes() > 16000 * 7200:
                raise ValueError('MEDIA_DURATION_LIMIT_2_HOURS')
            samples = np.frombuffer(pcm.readframes(pcm.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = engine.transcribe(samples)
    payload = {'source':source.name, 'segments':[{'startMs':int(s.start*1000),
        'endMs':max(int(s.start*1000)+1,int(s.end*1000)), 'transcript':s.text,
        'ocrTexts':[], 'evidenceFrames':[]} for s in segments]}
    document = normalize_video(payload, revision)
    if is_audio:
        document.sourceType = 'AUDIO'
        for element in document.elements:
            element.type = 'AUDIO_SEGMENT'
            element.extractionMethod = 'ASR'
            for locator in element.locators:
                locator['type'] = 'AUDIO'
    else:
        from rapidocr import RapidOCR
        root = Path(os.environ['DOVIDEO_OCR_MODEL_PATH'])
        models = {'Det':'PP-OCRv6_det_small.onnx','Cls':'ch_ppocr_mobile_v2.0_cls_mobile.onnx','Rec':'PP-OCRv6_rec_small.onnx'}
        if not all((root / name).is_file() for name in models.values()):
            raise ValueError('OCR_LOCAL_MODELS_MISSING')
        ocr = RapidOCR(params={f'{kind}.model_path':str(root/name) for kind,name in models.items()})
        frames = source.parent / 'frames'
        frames.mkdir()
        subprocess.run([ffmpeg,'-loglevel','error','-nostdin','-y','-threads','1','-i',str(source),
                        '-vf','fps=1/30:start_time=0:round=up,scale=1280:-2',
                        '-threads','1','-frames:v','120',str(frames/'%04d.jpg')], check=True, timeout=300,
                       stdout=subprocess.DEVNULL)
        for index, frame in enumerate(sorted(frames.glob('*.jpg'))):
            result = ocr(str(frame))
            texts = list(result.txts) if result.txts is not None else []
            if texts:
                document.elements.append(DocumentElement(f'{revision}-frame-{index}', 'VIDEO_FRAME',
                    '\n'.join(texts), [], [f'frames/{index}'],
                    [{'type':'VIDEO','startMs':index*30000,'endMs':min(int(duration*1000),(index+1)*30000)}], 'OCR',
                    data={'samplingIntervalMs':30000}))
        document.elements.sort(key=lambda item:item.locators[0]['startMs'])
        document.qualityFlags.append('VISUAL_SAMPLED_30_SECONDS_MAX_120_FRAMES')
        if conversion.returncode:
            document.qualityFlags.append('AUDIO_UNAVAILABLE')
    if not document.elements:
        raise ValueError('EMPTY_DOCUMENT')
    return save_artifacts(document, destination)
