import React, {useEffect, useState} from 'react';
import {Save} from 'lucide-react';

type Assignment={initialTranslation:{kind:'translation_api'|'llm';id:string};mappingModelId:string;rewriteModelId:string};
type Model={id:string;name?:string;model:string};
type Service={id:string;name:string};
async function request(path:string,body?:unknown){
 const response=await fetch('/api'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const value=await response.json();if(!response.ok)throw Error(value.detail||'任务配置失败');return value;
}

export function TaskAssignments({onSaved}:{onSaved:()=>Promise<void>}){
 const [assignment,setAssignment]=useState<Assignment|null>(null),[models,setModels]=useState<Model[]>([]),[services,setServices]=useState<Service[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[info,setInfo]=useState('');
 useEffect(()=>{let live=true;Promise.all([request('/task-assignments'),request('/settings'),request('/translation-settings')]).then(([a,m,s])=>{if(live){setAssignment(a);setModels(m.profiles);setServices(s.providers);}}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[]);
 async function save(){if(!assignment)return;setBusy(true);setInfo('');setError('');try{const saved=await request('/task-assignments',assignment);setAssignment(saved);await onSaved();setInfo('任务分配已保存；新任务使用此配置，已有译文与已启动的重译任务保持原配置。');}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <div className="task-assignments"><section className="config-preferences"><p className="config-note">先在“通用模型”或“翻译服务”添加并保存配置，再在这里统一指定每项任务使用的服务。</p>{assignment&&<>
 <label>初始翻译<select aria-label="初始翻译" value={`${assignment.initialTranslation.kind}:${assignment.initialTranslation.id}`} onChange={e=>{const [kind,...id]=e.target.value.split(':');setAssignment({...assignment,initialTranslation:{kind:kind as 'llm'|'translation_api',id:id.join(':')}});}}><optgroup label="专用翻译 API">{services.map(s=><option key={s.id} value={`translation_api:${s.id}`}>{s.name} · 翻译 API</option>)}</optgroup><optgroup label="通用 LLM">{models.map(m=><option key={m.id} value={`llm:${m.id}`}>{m.name||m.model} · LLM</option>)}</optgroup></select><small>专用 API 生成中文；选择 LLM 时，由该模型联合生成译文与初始映射。</small></label>
 <label>句子映射与修复<select aria-label="句子映射与修复" value={assignment.mappingModelId} onChange={e=>setAssignment({...assignment,mappingModelId:e.target.value})}>{models.map(m=><option key={m.id} value={m.id}>{m.name||m.model}</option>)}</select><small>用于专用翻译后的中英句子映射，以及对应关系修复，仅支持通用 LLM。</small></label>
 <label>英文回写<select aria-label="英文回写" value={assignment.rewriteModelId} onChange={e=>setAssignment({...assignment,rewriteModelId:e.target.value})}>{models.map(m=><option key={m.id} value={m.id}>{m.name||m.model}</option>)}</select><small>根据中文修改生成局部英文变更，仅支持通用 LLM。</small></label>
 </>}{!assignment&&!error&&<p>正在读取任务分配…</p>}</section><footer className="config-footer"><div aria-live="polite">{error&&<p className="config-error">{error}</p>}{info&&<p className="config-success">{info}</p>}</div><div><button className="config-save" disabled={!assignment||busy} onClick={save}><Save size={15}/>保存任务分配</button></div></footer></div>;
}
