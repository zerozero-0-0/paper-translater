const assert = require("node:assert/strict");
const test = require("node:test");
const { mathMatches } = require("../src/paper_translator/static/math.js");

const tex = (text) => mathMatches(text).map((match) => match.tex);

test("fractions under a root", () => {
  assert.deepEqual(tex("内積を 1/√d_k でスケーリングする"), ["\\frac{1}{\\sqrt{d_{k}}}"]);
  assert.deepEqual(tex("係数 1/√dk を除けば"), ["\\frac{1}{\\sqrt{d_{k}}}"]);
});

test("subscripts and superscripts", () => {
  assert.deepEqual(tex("d_k が小さい"), ["d_{k}"]);
  assert.deepEqual(tex("d_model次元"), ["d_{\\mathrm{model}}"]);
  assert.deepEqual(tex("ϵ = 10^−9 とした"), ["10^{-9}"]);
  assert.deepEqual(tex("W^Q_i と QK^T"), ["W^{Q}_{i}", "QK^{T}"]);
  assert.deepEqual(tex("BERT_BASE を用いる"), ["\\mathrm{BERT}_{\\mathrm{BASE}}"]);
  assert.deepEqual(tex("PE_pos+k は"), ["PE_{\\mathrm{pos}+k}"]);
});

test("stops before punctuation and hyphenated words", () => {
  assert.deepEqual(tex("d_k、d_v-dimensional, (x_1,..., x_n)"), ["d_{k}", "d_{v}", "x_{1}", "x_{n}"]);
});

test("leaves identifiers and urls alone", () => {
  assert.deepEqual(tex("step_num と warmup_steps = 4000"), []);
  assert.deepEqual(tex("Transformer は [12] で 2 BLEU 上回る"), []);
});

test("big O notation", () => {
  assert.deepEqual(tex("計算量は O(n) である"), ["O(n)"]);
  assert.deepEqual(tex("O(n^2 · d) と O(log_k(n))"), ["O(n^{2}  \\cdot  d)", "O(\\log_{k}(n))"]);
  assert.deepEqual(tex("MO(n) や O(1)"), ["O(1)"]);
});

test("lone letters become variables only when the PDF set them as variables", () => {
  const variables = (text, symbols) => mathMatches(text, symbols).map((match) => match.tex);
  assert.deepEqual(variables("系列長 n が次元 d より小さい", ["n", "d"]), ["n", "d"]);
  assert.deepEqual(variables("系列長 n と図 A", ["n"]), ["n"]);
  assert.deepEqual(variables("a model of n", ["n"]), ["n"]);
  assert.deepEqual(variables("BERT と GPU", ["B", "G"]), []);
  assert.deepEqual(variables("d_k と d", ["d", "k"]), ["d_{k}", "d"]);
});

test("real numbers and nested subscripts", () => {
  assert.deepEqual(tex("W^O ∈ℝ^{hd_v×d_model}"), [
    "W^{O}",
    "\\in",
    "\\mathbb{R}^{hd_{v}\\times d_{\\mathrm{model}}}",
  ]);
  assert.deepEqual(tex("x ∈ ℝ"), ["\\in", "\\mathbb{R}"]);
});

test("reports positions for replacement", () => {
  const [match] = mathMatches("値 d_k です");
  assert.equal("値 d_k です".slice(match.start, match.end), "d_k");
});
