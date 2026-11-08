<script setup>
import { nextTick, ref, watch } from 'vue'
import { request } from './api.js'
import StudyAnswer from './StudyAnswer.vue'

const props = defineProps({
  courseId: {type: String, required: true},
  settings: Boolean,
  revision: Number
})
defineEmits(['practice'])
const questions=ref([]), memories=ref([]), answers=ref({}), results=ref({})
const busy=ref(false), error=ref('')
const panel = ref(null)
const expanded = ref(false)
const selectedId = ref('')
const loadingQuestions = ref(false)
let refreshRevision = 0
const memoryEnabled=ref(true), explanationStyle=ref('')
const coursePath=()=>`/courses/${props.courseId}`
async function act(action) {
  if(busy.value)return
  busy.value=true;error.value=''
  try{await action()}catch(e){error.value=e.message}finally{busy.value=false}
}
async function refresh() {
  if (!props.settings) {
    const revision = ++refreshRevision
    loadingQuestions.value = true
    try {
      const { items } = await request(coursePath() + '/practice-questions')
      if (revision !== refreshRevision) return
      questions.value = items
      for (const { id, latest_attempt: attempt } of items) {
        if (!attempt) continue
        results.value[id] ??= attempt
        answers.value[id] ??= attempt.submitted_answer
      }
      error.value = ''
    } catch (err) {
      if (revision === refreshRevision) error.value = err.message
    } finally {
      if (revision === refreshRevision) loadingQuestions.value = false
    }
    return
  }
  return act(async () => {
  const [m,p]=await Promise.all([
    request(`/learning-memories?course_id=${encodeURIComponent(props.courseId)}`),request('/learning-preferences')])
  memories.value=m.items
  memoryEnabled.value=p.items.find(item=>item.key==='memory_enabled')?.value!=='false'
  explanationStyle.value=p.items.find(item=>item.key==='explanation_style')?.value||''
  })
}
watch(() => props.revision, refresh, { immediate: true })
async function openQuestion(id) {
  expanded.value = true
  selectedId.value = id
  if (!questions.value.some(question => question.id === id)) await refresh()
  await nextTick()
  panel.value?.focus({ preventScroll: true })
  panel.value?.scrollIntoView({ block: 'nearest' })
}
defineExpose({ openQuestion })
function answer(id){return act(async()=>{
  results.value[id]=await request(coursePath()+'/practice-attempts',{
    method:'POST',body:{question_id:id,submitted_answer:answers.value[id]}})
})}
function review(memory,remove=false){return act(async()=>{
  const saved=await request(`/learning-memories/${memory.id}`,remove?{method:'DELETE'}:{method:'PUT',body:{content:memory.content}})
  if(remove)memories.value=memories.value.filter(item=>item.id!==memory.id)
  else Object.assign(memory,saved)
})}
async function toggleMemory(event){const input=event.target, checked=input.checked;await act(async()=>{
  await request('/learning-preferences/memory_enabled',{method:'PUT',body:{value:String(checked)}})
  memoryEnabled.value=checked
});input.checked=memoryEnabled.value}
function saveStyle(){return act(async()=>{
  const value=explanationStyle.value.trim()
  await request('/learning-preferences/explanation_style',value?{method:'PUT',body:{value}}:{method:'DELETE'})
})}
</script>

<template>
  <section ref="panel" class="practice" tabindex="-1">
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="!settings">
    <header class="practice-header">
      <h3><button class="practice-action" type="button" :aria-expanded="expanded" @click="expanded = !expanded">
        {{ expanded ? '▾' : '▸' }} 课程自测 · {{ questions.length }} 题
      </button></h3>
      <button class="practice-action" type="button" @click="$emit('practice')">根据刚才的讲解出题</button>
    </header>
    <button v-if="error" type="button" :disabled="loadingQuestions" @click="refresh">重试加载</button>
    <div v-if="expanded">
      <p v-if="loadingQuestions" role="status">正在加载题目…</p>
      <p v-else-if="!questions.length && !error">还没有题目，可以根据刚才的讲解出题。</p>
      <ol v-if="questions.length" class="practice-list">
        <li v-for="(q, index) in questions" :key="q.id">
          <button type="button" :aria-expanded="selectedId === q.id" @click="selectedId = selectedId === q.id ? '' : q.id">
            第 {{ questions.length - index }} 题 <span>{{ results[q.id] ? '已作答' : '待作答' }}</span>
          </button>
        </li>
      </ol>
    <template v-for="q in questions" :key="q.id">
    <form v-if="q.id === selectedId" class="practice-question" @submit.prevent="answer(q.id)">
      <StudyAnswer :content="q.question" />
      <label class="response-label">
        你的答案
        <textarea v-model="answers[q.id]" required maxlength="1000" rows="3" placeholder="写下你的答案或推导过程" />
      </label>
      <div class="response-actions"><button type="submit" :disabled="busy || !answers[q.id]?.trim()">提交答案</button></div>
      <div v-if="results[q.id]" class="practice-feedback" role="status">
        <strong>{{ results[q.id].provisional ? '评阅建议' : results[q.id].correct ? '回答正确' : '参考答案' }}</strong>
        <StudyAnswer v-if="results[q.id].provisional || !results[q.id].correct"
          :content="(results[q.id].provisional ? results[q.id].feedback : results[q.id].expected_answer) || ''" />
      </div>
    </form>
    </template>
    </div>
    </template>
    <template v-else>
    <button v-if="error" type="button" :disabled="busy" @click="refresh">重试加载</button>
    <label><input type="checkbox" :checked="memoryEnabled" :disabled="busy" @change="toggleMemory" />启用学习记忆</label>
    <p>明确的学习目标、困难和自述进度会自动记录，可随时修改或移除。关闭后停止自动记录和使用学习记忆；已有聊天仍保留。</p>
    <form @submit.prevent="saveStyle">
      <label>长期讲解偏好<input v-model="explanationStyle" maxlength="300" placeholder="例如：先给结论，再用一个例子解释" /></label>
      <button :disabled="busy">保存偏好</button>
    </form>
    <p v-if="!memories.length">还没有保存的学习记忆。你可以直接在对话中说明学习目标或遇到的困难。</p>
    <form v-for="m in memories" :key="m.id" @submit.prevent="review(m)">
      <label>{{ m.status==='pending'?'待确认':m.automatic?'自动保存':'已保存' }}
        <input v-model="m.content" required maxlength="500" />
      </label>
      <button :disabled="busy">{{ m.status==='pending'?'确认':'保存修改' }}</button>
      <button type="button" :disabled="busy" @click="review(m,true)">移除</button>
    </form>
    </template>
  </section>
</template>

<style scoped>
.practice { margin-block: 16px; padding: 16px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); color: var(--ink); }
.practice-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; }
.practice h3 { margin: 0; font-size: 16px; }
.practice-list { list-style: none; display: grid; gap: 6px; margin: 12px 0 0; padding: 0; max-height: 160px; overflow: auto; }
.practice-list button { display: flex; justify-content: space-between; gap: 12px; width: 100%; text-align: left; }
.practice-list button[aria-expanded="true"] { border-color: var(--accent); }
.practice button {
  appearance: none; border: 1px solid transparent; border-radius: 8px;
  background: var(--accent-soft); color: var(--accent-strong); padding: 8px 13px;
  min-height: 36px; font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
}
.practice button:hover:not(:disabled) { border-color: var(--accent); }
.practice button:focus-visible, .practice textarea:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.practice button:disabled { opacity: .5; cursor: not-allowed; }
.practice button.practice-action { border-color: var(--line); background: var(--panel); }
.response-actions { display: flex; justify-content: flex-end; margin-top: 8px; }
.response-actions button { background: var(--accent-strong); color: white; }
.practice .practice-question { border-top: 1px solid var(--line); margin-top: 14px; padding-top: 16px; }
.response-label { display: block; margin-top: 12px; font-size: 13px; font-weight: 600; }
.practice textarea {
  box-sizing: border-box; display: block; width: 100%; margin-top: 5px; padding: 9px 12px;
  border: 1px solid var(--line); border-radius: 8px; background: var(--paper); color: var(--ink);
  font: inherit; font-weight: 400; resize: vertical;
}
.practice-feedback { margin-top: 12px; padding: 12px; border-radius: 8px; background: var(--paper); }
.practice form { padding-block: 10px; }
.practice input:not([type=checkbox]) { display: block; width: 100%; margin-block: 6px; padding: 8px; border: 1px solid var(--line); border-radius: 8px; }
.practice input[type=checkbox] { width: auto; min-height: 0; margin-inline-end: 6px; accent-color: var(--accent); }
.practice p { margin-block: 6px; }
</style>
