<template>
  <section class="courses-workbench">
    <div class="course-heading">
      <div>
        <button v-if="courseId" class="back-link" :disabled="busy" @click="navigate(null)">← 我的课程</button>
        <p class="eyebrow">LEARNING WORKSPACE</p>
        <h1>{{ course?.name || (courseId ? '课程资料' : '我的课程') }}</h1>
        <p class="muted">{{ courseId ? course?.description || '按章节收集视频、讲义与课件。' : '把每一门课的资料，放在一起。' }}</p>
      </div>
      <button v-if="!courseId" @click="showCreate = !showCreate">＋ 新建课程</button>
      <span v-else class="tag">{{ course?.semester || '未设置学期' }}</span>
    </div>

    <p v-if="error" class="notice error" role="alert">{{ error }} <button :disabled="busy" @click="reload()">重新加载</button></p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <p v-if="loading" class="muted" role="status">正在加载…</p>

    <template v-if="!courseId">
      <form v-if="showCreate" class="panel create-form" @submit.prevent="createCourse">
        <h2>新建课程</h2>
        <label>课程名称<input v-model="draft.name" required maxlength="100" placeholder="例如：数据结构" /></label>
        <label>学期<input v-model="draft.semester" maxlength="50" placeholder="例如：2026 秋季" /></label>
        <label>课程简介<textarea v-model="draft.description" maxlength="1000" rows="2" /></label>
        <div class="actions"><button :disabled="busy">{{ busy ? '创建中…' : '创建并进入' }}</button><button type="button" class="secondary" :disabled="busy" @click="showCreate=false">取消</button></div>
      </form>
      <div class="course-grid">
        <button v-for="item in courses" :key="item.id" class="course-card" @click="navigate(item.id)">
          <span class="tag">{{ item.semester || '课程' }}</span>
          <h2>{{ item.name }}</h2><p>{{ item.description || '进入课程，添加学习资料' }}</p>
          <span class="muted">{{ item.resourceCount }} 份资料　进入课程 →</span>
        </button>
      </div>
      <div v-if="!loading && !courses.length && !error" class="panel empty">还没有课程。点击“新建课程”，开始整理第一门课。</div>
      <div v-if="total > 20" class="actions pagination"><button :disabled="page===1 || loading" @click="changePage(-1)">上一页</button><span>{{ page }} / {{ Math.ceil(total/20) }}</span><button :disabled="page*20>=total || loading" @click="changePage(1)">下一页</button></div>
      <p class="muted">已有视频可在进入课程后，通过“加入已有视频”归档，无需重新上传。</p>
    </template>

    <div v-else-if="course" class="course-layout">
      <aside class="panel chapters">
        <h2>章节资料</h2>
        <button :class="{ selected: selectedChapter==='all' }" :disabled="busy" @click="selectChapter('all')">全部资料</button>
        <button :class="{ selected: selectedChapter==='unassigned' }" :disabled="busy" @click="selectChapter('unassigned')">未分章</button>
        <button v-for="item in course.chapters" :key="item.id" :class="{ selected: selectedChapter===item.id }" :disabled="busy" @click="selectChapter(item.id)">{{ item.name }}</button>
        <form @submit.prevent="createChapter">
          <label class="muted" for="chapter-name">新建章节</label>
          <input id="chapter-name" v-model="chapterName" maxlength="100" required placeholder="例如：第一章 绪论" />
          <button :disabled="busy || !chapterName.trim()">＋ 创建章节</button>
        </form>
      </aside>
      <div class="resource-area">
        <LearningAgentPanel :key="String(courseId)" :course-id="courseId" @practice-created="learningRefresh++" />
        <LearningProgressPanel :course-id="courseId" :refresh-key="learningRefresh" />
        <div class="panel">
          <h2>{{ chapterTitle }}</h2>
          <p class="muted">上传至：{{ uploadChapter ? chapterTitle : '未分章' }} · 视频沿用原处理流程；文档支持 PDF / DOCX / PPTX。</p>
          <div class="actions">
            <button :disabled="busy" @click="fileInput.click()">＋ 上传资料</button>
            <button class="secondary" :disabled="busy" @click="loadExisting">加入已有视频</button>
            <button v-if="busy" class="secondary" @click="cancelUpload">取消当前操作</button>
          </div>
          <input ref="fileInput" type="file" multiple hidden accept=".mp4,.mov,.mkv,.avi,.webm,.m4v,.pdf,.docx,.pptx" @change="uploadFiles" />
          <form class="url-form" @submit.prevent="uploadUrl">
            <input v-model="videoUrl" type="url" required aria-label="在线视频链接" placeholder="粘贴 B站 / YouTube 等视频链接" :disabled="busy" />
            <button :disabled="busy || !videoUrl.trim()">导入视频</button>
          </form>
          <p v-if="progress" role="status" class="notice">{{ progress }}</p>
          <ul v-if="uploadResults.length" class="upload-results" aria-live="polite"><li v-for="(item,index) in uploadResults" :key="index" :class="{error:item.failed}">{{ item.text }}</li></ul>
          <p class="muted small">文档每份不超过 50 MiB，一次最多 10 个文件。上传后会自动解析并建立索引；资料就绪后可在上方学习助手中检索。</p>
        </div>

        <div v-if="showExisting" class="panel">
          <div class="actions"><h2>待归课视频</h2><button class="secondary" @click="showExisting=false">收起</button></div>
          <p v-if="!existing.length" class="muted">暂无待归课视频。</p>
          <div v-for="item in existing" :key="item.id" class="existing-row"><span>{{ item.filename }}</span><button :disabled="busy" @click="joinExisting(item)">加入当前章节</button></div>
        </div>

        <div class="resource-toolbar"><h2>资料 <span class="muted">{{ resources.length }}</span></h2><button class="secondary" :disabled="busy || loading" @click="reload()">刷新状态</button><select v-model="typeFilter" aria-label="筛选资料类型"><option value="ALL">全部类型</option><option value="VIDEO">视频</option><option value="PDF">PDF</option><option value="DOCX">Word</option><option value="PPTX">PPT</option></select></div>
        <div v-if="!loading && !filteredResources.length" class="panel empty">这里还没有资料，上传文件或加入已有视频。</div>
        <article v-for="item in filteredResources" :key="item.id" class="panel resource-card">
          <span class="file-type">{{ {VIDEO:'视频',DOCX:'Word',PPTX:'PPT',PDF:'PDF'}[item.type] }}</span>
          <div class="resource-info"><h3>{{ item.filename }}</h3><p class="muted">{{ statusLabel(item) }} <span v-if="item.sizeBytes">· {{ formatBytes(item.sizeBytes) }}</span></p></div>
          <div v-if="item.type==='VIDEO'" class="actions video-actions">
            <button class="secondary" :disabled="item.status!=='COMPLETED'" @click="$emit('open-video',videoItem(item))">播放 / 分析</button>
            <button class="secondary" :disabled="item.status!=='COMPLETED'" @click="$emit('transcribe-video',videoItem(item))">提取文字</button>
            <button class="secondary" :disabled="item.status!=='COMPLETED'" @click="$emit('download-audio',videoItem(item))">下载音频</button>
            <button class="secondary" :disabled="busy || deletingId!=null" @click="$emit('delete-video',videoItem(item))">{{ String(deletingId)===item.mediaId ? '删除中…' : '删除视频' }}</button>
          </div>
          <button v-else class="secondary" :disabled="busy" @click="getFile(item)">获取原文件</button>
          <button v-if="['FAILED','CANCELLED'].includes(item.parseStatus) && item.parseJobId" class="secondary" :disabled="busy" @click="parseAction(item,'retry')">重试解析</button>
          <button v-if="['QUEUED','RUNNING','PARSED','INDEXING'].includes(item.parseStatus) && item.parseJobId" class="secondary" :disabled="busy" @click="parseAction(item,'cancel')">取消处理</button>
          <a v-if="download?.id===item.id" :href="download.url" target="_blank" rel="noopener noreferrer">打开 / 下载原文件</a>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref } from 'vue'
import { captureAuthSession } from '../../api.js'
import { uploadVideoInChunks, validateVideoFile, formatBytes } from '../../chunkUpload.js'
import { courseRequest, postJson, resourceFileKind, courseUrl } from './courseApi.js'
import { createUploadReceipts, receiptIdentity } from './uploadReceipts.js'
import { createRefreshLoop } from './refreshLoop.js'
import LearningAgentPanel from './LearningAgentPanel.vue'
import LearningProgressPanel from './LearningProgressPanel.vue'

const props = defineProps({
  user: { type: Object, required: true },
  deletingId: { type: [String, Number], default: null },
  activeTasks: { type: Array, default: () => [] }
})
const emit = defineEmits(['open-video','transcribe-video','download-audio','delete-video','media-changed'])
const courses=ref([]), course=ref(null), resources=ref([]), existing=ref([])
const courseId=ref(new URLSearchParams(location.search).get('course'))
const loading=ref(false), busy=ref(false), error=ref(''), notice=ref(''), progress=ref('')
const showCreate=ref(false), showExisting=ref(false), chapterName=ref(''), selectedChapter=ref('all')
const videoUrl=ref(''), fileInput=ref(null), typeFilter=ref('ALL'), download=ref(null), uploadResults=ref([])
const page=ref(1), total=ref(0), draft=reactive({name:'',semester:'',description:''})
const learningRefresh=ref(0)
let controller=new AbortController(), generation=0, loadSequence=0, operationController=null
let receiptStorage
try { receiptStorage=window.localStorage } catch { /* Browser storage is optional. */ }
const receipts=createUploadReceipts(receiptStorage)
const refreshLoop=createRefreshLoop(()=>reload({background:true}),()=>Boolean(courseId.value && course.value && !busy.value && !loading.value && !error.value && !document.hidden))
const uploadChapter=computed(()=> ['all','unassigned'].includes(selectedChapter.value)?null:selectedChapter.value)
const chapterTitle=computed(()=>selectedChapter.value==='all'?'全部资料':selectedChapter.value==='unassigned'?'未分章':course.value?.chapters.find(item=>item.id===selectedChapter.value)?.name || '章节资料')
const filteredResources=computed(()=>resources.value.filter(item=>typeFilter.value==='ALL'||item.type===typeFilter.value))
const videoItem=item=>({id:item.mediaId,filename:item.filename,status:item.status})
const statusLabel=item=> {
  const task=props.activeTasks.find(task=>String(task.id)===item.mediaId)
  if(item.type==='VIDEO' && task) return task.type==='ai'?'视频分析中':'文字提取中'
  return item.type==='VIDEO'?({COMPLETED:'视频已就绪',PROCESSING:'视频处理中',FAILED:'视频处理失败'}[item.status]||'视频已上传'):({UPLOADED:'已上传',QUEUED:'等待解析',RUNNING:'正在解析',PARSED:'解析完成 · 等待建立索引',INDEXING:'正在建立检索索引',READY:'资料已就绪',FAILED:'资料处理失败',CANCELLED:'资料处理已取消'}[item.status]||'已上传')
}

function capture() {
  const version=generation, session=captureAuthSession()
  return ()=>version===generation && !controller.signal.aborted && session()
}
function showError(e, valid) { if(valid() && e.name!=='AbortError') error.value=e.message || '操作失败' }
async function parseAction(item, action) {
  const valid=capture()
  busy.value=true; error.value=''
  try {
    await courseRequest(`/learn/parse-jobs/${encodeURIComponent(item.parseJobId)}/${action}`,postJson({},controller.signal))
    if(valid()) await reload()
  } catch(e) { showError(e,valid) }
  finally { if(valid()) busy.value=false }
}
async function reload({background=false}={}) {
  const current=capture(), sequence=++loadSequence
  const valid=()=>current() && sequence===loadSequence
  if(!background){loading.value=true; error.value=''}
  try {
    if(courseId.value) {
      const id=courseId.value
      const query=new URLSearchParams()
      if(uploadChapter.value) query.set('chapterId',uploadChapter.value)
      if(selectedChapter.value==='unassigned') query.set('unassigned','true')
      const [detail,items]=await Promise.all([courseRequest(`/learn/courses/${id}`,{signal:controller.signal}),courseRequest(`/learn/courses/${id}/resources?${query}`,{signal:controller.signal})])
      if(valid()) { course.value=detail; resources.value=items }
    } else {
      const data=await courseRequest(`/learn/courses?page=${page.value}&size=20`,{signal:controller.signal})
      if(valid()) {courses.value=data.items; total.value=data.total}
    }
  } catch(e) {showError(e,valid)} finally {if(valid()) loading.value=false}
}
function resetView() {
  generation++; controller.abort(); controller=new AbortController(); operationController?.abort()
  busy.value=false; course.value=null; resources.value=[]; selectedChapter.value='all'; showExisting.value=false
  error.value=''; notice.value=''; progress.value=''; download.value=null; uploadResults.value=[]
  chapterName.value='';videoUrl.value='';typeFilter.value='ALL';loading.value=false
}
function navigate(id) { resetView(); courseId.value=id; history.pushState({},'',courseUrl(id)); reload() }
function onPopState() { resetView(); courseId.value=new URLSearchParams(location.search).get('course'); reload() }
function selectChapter(id) {
  generation++; controller.abort(); controller=new AbortController()
  selectedChapter.value=id; download.value=null; reload()
}
function changePage(delta) {page.value+=delta; generation++; controller.abort();controller=new AbortController();reload()}
async function run(action) {
  if(busy.value) return
  const valid=capture(); busy.value=true; error.value=''; operationController=new AbortController()
  try { await action(valid,operationController.signal) }
  catch(e) {showError(e,valid)}
  finally {if(valid()) {busy.value=false;progress.value=''}}
}
async function createCourse() {
  await run(async(valid,signal)=>{
    const created=await courseRequest('/learn/courses',postJson(draft,signal))
    if(valid()) {showCreate.value=false;Object.assign(draft,{name:'',semester:'',description:''});navigate(created.id)}
  })
}
async function createChapter() {
  await run(async(valid,signal)=>{
    const item=await courseRequest(`/learn/courses/${courseId.value}/chapters`,postJson({name:chapterName.value},signal))
    if(valid()) {chapterName.value='';selectedChapter.value=item.id;await reload()}
  })
}
async function loadExisting() {
  await run(async(valid,signal)=>{const items=await courseRequest('/learn/available-videos',{signal});if(valid()){existing.value=items;showExisting.value=true}})
}
async function joinExisting(item) {
  const id=courseId.value, chapterId=uploadChapter.value
  await run(async(valid,signal)=>{
    await courseRequest(`/learn/courses/${id}/videos`,postJson({mediaId:item.id,chapterId},signal))
    if(valid()){existing.value=existing.value.filter(video=>video.id!==item.id);notice.value='视频已加入课程';await reload()}
  })
}
function cancelUpload() { operationController?.abort(); notice.value='已停止等待当前操作。服务端可能已保存资料，可刷新确认；视频分片进度会保留。' }
async function uploadFiles(event) {
  const files=Array.from(event.target.files || []);event.target.value=''
  if(!files.length)return
  if(files.length>10){error.value='一次最多上传 10 个文件';return}
  const id=courseId.value, chapterId=uploadChapter.value
  await run(async(valid,signal)=>{
    uploadResults.value=[]
    for(const file of files) {
      if(!valid() || signal.aborted) break
      progress.value=`正在上传：${file.name}`
      let videoSaved=false
      try {
        const kind=resourceFileKind(file.name)
        if(!kind) throw new Error('支持视频、PDF、DOCX、PPTX；旧格式请先转换')
        if(kind==='VIDEO') {
          const problem=validateVideoFile(file);if(problem)throw new Error(problem)
          const video=await uploadVideoInChunks(file,p=>{if(valid())progress.value=`${file.name} · ${p.percent==null?'处理中':`${p.percent}%`}`},signal,props.user.id)
          videoSaved=true
          if(!valid() || signal.aborted) break
          await courseRequest(`/learn/courses/${id}/videos`,postJson({mediaId:video.id,chapterId},signal))
        } else {
          if(!file.size || file.size>50*1024*1024) throw new Error('文档须非空且不超过 50 MiB')
          const data=new FormData();data.append('file',file);if(chapterId)data.append('chapterId',chapterId)
          const identity=receiptIdentity(props.user.id,id,chapterId,file)
          try {
            await courseRequest(`/learn/courses/${id}/documents`,{method:'POST',body:data,headers:{'Idempotency-Key':receipts.get(identity)},signal})
          } catch(e) {
            if(e.status===409) receipts.forget(identity)
            throw e
          }
        }
        if(valid())uploadResults.value.push({text:`${file.name}：已加入课程`,failed:false})
      } catch(e) {
        if(valid())uploadResults.value.push({text:`${file.name}：${videoSaved?'视频已保存，可从“加入已有视频”重试归课。':signal.aborted?'已取消，可重新选择文件继续上传。':e.message}`,failed:true})
      }
    }
    if(valid()) {emit('media-changed');await reload()}
  })
}
async function uploadUrl() {
  const id=courseId.value, chapterId=uploadChapter.value, url=videoUrl.value.trim()
  await run(async(valid,signal)=>{
    progress.value='正在导入视频链接…'
    const video=await courseRequest(`/media/upload-url?${new URLSearchParams({url})}`,{method:'POST',signal})
    if(!valid())return
    try {await courseRequest(`/learn/courses/${id}/videos`,postJson({mediaId:video.id,chapterId},signal))}
    catch(e){throw new Error(`视频已保存，请从“加入已有视频”重试归课。${e.message}`)}
    if(valid()){videoUrl.value='';notice.value='视频已导入';emit('media-changed');await reload()}
  })
}
async function getFile(item) {
  await run(async(valid,signal)=>{const data=await courseRequest(`/learn/resources/${item.id}/file`,{signal});if(valid())download.value={id:item.id,url:data.url}})
}
function onVisible() { if(!document.hidden && !busy.value) reload({background:true}) }
function beforeUnload(event) { if(busy.value){event.preventDefault();event.returnValue=''} }
defineExpose({reload})
onMounted(()=>{
  window.addEventListener('popstate',onPopState)
  window.addEventListener('beforeunload',beforeUnload)
  document.addEventListener('visibilitychange',onVisible)
  window.addEventListener('online',onVisible)
  refreshLoop.start();reload()
})
onBeforeUnmount(()=>{
  generation++;controller.abort();operationController?.abort();refreshLoop.stop()
  window.removeEventListener('popstate',onPopState)
  window.removeEventListener('beforeunload',beforeUnload)
  window.removeEventListener('online',onVisible)
  document.removeEventListener('visibilitychange',onVisible)
})
</script>

<style scoped>
.video-actions{flex-wrap:wrap;justify-content:flex-start}.video-actions button{font-size:12px;padding:8px 10px}
.courses-workbench{max-width:1200px;margin:0 auto;padding:30px 0 70px;color:var(--text-main,#eee)}
.course-heading,.actions,.resource-toolbar,.existing-row{display:flex;align-items:center;justify-content:space-between;gap:14px}.course-heading{margin-bottom:30px}.course-heading h1{font-size:32px;margin:8px 0}.eyebrow{letter-spacing:.16em;font-size:11px;color:var(--accent-lime,#c5ff51)}
.muted{color:var(--text-muted,#a0a7b3);font-size:14px;line-height:1.6}.small{font-size:12px}.tag{font-size:12px;border:1px solid #455044;border-radius:20px;padding:5px 10px}.panel{background:var(--bg-card,#161a20);border:1px solid var(--border-tech,#303840);border-radius:14px;padding:22px;margin-bottom:16px}
button{font:inherit;cursor:pointer;border:1px solid transparent;border-radius:8px;padding:10px 16px;background:var(--accent-lime,#c5ff51);color:#111;font-weight:600}button:disabled{opacity:.45;cursor:not-allowed}.secondary,.back-link{background:transparent;color:inherit;border-color:#414952}.back-link{margin-bottom:12px}input,textarea,select{font:inherit;box-sizing:border-box;border:1px solid #414952;border-radius:8px;background:#11161d;color:#eee;padding:11px;width:100%}input:focus,textarea:focus,select:focus,button:focus-visible,a:focus-visible{outline:2px solid var(--accent-lime,#c5ff51);outline-offset:3px}label{display:grid;gap:8px;margin-bottom:14px}.create-form{max-width:620px}.course-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:20px;margin-bottom:24px}.course-card{text-align:left;padding:26px;background:var(--bg-card,#161a20);color:inherit;border:1px solid #303840;min-height:190px;overflow-wrap:anywhere}.course-card:hover{border-color:var(--accent-lime,#c5ff51)}h2{font-size:18px;margin:0 0 16px}h3{font-size:15px;margin:0;overflow-wrap:anywhere}.course-card h2{margin-top:24px}.course-card p{font-size:14px;font-weight:400;color:#a0a7b3}.course-layout{display:grid;grid-template-columns:230px minmax(0,1fr);gap:24px}.chapters{align-self:start}.chapters>button{display:block;background:transparent;color:inherit;text-align:left;width:100%;margin-bottom:7px;overflow-wrap:anywhere}.chapters>button.selected{background:#c5ff5119;color:var(--accent-lime,#c5ff51)}.chapters form{border-top:1px solid #303840;margin-top:20px;padding-top:18px}.chapters form button{margin-top:12px;width:100%}.url-form{display:flex;gap:12px;margin-top:18px}.url-form button{white-space:nowrap}.notice{padding:12px 16px;background:#c5ff5110;border-radius:8px;overflow-wrap:anywhere}.error{color:#ffa5a5}.resource-toolbar{margin:24px 0 16px}.resource-toolbar h2{margin:0}.resource-toolbar select{width:130px}.resource-card{display:flex;align-items:center;flex-wrap:wrap;gap:16px;padding:18px}.resource-info{flex:1;min-width:140px}.resource-info p{margin:6px 0 0}.file-type{padding:10px;border-radius:8px;background:#c5ff5112;font-size:13px;color:var(--accent-lime,#c5ff51)}.empty{text-align:center;color:#a0a7b3;padding:40px 20px}.existing-row{padding:12px 0;border-top:1px solid #303840}.existing-row span{overflow-wrap:anywhere;min-width:0}.existing-row button{flex-shrink:0}.upload-results{padding-left:20px;font-size:13px;line-height:1.8;overflow-wrap:anywhere}a{color:var(--accent-lime,#c5ff51)}.pagination{justify-content:center;margin:20px}
@media(max-width:720px){.course-layout{grid-template-columns:1fr}.course-heading{align-items:flex-start}.course-heading h1{font-size:26px}.actions{flex-wrap:wrap}.url-form{flex-direction:column}.chapters{margin-bottom:0}.courses-workbench{padding-top:18px}.resource-card button{font-size:12px}}
</style>
