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

const BIG_O = /(?<![\w.])O\(((?:[^()]|\([^()]*\))*)\)/gu;
const LONE_LETTER = /(?<![A-Za-z0-9α-ωΑ-Ωϵ_^√/.'’-])[A-Za-zα-ωΑ-Ωϵ](?![A-Za-z0-9α-ωΑ-Ωϵ_^/'’-])/gu;

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

function texBigO(inner) {
  const body = inner
    .replace(/log_(\w+)/g, "\\log_{$1}")
    .replace(/\blog\b/g, "\\log")
    .replace(/\^([\w−-]+)/g, (_, power) => `^{${power.replaceAll("−", "-")}}`)
    .replace(/(?<![\\\w])([A-Za-z])_(\w+)/g, "$1_{$2}")
    .replaceAll("·", " \\cdot ")
    .replaceAll("×", " \\times ");
  return `O(${body})`;
}

function overlaps(matches, start, end) {
  return matches.some((match) => start < match.end && match.start < end);
}

// symbols は PDF で変数として組まれていた文字。ここにある字だけを変数として扱う
function mathMatches(text, symbols = []) {
  const matches = [];
  for (const match of text.matchAll(BIG_O)) {
    matches.push({ start: match.index, end: match.index + match[0].length, tex: texBigO(match[1]) });
  }
  for (const match of text.matchAll(MATH_PATTERN)) {
    const { numerator, fractionRoot, root, base, scripts } = match.groups;
    let tex = null;
    if (numerator) tex = `\\frac{${numerator}}{${texRoot(fractionRoot)}}`;
    else if (root) tex = texRoot(root);
    else tex = texScripted(base, scripts);
    const end = match.index + match[0].length;
    if (tex && !overlaps(matches, match.index, end)) matches.push({ start: match.index, end, tex });
  }
  for (const match of text.matchAll(LONE_LETTER)) {
    const end = match.index + match[0].length;
    if (symbols.includes(match[0]) && !overlaps(matches, match.index, end)) {
      matches.push({ start: match.index, end, tex: match[0] });
    }
  }
  return matches.sort((a, b) => a.start - b.start);
}

if (typeof module !== "undefined") module.exports = { mathMatches };
