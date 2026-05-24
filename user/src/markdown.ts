import { marked } from 'marked'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'

let initialized = false

function initMarkdown() {
  if (initialized) return
  initialized = true

  const renderer = new marked.Renderer()
  renderer.code = function ({ text, lang }: { text: string; lang?: string }) {
    const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
    const highlighted = hljs.highlight(text, { language }).value
    return `<pre><code class="hljs language-${language}">${highlighted}</code></pre>`
  }

  marked.setOptions({
    gfm: true,
    breaks: true,
    renderer,
  })
}

export function renderMarkdown(text: string): string {
  initMarkdown()
  const rawHtml = marked.parse(text) as string
  return DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS: [
      'h1','h2','h3','h4','h5','h6','p','br','hr',
      'strong','em','del','a','img',
      'ul','ol','li',
      'blockquote','pre','code',
      'table','thead','tbody','tr','th','td',
      'span','div'
    ],
    ALLOWED_ATTR: ['href','target','rel','class']
  })
}