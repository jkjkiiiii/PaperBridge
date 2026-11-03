import React, {useEffect,useState,useRef} from 'react';
import './native-pages.css';
type Rect=number[];
type Region={paragraphId:string;rects:Rect[];units?:{id:string;rects:Rect[]}[];status?:string};
type Layout={diff?:boolean;diffParagraphs?:string[];pendingParagraphs?:{id:string;status:string;error?:string}[];snapshotKind?:string;source?:string;revision:number;key:string;pages:{width:number;height:number;imageUrl:string;regions:Region[]}[]};
type Props={stateKey:string;diff:boolean;projectId:string;revision:number;original:boolean;language:"en"|"zh";active:string;editing:string;highlighted:string|null;onSelect:(id:string,pageIndex?:number)=>void;onHover:(id:string|null,unit?:string)=>void;unitStyle:(pid:string,uid:string)=>{color?:number;focused:boolean};renderEditor:(pid:string)=>React.ReactNode;onClose:()=>void};
const layouts=new Map<string,Layout>();
const requests=new Map<string,Promise<Layout>>();
function fetchLayout(key:string,url:string,revision:number,source:string){
 const cached=layouts.get(key);if(cached)return Promise.resolve(cached);
 let pending=requests.get(key);if(pending)return pending;
 pending=fetch(url).then(async r=>{if(!r.ok){const e=await r.json().catch(()=>({detail:'页面生成失败'}));throw Error(e.detail||'页面生成失败');}const data:Layout=await r.json();if(data.revision!==revision)throw Error('文档版本已变化，请重新加载页面。');const value={...data,source};layouts.set(key,value);while(layouts.size>12)layouts.delete(layouts.keys().next().value!);return value;}).finally(()=>requests.delete(key));
 requests.set(key,pending);return pending;
}
export function NativePages({stateKey,diff,projectId,revision,original,language,active,editing,highlighted,onSelect,onHover,unitStyle,renderEditor,onClose}:Props){
 const editingRef=useRef(editing);editingRef.current=editing;
 const rootRef=useRef<HTMLDivElement>(null);
 const [anchor,setAnchor]=useState<{id:string;page:number}|null>(null);
 const clicked=useRef<{id:string;page:number}|null>(null);
 const source=`${projectId}:${language}:${original}:${diff}`,cacheKey=`${source}:${revision}:${stateKey}`;
 const [layout,setLayout]=useState<Layout|null>(()=>layouts.get(cacheKey)||null),[error,setError]=useState(''),[retry,setRetry]=useState(0),[loading,setLoading]=useState(!layouts.has(cacheKey));
 useEffect(()=>{
  let cancelled=false;const cached=layouts.get(cacheKey);setError('');
  if(cached){setLayout(old=>editing && old?.source===source ? old : cached);setLoading(false);return;}
  setLayout(old=>old?.source===source?old:null);setLoading(true);
  fetchLayout(cacheKey,`/api/projects/${projectId}/native-layout?original=${original}&language=${language}&diff=${diff}`,revision,source).then(value=>{if(!cancelled){setLayout(old=>editingRef.current && old?.source===source ? old : value);setLoading(false);}}).catch(e=>{if(!cancelled){setError(e.message);setLoading(false);}});
  return ()=>{cancelled=true;};
 },[cacheKey,source,projectId,revision,original,language,diff,retry,editing]);
 useEffect(()=>{
  if(language!=='zh'||!editing||!layout||layout.source!==source)return;
  const candidates=layout.pages.flatMap((p,i)=>p.regions.some(r=>r.paragraphId===editing)?[i]:[]);
  if(!candidates.length){if(anchor)setAnchor(null);return;}
  if(anchor?.id===editing&&candidates.includes(anchor.page))return;
  const pane=rootRef.current?.closest('.pane');const bounds=pane?.getBoundingClientRect();
  const center=bounds?(bounds.top+bounds.bottom)/2:0;
  let selected=clicked.current?.id===editing&&candidates.includes(clicked.current.page)?clicked.current.page:candidates[0];
  if(clicked.current?.id!==editing)selected=candidates.reduce((best,i)=>{
    const a=rootRef.current?.querySelector<HTMLElement>(`[data-native-page="${i}"] [data-block="${editing}"]`)?.getBoundingClientRect();
    const b=rootRef.current?.querySelector<HTMLElement>(`[data-native-page="${best}"] [data-block="${editing}"]`)?.getBoundingClientRect();
    return a&&(!b||Math.abs(a.top-center)<Math.abs(b.top-center))?i:best;
   },selected);
  setAnchor({id:editing,page:selected});
  const el=rootRef.current?.querySelector<HTMLElement>(`[data-native-page="${selected}"] [data-block="${editing}"]`);
  if(el&&pane&&bounds){const rect=el.getBoundingClientRect();if(rect.top<bounds.top||rect.top>bounds.bottom-80)pane.scrollTop+=rect.top-bounds.top-24;}
 },[editing,language,layout,source,anchor]);
 if(error && !layout)return <div className="native-message" role="alert"><strong>Word 页面暂不可用</strong><p>{error}</p><button onClick={()=>(layouts.delete(cacheKey),setRetry(x=>x+1))}>重新生成</button><p>可以切换“结构编辑”继续处理未同步内容。</p></div>;
 if(!layout || layout.source!==source)return <div className="native-message" role="status">正在准备 Word 页面…<p>已缓存的页面会直接复用。</p></div>;
 const stale=loading || !!error || layout.revision!==revision;
 const editorPage=anchor?.id===editing?anchor.page:layout.pages.findIndex(p=>p.regions.some(r=>r.paragraphId===editing));
 return <div className="native-pages" ref={rootRef}>{stale && <div className="native-stale" role="status">{error || (editing ? "编辑中保留原位置，收起编辑后显示最新页面" : "正在更新 Word 页面…")} · 暂显示 r{layout.revision} 旧版，其他页面选区已停用。<button onClick={()=>(layouts.delete(cacheKey),setRetry(x=>x+1))}>重试</button></div>}{!!layout.pendingParagraphs?.length&&<div className="native-pending" role="status"><strong>{layout.pendingParagraphs.length} 段待处理 · 页面显示最近已同步内容，草稿已保留</strong><div>{layout.pendingParagraphs.map(p=><button key={p.id} title={p.error||p.status} onClick={()=>onSelect(p.id)}>处理 {p.id} · {p.status==='running'?'模型处理中':'待回写'}</button>)}</div></div>}<div className="native-hint">{layout.diff ? "Word 差异版面 · 红色删除，绿色新增；变更段按段定位" : "Word 原生版面 · 悬停句子查看对应颜色"} · 点击文字在中文原位编辑<br/>跨页段落可在当前页编辑；未定位内容仍可在本视图修改。</div>{language==='zh'&&editing&&editorPage<0&&<div className="native-unmapped-editor document-sheet"><div className="native-editor-title"><strong>位置未匹配 · 编辑当前段落</strong><button onClick={onClose}>收起</button></div><p>未能确定文字在页面上的位置；这里按已选段落编辑，不会猜测坐标。</p>{renderEditor(editing)}</div>}{layout.pages.map((page,index)=><div className="native-page-wrap" data-native-page={index} key={`${source}-${index}`}><div className="native-page" style={{aspectRatio:`${page.width}/${page.height}`}}><img src={page.imageUrl} alt={`Word 第 ${index+1} 页`} draggable={false} loading={index===0?'eager':'lazy'} decoding="async"/>{page.regions.map((r,i)=>{
 if(!r.rects.length)return null;
 const x=Math.min(...r.rects.map(v=>v[0])),y=Math.min(...r.rects.map(v=>v[1])),w=Math.max(...r.rects.map(v=>v[2]))-x,h=Math.max(...r.rects.map(v=>v[3]))-y;
 const place=(rect:Rect):React.CSSProperties=>({left:`${(rect[0]-x)/w*100}%`,top:`${(rect[1]-y)/h*100}%`,width:`${(rect[2]-rect[0])/w*100}%`,height:`${(rect[3]-rect[1])/h*100}%`});
 const hits=r.units?.length?r.units.flatMap(u=>u.rects.map(rect=>({rect,unit:u.id}))):r.rects.map(rect=>({rect,unit:undefined}));
 const editor=language==='zh'&&editing===r.paragraphId&&index===editorPage;
 const editorWidth=Math.min(page.width-24,Math.max(w,260));
 return <div key={`${r.paragraphId}-${i}`} data-block={r.paragraphId} className={`native-region ${editor?'editing-region':''}`} style={{left:`${x/page.width*100}%`,top:`${y/page.height*100}%`,width:`${w/page.width*100}%`,height:`${h/page.height*100}%`}}>{!stale&&hits.map(({rect,unit},j)=>{const paint=unit?unitStyle(r.paragraphId,unit):{focused:highlighted===r.paragraphId};return <button key={j} data-unit={unit} className={`native-hit ${active===r.paragraphId?'active':''} ${paint.focused?'highlighted':''}`} style={{...place(rect),...(paint.color!==undefined?{backgroundColor:`color-mix(in srgb, var(--c${paint.color%6}) ${paint.focused ? 82 : 62}%, transparent)`}:{})}} title={unit?'句子对应 · 点击编辑中文':'段落定位 · 点击编辑中文'} aria-label={`选择段落 ${r.paragraphId}`} onClick={()=>{clicked.current={id:r.paragraphId,page:index};setAnchor({id:r.paragraphId,page:index});onSelect(r.paragraphId,index);}} onMouseEnter={()=>onHover(r.paragraphId,unit)} onMouseLeave={()=>onHover(null)}/>;})}{editor&&<div className="native-inline-editor document-sheet" style={{width:`${editorWidth/w*100}%`,left:`${Math.min(0,page.width-12-x-editorWidth)/w*100}%`}}><div className="native-editor-title"><strong>原位编辑中文</strong><button onClick={onClose}>收起</button></div>{renderEditor(r.paragraphId)}</div>}</div>;
 })}</div><div className="native-page-number">{index+1} / {layout.pages.length}</div></div>)}</div>;
}
