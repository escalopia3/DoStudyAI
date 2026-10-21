<template>
  <section class="agent-panel" aria-labelledby="learning-agent-title">
    <div class="agent-heading">
      <div>
        <p class="eyebrow">COURSE COPILOT</p>
        <h2 id="learning-agent-title">课程学习助手</h2>
      </div>
      <select v-model="mode" class="mode-select" :disabled="submitting" aria-label="学习模式">
        <option value="QA">课程问答</option>
        <option value="TUTORING">引导讲解</option>
        <option value="NOTES">生成学习笔记</option>
        <option value="KEY_POINTS">重点与难点</option>
        <option value="REVIEW">针对性复习</option>
      </select>
    </div>

    <p class="muted">只使用本课程中已就绪的资料回答；每条引用保留章节、页码或视频时间定位。</p>
    <p class="mode-hint">{{ modeHint }}</p>
    <p v-if="error" class="agent-error" role="alert">{{ error }}</p>
    <div v-if="messages.length" class="messages" aria-live="polite">
      <article v-for="message in messages" :key="message.id" :class="['message', message.role]">
        <div class="message-meta">{{ message.role === 'user' ? '你' : '学习助手' }} · {{ modeLabel(message.mode) }} · {{ statusText(message.status) }}</div>
        <p v-if="message.content" class="message-content">{{ message.content }}</p>
        <p v-else class="muted">{{ active ? '正在检索课程资料并核验引用…' : '没有生成内容' }}</p>
        <details v-for="citation in message.citations || []" :key="`${message.id}-${citation.ordinal_no}`" class="citation">
          <summary>[{{ citation.source_id || `S${citation.ordinal_no}` }}] {{ titlePath(citation) }}</summary>
          <p>{{ citation.quote_text }}</p>
          <small>{{ locatorText(citation) }} · 索引版本 {{ citation.index_revision }}</small>
        </details>
      </article>
    </div>
    <p v-else class="muted empty-agent">还没有对话。可以先问一个课程概念，或切换模式生成笔记。</p>

    <form class="composer" @submit.prevent="ask()">
      <textarea v-model="question" class="question-input" rows="3" maxlength="4000" required
        :disabled="submitting" :placeholder="modePlaceholder" />
      <div class="composer-actions">
        <span class="muted">{{ question.length }} / 4000</span>
        <div v-if="mode === 'REVIEW'" class="review-actions" aria-label="复习内容生成方式">
          <button type="button" class="secondary action-button" :disabled="submitting || active || !question.trim()" @click="ask('PRACTICE')">生成练习题</button>
          <button type="button" class="secondary action-button" :disabled="submitting || active || !question.trim()" @click="ask('MOCK_EXAM')">生成模拟试卷</button>
        </div>
        <button v-if="active" type="button" class="secondary" @click="cancel">停止回答</button>
        <button :disabled="submitting || active || !question.trim()">{{ submitting ? '提交中…' : mode === 'REVIEW' ? '开始复习' : '发送' }}</button>
      </div>
    </form>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { courseRequest, postJson } from './courseApi.js'

const props=defineProps({courseId:{type:[String,Number],required:true}})
const emit=defineEmits(['practice-created'])
const conversationId=ref(''), messages=ref([]), question=ref(''), mode=ref('QA')
const active=ref(null), submitting=ref(false), error=ref('')
let stopped=false, pollTimer=null

const terminal=new Set(['COMPLETED','FAILED','CANCELLED','TIMED_OUT','BUDGET_EXCEEDED'])
const modeCopy={
  QA:{hint:'针对课程内容提问，助手会给出带原文定位的回答。',placeholder:'例如：请结合课程资料解释 B+ 树为什么适合数据库索引'},
  TUTORING:{hint:'从前置知识开始逐步讲解，并用一个问题检查理解。',placeholder:'例如：我不理解 B+ 树的分裂过程，请从基础开始教我'},
  NOTES:{hint:'按知识结构整理概念、原理、重点、难点与易混点。',placeholder:'例如：请根据本章资料生成一份结构化学习笔记'},
  KEY_POINTS:{hint:'提炼重点与共性难点，并说明每一项判断依据。',placeholder:'例如：总结本章重点、难点和容易混淆的概念'},
  REVIEW:{hint:'描述复习范围或粘贴提纲后，可以开始针对性复习，也可以直接生成练习题或模拟试卷。',placeholder:'粘贴复习提纲，或说明考试范围、薄弱知识点、题型和难度要求'},
}
const modeHint=computed(()=>modeCopy[mode.value]?.hint||modeCopy.QA.hint)
const modePlaceholder=computed(()=>modeCopy[mode.value]?.placeholder||modeCopy.QA.placeholder)
const modeLabels={QA:'课程问答',TUTORING:'引导讲解',NOTES:'学习笔记',KEY_POINTS:'重点与难点',REVIEW:'针对性复习',PRACTICE:'练习题',MOCK_EXAM:'模拟试卷'}
const modeLabel=value=>modeLabels[value]||'课程问答'
const statusText=status=>({QUEUED:'等待处理',RUNNING:'生成中',COMPLETED:'已完成',FAILED:'失败',CANCELLED:'已停止',TIMED_OUT:'已超时',BUDGET_EXCEEDED:'已达到本轮预算'}[status]||status||'')
function parseJson(value,fallback){try{return typeof value==='string'?JSON.parse(value):value??fallback}catch{return fallback}}
function titlePath(citation){const path=parseJson(citation.title_path_json,[]);return Array.isArray(path)&&path.length?path.join(' / '):'课程资料'}
function locatorText(citation){
  const locators=parseJson(citation.locator_json,[]), first=Array.isArray(locators)?locators[0]:null
  if(!first)return '原文定位已保留'
  if(first.page!=null)return `第 ${Number(first.page)+1} 页`
  if(first.pageIndex!=null)return `第 ${Number(first.pageIndex)+1} 页`
  if(first.startMs!=null)return `视频 ${Math.floor(first.startMs/60000)}:${String(Math.floor(first.startMs/1000)%60).padStart(2,'0')}`
  return '原文定位已保留'
}
async function ensureConversation(){
  const items=await courseRequest(`/learn/courses/${props.courseId}/conversations`)
  if(items.length)conversationId.value=items[0].id
  else conversationId.value=(await courseRequest(`/learn/courses/${props.courseId}/conversations`,postJson({title:'课程学习'},undefined))).conversationId
}
async function loadMessages(){if(conversationId.value)messages.value=await courseRequest(`/learn/conversations/${conversationId.value}/messages`)}
async function initialize(){
  try{await ensureConversation();await loadMessages()}catch(e){error.value=e.message||'学习助手加载失败'}
}
async function ask(requestedMode=mode.value){
  if(active.value||submitting.value)return
  const prompt=question.value.trim()
  if(!prompt)return
  submitting.value=true;error.value=''
  try{
    const run=await courseRequest(`/learn/conversations/${conversationId.value}/messages`,postJson({question:prompt,mode:requestedMode,resourceIds:[]},undefined))
    question.value='';active.value=run.runId;await loadMessages();schedulePoll(0)
  }catch(e){error.value=e.message||'问题提交失败'}finally{submitting.value=false}
}
function schedulePoll(delay=1200){clearTimeout(pollTimer);if(!stopped&&active.value)pollTimer=setTimeout(poll,delay)}
async function poll(){
  try{
    const run=await courseRequest(`/learn/agent-runs/${active.value}`)
    await loadMessages()
    if(terminal.has(run.state)){if(run.state!=='COMPLETED')error.value=`本轮回答未完成：${statusText(run.state)}${run.error_code?`（${run.error_code}）`:''}`;else if(messages.value.at(-1)?.mode==='PRACTICE')emit('practice-created');active.value=null;return}
  }catch(e){error.value=e.message||'获取回答状态失败'}
  schedulePoll()
}
async function cancel(){
  const run=active.value;if(!run)return
  try{await courseRequest(`/learn/agent-runs/${run}/cancel`,postJson({},undefined));active.value=null;await loadMessages()}
  catch(e){error.value=e.message||'停止失败'}
}
onMounted(initialize)
onBeforeUnmount(()=>{stopped=true;clearTimeout(pollTimer)})
</script>

<style scoped>
.agent-panel{background:linear-gradient(145deg,#171d21,#11161b);border:1px solid #43513f;border-radius:14px;padding:22px;margin-bottom:22px}.agent-heading,.composer-actions{display:flex;align-items:center;justify-content:space-between;gap:14px}.agent-heading h2{margin:4px 0}.eyebrow{margin:0;color:var(--accent-lime,#c5ff51);font-size:10px;letter-spacing:.15em}.muted{color:var(--text-muted,#a0a7b3);font-size:13px}.mode-hint{margin:8px 0 0;padding:9px 11px;border-left:2px solid var(--accent-lime,#c5ff51);background:#c5ff5108;color:#c4c9d0;font-size:12px;line-height:1.5}.agent-error{color:#ffa5a5;background:#ff525212;padding:10px;border-radius:8px}.mode-select,.question-input{box-sizing:border-box;border:1px solid #414952;background:#11161d;color:#eef1f3;font:inherit;transition:border-color .18s ease,box-shadow .18s ease,background .18s ease}.mode-select{width:180px;min-height:42px;padding:9px 40px 9px 13px;border-radius:9px;appearance:none;cursor:pointer;background-color:#171c22;background-image:linear-gradient(45deg,transparent 50%,#c5ff51 50%),linear-gradient(135deg,#c5ff51 50%,transparent 50%);background-position:calc(100% - 18px) 18px,calc(100% - 12px) 18px;background-size:6px 6px,6px 6px;background-repeat:no-repeat}.mode-select:hover,.question-input:hover{border-color:#59645b}.mode-select:focus,.question-input:focus{outline:none;border-color:var(--accent-lime,#c5ff51);box-shadow:0 0 0 3px #c5ff5120}.mode-select:disabled,.question-input:disabled{opacity:.55;cursor:not-allowed}.mode-select option{background:#171c22;color:#eef1f3}.messages{display:grid;gap:12px;max-height:520px;overflow:auto;margin:18px 0;padding-right:7px;scrollbar-width:thin;scrollbar-color:#59645b #11161d}.messages::-webkit-scrollbar{width:8px}.messages::-webkit-scrollbar-track{background:#11161d;border-radius:8px}.messages::-webkit-scrollbar-thumb{background:#59645b;border-radius:8px}.messages::-webkit-scrollbar-thumb:hover{background:#74806f}.message{padding:14px;border-radius:10px;background:#20262d}.message.user{margin-left:12%;background:#c5ff5112}.message.assistant{margin-right:7%}.message-meta{font-size:11px;color:#a0a7b3}.message-content{white-space:pre-wrap;line-height:1.7;overflow-wrap:anywhere}.citation{border-top:1px solid #3b444d;padding-top:8px;margin-top:8px;font-size:12px}.citation summary{cursor:pointer;color:var(--accent-lime,#c5ff51)}.citation p{line-height:1.6}.citation small{color:#a0a7b3}.question-input{display:block;width:100%;min-height:96px;padding:14px 16px;border-radius:10px;resize:vertical;line-height:1.6;caret-color:var(--accent-lime,#c5ff51)}.question-input::placeholder{color:#737c86}.composer-actions{margin-top:11px;justify-content:flex-end;flex-wrap:wrap}.review-actions{display:flex;gap:8px}.composer button{min-width:74px;padding:9px 16px;border:1px solid transparent;border-radius:8px;background:var(--accent-lime,#c5ff51);color:#111;font:inherit;font-weight:700;cursor:pointer;transition:filter .18s ease,transform .18s ease}.composer button:hover:not(:disabled){filter:brightness(1.05);transform:translateY(-1px)}.composer button:focus-visible{outline:2px solid var(--accent-lime,#c5ff51);outline-offset:3px}.composer button:disabled{opacity:.42;cursor:not-allowed}.composer .secondary{background:transparent;color:#eef1f3;border-color:#414952}.composer .action-button{border-color:#60743c;color:var(--accent-lime,#c5ff51)}.empty-agent{text-align:center;padding:18px}@media(max-width:720px){.agent-heading{align-items:flex-start}.mode-select{width:154px}.message.user,.message.assistant{margin-left:0;margin-right:0}.question-input{min-height:112px}.composer-actions{align-items:stretch}.review-actions{width:100%}.review-actions .action-button{flex:1;padding-inline:8px}}
</style>
