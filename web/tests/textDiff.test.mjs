import test from 'node:test';
import assert from 'node:assert/strict';
import {englishDisplayDiff,isInflectionPair} from '../src/textDiff.mjs';

const removed = p => p.filter(x=>x.removed).map(x=>x.value).join('');
const added = p => p.filter(x=>x.added).map(x=>x.value).join('');
test('different words sharing letters are whole-word replacements',()=>{
  for(const [a,b] of [['entirely','solely'],['attention','convolution'],['worker','workable'],['careful','careless'],['results','reports']]) {
    const p=englishDisplayDiff(a,b);
    assert.equal(removed(p),a);assert.equal(added(p),b);
    assert.equal(p.filter(x=>!x.added&&!x.removed).length,0);
  }
});
test('known tense and inflection families get local character marks',()=>{
  for(const [a,b] of [['work','worked'],['study','studied'],['make','making'],['run','running'],['trained','training'],['show','shows']]) {
    assert.equal(isInflectionPair(a,b),true,`${a}/${b}`);
    assert.ok(englishDisplayDiff(a,b).some(p=>!p.added&&!p.removed),`${a}/${b}`);
  }
  assert.equal(added(englishDisplayDiff('work','worked')),'ed');
  assert.equal(isInflectionPair('Entirely','entirely'),false);
  assert.equal(isInflectionPair('researcher','researchers'),false); // unknown stays coarse
  for (const [a,b] of [['run','runned'],['run','runing'],['make','maked'],['stop','stoped'],['have','haves'],['be','bes'],['set','setted']]) {
    assert.equal(isInflectionPair(a,b),false,`${a}/${b} is not a tense form`);
  }
  for (const [a,b] of [['show','showed'],['have','has'],['stop','stopped'],['map','mapping'],['set','setting']]) {
    assert.equal(isInflectionPair(a,b),true,`${a}/${b}`);
  }
});
test('compounds, contractions, and numbers remain atomic',()=>{
  for(const [a,b] of [['attention-based','attention-only'],["don't","doesn't"],['1.25','1.26'],['⟦P000⟧','⟦P001⟧']]) {
    const p=englishDisplayDiff(a,b);assert.equal(removed(p),a);assert.equal(added(p),b);
  }
});
test('reconstruction preserves all whitespace, punctuation and Unicode',()=>{
  const pairs=[
    ['We rely entirely on attention.','We rely solely on attention.'],
    ['First sentence. Delete this sentence. Last.','First sentence. Last. Added sentence.'],
    ['a  b\nc\t','a b\r\nc\t '],['','An addition.'],['Delete all.',''],
    ['naïve café 🧬 研究','naïve cafés 🧪 研究。'],
    ['[12] uses ⟦P000⟧.','[13] used ⟦P000⟧!'],
    ['The result was stable.','Results were more stable.'],
  ];
  for(const [a,b] of pairs){
    const p=englishDisplayDiff(a,b);
    assert.equal(p.filter(x=>!x.added).map(x=>x.value).join(''),a);
    assert.equal(p.filter(x=>!x.removed).map(x=>x.value).join(''),b);
  }
});
