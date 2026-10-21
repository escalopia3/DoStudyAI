import { apiRequest } from '../../api.js'

export async function courseRequest(path, options = {}) {
  const response = await apiRequest(path, options)
  if (!response.ok) {
    const error = new Error(await response.text() || '请求失败，请重试')
    error.status = response.status
    throw error
  }
  return response.json()
}

export function postJson(body, signal) {
  return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal }
}

export function resourceFileKind(filename) {
  if (/\.(mp4|mov|mkv|avi|webm|m4v)$/i.test(filename)) return 'VIDEO'
  if (/\.(pdf|docx|pptx)$/i.test(filename)) return 'DOCUMENT'
  return null
}

export function courseUrl(courseId, current = window.location.href) {
  const url = new URL(current)
  if (courseId) url.searchParams.set('course', courseId)
  else url.searchParams.delete('course')
  return `${url.pathname}${url.search}${url.hash}`
}
