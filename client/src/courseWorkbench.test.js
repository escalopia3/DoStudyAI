import test from 'node:test'
import assert from 'node:assert/strict'
import { receiptIdentity, createUploadReceipts } from './features/courses/uploadReceipts.js'
import { createRefreshLoop } from './features/courses/refreshLoop.js'
import { courseUrl, resourceFileKind, courseRequest } from './features/courses/courseApi.js'

test('receipt survives a lost response and reload without crossing accounts or destinations', () => {
  const entries = new Map()
  const storage = { getItem:key=>entries.get(key), setItem:(key,value)=>entries.set(key,value), removeItem:key=>entries.delete(key) }
  const file = { name:'lecture.pdf', size:120, lastModified:42 }
  const identity = receiptIdentity(1,2,null,file)
  const first = createUploadReceipts(storage,()=> 'receipt-original')
  assert.equal(first.get(identity),'receipt-original')
  const reloaded = createUploadReceipts(storage,()=> 'receipt-new')
  assert.equal(reloaded.get(identity),'receipt-original')
  assert.equal(reloaded.get(receiptIdentity(2,2,null,file)),'receipt-new')
  assert.notEqual(identity,receiptIdentity(1,3,null,file))
  assert.notEqual(identity,receiptIdentity(1,2,4,file))
  reloaded.forget(identity)
  assert.equal(reloaded.get(identity),'receipt-new')
})

test('blocked storage still preserves an in-page retry key', () => {
  let sequence = 0
  const receipts=createUploadReceipts({getItem(){throw Error()},setItem(){throw Error()}},()=>`receipt-${++sequence}`)
  assert.equal(receipts.get('file'),'receipt-1')
  assert.equal(receipts.get('file'),'receipt-1')
})

test('course navigation preserves video timestamps and other query parameters', () => {
  const original='http://localhost:5173/?other=1#video-t=42'
  assert.equal(courseUrl('9007199254740993',original),'/?other=1&course=9007199254740993#video-t=42')
  assert.equal(courseUrl(null,'http://localhost:5173/?other=1&course=2#video-t=42'),'/?other=1#video-t=42')
})

test('unsupported legacy formats are not advertised as accepted uploads', () => {
  assert.equal(resourceFileKind('lesson.PPTX'),'DOCUMENT')
  assert.equal(resourceFileKind('lesson.pdf'),'DOCUMENT')
  assert.equal(resourceFileKind('lesson.mp4'),'VIDEO')
  assert.equal(resourceFileKind('lesson.ppt'),null)
  assert.equal(resourceFileKind('lesson.doc'),null)
  assert.equal(resourceFileKind('lesson.docx.exe'),null)
})

test('refresh loop waits for in-flight refresh and does not restart after unmount', async () => {
  let callback, resolve, scheduled=0
  const clock={setTimeout(fn){callback=fn;scheduled++;return scheduled},clearTimeout(){callback=null}}
  const loop=createRefreshLoop(()=>new Promise(done=>{resolve=done}),()=>true,10,clock)
  loop.start(); loop.start()
  assert.equal(scheduled,1)
  const pending=callback()
  assert.equal(scheduled,1)
  loop.stop();resolve();await pending
  assert.equal(scheduled,1)
})

test('background refresh pauses while hidden or busy', async () => {
  let callback, calls=0
  const clock={setTimeout(fn){callback=fn;return 1},clearTimeout(){}}
  const loop=createRefreshLoop(async()=>calls++,()=>false,10,clock)
  loop.start();await callback();assert.equal(calls,0);loop.stop()
})

test('upload conflict preserves HTTP status for receipt recovery', async () => {
  globalThis.localStorage={getItem:()=>null}
  globalThis.fetch=async()=>new Response(JSON.stringify({code:40900,message:'different upload',data:null}),{status:409,headers:{'Content-Type':'application/json'}})
  await assert.rejects(courseRequest('/learn/courses/1/documents'),error=>error.status===409 && error.message==='different upload')
})
