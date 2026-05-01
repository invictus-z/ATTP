declare global {
  interface Window {
    marked: any;
    hljs: any;
    DOMPurify: any;
  }
}

let initialized = false;

function initMarkdown() {
  if (initialized || !window.marked) return;
  initialized = true;
  window.marked.setOptions({
    gfm: true,
    breaks: true,
    highlight: (code: string, lang: string) => {
      if (window.hljs && lang && window.hljs.getLanguage(lang)) {
        return window.hljs.highlight(code, { language: lang }).value;
      }
      return window.hljs ? window.hljs.highlightAuto(code).value : code;
    }
  });
}

export function renderMarkdown(text: string): string {
  initMarkdown();
  if (!window.marked) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML.replace(/\n/g, '<br>');
  }
  const rawHtml = window.marked.parse(text);
  if (window.DOMPurify) {
    return window.DOMPurify.sanitize(rawHtml, {
      ALLOWED_TAGS: [
        'h1','h2','h3','h4','h5','h6','p','br','hr',
        'strong','em','del','a','img',
        'ul','ol','li',
        'blockquote','pre','code',
        'table','thead','tbody','tr','th','td',
        'span','div'
      ],
      ALLOWED_ATTR: ['href','target','rel','class']
    });
  }
  return rawHtml;
}
