// Persist receipts across reloads. The server verifies actual content and destination.
export function receiptIdentity(userId, courseId, chapterId, file) {
  return `course-upload:${JSON.stringify([String(userId),String(courseId),chapterId == null ? null : String(chapterId),file.name,file.size,file.lastModified])}`
}

export function createUploadReceipts(storage, randomKey = () => {
  const bytes = new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
}) {
  const memory = new Map()
  return {
    get(identity) {
      if (memory.has(identity)) return memory.get(identity)
      let existing
      try { existing = storage?.getItem(identity) } catch { /* Private-mode fallback. */ }
      const key = /^[a-zA-Z0-9_-]{8,100}$/.test(existing || '') ? existing : randomKey()
      memory.set(identity, key)
      try { storage?.setItem(identity, key) } catch { /* Retry still works in this page. */ }
      return key
    },
    forget(identity) {
      memory.delete(identity)
      try { storage?.removeItem(identity) } catch { /* Browser storage is optional. */ }
    }
  }
}
