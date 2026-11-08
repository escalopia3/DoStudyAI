const base='/api/v2'
const key='dovideo-v2-token'
export const token=()=>localStorage.getItem(key)
export const saveToken=value=>localStorage.setItem(key,value)
export const clearToken=()=>localStorage.removeItem(key)
export const sessionEvents = new EventTarget()

async function responseError(response, requestToken) {
  const payload = await response.json().catch(() => ({}))
  const error = Object.assign(new Error(payload.message || `请求失败 (${response.status})`), {
    status: response.status, code: payload.code, requestId: payload.request_id
  })
  if (response.status === 401 && requestToken && requestToken === token()
      && ['SESSION_EXPIRED', 'INVALID_TOKEN', 'AUTH_REQUIRED'].includes(error.code)) {
    sessionEvents.dispatchEvent(new Event('expired'))
  }
  return error
}

export async function request(path,{method='GET',body,headers={},signal}={}){
  const requestToken = ['/auth/login', '/auth/register'].includes(path) ? null : token()
  const response=await fetch(base+path,{method,signal,headers:{...(requestToken?{Authorization:`Bearer ${requestToken}`}:{ }),
    ...(body && !(body instanceof Blob)?{'Content-Type':'application/json'}:{}),...headers},
    body:body && !(body instanceof Blob)?JSON.stringify(body):body})
  if(!response.ok) throw await responseError(response, requestToken)
  return response.status===204?null:response.json()
}
export async function streamRun(runId,onEvent,signal){
  let cursor=''
  for(let retry=0;retry<3&&!signal.aborted;retry++){
    const requestToken = token()
    const response=await fetch(`${base}/runs/${runId}/events`,{signal,headers:{...(requestToken?{Authorization:`Bearer ${requestToken}`}:{}),...(cursor?{'Last-Event-ID':cursor}:{})}})
    if(!response.ok) throw await responseError(response, requestToken)
    if(!response.body) throw new Error('运行事件连接没有返回数据')
    const reader=response.body.getReader(),decoder=new TextDecoder()
    let buffer=''
    try {
      while(!signal.aborted){
        const {value,done}=await reader.read();if(done)break
        buffer+=decoder.decode(value,{stream:true})
        let boundary
        while((boundary=buffer.indexOf('\n\n'))>=0){
          const raw=buffer.slice(0,boundary).replaceAll('\r','');buffer=buffer.slice(boundary+2)
          const id=raw.match(/^id: (.+)$/m)?.[1],kind=raw.match(/^event: (.+)$/m)?.[1]
          const data=raw.match(/^data: (.+)$/m)?.[1]
          if(id)cursor=id
          if(kind&&data){onEvent(kind,JSON.parse(data));if(['run.completed','run.failed','run.cancelled'].includes(kind))return}
        }
      }
    } finally {reader.releaseLock()}
  }
}
export function mime(file){const ext=file.name.split('.').pop().toLowerCase();return {
  pdf:'application/pdf',docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  pptx:'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  mp4:'video/mp4',webm:'video/webm',mp3:'audio/mpeg',wav:'audio/wav',png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg'}[ext]}
export async function upload(courseId,chapterId,file){
  const contentType=mime(file);if(!contentType)throw new Error('当前不支持此文件格式')
  const id=crypto.randomUUID().replaceAll('-','')
  const ticket=await request(`/courses/${courseId}/resources/uploads`,{method:'POST',headers:{'Idempotency-Key':id},
    body:{filename:file.name,contentType,sizeBytes:file.size,chapterId}})
  try {if(ticket.mode==='parts'){
    for(let number=1;number<=ticket.partCount;number++){
      const part=await request(`/uploads/${ticket.uploadId}/parts/${number}`,{method:'POST'})
      const start=(number-1)*ticket.partSize
      const response=await fetch(part.uploadUrl,{method:'PUT',body:file.slice(start,start+ticket.partSize)})
      if(!response.ok)throw new Error(`第${number}片上传失败`)
    }
  }else{
    const response=await fetch(ticket.uploadUrl,{method:'PUT',headers:ticket.headers||{'Content-Type':contentType},body:file})
    if(!response.ok)throw new Error('文件上传失败')
  }
  return await request(`/uploads/${ticket.uploadId}/complete`,{method:'POST'})
  } catch(error) {
    await request(`/uploads/${ticket.uploadId}/cancel`,{method:'POST'}).catch(()=>{})
    throw error
  }
}
