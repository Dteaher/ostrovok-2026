// Presentation-only typography. Never rewrite form values, messages, or data.
const copy = 'h1, h2, h3, .lux-description, .intro-caption, .decision-note, .booked-description, .site-footer';
const excluded = 'input, textarea, select, option, code, pre, [contenteditable], .chat-thread, .history';
const preposition = /(^|[\s(«„])((?:в|к|с|у|о|на|по|из|за|до|от|об|со)) (?=[\p{L}\p{N}«])/giu;

function typeset(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = root.nodeType === Node.TEXT_NODE ? [root] : [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const text of nodes) {
    const parent = text.parentElement;
    if (!parent?.closest(copy) || parent.closest(excluded)) continue;
    const value = text.data.replace(preposition, '$1$2\u00a0');
    if (value !== text.data) text.data = value;
  }
}

typeset(document.body);
new MutationObserver(records => {
  for (const record of records) {
    for (const node of record.addedNodes) typeset(node);
  }
}).observe(document.body, { childList: true, subtree: true });
