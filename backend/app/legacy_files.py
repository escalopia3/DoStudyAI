"""Verify exported originals and stage them through the authenticated v2 upload API."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from app.legacy_courses import legacy_id
from dovideo.config import load_local_environment

def verified_files(manifest,root):
    root=root.resolve()
    seen=set()
    for item in manifest['resources']:
        key=legacy_id(manifest['source'],'resource',item['id'])
        if key in seen:raise ValueError('duplicate legacy resource')
        seen.add(key)
        path=(root/item['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f'invalid export file for resource {item["id"]}')
        with path.open('rb') as source:
            digest=hashlib.file_digest(source,'sha256').hexdigest()
        if digest!=item['sha256'] or path.stat().st_size!=item['size_bytes']:
            raise ValueError(f'checksum or size mismatch for resource {item["id"]}')
        yield key,item,path

def stage(api,objects,minio_origin,source,key,item,path,attempt):
    course=legacy_id(source,'course',item['course_id'])
    chapter=legacy_id(source,'chapter',item['chapter_id']) if item.get('chapter_id') else None
    def send(method,url,**kwargs):
        response=api.request(method,url,**kwargs)
        response.raise_for_status()
        return response.json()
    def put(url,body,headers=None):
        target=urlsplit(url)
        if (target.scheme,target.netloc)!=minio_origin:
            raise ValueError('unexpected object storage origin')
        objects.put(url,content=body,headers=headers).raise_for_status()
    ticket=send('POST',f'/courses/{course}/resources/uploads',headers={'Idempotency-Key':f'legacy-{key}-{attempt}'},
                json={'filename':item['filename'],'contentType':item['content_type'],'sizeBytes':item['size_bytes'],
                      'chapterId':str(chapter) if chapter else None,'sha256':item['sha256']})
    upload_id=ticket['uploadId']
    if ticket['state']!='COMPLETED':
        with path.open('rb') as file:
            if ticket.get('mode')=='parts':
                for number in range(1,ticket['partCount']+1):
                    part=send('POST',f'/uploads/{upload_id}/parts/{number}')
                    put(part['uploadUrl'],file.read(ticket['partSize']))
            else:
                put(ticket['uploadUrl'],file.read(),ticket.get('headers'))
    return send('POST',f'/uploads/{upload_id}/complete')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--attempt',type=int,default=1)
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    files=list(verified_files(manifest,args.manifest.parent))
    if not args.apply:
        print(f'Verified {len(files)} original files; nothing uploaded.')
        return
    load_local_environment()
    token=os.environ['DOVIDEO_LEGACY_IMPORT_TOKEN']
    minio=urlsplit(os.environ['DOVIDEO_MINIO_ENDPOINT'])
    try:
        with httpx.Client(base_url='http://127.0.0.1:8092/api/v2',headers={'Authorization':'Bearer '+token},
                          trust_env=False,timeout=60) as api, httpx.Client(trust_env=False,timeout=120) as objects:
            for key,item,path in files:
                receipt=stage(api,objects,(minio.scheme,minio.netloc),manifest['source'],key,item,path,args.attempt)
                print(json.dumps({'legacy_id':item['id'],'resource_id':receipt['resourceId'],'job_id':receipt['jobId']}))
    except httpx.HTTPStatusError as exc:
        parser.exit(1,f'Upload rejected: HTTP {exc.response.status_code}\n')
    except httpx.RequestError:
        parser.exit(1,'Upload interrupted; check services and rerun the same attempt.\n')

if __name__=='__main__':main()
