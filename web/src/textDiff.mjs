import { diffArrays, diffChars } from 'diff';

// Preserve exact text, including whitespace and protected-object placeholders.
const TOKENS = /⟦P\d+⟧|\p{L}[\p{L}\p{M}]*(?:['’\-‑][\p{L}\p{M}]+)*|\p{N}+(?:[.,]\p{N}+)*|\s+|[^\s]/gu;
const WORD = /^[A-Za-z]+$/;
// Deliberately bounded: unknown vocabulary stays a whole-word replacement.
// Shared letters/suffixes alone are not evidence of grammatical inflection.
const VERBS = `accept add align allow apply argue ask assess assume avoid base build call change check claim compare compute connect consider contain continue create define delete describe design determine develop differ discuss display edit enable evaluate examine expect explain export find follow form generate give have help identify improve include indicate introduce keep learn leave limit link live load look make map measure model move need observe obtain offer open perform permit predict preserve present propose provide read receive record reduce refer relate remove report require return reveal revise run save say see select send set show speak start stop store study suggest support take test train translate try use validate vary view wait work write`.split(' ');
const IRREGULAR = {be:['am','is','are','was','were','been','being'],build:['built'],do:['did','done'],find:['found'],give:['gave','given'],have:['has','had'],keep:['kept'],leave:['left'],make:['made'],read:['read'],run:['ran'],say:['said'],see:['saw','seen'],send:['sent'],set:['set'],show:['showed','shown'],speak:['spoke','spoken'],take:['took','taken'],write:['wrote','written']};
function forms(base) {
  const values = new Set([base, ...(IRREGULAR[base] || [])]);
  if (base === 'be') return values;
  if (base !== 'have') values.add(/[^aeiou]y$/.test(base) ? base.slice(0,-1)+'ies' : /(?:s|x|z|ch|sh|o)$/.test(base) ? base+'es' : base+'s');
  // Known doubling verbs, rather than a similarity-based stem guess.
  const doubled = ['run','stop','refer','permit','prefer','occur','plan','drop','admit','map','set'].includes(base);
  if (!IRREGULAR[base]) values.add(/[^aeiou]y$/.test(base) ? base.slice(0,-1)+'ied' : base.endsWith('e') ? base+'d' : doubled ? base+base.at(-1)+'ed' : base+'ed');
  values.add(doubled ? base+base.at(-1)+'ing' : base.endsWith('ie') ? base.slice(0,-2)+'ying' : /[^e]e$/.test(base) ? base.slice(0,-1)+'ing' : base+'ing');
  return values;
}
const FAMILIES = [...new Set([...VERBS,...Object.keys(IRREGULAR)])].map(forms);
export function isInflectionPair(before, after) {
  if (!WORD.test(before) || !WORD.test(after) || before === after || before.toLowerCase() === after.toLowerCase()) return false;
  // Case style must agree; a case edit should remain visible as a whole word.
  if ((before[0] === before[0].toUpperCase()) !== (after[0] === after[0].toUpperCase())) return false;
  return FAMILIES.some(f => f.has(before.toLowerCase()) && f.has(after.toLowerCase()));
}

/** English: words first, with a narrow grammatical-inflection exception. */
export function englishDisplayDiff(before, after) {
  const parts = diffArrays(before.match(TOKENS) || [], after.match(TOKENS) || []);
  const output = [];
  for (let i=0; i<parts.length; i++) {
    const current=parts[i], next=parts[i+1];
    if (current.removed && next?.added && current.value.length===1 && next.value.length===1 && isInflectionPair(current.value[0],next.value[0])) {
      output.push(...diffChars(current.value[0],next.value[0])); i++; continue;
    }
    output.push({value:current.value.join(''),...(current.added ? {added:true}:{}),...(current.removed ? {removed:true}:{})});
  }
  return output;
}
