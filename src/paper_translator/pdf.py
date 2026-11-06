"""PDF から読み順どおりの段落を取り出す。"""

import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

TRANSLATED_KINDS = {"heading", "text", "caption", "footnote"}

FLAGS = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_LIGATURES & ~pymupdf.TEXT_PRESERVE_IMAGES
NUMBERED_HEADING = re.compile(r"^(\d+(\.\d+)*\.?|[A-Z](\.\d+)*\.?|[IVX]+\.)\s+[A-Z]")
CAPTION = re.compile(r"^(Figure|Fig\.|Table|Algorithm)\s+[A-Z]?\d+\s*[:.|]", re.I)
NUMBERED_REFERENCE = re.compile(r"^\[(\d+)\]")
SENTENCE_END = (".", "?", "!", ":", ";")
FIGURE_MARGIN = 14
MAX_CAPTION_GAP = 60
MATH_FONT = re.compile(r"^(CM|MSBM|MSAM|STIX|Cambria.?Math|.*Math|Symbol)", re.I)


@dataclass
class Block:
    page: int
    bbox: tuple[float, float, float, float]
    lines: list[str]
    size: float
    bold: bool
    text: str = ""
    tail: tuple[float, float, float, float] = (0, 0, 0, 0)
    visual: tuple[float, float, float, float] | None = None


@dataclass
class PageContent:
    rect: pymupdf.Rect
    regions: list[pymupdf.Rect]
    kept: list[Block]
    dropped: list[Block]


@dataclass
class Segment:
    kind: str
    page: int
    source: str
    boxes: list[list[float]] = field(default_factory=list)


def _line_text(spans: list[dict]) -> str:
    """文字サイズとベースラインの差から添字を d_k、W^O の形で復元する。"""
    visible = [span for span in spans if span["text"].strip()]
    if not visible:
        return ""
    weights = Counter()
    for span in visible:
        weights[(round(span["size"], 1), round(span["origin"][1], 1))] += len(span["text"].strip())
    base_size, base_y = weights.most_common(1)[0][0]

    text = ""
    previous = ""
    for span in spans:
        raw = span["text"]
        body = raw.strip()
        math = bool(MATH_FONT.match(span["font"]))
        shift = span["origin"][1] - base_y
        marker = ""
        if body and span["size"] <= base_size * 0.85 and (math or not body.isdigit()):
            if shift > 0.5:
                marker = "_"
            elif shift < -0.5 or math:
                marker = "^"
        if not body:
            text += raw
        elif not marker:
            text += raw
            previous = ""
        elif marker == previous:
            text = text.rstrip() + body
        else:
            text = text.rstrip() + marker + body
            previous = marker
    return text.strip()


def _join_fraction(lines: list[tuple[str, tuple, float]]) -> list[tuple[str, tuple, float]]:
    """本文中の分数は分子と分母が別の行になるので a/b の形につなぐ。"""
    joined: list[tuple[str, tuple, float]] = []
    for text, bbox, size in lines:
        if joined:
            top, top_bbox, top_size = joined[-1]
            overlap = top_bbox[3] - bbox[1]
            stacked = top_bbox[0] < bbox[2] and bbox[0] < top_bbox[2] and overlap > (top_bbox[3] - top_bbox[1]) * 0.3
            if stacked and len(top) < 12 and len(text) < 16:
                joined[-1] = (f"{top}/{text}", tuple(pymupdf.Rect(top_bbox) | pymupdf.Rect(bbox)), size)
                continue
            # 添字だけが別の行に分かれた場合は同じ行に戻す
            same_row = len(top) <= 2 and bbox[0] >= top_bbox[2] and overlap > (top_bbox[3] - top_bbox[1]) * 0.5
            if same_row:
                joined[-1] = (f"{top} {text}", tuple(pymupdf.Rect(top_bbox) | pymupdf.Rect(bbox)), size)
                continue
        joined.append((text, bbox, size))
    return joined


def _read_blocks(page: pymupdf.Page, page_no: int) -> list[Block]:
    blocks = []
    for raw in page.get_text("dict", flags=FLAGS)["blocks"]:
        rows, sizes, bold_chars, chars = [], Counter(), 0, 0
        for line in raw.get("lines", []):
            if abs(line["dir"][1]) > 0.01:  # arXiv の透かしなどの回転文字
                continue
            text = _line_text(line["spans"])
            if not text:
                continue
            rows.append((text, tuple(line["bbox"]), max(span["size"] for span in line["spans"])))
            for span in line["spans"]:
                n = len(span["text"].strip())
                sizes[round(span["size"] * 2) / 2] += n
                chars += n
                if span["flags"] & 16 or "bold" in span["font"].lower():
                    bold_chars += n
        if rows:
            rows = _join_fraction(rows)
            size = sizes.most_common(1)[0][0]
            lines = [row[0] for row in rows]
            blocks.append(Block(page_no, tuple(raw["bbox"]), lines, size, bold_chars > chars * 0.8, tail=rows[-1][1]))
    return blocks


def _merge_same_line(blocks: list[Block]) -> list[Block]:
    """添字などで同じ行が別ブロックに割れたものを、左から順につなぐ。"""
    merged: list[Block] = []
    for block in sorted(blocks, key=lambda b: b.bbox[0]):
        x0, y0, x1, y1 = block.bbox
        target = None
        if y1 - y0 < block.size * 2.5:
            for candidate in merged:
                tx0, ty0, tx1, ty1 = candidate.tail
                overlap = min(y1, ty1) - max(y0, ty0)
                if overlap > min(y1 - y0, ty1 - ty0) * 0.5 and -10 <= x0 - tx1 <= 15:
                    target = candidate
                    break
        if target is None:
            merged.append(block)
            continue
        joiner = "" if block.lines[0][:1] in ("_", "^", ",", ")") else " "
        target.lines[-1] += joiner + " ".join(block.lines)
        target.bbox = tuple(pymupdf.Rect(target.bbox) | pymupdf.Rect(block.bbox))
        target.tail = block.tail
    return merged


def _figure_regions(page: pymupdf.Page) -> list[pymupdf.Rect]:
    regions = [pymupdf.Rect(info["bbox"]) for info in page.get_image_info()]
    regions += [rect for rect in page.cluster_drawings() if rect.width > 50 and rect.height > 50]
    regions += [pymupdf.Rect(table.bbox) for table in page.find_tables().tables]
    return regions


def _in_regions(block: Block, regions: list[pymupdf.Rect]) -> bool:
    x0, y0, x1, y1 = block.bbox
    center = pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)
    return any(center in region for region in regions)


def _is_figure_label(block: Block, regions: list[pymupdf.Rect]) -> bool:
    """図のすぐ外に置かれた 1 行のラベル。見出しと文は除く。"""
    text = block.text
    x0, y0, x1, y1 = block.bbox
    if y1 - y0 > block.size * 1.6 or block.bold or text.endswith(SENTENCE_END) or NUMBERED_HEADING.match(text):
        return False
    return any(
        x0 < r.x1 and r.x0 < x1 and (0 <= r.y0 - y1 <= FIGURE_MARGIN or 0 <= y0 - r.y1 <= FIGURE_MARGIN)
        for r in regions
    )


def _gap(caption: Block, region: pymupdf.Rect, above: bool) -> float:
    return max(0, caption.bbox[1] - region.y1) if above else max(0, region.y0 - caption.bbox[3])


def _neighbors(caption: Block, regions: list[pymupdf.Rect], above: bool) -> list[pymupdf.Rect]:
    """キャプションの上下どちらかにあって、横方向に重なる領域を近い順に返す。"""
    x0, y0, x1, y1 = caption.bbox
    middle = (y0 + y1) / 2
    near = [r for r in regions if r.x0 < x1 and x0 < r.x1 and ((r.y0 + r.y1) / 2 < middle) == above]
    return sorted(near, key=lambda r: _gap(caption, r, above))


def _tables_sit_above_caption(pages: list["PageContent"]) -> bool:
    """表のキャプションの位置は論文ごとに揃っているので、多数決で決める。"""
    votes = Counter()
    for page in pages:
        for block in page.kept:
            if block.text.lower().startswith("table") and CAPTION.match(block.text):
                for above in (True, False):
                    near = _neighbors(block, page.regions, above)
                    votes[above] += bool(near) and _gap(block, near[0], above) < 35
    return votes[True] > votes[False]


def _attach_visuals(page: "PageContent", tables_above_caption: bool) -> None:
    """キャプションを起点に、隣の本文までを図や表の範囲として切り出す。"""
    for caption in page.kept:
        if not CAPTION.match(caption.text):
            continue
        above = tables_above_caption if caption.text.lower().startswith("table") else True
        near = _neighbors(caption, page.regions, above)
        if not near or _gap(caption, near[0], above) > MAX_CAPTION_GAP:
            above = not above
            near = _neighbors(caption, page.regions, above)
        if not near or _gap(caption, near[0], above) > MAX_CAPTION_GAP:
            continue

        x0, y0, x1, y1 = caption.bbox
        left, right = page.rect.x0, page.rect.x1
        middle = page.rect.width / 2
        prose = [b for b in page.kept if len(b.text) > 40]
        two_columns = sum(b.bbox[2] < middle + 10 for b in prose) >= 2 and sum(b.bbox[0] > middle - 10 for b in prose) >= 2
        if two_columns and x1 < middle + 10:
            right = middle
        elif two_columns and x0 > middle - 10:
            left = middle
        others = [
            b
            for b in page.kept
            if b is not caption
            and b.bbox[0] < x1
            and x0 < b.bbox[2]
            and (len(b.text) > 40 or b.bold or CAPTION.match(b.text))
        ]
        if above:
            top = max((b.bbox[3] for b in others if b.bbox[3] <= y0 + 1), default=page.rect.y0)
            band = pymupdf.Rect(left, top + 2, right, y0)
        else:
            bottom = min((b.bbox[1] for b in others if b.bbox[1] >= y1 - 1), default=page.rect.y1)
            band = pymupdf.Rect(left, y1, right, bottom - 2)

        visual = pymupdf.Rect()
        for region in near:
            visual |= region & band
        for block in page.dropped:
            box = pymupdf.Rect(block.bbox)
            if (box & band).get_area() > box.get_area() * 0.5:
                visual |= box & band
        if visual.is_empty:
            continue
        # 軸の目盛りのように図のすぐ外に残った短い文字列も図に含める
        for block in [b for b in page.kept if b is not caption and b not in others and len(b.text) < 60]:
            box = pymupdf.Rect(block.bbox)
            near_visual = (box + (-20, -20, 20, 20)).intersects(visual)
            if near_visual and (box & band).get_area() > box.get_area() * 0.5:
                visual |= box & band
                page.kept.remove(block)
        caption.visual = tuple((visual + (-3, -3, 3, 3)) & band)


def _reading_order(blocks: list[Block], width: float) -> list[Block]:
    """全幅のブロックを区切りに、その間を左段→右段の順に並べる。"""
    mid = width / 2
    left = [b for b in blocks if b.bbox[2] < mid + 10]
    right = [b for b in blocks if b.bbox[0] > mid - 10]
    ordered = sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
    if len(left) < 2 or len(right) < 2:
        return ordered

    result: list[Block] = []
    band: list[Block] = []

    def flush() -> None:
        band.sort(key=lambda b: (b.bbox[0] > mid - 10, b.bbox[1]))
        result.extend(band)
        band.clear()

    for block in ordered:
        if block.bbox[2] < mid + 10 or block.bbox[0] > mid - 10:
            band.append(block)
        else:
            flush()
            result.append(block)
    flush()
    return result


def _join_lines(lines: list[str], hyphenated: set[str]) -> str:
    text = ""
    for line in lines:
        match = re.search(r"([A-Za-z]+)-$", text)
        if match and line[:1].islower():
            head = match.group(1)
            tail = re.match(r"[A-Za-z]*", line).group()
            keep = f"{head}-{tail}".lower() in hyphenated
            text = (text if keep else text[:-1]) + line
        else:
            text = f"{text} {line}" if text else line
    text = re.sub(r"\s+", " ", text).strip()
    # 分母が本文と同じ行に入った分数は添字として読まれるので a/√b に戻す
    text = re.sub(r"(?<![\d.])(\d+) [\^_]?√[\^_]?(\w+)", r"\1/√\2", text)
    return re.sub(r"\s+([,.;:)\]])", r"\1", text)


def _is_heading(block: Block, body_size: float) -> bool:
    text = block.text
    if len(text) > 100 or len(block.lines) > 2 or text.endswith((".", ",")):
        return False
    if NUMBERED_HEADING.match(text):
        return block.bold or block.size > body_size
    return block.bold and len(text) < 80


def _is_fragment(text: str) -> bool:
    """本文として読めない断片。別行の数式の大半がここに入る。"""
    words = re.findall(r"[A-Za-z]{3,}", text)
    if len(text) < 60 and len(words) <= 3:
        return not (len(words) >= 2 and text[0].islower() and text.endswith("."))
    if len(text) >= 120 or text.endswith((".", ",")):
        return False
    return "=" in text or bool(re.search(r"\(\d{1,3}\)$", text))


def _classify(blocks: list[Block], body_size: float, page_heights: list[float]) -> list[Segment]:
    title = max(
        (b for b in blocks if b.page == 0 and b.bbox[1] < 300 and len(b.text) > 5),
        key=lambda b: b.size,
        default=None,
    )
    has_abstract = any(b.page == 0 and re.match(r"abstract\b", b.text, re.I) for b in blocks)
    in_front = has_abstract
    in_references = False
    in_abstract = False
    segments = []

    for block in blocks:
        text = block.text
        is_title_line = title and title.size > body_size and block.page == 0 and block.size == title.size
        if block is title or (is_title_line and block.bbox[1] < 300):
            kind = "title"
        elif in_front and not re.match(r"abstract\b", text, re.I):
            kind = "front"
        elif CAPTION.match(text):
            kind = "caption"
        elif _is_heading(block, body_size):
            kind = "heading"
            in_front = False
            in_abstract = False
            in_references = re.fullmatch(r"(\d+\.?\s+)?(references|bibliography)", text, re.I) is not None
        elif in_references:
            kind = "reference"
        elif _is_fragment(text):
            kind = "equation"
        elif (
            not in_abstract
            and block.size <= body_size - 0.7
            and block.bbox[1] > page_heights[block.page] * 0.5
        ):
            kind = "footnote"
        else:
            kind = "text"
        if in_front and re.match(r"abstract\b", text, re.I):
            in_front = False
            in_abstract = True
            kind = "heading" if len(text) < 20 else "text"
        if block.visual:
            segments.append(Segment("figure", block.page, "", [[block.page, *block.visual]]))
        segments.append(Segment(kind, block.page, text, [[block.page, *block.bbox]]))
    return segments


def _merge(segments: list[Segment]) -> list[Segment]:
    """ページや段をまたいで分断された段落と、数式の断片をつなぐ。"""
    merged: list[Segment] = []
    open_text: Segment | None = None
    open_note: Segment | None = None
    for segment in segments:
        if segment.kind in ("equation", "title") and merged and merged[-1].kind == segment.kind:
            merged[-1].source += " " + segment.source
            merged[-1].boxes += segment.boxes
            continue
        if segment.kind == "footnote" and open_note and not open_note.source.endswith(SENTENCE_END):
            open_note.source += " " + segment.source
            open_note.boxes += segment.boxes
            continue
        if segment.kind == "text" and open_text is not None:
            last = open_text.boxes[-1]
            box = segment.boxes[0]
            moved = box[0] != last[0] or abs(box[1] - last[1]) > 100
            if not open_text.source.endswith(SENTENCE_END) and (moved or segment.source[:1].islower()):
                open_text.source += " " + segment.source
                open_text.boxes += segment.boxes
                continue
        merged.append(segment)
        open_note = segment if segment.kind == "footnote" else open_note
        if segment.kind == "text":
            open_text = segment
        elif segment.kind not in ("caption", "footnote", "figure"):
            open_text = None
    return merged


def _merge_references(segments: list[Segment], hyphenated: set[str], page_width: float) -> list[Segment]:
    """行ごとに割れた参考文献を 1 件ずつにまとめる。番号がなければ字下げで区切りを見分ける。"""
    references = [s for s in segments if s.kind == "reference"]
    numbered = sum(bool(NUMBERED_REFERENCE.match(s.source)) for s in references) > len(references) / 2

    def column(segment: Segment) -> tuple[int, bool]:
        return segment.page, segment.boxes[0][1] > page_width / 2

    left_edges: dict[tuple[int, bool], float] = {}
    for segment in references:
        key = column(segment)
        left_edges[key] = min(left_edges.get(key, segment.boxes[0][1]), segment.boxes[0][1])

    merged: list[Segment] = []
    entry: Segment | None = None
    for segment in segments:
        if segment.kind != "reference":
            merged.append(segment)
            entry = None if segment.kind not in ("figure", "caption", "footnote") else entry
            continue
        if numbered:
            starts_entry = bool(NUMBERED_REFERENCE.match(segment.source))
        else:
            starts_entry = segment.boxes[0][1] - left_edges[column(segment)] < 3
        if entry is None or starts_entry:
            merged.append(segment)
            entry = segment
        else:
            entry.source = _join_lines([entry.source, segment.source], hyphenated)
            entry.boxes += segment.boxes
    return merged


def reference_index(segments: list[dict]) -> dict[str, dict[str, int]]:
    """本文中の引用から参考文献を引くための索引を作る。"""
    numbers: dict[str, int] = {}
    authors: dict[str, int] = {}
    for segment in segments:
        if segment["kind"] != "reference":
            continue
        source = segment["source"]
        if match := NUMBERED_REFERENCE.match(source):
            numbers[match.group(1)] = segment["idx"]
        year = re.search(r"\b(?:19|20)\d{2}[a-z]?\b", source)
        if not year:
            continue
        # 著者欄は最初の文末まで。頭文字の E. などは文末として扱わない
        people = re.split(r"(?<![A-Z])\.\s", source, maxsplit=1)[0]
        names = re.split(r",\s*(?:and\s+)?|\s+and\s+", people)
        # 複数語の姓は引用側の最後の語で拾えるように、2 人目までの姓を登録する
        for name in names[:2] if len(names) == 2 else names[:1]:
            if words := name.split():
                authors.setdefault(f"{words[-1].lower()} {year.group()}", segment["idx"])
    return {"numbers": numbers, "authors": authors}


def extract(document: pymupdf.Document) -> list[Segment]:
    pages: list[PageContent] = []
    for number, page in enumerate(document):
        regions = _figure_regions(page)
        blocks = _merge_same_line(_read_blocks(page, number))
        for block in blocks:
            block.text = " ".join(block.lines)
        kept, dropped = [], []
        for block in blocks:
            in_figure = _in_regions(block, regions) or _is_figure_label(block, regions)
            (dropped if in_figure and not CAPTION.match(block.text) else kept).append(block)
        pages.append(PageContent(page.rect, regions, kept, dropped))

    repeated = Counter()
    for content in pages:
        height = content.rect.height
        for block in content.kept:
            if block.bbox[1] < height * 0.1 or block.bbox[3] > height * 0.9:
                repeated[re.sub(r"\d+", "", block.text)] += 1

    def is_noise(block: Block, height: float) -> bool:
        edge = block.bbox[1] < height * 0.1 or block.bbox[3] > height * 0.9
        key = re.sub(r"\d+", "", block.text)
        return edge and (block.text.isdigit() or (len(key) > 3 and repeated[key] >= 3))

    sizes = Counter()
    hyphenated: set[str] = set()
    for content in pages:
        for block in content.kept:
            sizes[block.size] += len(block.text)
            hyphenated.update(w.lower() for w in re.findall(r"[A-Za-z]+-[A-Za-z]+", block.text))
    body_size = sizes.most_common(1)[0][0] if sizes else 10.0

    for content in pages:
        content.kept = [b for b in content.kept if not is_noise(b, content.rect.height)]
    tables_above_caption = _tables_sit_above_caption(pages)

    ordered: list[Block] = []
    for content in pages:
        _attach_visuals(content, tables_above_caption)
        ordered += _reading_order(content.kept, content.rect.width)
    for block in ordered:
        block.text = _join_lines(block.lines, hyphenated)
    heights = [page.rect.height for page in document]
    segments = _merge(_classify(ordered, body_size, heights))
    return _merge_references(segments, hyphenated, document[0].rect.width if len(document) else 0)
