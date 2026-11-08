<script setup>
import { onMounted, ref } from 'vue'
import { request } from './api.js'

const props = defineProps({ courseId: { type: String, required: true } })
const records = ref([])
const entries = ref(null)
const selected = ref('')
const nextOffset = ref(0)
const loading = ref(false)
const error = ref('')
const path = `/courses/${props.courseId}/legacy-history`

async function load() {
  if (loading.value || nextOffset.value === null) return
  loading.value = true
  error.value = ''
  try {
    const page = await request(`${path}?offset=${nextOffset.value}`)
    records.value.push(...page.items)
    nextOffset.value = page.next_offset
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function open(record) {
  if (loading.value) return
  loading.value = true
  selected.value = record.id
  entries.value = null
  error.value = ''
  try {
    entries.value = (await request(`${path}/${record.id}`)).entries
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<template>
  <details v-if="records.length || error">
    <summary>旧版归档</summary>
    <p v-if="error" role="alert">{{ error }}</p>
    <ul v-if="records.length">
      <li v-for="record in records" :key="record.id">
        <button type="button" :disabled="loading" @click="open(record)">
          {{ record.kind === 'conversation' ? '对话' : '练习' }} · {{ record.title }}
        </button>
        <dl v-if="selected === record.id && entries">
          <template v-for="(entry, index) in entries" :key="index">
            <dt>{{ entry.label }}</dt>
            <dd>{{ entry.text }}</dd>
          </template>
        </dl>
      </li>
    </ul>
    <button v-if="nextOffset !== null" type="button" :disabled="loading" @click="load">加载记录</button>
  </details>
</template>

<style scoped>
details { margin-top: 1rem; }
ul { padding-inline-start: 1rem; }
dd { margin: 0 0 .75rem; overflow-wrap: anywhere; white-space: pre-wrap; }
</style>
