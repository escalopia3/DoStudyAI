import test from 'node:test'
import assert from 'node:assert/strict'
import {clearToken, request, saveToken, sessionEvents, streamRun, upload} from './features/v2/api.js'

test('only an authentication error for the current v2 token expires the session', async () => {
  const originalFetch = globalThis.fetch
  const originalStorage = globalThis.localStorage
  const saved = new Map()
  globalThis.localStorage = {
    getItem: key => saved.get(key),
    setItem: (key, value) => saved.set(key, value),
    removeItem: key => saved.delete(key)
  }
  let expired = 0
  const onExpired = () => { expired++ }
  sessionEvents.addEventListener('expired', onExpired)
  const reply = code => Response.json({code, request_id: 'req-1'}, {status: 401})
  try {
    saveToken('old')
    globalThis.fetch = async () => {
      saveToken('new')
      return reply('SESSION_EXPIRED')
    }
    await assert.rejects(request('/courses'), {code: 'SESSION_EXPIRED', requestId: 'req-1'})
    globalThis.fetch = async () => reply('INVALID_CREDENTIALS')
    await assert.rejects(request('/auth/login'), {code: 'INVALID_CREDENTIALS'})
    assert.equal(expired, 0)

    globalThis.fetch = async () => reply('SESSION_EXPIRED')
    await assert.rejects(request('/courses'), {code: 'SESSION_EXPIRED'})
    assert.equal(expired, 1)
  } finally {
    sessionEvents.removeEventListener('expired', onExpired)
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalStorage
  }
})

test('v2 API keeps its own token and reports gateway errors', async () => {
  const originalFetch = globalThis.fetch
  const originalStorage = globalThis.localStorage
  const saved = new Map()
  globalThis.localStorage = {getItem:key=>saved.get(key)||null,setItem:(key,value)=>saved.set(key,value),removeItem:key=>saved.delete(key)}
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/v2/courses')
    assert.equal(options.headers.Authorization, 'Bearer v2-session')
    return new Response(JSON.stringify({code:'COURSE_NOT_FOUND',message:'课程不存在'}), {status:404,headers:{'Content-Type':'application/json'}})
  }
  try {
    saveToken('v2-session')
    await assert.rejects(request('/courses'), error=>error.status===404 && error.message==='课程不存在')
    assert.equal(saved.has('authToken'), false)
  } finally {clearToken();globalThis.fetch=originalFetch;globalThis.localStorage=originalStorage}
})

test('failed direct upload cancels its pending session', async () => {
  const originalFetch=globalThis.fetch
  const originalStorage=globalThis.localStorage
  const calls=[]
  globalThis.localStorage={getItem:()=>null}
  globalThis.fetch=async (url, options) => {
    calls.push([url,options.method])
    if(url.endsWith('/resources/uploads')) return Response.json({uploadId:'u1',mode:'single',uploadUrl:'http://storage/object',headers:{'Content-Type':'application/pdf'}})
    if(url==='http://storage/object') return new Response('',{status:503})
    if(url.endsWith('/uploads/u1/cancel')) return Response.json({state:'CANCELLED'})
    throw new Error(`Unexpected request: ${url}`)
  }
  try {
    const file=new Blob(['%PDF-1.4'],{type:'application/pdf'});file.name='notes.pdf'
    await assert.rejects(upload('course',null,file),/文件上传失败/)
    assert.deepEqual(calls.map(([url])=>url),[
      '/api/v2/courses/course/resources/uploads','http://storage/object','/api/v2/uploads/u1/cancel'])
  } finally {globalThis.fetch=originalFetch;globalThis.localStorage=originalStorage}
})

test('v2 run events parse fragmented SSE frames', async () => {
  const originalFetch=globalThis.fetch
  const originalStorage=globalThis.localStorage
  globalThis.localStorage={getItem:()=>null}
  globalThis.fetch=async ()=>new Response(new ReadableStream({start(controller){
    controller.enqueue(new TextEncoder().encode('id: 1\nevent: tool.started\ndata: {"name":"query_course_'))
    controller.enqueue(new TextEncoder().encode('knowledge"}\n\nid: 2\nevent: run.completed\ndata: {"answer":"好"}\n\n'))
    controller.close()
  }}))
  try {
    const seen=[]
    await streamRun('r1',(kind,data)=>seen.push([kind,data]),new AbortController().signal)
    assert.deepEqual(seen,[['tool.started',{name:'query_course_knowledge'}],['run.completed',{answer:'好'}]])
  } finally {globalThis.fetch=originalFetch;globalThis.localStorage=originalStorage}
})
