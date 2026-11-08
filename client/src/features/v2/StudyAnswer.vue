<script setup>
import { computed, ref } from 'vue'
import { Marked } from 'marked'
import renderMathInElement from 'katex/contrib/auto-render'
import 'katex/dist/katex.min.css'
import { renderMarkdown } from '../../markdown.js'
import { request } from './api.js'

// Preserve LaTeX delimiters and backslashes until KaTeX sees the sanitized text.
const mathMarkdown = new Marked({
  extensions: [{
    name: 'studyMath',
    level: 'inline',
    start: text => text.search(/\$\$|\\[([]|(?<!\$)\$(?![\s$])/),
    tokenizer(text) {
      const raw = text.match(/^(?:\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\(.+?\\\)|\$(?![\s$])[^\n$]+?(?<!\s)\$(?!\d))/)?.[0]
      if (raw) return { type: 'studyMath', raw }
    },
    renderer: token => token.raw.replace(/[&<>]/g, value => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[value])
  }]
})

const props = defineProps({
  content: { type: String, required: true },
  references: { type: Array, default: () => [] },
  resources: { type: Array, default: () => [] }
})

const dialog = ref(null)
const selected = ref(null)
const page = ref(null)
const sourceUrl = ref('')
const loadError = ref('')
const loading = ref(false)
let selection = 0

const filename = reference => props.resources.find(file => file.id === reference.resource_id)?.filename
  || reference.title_path?.at(-1) || '课程资料'
function pageRanges(pages) {
  const ranges = []
  for (const page of [...new Set(pages)].sort((a, b) => a - b)) {
    const last = ranges.at(-1)
    if (last && page === last[1] + 1) last[1] = page
    else ranges.push([page, page])
  }
  return ranges.map(([first, last]) => first === last ? first : first + '–' + last).join('、')
}
const sourceLabel = reference => reference.pages?.length
  ? '第 ' + pageRanges(reference.pages) + ' 页'
  : '课件来源'
const pdfUrl = computed(() => sourceUrl.value && /\.pdf$/i.test(filename(selected.value))
  ? sourceUrl.value.split('#')[0] + (page.value ? `#page=${page.value}` : '') : '')

const html = computed(() => {
  const template = document.createElement('template')
  template.innerHTML = renderMarkdown(props.content, { parser: mathMarkdown, videoTimestamps: false })
  const rendered = document.createElement('div')
  rendered.append(template.content)
  const sources = new Map(props.references.map(reference => [reference.id, reference]))
  const sourceNumbers = new Map(props.references.map((reference, index) => [reference.id, index + 1]))
  const walker = document.createTreeWalker(rendered, NodeFilter.SHOW_TEXT)
  const nodes = []
  while (walker.nextNode()) nodes.push(walker.currentNode)
  for (const node of nodes) {
    if (node.parentElement?.closest('a, pre, code')) continue
    const fragment = document.createDocumentFragment()
    let cursor = 0
    const tokens = /\[(S\d+)\]|(?<=[；;。]\s*|\s)([一二三四五六七八九十]+、)(?=\s*\p{Script=Han})/gu
    for (const match of node.data.matchAll(tokens)) {
      const reference = sources.get(match[1])
      if (!reference && !match[2]) continue
      if (match[2]) {
        fragment.append(node.data.slice(cursor, match.index).trimEnd(), document.createElement('br'), match[2])
        cursor = match.index + match[0].length
        continue
      }
      const previous = fragment.lastElementChild
      if (previous?.hash === '#study-source-' + reference.id
          && /^[\s、，,]*$/.test(node.data.slice(cursor, match.index))) {
        cursor = match.index + match[0].length
        continue
      }
      fragment.append(node.data.slice(cursor, match.index))
      const link = document.createElement('a')
      link.className = 'inline-source'
      link.href = `#study-source-${reference.id}`
      link.title = filename(reference) + ' · ' + sourceLabel(reference)
      link.setAttribute('aria-label', link.title)
      link.textContent = String(sourceNumbers.get(reference.id))
      fragment.append(link)
      cursor = match.index + match[0].length
    }
    if (cursor) {
      fragment.append(node.data.slice(cursor))
      node.replaceWith(fragment)
    }
  }
  renderMathInElement(rendered, {
    delimiters: [
      { left: '$$', right: '$$', display: true },
      { left: '\\[', right: '\\]', display: true },
      { left: '\\(', right: '\\)', display: false },
      { left: '$', right: '$', display: false }
    ],
    ignoredTags: ['pre', 'code', 'a'],
    throwOnError: false,
    trust: false
  })
  return rendered.innerHTML
})

async function openSource(event) {
  const link = event.target.closest?.('.inline-source')
  if (!link) return
  event.preventDefault()
  const reference = props.references.find(item => link.hash === `#study-source-${item.id}`)
  if (!reference) return
  const id = ++selection
  selected.value = reference
  page.value = reference.pages?.[0] ?? null
  sourceUrl.value = ''
  loadError.value = ''
  loading.value = true
  dialog.value.showModal()
  try {
    const result = await request(`/resources/${reference.resource_id}/download`)
    const url = new URL(result.url, location.origin)
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error('资料地址无效')
    if (id === selection) sourceUrl.value = url.href
  } catch (error) {
    if (id === selection) loadError.value = error.message
  } finally {
    if (id === selection) loading.value = false
  }
}
</script>

<template>
  <div class="answer-content" v-html="html" @click="openSource"></div>
  <dialog ref="dialog" class="source-panel" aria-label="课件引用" @close="selection++">
    <template v-if="selected">
      <header>
        <div><strong>{{ filename(selected) }}</strong><p>{{ sourceLabel(selected) }}</p></div>
        <form method="dialog"><button type="submit" autofocus>关闭</button></form>
      </header>
      <p v-if="loading" role="status">正在加载课件…</p>
      <p v-else-if="loadError" role="alert">{{ loadError }}</p>
      <template v-else-if="sourceUrl">
        <label v-if="pdfUrl && selected.pages?.length > 1">
          查看引用页
          <select v-model.number="page">
            <option v-for="number in selected.pages" :key="number" :value="number">第 {{ number }} 页</option>
          </select>
        </label>
        <iframe v-if="pdfUrl" :key="pdfUrl" :src="pdfUrl" :title="`课件预览 · ${filename(selected)}`"></iframe>
        <p v-else>此文件需要在原文件中查看。请按上方标注的页码定位。</p>
        <a :href="pdfUrl || sourceUrl" target="_blank" rel="noopener noreferrer">在新窗口打开{{ pdfUrl ? ' PDF' : '原文件' }} ↗</a>
      </template>
    </template>
  </dialog>
</template>

<style scoped>
.answer-content { color: var(--ink); font-size: 16px; line-height: 1.85; overflow-wrap: anywhere; }
.answer-content :deep(p) { margin: 0 0 .85em; white-space: normal; }
.answer-content :deep(:is(h1, h2, h3, h4)) { margin: 1.1em 0 .45em; font-size: 1.16em; line-height: 1.4; }
.answer-content :deep(:is(ul, ol)) { margin: .5em 0 1em; padding-inline-start: 1.5em; }
.answer-content :deep(pre) { overflow: auto; padding: 12px; background: var(--accent-soft); }
.answer-content :deep(table) { display: block; overflow-x: auto; border-collapse: collapse; }
.answer-content :deep(:is(th, td)) { border: 1px solid var(--line); padding: 6px 10px; }
.answer-content :deep(a) { color: var(--accent-strong); }
.answer-content :deep(.katex-display) {
  overflow-x: auto; overflow-y: hidden; margin: 1em 0;
  padding: 5px 8px;
}
.answer-content :deep(.inline-source) {
  display: inline-block; margin-inline: 2px; padding: 0 3px; border-radius: 3px;
  font-size: .65em; line-height: 1.2; vertical-align: super;
  text-decoration: underline; text-underline-offset: 2px; white-space: nowrap;
}
.answer-content :deep(.inline-source:hover) { text-decoration: underline; }
.source-panel {
  position: fixed; inset: 0 0 0 auto; margin: 0; width: min(560px, 100%); max-width: 100%;
  height: 100%; max-height: 100%; box-sizing: border-box; border: 0; border-left: 1px solid var(--line);
  padding: 20px; color: var(--ink); background: var(--panel); overflow: auto;
}
.source-panel::backdrop { background: #17182f55; }
.source-panel header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.source-panel p { margin: 6px 0 12px; }
.source-panel iframe { display: block; width: 100%; height: max(300px, 72dvh); border: 1px solid var(--line); margin: 12px 0; }
.source-panel button { padding: 7px 12px; background: var(--accent-soft); color: var(--accent-strong); }
.source-panel a { color: var(--accent-strong); }
</style>
