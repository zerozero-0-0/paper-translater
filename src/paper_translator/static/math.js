// 本文に残した d_k や 1/√d_k を検出して TeX に変換する
const SCRIPT = "-?(?:[A-Za-z0-9α-ωΑ-Ωϵ+−×]|\\.(?=\\d))+";
const MATH_PATTERN = new RegExp(
  [
    "(?<![\\w.])(?<numerator>\\d+)/√(?<fractionRoot>[A-Za-z]+(?:_[A-Za-z0-9]+)?)",
    "√(?<root>[A-Za-z]+(?:_[A-Za-z0-9]+)?)",
    `(?<![\\w/])(?<base>[A-Za-z0-9α-ωΑ-Ωϵ]+)(?<scripts>(?:[_^]${SCRIPT})+)`,
  ].join("|"),
  "gu",
);

function texWord(word) {
  return word.length > 2 && /^[A-Za-z]+$/.test(word) ? `\\mathrm{${word}}` : word;
}

function texScript(script) {
  return script
    .replace(/[A-Za-z]{3,}/g, (word) => `\\mathrm{${word}}`)
    .replaceAll("−", "-")
    .replaceAll("×", "\\times ");
}

// PDF で下付きが失われた √dk は √d_k として読む
function texRoot(root) {
  const lost = root.match(/^([A-Za-z])([A-Za-z])$/);
  const [base, script] = lost ? [lost[1], lost[2]] : root.split("_");
  return `\\sqrt{${script ? `${texWord(base)}_{${texScript(script)}}` : texWord(base)}}`;
}

function isIdentifier(base, scripts) {
  // step_num のように下線そのものを含む名前は数式にしない
  return /^[a-z]{2,}$/.test(base) && /^_[a-z]{2,}/.test(scripts);
}

function texScripted(base, scripts) {
  if (isIdentifier(base, scripts)) return null;
  if (/^\d+$/.test(base) && scripts.startsWith("_")) return null;
  const parts = [...scripts.matchAll(new RegExp(`([_^])(${SCRIPT})`, "gu"))];
  return texWord(base) + parts.map(([, marker, script]) => `${marker}{${texScript(script)}}`).join("");
}

function mathMatches(text) {
  const matches = [];
  for (const match of text.matchAll(MATH_PATTERN)) {
    const { numerator, fractionRoot, root, base, scripts } = match.groups;
    let tex = null;
    if (numerator) tex = `\\frac{${numerator}}{${texRoot(fractionRoot)}}`;
    else if (root) tex = texRoot(root);
    else tex = texScripted(base, scripts);
    if (tex) matches.push({ start: match.index, end: match.index + match[0].length, tex });
  }
  return matches;
}

if (typeof module !== "undefined") module.exports = { mathMatches };
