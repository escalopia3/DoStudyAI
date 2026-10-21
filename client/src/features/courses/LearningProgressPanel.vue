<template>
  <section class="progress-panel panel" aria-labelledby="learning-progress-title">
    <div class="heading">
      <div><p class="eyebrow">LEARNING PROGRESS</p><h2 id="learning-progress-title">练习与学习进度</h2></div>
      <button class="secondary" :disabled="loading" @click="loadAll">刷新</button>
    </div>
    <nav class="tabs" aria-label="学习进度分类">
      <button v-for="item in tabs" :key="item.id" :class="{selected:tab===item.id}" @click="tab=item.id">{{ item.label }}</button>
    </nav>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="loading" class="muted">正在加载学习进度…</p>

    <div v-if="tab==='practice' && !loading" class="practice-layout">
      <div class="set-list">
        <button v-for="item in sets" :key="item.id" :class="['set-card',{selected:selected?.id===item.id}]" @click="openSet(item.id)">
          <strong>{{ item.title }}</strong><small>{{ item.question_count }} 题 · {{ dateText(item.created_at) }}</small>
        </button>
        <p v-if="!sets.length" class="muted">还没有结构化练习。请在“针对性复习”中点击“生成练习题”。</p>
      </div>
      <form v-if="selected" class="question-list" @submit.prevent="submitPractice">
        <div class="practice-title"><div><h3>{{ selected.title }}</h3><p class="muted">{{ selected.instructions }}</p></div><span class="tag">{{ selected.questions.length }} 题</span></div>
        <article v-for="question in selected.questions" :key="question.id" class="question">
          <div class="question-meta">第 {{ question.ordinal_no }} 题 · {{ typeLabel(question.question_type) }} · {{ difficultyLabel(question.difficulty) }} · {{ question.points }} 分</div>
          <p class="stem">{{ question.stem }}</p>
          <label v-for="option in question.options || []" :key="option.id" class="option"><input v-model="answers[question.id]" type="radio" :name="question.id" :value="option.id" /> <span>{{ option.id }}. {{ option.text }}</span></label>
          <textarea v-if="question.question_type==='SHORT_ANSWER'" v-model="answers[question.id]" rows="3" maxlength="2000" placeholder="输入你的答案" />
          <p class="knowledge">知识点：{{ (question.knowledge_points || []).join('、') }}</p>
        </article>
        <button :disabled="submitting">{{ submitting ? '判分中…' : '提交练习' }}</button>
      </form>
      <div v-if="result" class="result-card">
        <h3>本次得分 {{ result.score }} / {{ result.max_score }}</h3>
        <article v-for="item in result.answers" :key="item.question_id" :class="['answer-result',{correct:Boolean(item.is_correct)}]">
          <strong>第 {{ item.ordinal_no }} 题 · {{ item.is_correct ? '正确' : '需要复习' }} · {{ item.score }}/{{ item.max_score }}</strong>
          <p>{{ item.feedback }}</p><p class="muted">参考解析：{{ item.explanation }}</p>
        </article>
      </div>
    </div>

    <div v-else-if="tab==='wrong' && !loading" class="card-grid">
      <article v-for="item in wrong" :key="item.question_id" class="info-card"><span :class="['state',item.status.toLowerCase()]">{{ item.status==='MASTERED'?'已巩固':'待巩固' }}</span><h3>{{ item.stem }}</h3><p class="muted">错 {{ item.wrong_count }} 次 · 连续答对 {{ item.correct_streak }} 次</p><details><summary>查看解析</summary><p>{{ item.explanation }}</p></details></article>
      <p v-if="!wrong.length" class="muted">错题本为空。提交练习后会自动记录。</p>
    </div>

    <div v-else-if="tab==='mastery' && !loading" class="mastery-list">
      <article v-for="item in mastery" :key="item.knowledge_point_id"><div class="mastery-label"><strong>{{ item.name }}</strong><span>{{ percent(item.mastery_score) }}%</span></div><div class="meter"><i :style="{width:`${percent(item.mastery_score)}%`}" /></div><small>练习 {{ item.confidence_count }} 次 · 对 {{ item.correct_count }} / 错 {{ item.wrong_count }}</small></article>
      <p v-if="!mastery.length" class="muted">暂无掌握度记录。</p>
    </div>

    <div v-else-if="tab==='memory' && !loading" class="memory-area">
      <form class="memory-form" @submit.prevent="createMemory"><select v-model="memoryDraft.type"><option value="PREFERENCE">学习偏好</option><option value="WEAKNESS">薄弱点</option><option value="MASTERY">已掌握</option><option value="LEARNING_GOAL">学习目标</option></select><input v-model="memoryDraft.content" required maxlength="1000" placeholder="例如：讲解时先给直观例子，再解释公式" /><button>添加</button></form>
      <article v-for="item in memories" :key="item.id" class="memory-card"><div><span class="tag">{{ memoryLabel(item.memory_type) }}</span><p>{{ item.content }}</p><small>{{ item.source_type==='USER'?'由你添加':'根据练习表现自动更新' }}</small></div><button class="secondary danger" @click="deleteMemory(item.id)">删除</button></article>
      <button v-if="memories.length" class="secondary clear" @click="clearMemories">清空本课程学习记忆</button>
      <p v-else class="muted">暂无学习记忆。记忆只用于个性化讲解，不会作为课程事实或引用来源。</p>
    </div>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { courseRequest, postJson } from './courseApi.js'

const props=defineProps({courseId:{type:[String,Number],required:true},refreshKey:{type:Number,default:0}})
const tabs=[{id:'practice',label:'练习'},{id:'wrong',label:'错题本'},{id:'mastery',label:'掌握度'},{id:'memory',label:'学习记忆'}]
const tab=ref('practice'),loading=ref(false),submitting=ref(false),error=ref('')
const sets=ref([]),selected=ref(null),result=ref(null),wrong=ref([]),mastery=ref([]),memories=ref([]),answers=reactive({})
const memoryDraft=reactive({type:'PREFERENCE',content:''})
const request=(path,options)=>courseRequest(path,options)
async function loadAll(){loading.value=true;error.value='';try{const id=props.courseId;[sets.value,wrong.value,mastery.value,memories.value]=await Promise.all([request(`/learn/courses/${id}/practice-sets`),request(`/learn/courses/${id}/wrong-questions`),request(`/learn/courses/${id}/mastery`),request(`/learn/courses/${id}/memories`)])}catch(e){error.value=e.message||'学习进度加载失败'}finally{loading.value=false}}
async function openSet(id){try{selected.value=await request(`/learn/practice-sets/${id}`);result.value=null;Object.keys(answers).forEach(key=>delete answers[key])}catch(e){error.value=e.message||'练习加载失败'}}
async function submitPractice(){submitting.value=true;error.value='';try{result.value=await request(`/learn/practice-sets/${selected.value.id}/submit`,postJson({answers:{...answers}},undefined));await loadAll()}catch(e){error.value=e.message||'练习提交失败'}finally{submitting.value=false}}
async function createMemory(){try{await request(`/learn/courses/${props.courseId}/memories`,postJson({...memoryDraft},undefined));memoryDraft.content='';await loadAll()}catch(e){error.value=e.message||'记忆添加失败'}}
async function deleteMemory(id){try{await request(`/learn/courses/${props.courseId}/memories/${id}`,{method:'DELETE'});await loadAll()}catch(e){error.value=e.message||'记忆删除失败'}}
async function clearMemories(){if(!confirm('确定清空本课程的全部学习记忆吗？'))return;try{await request(`/learn/courses/${props.courseId}/memories`,{method:'DELETE'});await loadAll()}catch(e){error.value=e.message||'记忆清空失败'}}
const typeLabel=value=>({SINGLE_CHOICE:'单选题',TRUE_FALSE:'判断题',SHORT_ANSWER:'简答题'}[value]||value)
const difficultyLabel=value=>({EASY:'基础',MEDIUM:'中等',HARD:'困难'}[value]||value)
const memoryLabel=value=>({PREFERENCE:'学习偏好',WEAKNESS:'薄弱点',MASTERY:'已掌握',LEARNING_GOAL:'学习目标'}[value]||value)
const percent=value=>Math.round(Math.max(0,Math.min(1,Number(value)||0))*100)
const dateText=value=>value?new Date(value).toLocaleDateString():'刚刚'
watch(()=>props.refreshKey,loadAll)
onMounted(loadAll)
</script>

<style scoped>
.progress-panel{background:linear-gradient(145deg,#171d21,#11161b)!important;border-color:#43513f!important}.heading,.practice-title,.mastery-label,.memory-card{display:flex;justify-content:space-between;align-items:center;gap:14px}.eyebrow{margin:0;color:var(--accent-lime,#c5ff51);font-size:10px;letter-spacing:.15em}.heading h2{margin:4px 0}.tabs{display:flex;gap:7px;border-bottom:1px solid #303840;margin:18px 0}.tabs button{background:transparent;color:#a0a7b3;padding:9px 13px;border-radius:8px 8px 0 0}.tabs button.selected{color:var(--accent-lime,#c5ff51);border-bottom-color:var(--accent-lime,#c5ff51);background:#c5ff510b}.practice-layout{display:grid;grid-template-columns:190px minmax(0,1fr);gap:18px}.set-list{display:grid;align-content:start;gap:8px}.set-card{display:grid;text-align:left;background:#11161d;color:#eef1f3;border:1px solid #303840;padding:12px}.set-card.selected{border-color:var(--accent-lime,#c5ff51)}.set-card small{color:#a0a7b3;margin-top:7px}.question-list{min-width:0}.question{padding:15px 0;border-top:1px solid #303840}.question-meta,.knowledge{font-size:12px;color:#a0a7b3}.stem{line-height:1.65;font-weight:600}.option{display:flex!important;grid-template-columns:none!important;align-items:flex-start;gap:8px;margin:8px 0!important}.option input{width:auto!important;margin-top:4px}.question textarea{width:100%;background:#11161d;color:#eee;border:1px solid #414952;border-radius:8px;padding:10px}.result-card{grid-column:2;padding-top:12px}.answer-result{border-left:3px solid #ff9b80;background:#ff9b8009;padding:11px;margin:8px 0}.answer-result.correct{border-color:#c5ff51;background:#c5ff5109}.card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}.info-card,.memory-card,.mastery-list article{background:#11161d;border:1px solid #303840;border-radius:10px;padding:14px}.state{font-size:11px;color:#ffb29f}.state.mastered{color:#c5ff51}.mastery-list{display:grid;gap:10px}.meter{height:7px;background:#303840;border-radius:9px;margin:9px 0;overflow:hidden}.meter i{display:block;height:100%;background:linear-gradient(90deg,#7b9846,#c5ff51)}.mastery-list small,.memory-card small{color:#a0a7b3}.memory-form{display:grid;grid-template-columns:140px 1fr auto;gap:9px;margin-bottom:12px}.memory-form select,.memory-form input{background:#11161d;color:#eee;border:1px solid #414952;border-radius:8px;padding:10px}.memory-card{margin:8px 0}.memory-card p{margin:10px 0}.danger{color:#ffb2b2!important}.clear{margin-top:10px}.error{color:#ffa5a5}.muted{color:#a0a7b3}.tag{font-size:11px;border:1px solid #455044;border-radius:20px;padding:4px 8px}@media(max-width:760px){.practice-layout{grid-template-columns:1fr}.result-card{grid-column:1}.set-list{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}.memory-form{grid-template-columns:1fr}.tabs{overflow:auto}.heading{align-items:flex-start}}
</style>
