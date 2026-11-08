<template>
  <main class="study-app">
    <header class="topbar"><a class="brand" href="/" aria-label="DoStudy 首页"><img class="brand-mark" src="/dostudy-mark.svg" width="40" height="40" alt="" />DoStudy<span class="brand-note">专注每一次理解</span></a><div v-if="user" class="account"><span>{{ user.nickname || user.username }}</span><button class="quiet" @click="logout">退出</button></div></header>
    <div v-if="error" class="banner error" role="alert">{{ error }}<button class="quiet" @click="error=''">关闭</button></div>
    <div v-if="notice" class="banner" role="status">{{ notice }}<button class="quiet" @click="notice=''">关闭</button></div>
    <div v-if="restoring" class="dashboard" role="status">正在验证登录状态…</div>
    <div v-else-if="!user" class="welcome">
      <section class="welcome-copy"><span class="eyebrow">YOUR SPACE TO LEARN</span><h1>把知识理清，<br/>让学习从容一点。</h1><p>课件、笔记与学习中的每个疑问，<br/>在这里连接起来。</p><div class="welcome-tags"><span>课程资料</span><span>随时答疑</span><span>专注复习</span></div></section>
      <form class="login-card" @submit.prevent="authenticate"><h2>{{ registering?'开启你的学习空间':'欢迎回来' }}</h2><p>登录后，继续你的课程与对话。</p><label>用户名<input v-model="username" required minlength="3" maxlength="32" autocomplete="username" placeholder="输入用户名" /></label><label>密码<input v-model="password" required minlength="8" maxlength="128" type="password" :autocomplete="registering?'new-password':'current-password'" placeholder="输入密码" /></label><button class="primary wide" :disabled="busy">{{ registering?'创建账号':'进入学习空间' }} →</button><button type="button" class="quiet wide" @click="registering=!registering">{{ registering?'已有账号？登录':'还没有账号？注册' }}</button></form>
    </div>
    <template v-else>
      <section v-if="!course" class="dashboard"><span class="eyebrow">MY LEARNING SPACE</span><h1>今天，想学点什么？</h1><p class="muted">每门课程，一个专属的学习空间。</p><form class="create-course" @submit.prevent="createCourse"><input v-model="courseName" required maxlength="100" aria-label="课程名称" placeholder="添加一门课程，例如：高等数学"/><button class="primary" :disabled="busy">＋ 新建课程</button></form><div class="course-grid"><button v-for="(item,i) in courses" :key="item.id" class="course-tile" @click="selectCourse(item.id)"><span class="course-number">{{ String(i+1).padStart(2,'0') }}</span><h2>{{ item.name }}</h2><p>{{ item.resourceCount }} 份学习资料</p><span class="enter">进入课程 ↗</span></button></div><div v-if="!courses.length" class="empty-courses">从第一门课程开始，上传课件，把疑问留在这里。</div></section>
      <div v-else class="workspace">
        <aside class="sidebar"><button class="quiet back" @click="selectCourse(null)">← 我的课程</button><h2>{{ course.name }}</h2><p class="muted">你的课程资料库</p><details class="chapter-editor"><summary>章节管理</summary><form @submit.prevent="createChapter"><input v-model="chapterName" maxlength="100" required placeholder="新章节名称" aria-label="新章节名称"/><button class="secondary" :disabled="busy">添加章节</button></form></details><label class="field-label">资料上传到<select v-model="chapterId"><option value="">未分章</option><option v-for="c in course.chapters" :key="c.id" :value="c.id">{{ c.name }}</option></select></label><label class="upload-box"><span>＋ 添加学习资料</span><small>PDF · PPT · Word · 音视频 · 图片</small><input type="file" multiple accept=".pdf,.docx,.pptx,.mp4,.webm,.mp3,.wav,.png,.jpg,.jpeg" @change="uploadFiles" :disabled="busy" aria-label="上传课程资料" /></label><div class="section-label">全部资料 <span>{{ resources.length }}</span></div><p v-if="!resources.length" class="muted">上传课程资料，让回答与你的课堂内容联系起来。</p><article v-for="r in resources" :key="r.id" class="resource"><div class="file-icon">{{ r.filename.split('.').pop().toUpperCase().slice(0,4) }}</div><div class="resource-body"><strong>{{ r.filename }}</strong><span class="resource-status">{{ resourceState(r) }}</span><div class="resource-actions"><button class="quiet" @click="download(r.id)">查看原文件 ↗</button><details><summary aria-label="资料操作">•••</summary><button class="quiet" @click="rebuild(r.id)">重新整理</button><button class="quiet danger" @click="remove(r.id)">删除资料</button></details></div></div></article><LegacyHistory :key="course.id" :course-id="course.id" /><p class="sidebar-foot">一步一步，把不懂变成理解。</p></aside>
        <section class="learning"><header class="learning-header"><div><span class="eyebrow">STUDY WITH FOCUS</span><h2>学习对话</h2></div><div class="thread-actions"><details class="study-settings" @toggle="settingsOpen = $event.currentTarget.open"><summary>学习设置</summary><StudyPractice v-if="settingsOpen" :key="course.id" :course-id="course.id" settings /></details><select v-model="threadId" @change="changeThread" aria-label="历史学习对话"><option value="">新的学习对话</option><option v-for="t in threads" :key="t.thread_id" :value="t.thread_id">{{ new Date(t.created_at).toLocaleString() }}</option></select><button class="secondary" @click="newThread" :disabled="busy">＋ 新对话</button></div></header>
          <div class="conversation"><div v-if="!messages.length" class="conversation-empty"><span class="learning-symbol">✦</span><h1>从一个问题开始。</h1><p>理解一个概念，梳理一章内容，或为下一次考试做准备。</p><div class="suggestions"><button @click="question='请结合课程资料，帮我梳理本章的核心概念。'">梳理核心概念 <span>↗</span></button><button @click="question='请先通览所选范围的课程资料。用「本节会学什么」说明目标，用「知识框架」梳理各知识点的关系，然后按框架从基础概念讲起，给出定义、例子、易错点和一道自测题。若只读到部分资料，请标明覆盖范围。'">开始课程预习 <span>↗</span></button><button @click="question='请结合课程资料，帮我制定考前复习计划。'">准备考前复习 <span>↗</span></button></div></div><article v-for="m in messages" :key="m.run_id" class="turn"><div class="user-message"><span class="speaker">你</span><p>{{ m.user }}</p></div><div class="assistant-message"><span class="speaker">DoStudy</span><div v-if="m.practice_question_ids?.length" class="practice-links"><button v-for="(id, index) in m.practice_question_ids" :key="id" class="secondary" type="button" @click="practicePanel?.openQuestion(id)">查看自测题{{ m.practice_question_ids.length > 1 ? ` ${index + 1}` : '' }} ↗</button></div><StudyAnswer v-if="(m.assistant || (m.run_id === activeRun && partial)) && !(m.practice_question_ids?.length && standalonePractice(m.user))" :content="m.assistant || partial" :references="m.references || []" :resources="resources" /><p v-else-if="!m.practice_question_ids?.length" role="status">{{ answerStatus(m.state) }}</p><p v-if="m.state==='FAILED' && m.assistant" role="status">{{ m.error_code==='PARTIAL_STREAM' ? '回答传输中断，以上内容不完整，尚未自动重试。' : m.error_code==='CITATION_VALIDATION_FAILED' ? '以上回答的引用未通过校验，请勿作为已核实结论使用。' : '本次回答未完成，以上内容仅供参考。' }}</p></div></article>
            <StudyPractice ref="practicePanel" :key="course.id" :course-id="course.id" :revision="practiceRevision" @practice="question = '请围绕刚才讲解的知识点出一道新的自测题，避免重复已经出过的题。'" />
          </div>
          <footer class="composer-area"><p v-if="!modelConfigured" class="model-notice">聊天模型尚未配置，暂时无法发送消息。请在本机配置模型后重启服务。</p><p v-if="activeRun" class="activity" role="status">{{ runState }}</p><form class="composer" @submit.prevent="ask"><textarea v-model="question" @keydown="onComposerKeydown" required maxlength="10000" placeholder="写下你的问题，我们一起理清思路…" aria-label="学习问题"/><div class="composer-bottom"><span>{{ modelId || '基于你的课程资料学习' }}</span><button v-if="activeRun" type="button" class="secondary" @click="cancelRun">停止回答</button><button v-else class="primary" :disabled="busy||!modelConfigured||!question.trim()">发送 ↑</button></div></form><p class="composer-hint">Enter 发送 · Shift + Enter 换行</p></footer>
        </section>
      </div>
    </template>
  </main>
</template>
<script setup>
import {computed,onMounted,onBeforeUnmount,ref} from 'vue'
import StudyPractice from './StudyPractice.vue'
import StudyAnswer from './StudyAnswer.vue'
import LegacyHistory from './LegacyHistory.vue'
import {request,token,saveToken,clearToken,upload,streamRun,sessionEvents} from './api.js'
const user=ref(null),courses=ref([]),course=ref(null),resources=ref([]),indexes=ref({}),messages=ref([]),threads=ref([]),modelConfigured=ref(false)
const username=ref(''),password=ref(''),registering=ref(false),busy=ref(false),error=ref(''),notice=ref('')
const partial=ref('')
const courseName=ref(''),chapterName=ref(''),chapterId=ref(''),question=ref(''),threadId=ref(''),activeRun=ref(''),runState=ref(''),modelId=ref(''),usage=ref(null)
let timer=null,epoch=0,ticking=false,streamAbort=null
const practicePanel = ref(null)
const practiceRevision = computed(() => messages.value.flatMap(message => message.practice_question_ids || []).join(','))
const standalonePractice = message => /^(?:请|帮我|你|能否|可以|麻烦|再|给我|围绕[^。！？]*?|根据[^。！？]*?|\s)*(?:出|生成|来)(?:[^。！？]*?)(?:自测|练习|测验|题)/.test(message || '')
const answerStatus = state => ({
  QUEUED: '正在准备回答…', RUNNING: '正在整理回答…',
  FAILED: '这次回答未能完成，请稍后重试。', CANCELLED: '本次回答已停止。'
}[state] || '正在整理回答…')
const restoring = ref(Boolean(token()))
const courseLoadFailed = ref(false)
const settingsOpen = ref(false)
const indexState=r=>indexes.value[r.id]?.indexState||'尚未索引'
const resourceState=r=>{
  const index=indexes.value[r.id]
  if(index?.activeIndexId)return index.indexState==='FAILED'?'可用于学习（重建失败）':'可用于学习'
  if(r.state==='PARSED')return {QUEUED:'等待建立知识索引',RUNNING:'正在建立知识索引',FAILED:'知识索引失败，请重试',CANCELLED:'知识索引已取消',NOT_STARTED:'尚未建立知识索引'}[index?.indexState]||'正在检查知识索引'
  return {VALIDATING:'等待文件校验',READY:'等待解析',PARSING:'正在解析',PARSE_FAILED:'解析失败',FAILED:'文件校验失败',PARSE_CANCELLED:'解析已取消'}[r.state]||'处理中'
}
async function attempt(action){error.value='';busy.value=true;try{await action()}catch(e){error.value=e.message}finally{busy.value=false}}
async function authenticate(){await attempt(async()=>{if(registering.value)await request('/auth/register',{method:'POST',body:{username:username.value,password:password.value}})
  const result=await request('/auth/login',{method:'POST',body:{username:username.value,password:password.value}})
  saveToken(result.token);user.value=result.user;password.value='';registering.value=false;await loadCourses()})}
function stopStream(){streamAbort?.abort();streamAbort=null}
function resetSession() {
  stopStream()
  clearToken()
  user.value = null
  course.value = null
  courses.value = []
  messages.value = []
  threads.value = []
  threadId.value = ''
  activeRun.value = ''
  runState.value = ''
  partial.value = ''
  settingsOpen.value = false
  epoch++
}
function expireSession() {
  resetSession()
  notice.value = '登录状态已失效，请重新登录。当前输入草稿已保留。'
}
function logout() {
  if (token()) request('/auth/logout', {method: 'POST'}).catch(() => {})
  resetSession()
  question.value = ''
  notice.value = ''
}
async function loadCourses() {
  const currentToken = token()
  try {
    const data = await request('/courses')
    if (currentToken === token()) {
      courses.value = data.items
      courseLoadFailed.value = false
    }
  } catch (error) {
    if (currentToken === token()) courseLoadFailed.value = true
    throw error
  }
}
async function createCourse(){await attempt(async()=>{const item=await request('/courses',{method:'POST',body:{name:courseName.value}});courseName.value='';await loadCourses();await selectCourse(item.id)})}
async function selectCourse(id){stopStream();const turn=++epoch;course.value=null;threadId.value='';messages.value=[];threads.value=[];activeRun.value='';if(!id){await loadCourses();return}
  settingsOpen.value = false
  await attempt(async()=>{const [data,history,capabilities]=await Promise.all([request(`/courses/${id}`),request(`/courses/${id}/threads`),request('/agent/capabilities')]);if(turn!==epoch)return
    course.value=data;threads.value=history.items;modelConfigured.value=capabilities.model_configured;modelId.value=capabilities.model_id||''
    threadId.value=threads.value[0]?.thread_id||'';await refresh();if(threadId.value)await loadMessages()})}
async function newThread(){if(!course.value)return;await attempt(async()=>{const created=await request(`/courses/${course.value.id}/threads`,{method:'POST'});stopStream();threads.value.unshift({...created,created_at:new Date().toISOString()});threadId.value=created.thread_id;messages.value=[];activeRun.value='';runState.value=''})}
async function changeThread(){stopStream();messages.value=[];activeRun.value='';runState.value='';await attempt(loadMessages)}
async function refresh(){if(!course.value)return;const id=course.value.id
  const [files,status]=await Promise.all([request(`/courses/${id}/resources`),request(`/courses/${id}/knowledge`)])
  if(course.value?.id===id){resources.value=files;indexes.value=Object.fromEntries(status.items.map(x=>[x.resourceId,x]))}}
async function createChapter(){await attempt(async()=>{await request(`/courses/${course.value.id}/chapters`,{method:'POST',body:{name:chapterName.value}})
  chapterName.value='';course.value=await request(`/courses/${course.value.id}`)})}
async function uploadFiles(event){const files=[...event.target.files];event.target.value='';await attempt(async()=>{for(const file of files){const result=await upload(course.value.id,chapterId.value||null,file);notice.value=`${file.name} 已上传，整理完成后即可用于学习。`}await refresh()})}
async function download(id){await attempt(async()=>{const data=await request(`/resources/${id}/download`);window.open(data.url,'_blank','noopener')})}
async function rebuild(id){await attempt(async()=>{const data=await request(`/resources/${id}/indexes`,{method:'POST'});notice.value='正在重新整理这份资料。';await refresh()})}
async function remove(id){if(!window.confirm('删除这份课程资料？删除后将无法再通过它查询知识。'))return;await attempt(async()=>{await request(`/resources/${id}`,{method:'DELETE'});await refresh()})}
function onComposerKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey
      || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  if (!event.repeat) event.currentTarget.form?.requestSubmit()
}
async function ask(){const text=question.value.trim();if(!text||!modelConfigured.value||activeRun.value||busy.value)return
  if(!threadId.value)await newThread();if(!threadId.value)return
  await attempt(async()=>{const result=await request(`/threads/${threadId.value}/runs`,{method:'POST',body:{message:text}})
    question.value='';activeRun.value=result.run_id;runState.value='正在准备回答…';await loadMessages()})}
async function loadMessages(){if(!threadId.value)return;const selected=threadId.value;const data=await request(`/threads/${selected}/messages`);if(selected!==threadId.value)return
  messages.value=data.items;const pending=data.items.findLast(m=>['QUEUED','RUNNING'].includes(m.state));if(pending){activeRun.value=pending.run_id;if(!streamAbort)watchRun(pending.run_id)}}
function watchRun(runId){stopStream();partial.value='';const controller=new AbortController();streamAbort=controller
  streamRun(runId,(kind,data)=>{if(activeRun.value!==runId)return
    if(kind==='tool.started')runState.value='正在查找相关资料…'
    else if(kind==='tool.completed')runState.value='正在整理学习思路…'
    else if(kind==='model.started')partial.value=''
    else if(kind==='model.delta'){runState.value='正在整理回答';partial.value+=data.text||''}
    else if(kind==='run.completed'||kind==='run.failed'||kind==='run.cancelled'){runState.value=kind==='run.completed'?'已完成':`运行失败：${data.code||'未知错误'}`;activeRun.value='';loadMessages().catch(()=>{})}
  },controller.signal).catch(error=>{if(!controller.signal.aborted)runState.value=`事件连接中断：${error.message}；正在轮询状态`})
    .finally(()=>{if(streamAbort===controller)streamAbort=null})}
async function cancelRun(){if(activeRun.value)await attempt(async()=>{await request(`/runs/${activeRun.value}/cancel`,{method:'POST'})})}
async function tick(){if(!course.value||document.hidden||ticking)return;ticking=true
  try{await refresh();if(activeRun.value){const row=await request(`/runs/${activeRun.value}`);if(!streamAbort)runState.value=row.error_code?`${row.state}: ${row.error_code}`:row.state
    if(['SUCCEEDED','FAILED','CANCELLED'].includes(row.state)){usage.value=row.usage;activeRun.value='';stopStream()}await loadMessages()}}catch(e){error.value=e.message}finally{ticking=false}}
async function restoreSession() {
  const currentToken = token()
  if (!currentToken) return
  restoring.value = true
  try {
    await attempt(async () => {
      const account = await request('/auth/me')
      if (currentToken !== token()) return
      user.value = account
      await loadCourses()
    })
  } finally {
    restoring.value = false
  }
}
onMounted(() => {
  sessionEvents.addEventListener('expired', expireSession)
  restoreSession()
  timer = setInterval(tick, 5000)
})
onBeforeUnmount(() => {
  sessionEvents.removeEventListener('expired', expireSession)
  clearInterval(timer)
  stopStream()
  epoch++
})
</script>
<style scoped>
.study-app{--ink:#263d37;--muted:#7b8983;--accent:#267b66;--line:#e1e8e1;background:#f7f8f4;color:var(--ink);min-height:100vh;font:14px/1.65 'Noto Sans SC',system-ui,sans-serif}.study-app *{box-sizing:border-box}.study-app button,.study-app input,.study-app select,.study-app textarea{font:inherit}.study-app button{cursor:pointer;border:0;border-radius:9px;transition:background .15s}.study-app button:disabled{opacity:.45;cursor:not-allowed}.study-app button:focus-visible,.study-app input:focus-visible,.study-app textarea:focus-visible,.study-app select:focus-visible,.study-app summary:focus-visible{outline:2px solid #267b66;outline-offset:3px}.study-app h1,.study-app h2,.study-app p{margin:0}.study-app h1{font-size:32px;font-weight:550;letter-spacing:-1px}.study-app h2{font-size:19px;font-weight:600}.topbar{height:76px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 36px;background:#fff}.brand{color:var(--ink);text-decoration:none;display:flex;gap:12px;align-items:center;font-size:23px;font-weight:700;letter-spacing:-.6px}.brand-note{font-size:12px;font-weight:400;letter-spacing:1px;color:var(--muted);border-left:1px solid var(--line);padding-left:16px;margin-left:8px}.account{display:flex;gap:16px;align-items:center;font-size:13px}.quiet{background:transparent;color:var(--muted);padding:5px 7px}.quiet:hover{color:var(--accent);background:#eaf1eb}.primary{background:var(--accent);color:white;padding:10px 20px}.primary:hover{background:#1b6553}.secondary{background:#eef3ed;color:var(--accent);padding:8px 12px}.muted{color:var(--muted);font-size:13px}.eyebrow{display:block;font-size:10px;font-weight:600;letter-spacing:2px;color:#7d9689;margin-bottom:8px}.banner{padding:12px 32px;background:#e9f3eb;display:flex;align-items:center;justify-content:space-between}.error{background:#fff0ec;color:#9b4739}.study-app input,.study-app select{width:100%;border:1px solid var(--line);background:#fff;color:var(--ink);padding:11px 12px;border-radius:8px}.welcome{max-width:1050px;margin:12vh auto;display:grid;grid-template-columns:1.3fr 1fr;gap:100px;align-items:center;padding:24px}.welcome-copy h1{font-size:44px;line-height:1.5;margin:18px 0}.welcome-copy p{color:var(--muted);line-height:2}.welcome-tags{display:flex;gap:12px;margin-top:36px}.welcome-tags span{border:1px solid var(--line);padding:6px 14px;border-radius:24px;font-size:12px}.login-card{padding:36px;background:white;border:1px solid var(--line);border-radius:20px;box-shadow:0 16px 60px #263d3706}.login-card p{color:var(--muted);font-size:13px;margin:8px 0 24px}.login-card label{display:block;font-size:12px;margin:18px 0}.login-card input{margin-top:7px}.wide{width:100%;margin-top:12px}.dashboard{max-width:1120px;margin:64px auto;padding:0 24px}.dashboard>.muted{margin:12px 0 32px}.create-course{display:flex;gap:12px;max-width:600px;margin-bottom:36px}.create-course button{white-space:nowrap}.course-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}.course-tile{padding:26px;text-align:left;background:white;border:1px solid var(--line)!important;min-height:210px;color:var(--ink);position:relative}.course-tile:hover{background:#eef5ee}.course-number{color:#88a798;font-size:12px}.course-tile h2{margin:22px 0 8px}.course-tile p{color:var(--muted);font-size:12px}.enter{display:block;margin-top:24px;color:var(--accent);font-size:12px}.empty-courses{padding:60px 20px;text-align:center;color:var(--muted);border:1px dashed #cbd8cb;border-radius:16px}.workspace{display:grid;grid-template-columns:300px minmax(0,1fr);height:calc(100vh - 76px);min-height:620px}.sidebar{padding:24px 22px;border-right:1px solid var(--line);background:#f0f3ed;overflow:auto}.back{margin:0 0 22px -7px}.sidebar h2{overflow-wrap:anywhere}.chapter-editor{margin:24px 0 14px}.study-app summary{cursor:pointer;color:var(--muted);font-size:12px}.chapter-editor form{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}.field-label{display:block;font-size:11px;color:var(--muted)}.field-label select{margin:6px 0 14px;font-size:12px}.upload-box{border:1px dashed #a6bfae;border-radius:10px;display:flex;flex-direction:column;align-items:center;padding:20px 10px;position:relative;cursor:pointer;background:#fafcf8;color:var(--accent)}.upload-box small{font-size:10px;color:var(--muted);margin-top:5px}.upload-box input{position:absolute;inset:0;opacity:0;cursor:pointer}.section-label{margin:28px 0 12px;display:flex;justify-content:space-between;font-size:12px;color:var(--muted)}.resource{display:flex;gap:10px;padding:16px 0;border-bottom:1px solid var(--line)}.file-icon{background:#e0e9df;color:#56765d;font-size:9px;min-width:34px;height:40px;display:grid;place-items:center;border-radius:6px}.resource-body{min-width:0;flex:1}.resource strong{display:block;font-size:12px;font-weight:500;overflow-wrap:anywhere}.resource-status{font-size:10px;color:var(--muted)}.resource-actions{display:flex;justify-content:space-between;align-items:center;margin-top:5px}.resource-actions button{font-size:11px;padding:0 2px}.resource-actions details{position:relative}.resource-actions details[open]{background:white;padding:8px;border-radius:6px}.resource-actions details button{display:block;margin:8px}.danger{color:#b16b62}.sidebar-foot{margin-top:40px!important;font-size:11px;color:#91a393}.learning{display:flex;flex-direction:column;min-width:0;background:#fdfefb;overflow:hidden}.learning-header{padding:24px 34px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #edf0e9}.learning-header .eyebrow{font-size:9px;margin-bottom:2px}.thread-actions{display:flex;align-items:center;gap:10px}.thread-actions select{max-width:230px;font-size:12px;border:0;background:transparent}.thread-actions button{white-space:nowrap;font-size:12px}.conversation{flex:1;overflow:auto;padding:24px max(32px,calc((100% - 780px)/2));scroll-behavior:smooth}.conversation-empty{padding:48px 0;text-align:center}.learning-symbol{display:inline-grid;place-items:center;width:58px;height:58px;background:#e9f0e4;border-radius:20px;color:#77956b;font-size:28px;margin-bottom:22px}.conversation-empty h1{font-size:28px}.conversation-empty p{font-size:13px;color:var(--muted);margin:12px 0 30px}.suggestions{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.suggestions button{background:#f3f5ef;border:1px solid #e5eadf;color:#52674f;padding:16px 12px;font-size:12px;text-align:left}.suggestions span{float:right;color:#98aa93}.suggestions button:hover{background:#e9f0e4}.turn{margin:0 0 36px}.speaker{display:block;font-size:11px;color:var(--muted);margin-bottom:10px}.user-message{margin:0 0 24px 12%;padding:16px 20px;background:#edf3e9;border-radius:14px}.assistant-message{padding:12px 0}.assistant-message .speaker{color:var(--accent);font-weight:600}.turn p{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.9}.composer-area{padding:12px max(32px,calc((100% - 780px)/2)) 16px;background:#fdfefb}.composer{padding:14px 16px;border:1px solid #cbd8c8;border-radius:16px;background:white;box-shadow:0 4px 20px #233d2d04}.composer:focus-within{border-color:#72a58c;box-shadow:0 0 0 3px #267b6609}.composer textarea{width:100%;border:0;outline:none!important;resize:vertical;min-height:65px;max-height:180px;background:transparent;color:var(--ink);font-size:14px;line-height:1.7}.composer-bottom{display:flex;align-items:center;justify-content:space-between;margin-top:8px}.composer-bottom span{font-size:10px;color:#96a396}.composer-bottom button{font-size:12px;padding:7px 16px}.composer-hint{text-align:center;color:#9aa599;font-size:10px;margin-top:10px!important}.model-notice{font-size:12px;color:#98754c;background:#faf3e8;border-radius:8px;padding:8px 12px;margin-bottom:12px!important}.activity{font-size:12px;color:var(--accent);margin-bottom:10px!important}
@media(max-width:1000px){.workspace{grid-template-columns:250px minmax(0,1fr)}.learning-header{padding:20px}.conversation,.composer-area{padding-left:24px;padding-right:24px}.thread-actions select{max-width:150px}.suggestions{grid-template-columns:1fr}.conversation-empty{padding:22px 0}.welcome{gap:40px}.brand-note{display:none}}
@media(max-width:700px){.topbar{padding:0 18px;height:64px}.workspace{display:flex;flex-direction:column;height:auto}.sidebar{border-right:0;border-bottom:1px solid var(--line);max-height:330px;overflow:auto}.sidebar-foot{display:none}.learning{min-height:650px}.learning-header{align-items:flex-start;gap:12px;flex-wrap:wrap}.conversation{min-height:280px;max-height:65vh}.course-grid{grid-template-columns:1fr}.welcome{grid-template-columns:1fr;margin:24px auto}.welcome-copy h1{font-size:32px}.welcome-copy{padding:0 12px}.welcome-tags{display:none}.dashboard{margin-top:36px}.create-course{flex-direction:column}.account span{display:none}}
</style>
<style scoped src="./v2-theme.css"></style>
