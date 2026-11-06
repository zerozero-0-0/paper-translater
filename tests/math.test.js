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

test("reports positions for replacement", () => {
  const [match] = mathMatches("値 d_k です");
  assert.equal("値 d_k です".slice(match.start, match.end), "d_k");
});
