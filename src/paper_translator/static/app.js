const $ = (id) => document.getElementById(id);
const IMAGE_KINDS = ["equation", "figure"];
const MARKED_SKIPPED_KINDS = [...IMAGE_KINDS, "reference"];
const ANCHOR_KINDS = ["heading", "text", "equation", "reference"];
const READING_LINE = 0.3;
const SYNC_STORAGE_KEY = "scroll-sync";
const STATUS_LABELS = { queued: "待機中", translating: "翻訳中", paused: "一時停止", done: "完了", error: "エラー" };
const NUMERIC_CITATION = /\[(\d+(?:\s*[,;]\s*\d+)*)\]/gu;
const AUTHOR_CITATION = /(\p{Lu}[\p{Script=Latin}'’-]+)(?:\s+et al\.?|\s+and\s+\p{Lu}[\p{Script=Latin}'’-]+|ら|\s*&\s*\p{Lu}[\p{Script=Latin}'’-]+)?(?:,\s*|\s*[（(]\s*)((?:19|20)\d{2}[a-z]?)/gu;
const JUMP_SETTLE_MS = 1200;
let current = null;
let source = null;
let jumping = false;
let jumpTimer = null;
let leader = null;
let anchors = null;
let syncFrame = 0;
let syncEnabled = loadSyncPreference();

async function api(path, options) {
  const response = await fetch(`/api/papers${path}`, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `エラーが発生しました (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
}

function iconButton(name, label) {
  const button = element("button", "icon-button");
  button.type = "button";
  button.title = label;
  button.setAttribute("aria-label", label);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("icon");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#icon-${name}`);
  svg.append(use);
  button.append(svg);
  return button;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// 完了した論文には何も表示せず、未完のものだけ状態を返す
function paperState(paper) {
  if (paper.status === "done" && !paper.failed) return null;
  if (paper.status === "done") return { text: `${paper.failed} 段落が未翻訳`, className: "has-error", resumable: true };
  const text = `${STATUS_LABELS[paper.status]} ${paper.done}/${paper.total}`;
  if (paper.status === "error") return { text, className: "has-error", resumable: true };
  if (paper.status === "paused") return { text, className: "needs-action", resumable: true };
  return { text, className: "", resumable: false };
}

async function showLibrary() {
  closeEvents();
  closeCitation();
  current = null;
  document.body.dataset.screen = "library";
  $("library").hidden = false;
  $("reader").hidden = true;
  $("controls").hidden = true;
  document.title = "Paper Translator";
  document.body.classList.remove("bar-hidden");
  $("progress").classList.remove("running");
  const list = $("papers");
  list.replaceChildren();
  const papers = await api("");
  $("empty").hidden = papers.length > 0;
  for (const paper of papers) {
    const item = element("li");
    const link = element("a");
    link.href = `#${paper.id}`;
    const state = paperState(paper);
    const meta = element("small", "", paper.filename);
    if (state) meta.append(" ・ ", element("span", state.className, state.text));
    link.append(element("span", "paper-name", paper.title), meta);
    const remove = iconButton("trash", "削除");
    remove.addEventListener("click", async () => {
      if (!confirm(`「${paper.title}」と翻訳結果を削除しますか？`)) return;
      await api(`/${paper.id}`, { method: "DELETE" });
      showLibrary();
    });
    item.append(link);
    if (state?.resumable) {
      const resume = element("button", "text-button", "再開");
      resume.type = "button";
      resume.addEventListener("click", async () => {
        await api(`/${paper.id}/resume`, { method: "POST" });
        location.hash = paper.id;
      });
      item.append(resume);
    }
    item.append(remove);
    list.append(item);
  }
}

const narrow = window.matchMedia("(max-width: 800px)");

function loadSyncPreference() {
  try {
    return localStorage.getItem(SYNC_STORAGE_KEY) !== "off";
  } catch {
    return true;
  }
}

function saveSyncPreference() {
  try {
    localStorage.setItem(SYNC_STORAGE_KEY, syncEnabled ? "on" : "off");
  } catch {
    // 保存できなくても今の画面では動く
  }
}

function offsetIn(pane, node) {
  return pane.scrollTop + node.getBoundingClientRect().top - pane.getBoundingClientRect().top;
}

// 段落ごとの原文と訳文の位置を対応点にする。2 段組などで順序が戻る点は使わない
function buildAnchors() {
  const pages = $("pages");
  const segments = $("segments");
  const points = [{ ja: 0, en: 0 }];
  for (const segment of current.segments) {
    if (!ANCHOR_KINDS.includes(segment.kind)) continue;
    const mark = document.querySelector(`.mark[data-idx="${segment.idx}"]`);
    if (!mark) continue;
    const point = { ja: offsetIn(segments, $(`segment-${segment.idx}`)), en: offsetIn(pages, mark) };
    const last = points[points.length - 1];
    if (point.ja > last.ja && point.en > last.en) points.push(point);
  }
  const last = points[points.length - 1];
  points.push({ ja: Math.max(segments.scrollHeight, last.ja + 1), en: Math.max(pages.scrollHeight, last.en + 1) });
  return points;
}

function mapPosition(position, from, to) {
  let low = 0;
  let high = anchors.length - 1;
  while (high - low > 1) {
    const middle = (low + high) >> 1;
    if (anchors[middle][from] <= position) low = middle;
    else high = middle;
  }
  const start = anchors[low];
  const end = anchors[high];
  const ratio = Math.min(1, Math.max(0, (position - start[from]) / (end[from] - start[from])));
  return start[to] + (end[to] - start[to]) * ratio;
}

function syncPanes(source) {
  if (!current || !syncEnabled || narrow.matches || jumping) return;
  const follower = source === $("pages") ? $("segments") : $("pages");
  if (source.scrollTop === 0) {
    follower.scrollTop = 0;
    return;
  }
  anchors ??= buildAnchors();
  const [from, to] = source === $("pages") ? ["en", "ja"] : ["ja", "en"];
  const line = source.scrollTop + source.clientHeight * READING_LINE;
  follower.scrollTop = mapPosition(line, from, to) - follower.clientHeight * READING_LINE;
}

function setSync(enabled) {
  syncEnabled = enabled;
  $("sync").setAttribute("aria-pressed", enabled);
  saveSyncPreference();
}

function setView(view) {
  $("reader").dataset.view = view;
  $("view-ja").setAttribute("aria-pressed", view === "ja");
  $("view-en").setAttribute("aria-pressed", view === "en");
}

function firstVisibleIdx(pane, selector) {
  const top = pane.getBoundingClientRect().top;
  const node = [...pane.querySelectorAll(selector)]
    .filter((candidate) => candidate.getBoundingClientRect().bottom > top)
    .sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top)[0];
  return node?.dataset.idx;
}

function switchView(view) {
  if ($("reader").dataset.view === view) return;
  const idx = view === "en" ? firstVisibleIdx($("segments"), ".segment:not(.kind-front, .kind-title, .kind-figure, .kind-caption, .kind-footnote)") : firstVisibleIdx($("pages"), ".mark");
  startJump();
  setView(view);
  const target = view === "en" ? document.querySelector(`.mark[data-idx="${idx}"]`) : $(`segment-${idx}`);
  target?.scrollIntoView({ block: "center" });
}

function clearActive() {
  document.querySelectorAll(".active").forEach((node) => node.classList.remove("active"));
}

// 移動による自動スクロールと、読み手のスクロールを区別する
function startJump() {
  jumping = true;
  clearTimeout(jumpTimer);
  jumpTimer = setTimeout(() => {
    jumping = false;
  }, JUMP_SETTLE_MS);
}

function setActive(idx, scrollTarget) {
  if (narrow.matches) setView(scrollTarget === "page" ? "en" : "ja");
  clearActive();
  startJump();
  // 強調は読みにくくなるので移動先だけに付ける
  const nodes = scrollTarget === "page" ? [...document.querySelectorAll(`.mark[data-idx="${idx}"]`)] : [$(`segment-${idx}`)];
  nodes.forEach((node) => node.classList.add("active"));
  nodes[0]?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderPages(paper) {
  const pages = paper.pages.map((size, number) => {
    const page = element("div", "page");
    page.style.aspectRatio = `${size.width} / ${size.height}`;
    page.style.maxWidth = "900px";
    const image = element("img");
    image.loading = "lazy";
    image.alt = `${number + 1} ページ`;
    image.src = `/api/papers/${paper.id}/pages/${number}.png`;
    page.append(image);
    return page;
  });
  for (const segment of paper.segments) {
    if (segment.status === "skipped" && !MARKED_SKIPPED_KINDS.includes(segment.kind)) continue;
    for (const [number, x0, y0, x1, y1] of segment.boxes) {
      const size = paper.pages[number];
      const mark = element("div", "mark");
      mark.dataset.idx = segment.idx;
      mark.style.left = `${(x0 / size.width) * 100}%`;
      mark.style.top = `${(y0 / size.height) * 100}%`;
      mark.style.width = `${((x1 - x0) / size.width) * 100}%`;
      mark.style.height = `${((y1 - y0) / size.height) * 100}%`;
      mark.addEventListener("click", () => setActive(segment.idx, "segment"));
      pages[number].append(mark);
    }
  }
  $("pages").replaceChildren(...pages);
  $("pages").scrollTop = 0;
}

function citationButton(text, idx) {
  // button は行の途中で折り返せないのでリンクにする
  const link = element("a", "cite", text);
  link.href = `#reference-${idx}`;
  link.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    showCitation(idx);
  });
  return link;
}

function citationMatches(text) {
  const { numbers, authors } = current.references;
  const matches = [];
  for (const match of text.matchAll(NUMERIC_CITATION)) {
    const parts = match[1].split(/[,;]/).map((part) => part.trim());
    if (!parts.every((part) => part in numbers)) continue;
    let offset = match.index + 1;
    for (const part of parts) {
      const start = text.indexOf(part, offset);
      matches.push({ start, end: start + part.length, idx: numbers[part] });
      offset = start + part.length;
    }
  }
  for (const match of text.matchAll(AUTHOR_CITATION)) {
    const idx = authors[`${match[1].toLowerCase()} ${match[2]}`];
    if (idx !== undefined) matches.push({ start: match.index, end: match.index + match[0].length, idx });
  }
  return matches.sort((a, b) => a.start - b.start);
}

function mathNode(tex, fallback) {
  const node = element("span");
  try {
    katex.render(tex, node, { throwOnError: true });
    return node;
  } catch {
    return fallback;
  }
}

function renderText(node, rawText) {
  // 脚注記号は添字として抽出されるので、記号だけに戻す
  const text = rawText.replace(/\^([∗†‡]+)/gu, "$1");
  const parts = [];
  let position = 0;
  const matches = [...citationMatches(text), ...mathMatches(text)].sort((a, b) => a.start - b.start);
  for (const { start, end, idx, tex } of matches) {
    if (start < position) continue;
    const raw = text.slice(start, end);
    parts.push(text.slice(position, start), tex ? mathNode(tex, raw) : citationButton(raw, idx));
    position = end;
  }
  parts.push(text.slice(position));
  node.replaceChildren(...parts);
}

function showCitation(idx) {
  $("citation-text").textContent = $(`segment-${idx}`).dataset.source;
  $("citation-jump").onclick = () => {
    closeCitation();
    setActive(idx, "segment");
  };
  $("citation").classList.add("open");
}

function closeCitation() {
  $("citation").classList.remove("open");
}

function fillSegment(node, segment) {
  anchors = null;
  node.classList.remove("pending", "failed");
  if (segment.status === "pending") node.classList.add("pending");
  if (segment.status === "failed") node.classList.add("failed");
  renderText(node, segment.translation || segment.source);
}

function renderSegments(paper) {
  const nodes = paper.segments.map((segment) => {
    const node = element("div", `segment kind-${segment.kind}`);
    node.id = `segment-${segment.idx}`;
    node.dataset.idx = segment.idx;
    node.dataset.source = segment.source;
    if (IMAGE_KINDS.includes(segment.kind)) {
      const image = element("img");
      image.loading = "lazy";
      image.alt = segment.source || "図表";
      const boxes = segment.boxes.filter((box) => box[0] === segment.boxes[0][0]);
      image.width = Math.max(...boxes.map((box) => box[3])) - Math.min(...boxes.map((box) => box[1]));
      image.height = Math.max(...boxes.map((box) => box[4])) - Math.min(...boxes.map((box) => box[2]));
      image.src = `/api/papers/${paper.id}/segments/${segment.idx}.png`;
      node.append(image);
    } else {
      fillSegment(node, segment);
    }
    node.addEventListener("click", () => setActive(segment.idx, "page"));
    return node;
  });
  $("segments").replaceChildren(...nodes);
  $("segments").scrollTop = 0;
}

function renderStatus(paper) {
  const active = paper.status === "translating" || paper.status === "queued";
  const state = paperState(paper);
  const finished = !state;
  $("progress-label").textContent = state?.text ?? "";
  $("progress").classList.toggle("running", !finished);
  $("progress-label").title = paper.error || "";
  $("progress-bar").style.width = `${paper.total ? (paper.done / paper.total) * 100 : 0}%`;
  $("toggle").hidden = finished;
  const label = active ? "一時停止" : "再開";
  $("toggle").dataset.state = active ? "running" : "stopped";
  $("toggle").title = label;
  $("toggle").setAttribute("aria-label", label);
}

function closeEvents() {
  source?.close();
  source = null;
}

function openEvents(id) {
  closeEvents();
  source = new EventSource(`/api/papers/${id}/events`);
  source.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.type === "paper") {
      Object.assign(current, event);
      renderStatus(current);
      return;
    }
    const node = $(`segment-${event.idx}`);
    if (node) fillSegment(node, { ...event, source: node.dataset.source });
  };
}

async function showPaper(id) {
  const paper = await api(`/${id}`);
  current = paper;
  document.body.dataset.screen = "reader";
  $("library").hidden = true;
  $("reader").hidden = false;
  $("controls").hidden = false;
  document.title = paper.title;
  document.body.classList.remove("bar-hidden");
  $("export").href = `/api/papers/${id}/export.md`;
  $("export").download = `${paper.filename.replace(/\.pdf$/i, "")}.ja.md`;
  setView("ja");
  anchors = null;
  leader = null;
  renderPages(paper);
  renderSegments(paper);
  renderStatus(paper);
  openEvents(id);
}

async function route() {
  const id = location.hash.slice(1);
  try {
    await (id ? showPaper(id) : showLibrary());
  } catch (error) {
    location.hash = "";
    $("message").textContent = error.message;
  }
}

async function upload(file) {
  location.hash = "";
  $("message").textContent = "";
  const body = new FormData();
  body.append("file", file);
  try {
    const paper = await api("", { method: "POST", body });
    location.hash = paper.id;
  } catch (error) {
    $("message").textContent = error.message;
  }
}

// 読み進めるときはバーを隠し、上へ戻すと出す
for (const pane of [$("pages"), $("segments")]) {
  let last = 0;
  pane.addEventListener("scroll", () => {
    const top = pane.scrollTop;
    if (leader && pane !== leader) {
      last = top;
      return;
    }
    if (!syncFrame) {
      syncFrame = requestAnimationFrame(() => {
        syncFrame = 0;
        syncPanes(pane);
      });
    }
    if (Math.abs(top - last) < 8) return;
    if (!jumping) clearActive();
    if (narrow.matches) {
      last = top;
      return;
    }
    document.body.classList.toggle("bar-hidden", top > last && top > 40);
    last = top;
  }, { passive: true });
  // 触っている側だけを基準にして、追従した側のスクロールで往復しないようにする
  for (const name of ["pointerenter", "pointerdown", "wheel", "touchstart"]) {
    pane.addEventListener(name, () => {
      leader = pane;
    }, { passive: true });
  }
}

window.addEventListener("resize", () => {
  anchors = null;
});

$("citation-close").addEventListener("click", closeCitation);
$("sync").addEventListener("click", () => setSync(!syncEnabled));
$("sync").setAttribute("aria-pressed", syncEnabled);
$("view-ja").addEventListener("click", () => switchView("ja"));
$("view-en").addEventListener("click", () => switchView("en"));

$("toggle").addEventListener("click", async () => {
  const active = current.status === "translating" || current.status === "queued";
  const paper = await api(`/${current.id}/${active ? "pause" : "resume"}`, { method: "POST" });
  Object.assign(current, paper);
  if (!active) document.querySelectorAll(".segment.failed").forEach((node) => node.classList.replace("failed", "pending"));
  renderStatus(current);
});

$("open-file").addEventListener("click", () => $("file").click());

$("file").addEventListener("change", (event) => {
  if (event.target.files[0]) upload(event.target.files[0]);
  event.target.value = "";
});

// ページ全体をドロップ先にする
let dragDepth = 0;
function hasFile(event) {
  return event.dataTransfer?.types.includes("Files");
}
window.addEventListener("dragenter", (event) => {
  if (!hasFile(event)) return;
  event.preventDefault();
  dragDepth += 1;
  document.body.classList.add("dragging");
});
window.addEventListener("dragover", (event) => {
  if (hasFile(event)) event.preventDefault();
});
window.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) document.body.classList.remove("dragging");
});
window.addEventListener("drop", (event) => {
  event.preventDefault();
  dragDepth = 0;
  document.body.classList.remove("dragging");
  if (event.dataTransfer.files[0]) upload(event.dataTransfer.files[0]);
});

window.addEventListener("hashchange", route);
route();
