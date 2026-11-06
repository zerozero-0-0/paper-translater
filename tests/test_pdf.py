import pymupdf

from paper_translator.pdf import (
    VARIABLE,
    VARIABLE_FONT,
    Block,
    Segment,
    _is_figure_label,
    _join_fraction,
    _join_lines,
    _line_text,
    _merge,
    _merge_references,
    _merge_same_line,
    extract,
    reference_index,
)


def test_join_lines_repairs_line_break_hyphen():
    assert (
        _join_lines(["dot-product (multi-", "plicative) attention"], set()) == "dot-product (multiplicative) attention"
    )


def test_join_lines_keeps_real_compound():
    assert _join_lines(["a self-", "attention layer"], {"self-attention"}) == "a self-attention layer"


def test_join_lines_repairs_fraction_sharing_a_line_with_prose():
    assert (
        _join_lines(["the scaling factor of 1 ^√_dk. Additive attention"], set())
        == "the scaling factor of 1/√dk. Additive attention"
    )


def test_merge_joins_paragraph_split_across_pages():
    segments = [
        Segment("text", 0, "An attention function computes a weighted sum", [[0, 100, 700, 500, 720]]),
        Segment("caption", 1, "Figure 2: Attention.", [[1, 100, 270, 500, 280]]),
        Segment("text", 1, "of the values.", [[1, 100, 317, 500, 330]]),
    ]
    merged = _merge(segments)
    assert [s.kind for s in merged] == ["text", "caption"]
    assert merged[0].source.endswith("weighted sum of the values.")
    assert len(merged[0].boxes) == 2


def test_merge_keeps_finished_paragraphs_apart():
    segments = [
        Segment("text", 0, "First paragraph ends here.", [[0, 100, 100, 500, 120]]),
        Segment("text", 0, "Second paragraph starts here.", [[0, 100, 130, 500, 150]]),
    ]
    assert len(_merge(segments)) == 2


def test_extract_reads_two_columns_left_then_right():
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    sentence = "This sentence is ordinary prose for column number {} in the test."
    for y, n in ((100, 1), (200, 2)):
        page.insert_textbox((50, y, 290, y + 80), sentence.format(n), fontsize=10)
    for y, n in ((100, 3), (200, 4)):
        page.insert_textbox((320, y, 560, y + 80), sentence.format(n), fontsize=10)

    numbers = [s.source.split("number ")[1][0] for s in extract(document) if "number" in s.source]
    assert numbers == ["1", "2", "3", "4"]


def test_title_does_not_absorb_body_of_same_size():
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    for y, text in ((80, "A Plain Title Line"), (150, "This is an ordinary sentence of body text in the paper.")):
        page.insert_textbox((50, y, 560, y + 40), text, fontsize=10)

    assert [s.kind for s in extract(document)] == ["title", "text"]


def test_figure_label_is_separated_from_heading_and_prose():
    regions = [pymupdf.Rect(150, 83, 450, 260)]

    def block(text, bold=False):
        return Block(0, (148, 71, 450, 81), [text], 10.0, bold, text)

    assert _is_figure_label(block("Scaled Dot-Product Attention"), regions)
    assert not _is_figure_label(block("Attention Visualizations", bold=True), regions)
    assert not _is_figure_label(block("This line is a finished sentence."), regions)


def span(text, size=10.0, y=100.0, font="CMMI10"):
    return {"text": text, "size": size, "origin": (0, y), "font": font}


def test_line_text_restores_subscript_and_superscript():
    spans = [
        span("values of dimension "),
        span("d"),
        span("k", 7.0, 101.5),
        span(" and "),
        span("W"),
        span("O", 7.0, 96.0),
    ]
    assert _line_text(spans) == "values of dimension d_k and W^O"


def test_line_text_keeps_nested_subscripts_and_blackboard_letters():
    spans = [
        span("W"),
        span("O", 7.0, 96.0),
        span(" ∈", font="CMSY10"),
        span("R", font="MSBM10"),
        span("h", 7.0, 96.0),
        span("d", 7.0, 96.0),
        span("v", 5.0, 97.0),
        span("×", 7.0, 96.0, "CMSY7"),
        span("d", 7.0, 96.0),
        span("model", 5.0, 97.0, "NimbusRomNo9L"),
    ]
    assert _line_text(spans) == "W^O ∈ℝ^{hd_v×d_model}"


def test_line_text_ignores_small_text_when_choosing_the_baseline():
    spans = [span("R", font="MSBM10"), span("dmodel", 7.0, 96.0)]
    assert _line_text(spans) == "ℝ^dmodel"


def test_line_text_keeps_footnote_marker_in_prose_font():
    spans = [span("small gradients", font="Nimbus"), span("4", 7.0, 96.0, "Nimbus"), span(".", font="Nimbus")]
    assert _line_text(spans) == "small gradients4."


def test_join_fraction_stacks_numerator_over_denominator():
    rows = [
        ("scale by", (108, 604, 437, 615), 10.0),
        ("1", (446, 603, 450, 610), 7.0),
        ("√d_k", (441, 605, 459, 620), 7.0),
    ]
    assert [row[0] for row in _join_fraction(rows)] == ["scale by", "1/√d_k"]


def test_merge_same_line_keeps_columns_apart():
    def block(x0, x1, text):
        return Block(0, (x0, 100, x1, 112), [text], 10.0, False, tail=(x0, 100, x1, 112))

    joined = _merge_same_line([block(100, 200, "head"), block(205, 250, "_i = Attention")])
    assert [b.lines for b in joined] == [["head_i = Attention"]]
    assert len(_merge_same_line([block(50, 290, "left column"), block(320, 560, "right column")])) == 2


def add_rect(page, rect):
    page.draw_rect(rect, color=(0, 0, 0), fill=(0.5, 0.5, 0.5))


def test_figure_is_clipped_between_body_and_caption():
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    prose = "This paragraph is ordinary body text that sits above the figure and must not be included."
    page.insert_textbox((100, 60, 500, 110), prose, fontsize=10)
    add_rect(page, (150, 130, 450, 300))
    page.insert_textbox((100, 310, 500, 340), "Figure 1: A small example figure.", fontsize=10)

    figure = next(s for s in extract(document) if s.kind == "figure")
    _, x0, y0, x1, y1 = figure.boxes[0]
    assert 140 < x0 < 150 and 120 < y0 < 130 and 450 < x1 < 460
    assert 300 <= y1 <= 310


def test_figure_crop_stops_before_caption_even_when_drawing_overlaps_it():
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    add_rect(page, (150, 130, 450, 330))
    page.insert_textbox((100, 310, 500, 340), "Figure 1: A caption overlapping the drawing.", fontsize=10)

    figure = next(s for s in extract(document) if s.kind == "figure")
    assert figure.boxes[0][4] <= 312


def reference(text, x0=72.0, page=10):
    return Segment("reference", page, text, [[page, x0, 100, 280, 110]])


def test_merge_references_uses_numbers():
    segments = [
        reference("[1] Jimmy Ba. Layer normali-"),
        reference("zation. arXiv, 2016."),
        reference("[2] Dzmitry Bahdanau."),
    ]
    merged = _merge_references(segments, set(), 612)
    assert [s.source for s in merged] == ["[1] Jimmy Ba. Layer normalization. arXiv, 2016.", "[2] Dzmitry Bahdanau."]


def test_merge_references_uses_hanging_indent_without_numbers():
    segments = [
        reference("Alan Akbik, Duncan Blythe."),
        reference("2018. Contextual strings.", 83.0),
        reference("Rie Ando and Tong Zhang. 2005."),
    ]
    merged = _merge_references(segments, set(), 612)
    assert [s.source for s in merged] == [
        "Alan Akbik, Duncan Blythe. 2018. Contextual strings.",
        "Rie Ando and Tong Zhang. 2005.",
    ]


def test_reference_index_builds_number_and_author_year_keys():
    segments = [
        {"kind": "reference", "idx": 5, "source": "[6] Francois Chollet. Xception. arXiv, 2016."},
        {"kind": "reference", "idx": 6, "source": "Matthew Peters, Mark Neumann, and Others. 2018a. Deep."},
        {"kind": "reference", "idx": 7, "source": "Rie Kubota Ando and Tong Zhang. 2005. A framework."},
    ]
    index = reference_index(segments)
    assert index["numbers"] == {"6": 5}
    assert index["authors"]["peters 2018a"] == 6
    assert index["authors"]["ando 2005"] == 7
    assert index["authors"]["zhang 2005"] == 7


def test_reference_index_handles_single_author_without_comma():
    segments = [
        {"kind": "reference", "idx": 1, "source": "Wilson L Taylor. 1953. Cloze procedure. Journalism Bulletin."}
    ]
    assert reference_index(segments)["authors"] == {"taylor 1953": 1}


def test_variables_are_collected_only_from_math_italic_fonts():
    spans = [
        {"text": "a sequence of length ", "size": 10.0, "origin": (0, 100), "font": "NimbusRomNo9L"},
        {"text": "n", "size": 10.0, "origin": (0, 100), "font": "CMMI10"},
    ]
    assert not VARIABLE_FONT.match(spans[0]["font"])
    assert VARIABLE.findall(spans[1]["text"]) == ["n"]
    assert VARIABLE.findall("Q, K, V") == ["Q", "K", "V"]
