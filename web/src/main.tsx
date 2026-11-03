import { ModelSettings } from "./ModelSettings";
import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { diffChars } from "diff";
import { englishDisplayDiff } from "./textDiff.mjs";
import {
  ArrowRight,
  ArrowLeftRight,
  BookOpen,
  Check,
  ChevronDown,
  Download,
  FileText,
  FolderOpen,
  Highlighter,
  Languages,
  Link2,
  LoaderCircle,
  Plus,
  RefreshCw,
  Settings,
  Trash2,
  Undo2,
  Redo2,
  X,
  AlertCircle,
  Upload,
  Pencil,
  Save,
} from "lucide-react";
import "./style.css";
import { NativePages } from "./NativePages";

type Unit = { id: string; text: string; start: number; end: number };
type Link = { source_ids: string[]; target_ids: string[] };
type Group = Link & { id: string; color: number; kind: string; edges: Link[] };
type Paragraph = {
  id: string;
  index: number | null;
  originalEn: string;
  originalUnits?: Unit[];
  en: string;
  zh: string;
  initialZh: string;
  draftZh: string;
  units: Unit[];
  targetUnits: Unit[];
  groups: Group[];
  status: string;
  revision: number;
  deleted: boolean;
  inserted: boolean;
  container: string;
  paragraphStyle: string;
  protected: string[];
  hasSection: boolean;
  error: string;
  stylePolicy?: string;
  history: unknown[];
  redo: unknown[];
  runs: {
    start: number;
    end: number;
    style: React.CSSProperties;
    protected: boolean;
    text: string;
  }[];
  modelMeta?: { model: string; seconds: number; alignmentWarning?: string; alignmentNotes?: string[]; alignmentMethod?: string; translationService?: {id:string;kind:string} };
  mappingSource?: string;
  translationPolicy?: "translate" | "skip_reference";
  skipReason?: string;
};
type LayoutNode = { type: "paragraph"; id: string; style?: React.CSSProperties } | { type: "table"; id?: string; columnWidths?: number[]; rows: { cells: { omitted?: boolean; colSpan?: number; rowSpan?: number; style?: React.CSSProperties; blocks: LayoutNode[] }[] }[] };
type Project = {
  retranslation?: {status:string;total:number;completed:number;failed:number;skipped?:number;model:string;error?:string;stopRequested?:boolean};
  layout?: LayoutNode[];
  id: string;
  name: string;
  revision: number;
  paragraphs: Paragraph[];
  events: unknown[];
};
type Summary = { id: string; name: string; created: string; revision: number };
type Provider = {
  id: string;
  name: string;
  protocol: string;
  baseUrl: string;
  timeout: number;
  hasKey?: boolean;
  apiKey?: string;
};
type Profile = {
  id: string;
  providerId: string;
  model: string;
  outputMode: string;
  maxTokens: number;
  contextTokens: number;
  temperature?: number;
  extraBody?: Record<string, unknown>;
};
type Config = {
  providers: Provider[];
  profiles: Profile[];
  routes: Record<string, string>;
  style: string;
  glossary: { en: string; zh: string }[];
};
const tasks = ["translate_align", "rewrite_en", "repair_alignment"];
const labels: Record<string, string> = {
  ready: "已同步",
  untranslated: "未翻译",
  pending: "待回写",
  running: "模型处理中",
  failed: "需要处理",
  needs_alignment: "待对齐",
  conflict: "冲突",
};
const cp = (s: string, n: number) => Array.from(s.slice(0, n)).length;
const slice = (s: string, a: number, b?: number) =>
  Array.from(s).slice(a, b).join("");
function parseGlossary(text: string, json: boolean) {
  if (json) {
    const value = JSON.parse(text);
    if (
      !Array.isArray(value) ||
      value.some((g) => typeof g.en !== "string" || typeof g.zh !== "string")
    )
      throw Error('JSON 术语表应为 [{"en":"...","zh":"..."}]');
    return value as { en: string; zh: string }[];
  }
  const rows: string[][] = [];
  let row: string[] = [],
    field = "",
    quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '"') {
      if (quoted && text[i + 1] === '"') {
        field += '"';
        i++;
      } else quoted = !quoted;
    } else if (ch === "," && !quoted) {
      row.push(field);
      field = "";
    } else if ((ch === "\n" || ch === "\r") && !quoted) {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      if (row.some((x) => x.trim())) rows.push(row);
      row = [];
      field = "";
    } else field += ch;
  }
  if (quoted) throw Error("CSV 引号未闭合");
  row.push(field);
  if (row.some((x) => x.trim())) rows.push(row);
  if (
    rows.length &&
    ["en", "english", "英文"].includes(rows[0][0].trim().toLowerCase())
  )
    rows.shift();
  if (rows.some((r) => r.length !== 2)) throw Error("CSV 需要两列：en,zh");
  return rows.map((r) => ({ en: r[0].trim(), zh: r[1].trim() }));
}
async function api<T = any>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(
    "/api" + url,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  if (!response.ok) {
    const e = await response.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(
      typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail),
    );
  }
  return response.json();
}
function App() {
  const [projects, setProjects] = useState<Summary[]>([]),
    [project, setProject] = useState<Project | null>(null),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState<Config | null>(null),
    [settingsOpen, setSettingsOpen] = useState(false);
  const [nativeView, setNativeView] = useState(true);
  const [diff, setDiff] = useState(false),
    [colors, setColors] = useState(false),
    [original, setOriginal] = useState(false),
    [active, setActive] = useState(""),
    [editing, setEditing] = useState("");
  const [hover, setHover] = useState<{
      pid: string;
      side: string;
      ids: string[];
    } | null>(null),
    [selection, setSelection] = useState<typeof hover>(null),
    [drafts, setDrafts] = useState<Record<string, string>>({});
  const [mapping, setMapping] = useState<Paragraph | null>(null),
    [mapLinks, setMapLinks] = useState<Link[]>([]),
    [mapEn, setMapEn] = useState<string[]>([]),
    [mapZh, setMapZh] = useState<string[]>([]),
    [scope, setScope] = useState<string[]>([]);
  const [auto, setAuto] = useState(true),
    [working, setWorking] = useState<Set<string>>(new Set()),
    [exporting, setExporting] = useState(false);
  const left = useRef<HTMLDivElement>(null),
    right = useRef<HTMLDivElement>(null),
    scrollOwner = useRef<"left" | "right" | null>(null),
    timer = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const pointerTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pointerSource = useRef<{side: "left" | "right"; x: number; y: number} | null>(null);
  const fileInput = useRef<HTMLInputElement>(null),
    configInput = useRef<HTMLInputElement>(null),
    projectRef = useRef(project),
    draftRef = useRef(drafts),
    composing = useRef(false),
    dragging = useRef(false),
    editSerial = useRef<Record<string, number>>({}),
    saveQueue = useRef<Record<string, Promise<void>>>({}),
    batchStop = useRef(false);
  projectRef.current = project;
  draftRef.current = drafts;
  function accept(p: Project) {
    if (
      projectRef.current?.id === p.id &&
      p.revision < projectRef.current.revision
    )
      return;
    setProject(p);
    projectRef.current = p;
  }
  const hasRunningParagraph = !!project?.paragraphs.some(p => p.status === "running") || ["running", "stopping"].includes(project?.retranslation?.status || "");
  useEffect(() => {
    if (!project?.id || !hasRunningParagraph) return;
    const id = project.id;
    let stopped = false, fetching = false;
    const tick = async () => {
      if (stopped || fetching || document.hidden) return;
      fetching = true;
      try {
        const fresh = await api<Project>("/projects/" + id);
        const current = projectRef.current;
        if (!stopped && current?.id === id && fresh.revision >= current.revision &&
            (fresh.revision !== current.revision || JSON.stringify(fresh.retranslation) !== JSON.stringify(current.retranslation) || fresh.paragraphs.some((p,i) => p.status !== current.paragraphs[i]?.status || p.revision !== current.paragraphs[i]?.revision))) accept(fresh);
      } catch { /* Keep local drafts and retry while the task is running. */ }
      finally { fetching = false; }
    };
    const interval = setInterval(tick, 2000);
    return () => { stopped = true; clearInterval(interval); };
  }, [project?.id, hasRunningParagraph]);
  function toast(e: unknown) {
    setNotice(e instanceof Error ? e.message : String(e));
  }
  const refresh = () =>
    api<Summary[]>("/projects").then(setProjects).catch(toast);
  useEffect(() => {
    refresh();
    api<Config>("/settings").then(setSettings).catch(toast);
  }, []);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(""), 8000);
    return () => clearTimeout(t);
  }, [notice]);
  useEffect(() => {
    const fn = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setSelection(null);
        setHover(null);
        setMapping(null);
      }
    };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, []);
  useEffect(() => {
    const fn = (e: BeforeUnloadEvent) => {
      if (
        Object.keys(draftRef.current).length ||
        Object.keys(saveQueue.current).length
      ) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", fn);
    return () => window.removeEventListener("beforeunload", fn);
  }, []);
  async function open(id: string) {
    if (Object.keys(draftRef.current).length) {
      toast("请先保存当前编辑，再切换文档");
      return;
    }
    setBusy(true);
    try {
      const p = await api<Project>("/projects/" + id);
      setProject(p);
      setDrafts({});
      setSelection(null);
      setEditing("");
      setActive(p.paragraphs[0]?.id || "");
    } catch (e) {
      toast(e);
    } finally {
      setBusy(false);
    }
  }
  async function upload(file?: File) {
    if (!file) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await fetch("/api/projects", { method: "POST", body: form });
      const data = await r.json();
      if (!r.ok) throw Error(data.detail);
      setProject(data);
      setDrafts({});
      setActive(data.paragraphs[0]?.id || "");
      refresh();
      toast("文档已导入，原始文件只读保存");
    } catch (e) {
      toast(e);
    } finally {
      setBusy(false);
    }
  }
  async function act(p: Paragraph, action: string, extra = {}) {
    if (!project) return;
    try {
      accept(
        await api(`/projects/${project.id}/paragraphs/${p.id}/action`, {
          action,
          ...extra,
        }),
      );
      setSelection(null);
    } catch (e) {
      toast(e);
    }
  }
  async function model(p: Paragraph, task: string, allowedIds?: string[]) {
    const current = projectRef.current;
    if (!current) return;
    setWorking((s) => new Set(s).add(p.id));
    try {
      const result = await api<Project>(
        `/projects/${current.id}/paragraphs/${p.id}/model`,
        { task, allowedIds },
      );
      if (projectRef.current?.id === current.id) accept(result);
      const updated = result.paragraphs.find((x) => x.id === p.id);
      if (updated?.error) toast(updated.error);
    } catch (e) {
      toast(e);
    } finally {
      setWorking((s) => {
        const n = new Set(s);
        n.delete(p.id);
        return n;
      });
    }
  }
  async function saveDraft(id: string, run = auto) {
    clearTimeout(timer.current[id]);
    const operation = async () => {
      const current = projectRef.current;
      if (!current) return;
      const p = current.paragraphs.find((p) => p.id === id);
      const text = draftRef.current[id];
      if (!p || text === undefined) return;
      const serial = editSerial.current[id] || 0;
      try {
        const result = await api<Project>(
          `/projects/${current.id}/paragraphs/${id}/draft`,
          { text, revision: p.revision },
        );
        accept(result);
        if ((editSerial.current[id] || 0) === serial)
          setDrafts((s) => {
            const n = { ...s };
            delete n[id];
            draftRef.current = n;
            return n;
          });
        const item = result.paragraphs.find((x) => x.id === id)!;
        if (
          run &&
          item.status === "pending" &&
          (editSerial.current[id] || 0) === serial
        )
          void model(item, "rewrite_en");
      } catch (e) {
        toast(e);
      }
    };
    const previous = saveQueue.current[id] || Promise.resolve();
    const promise = previous.then(operation);
    saveQueue.current[id] = promise;
    await promise;
    if (saveQueue.current[id] === promise) delete saveQueue.current[id];
  }
  function changeDraft(p: Paragraph, text: string) {
    const tokens = text.match(/⟦P\d+⟧/g) || [];
    if (JSON.stringify(tokens) !== JSON.stringify(p.protected)) {
      toast("保护对象不可编辑，请只修改普通文字");
      return;
    }
    setDrafts((s) => {
      const n = { ...s, [p.id]: text };
      draftRef.current = n;
      return n;
    });
    editSerial.current[p.id] = (editSerial.current[p.id] || 0) + 1;
    setSelection(null);
    setHover(null);
    clearTimeout(timer.current[p.id]);
    if (!composing.current)
      timer.current[p.id] = setTimeout(() => saveDraft(p.id), 850);
  }
  async function translateAll() {
    if (!project) return;
    setBusy(true);
    batchStop.current = false;
    try {
      for (const p of project.paragraphs) {
        if (batchStop.current) break;
        if (p.deleted || p.translationPolicy === "skip_reference" || p.zh || !p.en.trim()) continue;
        await model(p, "translate_align");
      }
    } finally {
      setBusy(false);
    }
  }
  async function retranslateAll() {
    if (!project || busy) return;
    const sourceId = project.id;
    setBusy(true);
    try {
      for (const id of Object.keys(draftRef.current)) await saveDraft(id, false);
      await Promise.all(Object.values(saveQueue.current));
      if (Object.keys(draftRef.current).length) throw Error("仍有未保存文字，请先保存后重试");
      const source = await api<Project>(`/projects/${sourceId}`);
      if (source.paragraphs.some(p => !p.deleted && (!["ready", "untranslated"].includes(p.status) || p.draftZh !== p.zh))) {
        throw Error("请先完成、重试或撤销待回写内容，再重新翻译全文。");
      }
      if (!window.confirm("将使用当前已同步的英文创建新的重译版本，按当前选择的翻译服务生成全文中文，再用通用模型重建句子映射。原项目、译文和编辑记录保留。是否开始？")) return;
      const next = await api<Project>(`/projects/${sourceId}/retranslate`, {});
      setProject(next); projectRef.current = next;
      setDrafts({}); draftRef.current = {}; setEditing(""); setSelection(null); setHover(null);
      setActive(next.paragraphs[0]?.id || ""); refresh();
      toast("已创建重译版本，后台正在翻译并重建映射；可随时暂停后续段落。");
    } catch (e) { toast(e); } finally { setBusy(false); }
  }
  async function retranslationAction(action: "stop" | "resume") {
    if (!project) return;
    try { accept(await api<Project>(`/projects/${project.id}/retranslate/${action}`, {})); }
    catch (e) { toast(e); }
  }
  function cancelPointerAlignment(clearSource = false) {
    if (pointerTimer.current) clearTimeout(pointerTimer.current);
    pointerTimer.current = null;
    if (clearSource) pointerSource.current = null;
  }
  useEffect(() => {
    cancelPointerAlignment(true);
    return () => cancelPointerAlignment(true);
  }, [project?.id, nativeView, editing]);
  function schedulePointerAlignment(side: "left" | "right") {
    cancelPointerAlignment();
    if (editing || selection || composing.current) return;
    pointerTimer.current = setTimeout(() => {
      const point = pointerSource.current;
      if (!point || point.side !== side || composing.current) return;
      const selected = window.getSelection();
      if (selected && !selected.isCollapsed) return;
      const pane = side === "left" ? left.current : right.current;
      const other = side === "left" ? right.current : left.current;
      if (!pane || !other) return;
      const hit = document.elementFromPoint(point.x, point.y) as HTMLElement | null;
      if (!hit || !pane.contains(hit) || hit.closest("textarea,input,select,.paragraph-tools,.native-inline-editor,.native-unmapped-editor")) return;
      const block = hit.closest<HTMLElement>("[data-block]");
      if (!block || !pane.contains(block)) return;
      const id = block.dataset.block!;
      const paragraph = projectRef.current?.paragraphs.find(p => p.id === id);
      const sourceUnit = hit.closest<HTMLElement>("[data-unit]")?.dataset.unit;
      const corresponding = new Set<string>();
      if (paragraph && sourceUnit && isMapped(paragraph) && !(original && paragraph.en !== paragraph.originalEn)) {
        for (const group of paragraph.groups) for (const edge of group.edges || [group]) {
          const from = side === "left" ? edge.source_ids : edge.target_ids;
          if (from.includes(sourceUnit)) (side === "left" ? edge.target_ids : edge.source_ids).forEach(id => corresponding.add(id));
        }
      }
      const sourceOffset = block.getBoundingClientRect().top - pane.getBoundingClientRect().top;
      const candidates = Array.from(other.querySelectorAll<HTMLElement>(`[data-block="${id}"]`));
      const mapped = candidates.filter(el => Array.from(el.querySelectorAll<HTMLElement>("[data-unit]")).some(u => corresponding.has(u.dataset.unit!)));
      const targetTop = other.getBoundingClientRect().top;
      const target = (mapped.length ? mapped : candidates).sort((a,b) =>
        Math.abs(a.getBoundingClientRect().top - targetTop - sourceOffset) - Math.abs(b.getBoundingClientRect().top - targetTop - sourceOffset))[0];
      if (!target) return;
      // Only the opposite pane moves. Its scroll/mouseenter cannot become authority.
      const delta = target.getBoundingClientRect().top - targetTop - sourceOffset;
      if (Math.abs(delta) > 1) other.scrollTop += delta;
      setActive(id);
    }, 120);
  }
  function pointerMoved(side: "left" | "right", event: React.PointerEvent<HTMLDivElement>) {
    if (event.pointerType === "touch" || event.buttons) { cancelPointerAlignment(true); return; }
    const previous = pointerSource.current;
    if (previous?.side === side && previous.x === event.clientX && previous.y === event.clientY) return;
    pointerSource.current = {side, x:event.clientX, y:event.clientY};
    schedulePointerAlignment(side);
  }
  function locate(id: string) {
    cancelPointerAlignment(true);
    scrollOwner.current = null;
    setActive(id);
    for (const pane of [left.current, right.current]) {
      const el = pane?.querySelector<HTMLElement>(`[data-block="${id}"]`);
      if (el && pane)
        pane.scrollTo({
          top:
            pane.scrollTop +
            el.getBoundingClientRect().top -
            pane.getBoundingClientRect().top -
            12,
          behavior: "auto",
        });
    }
  }
  function isMapped(p: Paragraph) {

  return (
      p.translationPolicy !== "skip_reference" && p.status === "ready" && drafts[p.id] === undefined && !working.has(p.id)
    );
  }
  function targets(p: Paragraph, side: string) {
    const focus = selection || hover;
    if (!focus || focus.pid !== p.id || !isMapped(p)) return new Set<string>();
    if (focus.side === side) return new Set(focus.ids);
    const result = new Set<string>();
    for (const g of p.groups)
      for (const e of g.edges || [g]) {
        const source = focus.side === "en" ? e.source_ids : e.target_ids;
        const target = side === "en" ? e.source_ids : e.target_ids;
        if (source.some((x) => focus.ids.includes(x)))
          target.forEach((x) => result.add(x));
      }
    return result;
  }
  function onSelection(
    p: Paragraph,
    side: string,
    e: React.MouseEvent<HTMLElement>,
  ) {
    dragging.current = false;
    const s = window.getSelection();
    if (!s || s.isCollapsed) {
      setSelection(null);
      return;
    }
    const range = s.getRangeAt(0);
    const block = e.currentTarget;
    if (
      !block.contains(range.startContainer) ||
      !block.contains(range.endContainer)
    ) {
      toast("联动选区仅支持一个段落");
      setSelection(null);
      return;
    }
    const ids = Array.from(block.querySelectorAll<HTMLElement>("[data-unit]"))
      .filter((el) => {
        if (!range.intersectsNode(el)) return false;
        const r = document.createRange();
        r.selectNodeContents(el);
        return (
          range.compareBoundaryPoints(Range.END_TO_START, r) < 0 &&
          range.compareBoundaryPoints(Range.START_TO_END, r) > 0
        );
      })
      .map((el) => el.dataset.unit!);
    if (ids.length) setSelection({ pid: p.id, side, ids: [...new Set(ids)] });
  }
  function textView(p: Paragraph, side: "en" | "zh") {
    if (p.translationPolicy === "skip_reference") return p.en;
    const text = side === "en" ? (original ? p.originalEn : p.en) : p.zh;
    const units =
      side === "en"
        ? original
          ? p.originalUnits || p.units
          : p.units
        : p.targetUnits;
    const selected = targets(p, side);
    const positionMap: number[] = [];
    let oldOffset = 0;
    if (side === "en")
      for (const part of diffChars(p.originalEn, text)) {
        if (part.removed) {
          oldOffset += Array.from(part.value).length;
          continue;
        }
        for (const char of Array.from(part.value)) {
          positionMap.push(part.added ? Math.max(0, oldOffset - 1) : oldOffset);
          if (!part.added) oldOffset++;
        }
      }
    const styled = (value: string, start: number) => {
      if (side !== "en") return value;
      const chunks: {
        text: string;
        style: React.CSSProperties;
        protected: boolean;
      }[] = [];
      Array.from(value).forEach((char, i) => {
        const at = positionMap[start + i] ?? 0,
          r = p.runs.find((r) => r.start <= at && r.end > at);
        const style = r?.style || {};
        const last = chunks[chunks.length - 1];
        if (
          last &&
          JSON.stringify(last.style) === JSON.stringify(style) &&
          last.protected === !!r?.protected
        )
          last.text += char;
        else chunks.push({ text: char, style, protected: !!r?.protected });
      });
      return chunks.map((c, i) => (
        <span
          key={i}
          style={c.style}
          className={c.protected ? "protected-token" : undefined}
        >
          {c.text}
        </span>
      ));
    };
    const render = (value: string, start: number, kind = "normal") => {
      const end = start + Array.from(value).length;
      const pieces: React.ReactNode[] = [];
      let cursor = start;
      const bounds = [
        ...new Set([
          start,
          ...units
            .flatMap((u) => [u.start, u.end])
            .filter((n) => n > start && n < end),
          end,
        ]),
      ].sort((a, b) => a - b);
      for (let i = 0; i < bounds.length - 1; i++) {
        const a = bounds[i],
          b = bounds[i + 1],
          u = units.find((u) => u.start <= a && u.end > a),
          g = u
            ? p.groups.find((g) =>
                (side === "en" ? g.source_ids : g.target_ids).includes(u.id),
              )
            : undefined;
        const hit = !!u && selected.has(u.id),
          paint = isMapped(p) && g && (hit || colors),
          style: React.CSSProperties = paint
            ? ({
                "--group-color": `var(--c${g.color % 6})`,
              } as React.CSSProperties)
            : {};
        pieces.push(
          <span
            key={`${start}-${i}-${kind}`}
            data-unit={kind === "removed" ? undefined : u?.id}
            className={`sentence ${paint ? "colored" : ""} ${hit ? "focused" : ""} ${kind} ${diff ? "diff-on" : ""}`}
            style={style}
            title={
              g
                ? `对应组 ${p.groups.indexOf(g) + 1} · ${g.kind}${g.source_ids.length > 1 && g.target_ids.length > 1 ? " · 组级对应" : ""}`
                : undefined
            }
            onMouseEnter={() => {
              if (u && isMapped(p) && !dragging.current && !selection)
                setHover({ pid: p.id, side, ids: [u.id] });
            }}
            onMouseLeave={() => {
              if (!selection) setHover(null);
            }}
          >
            {styled(slice(value, a - start, b - start), a)}
          </span>,
        );
        cursor = b;
      }
      return pieces;
    };
    if (diff) {
      let offset = 0;
      const before = side === "en" ? p.originalEn : p.initialZh;
      return (side === "en" ? englishDisplayDiff(before, text) : diffChars(before, text)).map((part, i) => {
        const start = offset;
        if (!part.removed) offset += Array.from(part.value).length;
        return (
          <React.Fragment key={i}>
            {part.removed ? (
              <del className="removed">{part.value}</del>
            ) : (
              render(part.value, start, part.added ? "added" : "normal")
            )}
          </React.Fragment>
        );
      });
    }
    return render(text, 0);
  }
  function openMapping(p: Paragraph) {
    setMapping(p);
    setMapLinks(p.groups.flatMap((g) => g.edges || [g]));
    setMapEn([]);
    setMapZh([]);
    setScope([]);
  }
  async function saveMapping() {
    if (!mapping || !project) return;
    try {
      accept(
        await api(`/projects/${project.id}/paragraphs/${mapping.id}/mapping`, {
          revision: mapping.revision,
          links: mapLinks,
        }),
      );
      setMapping(null);
      toast("映射已保存并校验覆盖范围");
    } catch (e) {
      toast(e);
    }
  }
  async function glossaryImport(file?: File) {
    if (!file || !settings) return;
    try {
      const glossary = parseGlossary(
        (await file.text()).replace(/^\uFEFF/, ""),
        file.name.endsWith(".json"),
      );
      setSettings({ ...settings, glossary });
      toast(`已载入 ${glossary.length} 条术语，保存设置后用于后续请求`);
    } catch (e) {
      toast(e);
    }
  }
  async function configImport(file?: File) {
    if (!file || !project) return;
    try {
      const config = JSON.parse(await file.text());
      const preview = await api(`/projects/${project.id}/config`, {
        config,
        apply: false,
      });
      if (preview.conflicts.length) {
        toast(
          preview.conflicts
            .map((x: any) => `${x.paragraphId}: ${x.reason}`)
            .join("；"),
        );
        return;
      }
      const migrationText = preview.migration?.length
        ? `原文件版本不同，已按唯一精确原文匹配迁移 ${preview.migration.length} 个段落。\n`
        : "";
      if (
        !window.confirm(
          `${migrationText}校验通过，将合并 ${preview.count} 项变更。继续？`,
        )
      )
        return;
      const r = await api(`/projects/${project.id}/config`, {
        config,
        apply: true,
      });
      if (r.project) accept(r.project);
      else toast(JSON.stringify(r.conflicts));
    } catch (e) {
      toast(e);
    }
  }
  async function saveConfig() {
    if (!project) return;
    try {
      for (const id of Object.keys(draftRef.current))
        await saveDraft(id, false);
      await Promise.all(Object.values(saveQueue.current));
      if (Object.keys(draftRef.current).length)
        throw Error("仍有未保存文字，请处理错误后重试");
      const config = await api(`/projects/${project.id}/config`);
      const blob = new Blob([JSON.stringify(config, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob),
        a = document.createElement("a");
      a.href = url;
      a.download = `changes-r${config.revision}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast("项目 JSON 已保存，包含当前中文草稿和映射状态");
    } catch (e) {
      toast(e);
    }
  }
  async function exportWord() {
    if (!project) return;
    setExporting(true);
    try {
      for (const id of Object.keys(draftRef.current))
        await saveDraft(id, false);
      await Promise.all(Object.values(saveQueue.current));
      if (Object.keys(draftRef.current).length)
        throw Error("仍有未保存文字，请先处理保存错误");
      const r = await fetch(`/api/projects/${project.id}/export`);
      if (!r.ok) {
        throw Error((await r.json()).detail);
      }
      const blob = await r.blob(),
        url = URL.createObjectURL(blob),
        a = document.createElement("a");
      a.href = url;
      a.download = `${project.name.replace(/\.docx$/i, "")}_edited_r${r.headers.get("X-Project-Revision")}.docx`;
      a.click();
      URL.revokeObjectURL(url);
      toast("Word 副本已导出，原文件未修改");
    } catch (e) {
      toast(e);
    } finally {
      setExporting(false);
    }
  }
  const ready =
      project?.paragraphs.filter((p) => p.status === "ready" && !p.deleted && p.translationPolicy !== "skip_reference")
        .length || 0,
    pending =
      project?.paragraphs.filter(
        (p) => !["ready", "untranslated"].includes(p.status) && !p.deleted,
      ).length || 0;
    function renderParagraph(p: Paragraph, i: number, side: "en" | "zh", style?: React.CSSProperties) {
                    const running = working.has(p.id) || p.status === "running",
                      canMap = isMapped(p),
                      isEditing = editing === p.id && side === "zh" && p.translationPolicy !== "skip_reference";
                    return (
                      <section
                        key={p.id}
                        data-block={p.id}
                        style={style}
                        onDoubleClick={() => { if(side === "zh" && !p.deleted && p.status !== "untranslated" && p.translationPolicy !== "skip_reference") setEditing(p.id); }}
                        className={`paragraph ${active === p.id ? "active" : ""} ${p.deleted ? "deleted-block" : ""}`}
                        onMouseDown={() => {
                          setActive(p.id);
                          dragging.current = true;
                        }}
                        onMouseUp={(e) => onSelection(p, side, e)}
                      >
                        <div className="paragraph-inner">
                          {side === "zh" && p.modelMeta?.alignmentWarning && p.mappingSource !== "manual" && <div className="translation-alignment-warning" role="status">{p.modelMeta.alignmentWarning}</div>}
                          {side === "zh" && p.modelMeta?.alignmentNotes?.map((note, i) => <div key={i} className="translation-alignment-warning" role="status">对应关系提示：{note}</div>)}
                          {side === "zh" && p.modelMeta?.translationService && <small className="translation-provenance">译文：{p.modelMeta.model} · 对应：{p.mappingSource === "manual" ? "人工修复映射" : p.modelMeta.alignmentMethod === "llm" ? "LLM 句子映射" : "段落级对应"}</small>}
                          <div className="paragraph-label">
                            <span>
                              ¶ {String(i + 1).padStart(2, "0")}{" "}
                              {p.container === "table" && "· 表格"}{" "}
                              {p.inserted && "· 新增"}
                            </span>
                            {side === "zh" ? (
                              <span className={`paragraph-status ${p.status}`}>
                                {running ? (
                                  <LoaderCircle size={12} className="spin" />
                                ) : p.status === "ready" ? (
                                  <Check size={12} />
                                ) : null}
                                {p.deleted ? "已删除" : labels[p.status]}
                              </span>
                            ) : (
                              <span>
                                {p.paragraphStyle === "Normal"
                                  ? "正文"
                                  : p.paragraphStyle}
                              </span>
                            )}
                          </div>
                          {p.deleted ? (
                            <div className="deleted-placeholder">
                              此段已标记删除
                              {diff && (
                                <del>
                                  {side === "en" ? p.originalEn : p.initialZh}
                                </del>
                              )}
                            </div>
                          ) : side === "en" ? (
                            <div className="paragraph-text" tabIndex={0}>
                              {textView(p, side) || (
                                <span className="placeholder">
                                  新增段落的英文将在回写后显示
                                </span>
                              )}
                            </div>
                          ) : p.translationPolicy === "skip_reference" ? (
                            <div className="paragraph-text reference-preserved"><small>参考文献 · 保留英文，不翻译或匹配</small><div>{p.en}</div><button onClick={() => act(p,"translation_policy",{policy:"translate"})}>识别有误？纳入翻译</button></div>
                          ) : p.status === "untranslated" ? (
                            <div className="untranslated">
                              <span>译文将在这里与英文逐段对应</span>
                              <button
                                onClick={() => model(p, "translate_align")}
                                disabled={running}
                              >
                                <Languages size={14} />
                                翻译本段
                              </button>
                            </div>
                          ) : (
                            <>
                              {isEditing ? (
                                <textarea
                                  aria-label={`编辑第 ${i + 1} 段中文`}
                                  autoFocus
                                  value={drafts[p.id] ?? p.draftZh}
                                  onChange={(e) =>
                                    changeDraft(p, e.target.value)
                                  }
                                  onCompositionStart={() => {
                                    composing.current = true;
                                    clearTimeout(timer.current[p.id]);
                                  }}
                                  onCompositionEnd={(e) => {
                                    composing.current = false;
                                    changeDraft(p, e.currentTarget.value);
                                  }}
                                  onKeyDown={(e) => {
                                    if (
                                      e.key === "Enter" &&
                                      !e.nativeEvent.isComposing
                                    ) {
                                      e.preventDefault();
                                      toast(
                                        "段内编辑不新增段落，请使用“＋段落”",
                                      );
                                    }
                                  }}
                                  onPaste={(e) => {
                                    if (
                                      /\r|\n/.test(
                                        e.clipboardData.getData("text"),
                                      )
                                    ) {
                                      e.preventDefault();
                                      toast("粘贴内容包含换行，请分段粘贴");
                                    }
                                  }}
                                  onSelect={(e) => {
                                    if (!canMap) return;
                                    const el = e.currentTarget,
                                      a = cp(el.value, el.selectionStart),
                                      b = cp(el.value, el.selectionEnd);
                                    if (a === b) return;
                                    setSelection({
                                      pid: p.id,
                                      side: "zh",
                                      ids: p.targetUnits
                                        .filter((u) => u.start < b && u.end > a)
                                        .map((u) => u.id),
                                    });
                                  }}
                                />
                              ) : (
                                <div className="paragraph-text" tabIndex={0}>
                                  {p.draftZh !== p.zh ? (
                                    <span>{p.draftZh}</span>
                                  ) : (
                                    textView(p, side)
                                  )}
                                </div>
                              )}
                              {!canMap && p.draftZh !== p.zh && (
                                <div className="inline-note">
                                  中文草稿已变化 ·
                                  对应高亮待更新，左侧保留最近同步版本
                                </div>
                              )}
                              {p.error && (
                                <div className="paragraph-error">
                                  <AlertCircle size={14} />
                                  {p.error}
                                </div>
                              )}
                            </>
                          )}
                          {side === "zh" && p.translationPolicy !== "skip_reference" && (
                            <div className="paragraph-tools">
                              {!p.deleted && p.status !== "untranslated" && (
                                <>
                                  <button
                                    title={
                                      isEditing ? "保存并结束编辑" : "编辑中文"
                                    }
                                    onClick={async () => {
                                      if (isEditing) {
                                        await saveDraft(p.id);
                                        setEditing("");
                                      } else setEditing(p.id);
                                    }}
                                  >
                                    {isEditing ? (
                                      <Check size={14} />
                                    ) : (
                                      <Pencil size={14} />
                                    )}
                                    <span>{isEditing ? "完成" : "编辑"}</span>
                                  </button>
                                  <button
                                    title="立即回写"
                                    onClick={async () => {
                                      await saveDraft(p.id, false);
                                      const current =
                                        projectRef.current?.paragraphs.find(
                                          (x) => x.id === p.id,
                                        );
                                      if (current) model(current, "rewrite_en");
                                    }}
                                    disabled={
                                      running ||
                                      (!drafts[p.id] && p.draftZh === p.zh)
                                    }
                                  >
                                    <RefreshCw size={14} />
                                    <span>回写</span>
                                  </button>
                                  <button
                                    title="映射与回写范围"
                                    onClick={() => openMapping(p)}
                                  >
                                    <Link2 size={14} />
                                    <span>对应关系</span>
                                  </button>
                                </>
                              )}
                              <button
                                title="撤销"
                                onClick={() => act(p, "undo")}
                                disabled={!p.history.length}
                              >
                                <Undo2 size={14} />
                              </button>
                              <button title="将本段识别为参考文献并跳过翻译和匹配" disabled={running || p.deleted} onClick={()=>act(p,"translation_policy",{policy:"skip_reference"})}>跳过参考文献</button>
                              <button
                                title="重做"
                                onClick={() => act(p, "redo")}
                                disabled={!p.redo.length}
                              >
                                <Redo2 size={14} />
                              </button>
                              <button
                                title="新增下一段"
                                onClick={() => act(p, "insert")}
                                disabled={p.container !== "body" || p.deleted}
                              >
                                <Plus size={14} />
                                <span>段落</span>
                              </button>
                              <button
                                title={p.deleted ? "恢复段落" : "删除段落"}
                                onClick={() => act(p, "delete")}
                                disabled={
                                  !!p.protected.length ||
                                  p.hasSection ||
                                  p.container !== "body"
                                }
                              >
                                <Trash2 size={14} />
                              </button>
                              {!p.deleted && (
                                <select
                                  title="新增／替换文字的格式继承"
                                  value={p.stylePolicy || ""}
                                  onChange={(e) =>
                                    act(p, "style", {
                                      policy: e.target.value || null,
                                    })
                                  }
                                >
                                  <option value="">格式自动匹配</option>
                                  <option value="left">歧义时继承左侧</option>
                                  <option value="right">歧义时继承右侧</option>
                                </select>
                              )}
                            </div>
                          )}
                        </div>
                      </section>
                    );

  }

  function renderDocument(side: "en" | "zh") {
    if (!project) return null;
    if (!project.layout?.length) return project.paragraphs.map((p, i) => renderParagraph(p, i, side));
    const seen = new Set<string>();
    const renderNodes = (nodes: LayoutNode[]): React.ReactNode => nodes.map((node, n) => {
      if (node.type === "paragraph") {
        const i = project.paragraphs.findIndex(p => p.id === node.id);
        if (i < 0) return null;
        seen.add(node.id);
        const following: React.ReactNode[] = [];
        for(let j=i+1;j<project.paragraphs.length && project.paragraphs[j].inserted;j++) {
          const p=project.paragraphs[j]; seen.add(p.id); following.push(renderParagraph(p,j,side));
        }
        return <React.Fragment key={node.id}>{renderParagraph(project.paragraphs[i],i,side,node.style)}{following}</React.Fragment>;
      }
      return <div className="document-table-wrap" key={node.id || n}><table className="document-table" aria-label="文稿表格">
        {node.columnWidths && <colgroup>{node.columnWidths.map((w,i)=><col key={i} style={{width:`${w / node.columnWidths!.reduce((a,b)=>a+b,0)*100}%`}} />)}</colgroup>}
        <tbody>{node.rows.map((row,r)=><tr key={r}>{row.cells.map((cell,c)=><td key={c} colSpan={cell.colSpan || 1} rowSpan={cell.rowSpan || 1} style={{...cell.style, ...(cell.omitted ? {border:"none"} : {})}}>{renderNodes(cell.blocks)}</td>)}</tr>)}</tbody>
      </table></div>;
    });
    const content=renderNodes(project.layout);
    return <>{content}{project.paragraphs.filter(p=>!seen.has(p.id)).map(p=>renderParagraph(p,project.paragraphs.indexOf(p),side))}</>;
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brandmark">
            <ArrowLeftRight size={22} />
          </span>
          <div>
            纸桥 <small>PaperBridge</small>
          </div>
        </div>
        <div className="workspace-label">
          我的工作台 <span>LOCAL</span>
        </div>
        <button
          className="import-btn"
          onClick={() => fileInput.current?.click()}
        >
          <Plus size={17} />
          导入 Word 论文
        </button>
        <div className="sidebar-section">
          文档 <span>{projects.length}</span>
        </div>
        <nav>
          {projects.map((p) => (
            <button
              className={`doc-nav ${p.id === project?.id ? "selected" : ""}`}
              key={p.id}
              onClick={() => open(p.id)}
            >
              <FileText size={17} />
              <span>
                {p.name}
                <small>本地项目 · r{p.revision}</small>
              </span>
            </button>
          ))}
        </nav>
        {project && (
          <>
            <div className="sidebar-section">
              正文导航 <span>{project.paragraphs.length}</span>
            </div>
            <div className="paragraph-nav">
              {project.paragraphs.filter(p => p.container !== "table").map((p, i) => (
                <button
                  key={p.id}
                  className={active === p.id ? "active" : ""}
                  onClick={() => locate(p.id)}
                >
                  <span className={`dot ${p.deleted ? "deleted" : p.status}`} />
                  <span>{String(i + 1).padStart(2, "0")}</span>
                  <span>
                    {p.deleted
                      ? "已删除"
                      : p.en.replace(/⟦.*?⟧/g, "▧").slice(0, 26) || "新增段落"}
                  </span>
                </button>
              ))}
            </div>
          </>
        )}
        <div className="sidebar-bottom">
          <span className="online-dot" /> 本地存储 · 原文件只读
          <button onClick={() => setSettingsOpen(true)}>
            <Settings size={17} />
            模型与术语设置
          </button>
        </div>
      </aside>
      <main>
        <header>
          <div>
            <div className="breadcrumb">
              工作台 <span>/</span> 双语论文编辑
            </div>
            <h1>
              {project
                ? project.name.replace(/\.docx$/i, "")
                : "让理解与修改，在两种语言间同步。"}
            </h1>
          </div>
          <button
            className="icon-btn"
            title="模型设置"
            onClick={() => setSettingsOpen(true)}
          >
            <Settings size={19} />
          </button>
        </header>
        {!project ? (
          <div className="welcome">
            <div className="welcome-icon">
              <BookOpen size={42} />
            </div>
            <span className="eyebrow">READ · REFINE · TRACE</span>
            <h2>从一篇 Word 论文开始</h2>
            <p>
              左边读原文，右边改中文。
              <br />
              逐句关联、局部英文回写，每次修改都有迹可循。
            </p>
            <button
              className="primary"
              onClick={() => fileInput.current?.click()}
              disabled={busy}
            >
              <Upload size={18} />
              选择 .docx 文件
            </button>
            <div className="features">
              <span>
                <Link2 />
                句子级对应
              </span>
              <span>
                <Highlighter />
                变更追踪
              </span>
              <span>
                <FileText />
                保留原始样式
              </span>
            </div>
            <small>文稿保存在本机 · 模型通过你配置的接口调用</small>
          </div>
        ) : (
          <>
            <div className="document-bar">
              <div className="document-status">
                <span className="status-pill">
                  <span className="online-dot" />
                  本地项目
                </span>
                <span>
                  {ready} / {project.paragraphs.filter(p=>!p.deleted && p.translationPolicy !== "skip_reference").length} 段已同步 · {project.paragraphs.filter(p=>p.translationPolicy === "skip_reference").length} 段参考文献保留
                </span>
                {pending > 0 && (
                  <span className="warning-text">{pending} 段待处理</span>
                )}
              </div>
              <div className="actions">
                <button onClick={() => configInput.current?.click()}>
                  <FolderOpen size={15} />
                  导入 config
                </button>
                <button className="button" onClick={saveConfig}>
                  <Save size={15} />
                  保存项目 JSON
                </button>
                <button
                  className="primary"
                  onClick={exportWord}
                  disabled={exporting}
                >
                  <Download size={16} />
                  {exporting ? "检查并导出…" : "导出 Word"}
                </button>
              </div>
            </div>
            <div className="toolbar">
              <div className="toolbar-group">
                <button
                  className="translate"
                  onClick={translateAll}
                  disabled={busy || ["running", "stopping"].includes(project.retranslation?.status || "")}
                >
                  <Languages size={17} />
                  {busy ? "翻译进行中…" : "翻译未处理段落"}
                </button>
                <button onClick={retranslateAll} disabled={busy || ["running", "stopping"].includes(project.retranslation?.status || "")} title="创建新版本，重新翻译并建立句子映射"><RefreshCw size={15} />重新翻译全文</button>
                {busy && (
                  <button
                    onClick={() => {
                      batchStop.current = true;
                    }}
                  >
                    停止后续
                  </button>
                )}
                <span className="divider" />
                <label>
                  <input
                    type="checkbox"
                    checked={auto}
                    onChange={(e) => setAuto(e.target.checked)}
                  />
                  自动回写
                </label>
              </div>
              <div className="toolbar-group">
                <label>
                  <input
                    type="checkbox"
                    checked={diff}
                    onChange={(e) => setDiff(e.target.checked)}
                  />
                  差异视图
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={colors}
                    onChange={(e) => setColors(e.target.checked)}
                  />
                  全部对应着色
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={original}
                    onChange={(e) => setOriginal(e.target.checked)}
                  />
                  最初英文
                </label>
              </div>
            </div>
            {project.retranslation && <div className="retranslation-progress" role="status">
              <strong>全文重译 · {project.retranslation.status === "running" ? (project.retranslation.stopRequested ? "完成当前段后暂停" : "翻译中") : project.retranslation.status === "stopping" ? "完成当前段后暂停" : project.retranslation.status === "completed" ? "已完成" : project.retranslation.status === "completed_with_errors" ? "已结束，部分段落需重试" : "已暂停／待处理"}</strong>
              <span>{project.retranslation.completed} / {project.retranslation.total} 段 · {project.retranslation.skipped || 0} 段参考文献跳过 · {project.retranslation.failed} 段失败 · {project.retranslation.model}</span>
              {["running", "stopping"].includes(project.retranslation.status) ? <button disabled={project.retranslation.status === "stopping" || project.retranslation.stopRequested} onClick={() => retranslationAction("stop")}>暂停后续</button> : project.retranslation.status !== "completed" && <button onClick={() => retranslationAction("resume")}>继续／重试未完成</button>}
              {project.retranslation.error && <span className="warning-text">{project.retranslation.error}</span>}
            </div>}
            <div className="word-preview-links"><div className="native-mode-switch"><button className={nativeView ? "selected" : ""} onClick={() => setNativeView(true)}>Word 原生版面</button><button className={!nativeView ? "selected" : ""} onClick={() => setNativeView(false)}>结构编辑</button></div><a href={`/api/projects/${project.id}/preview?original=true`} target="_blank" rel="noreferrer">原稿版面 ↗</a><a href={`/api/projects/${project.id}/preview?original=false`} target="_blank" rel="noreferrer">当前英文版面 ↗</a><small>{nativeView ? "双侧 Word 排版 · 点击句子在中文原位编辑" : "结构视图 · 双击中文编辑"}</small></div>
            <div className="column-heads">
              <div>
                <span className="language-tag">EN</span>
                <strong>{original ? "英文原文" : "英文 · 当前版本"}</strong>
                <span>只读预览</span>
              </div>
              <div>
                <span className="language-tag zh">中</span>
                <strong>中文 · 编辑区</strong>
                <span>
                  <Link2 size={13} />
                  段落锚点同步
                </span>
              </div>
            </div>
            <div className="panes">
              {(["en", "zh"] as const).map((side) => (
                <div
                  className={`pane ${side}`}
                  key={side}
                  ref={side === "en" ? left : right}
                  tabIndex={0}
                  onPointerMove={(event) => pointerMoved(side === "en" ? "left" : "right", event)}
                  onPointerLeave={() => cancelPointerAlignment(true)}
                  onPointerDown={() => cancelPointerAlignment(true)}
                  onScroll={() => {
                    const source = side === "en" ? "left" : "right";
                    if (pointerSource.current?.side === source) schedulePointerAlignment(source);
                  }}
                >
                  {nativeView ? <NativePages diff={diff} stateKey={project.paragraphs.map(p=>`${p.id}:${p.revision}:${p.status}`).join("|")} projectId={project.id} revision={project.revision} original={side === "en" && original} language={side} active={active} editing={editing} highlighted={(selection || hover)?.pid || null} onSelect={(id) => {
                    scrollOwner.current = null; setActive(id); const p = project.paragraphs.find(p => p.id === id);
                    if (p && !p.deleted && p.status !== "untranslated" && p.translationPolicy !== "skip_reference") setEditing(id);
                  }} onHover={(id, unit) => {
                    const p = project.paragraphs.find(p => p.id === id);
                    if (!selection) setHover(p && isMapped(p) && !(side === "en" && original && p.en !== p.originalEn) ? {pid:p.id,side,ids:unit ? [unit] : (side === "en" ? p.units : p.targetUnits).map(u=>u.id)} : null);
                  }} unitStyle={(pid, uid) => {
                    const p=project.paragraphs.find(p=>p.id===pid);
                    if(!p || !isMapped(p) || (side === "en" && original && p.en !== p.originalEn)) return {focused:false};
                    const g=p.groups.find(g=>(side === "en" ? g.source_ids : g.target_ids).includes(uid));
                    const focused=targets(p,side).has(uid);
                    return {focused,color:g && (colors || focused) ? g.color : undefined};
                  }} renderEditor={(pid)=>{const p=project.paragraphs.find(p=>p.id===pid);return p ? renderParagraph(p,project.paragraphs.indexOf(p),"zh") : null;}} onClose={()=>setEditing("")}/> : <div className="document-sheet">{renderDocument(side)}</div>}
                </div>
              ))}
            </div>
            <footer>
              <span>
                <Link2 size={13} />
                {nativeView ? "鼠标所指段落驱动对侧定位 · 中文原位编辑" : "鼠标所指段落驱动对侧定位 · 段内拖选联动高亮"}
              </span>
              <span>
                {Object.keys(drafts).length ? "文字保存中…" : "草稿保存在本机"}{" "}
                · r{project.revision}
              </span>
            </footer>
          </>
        )}
      </main>
      <input
        type="file"
        accept=".docx"
        hidden
        ref={fileInput}
        onChange={(e) => {
          upload(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <input
        type="file"
        accept=".json"
        hidden
        ref={configInput}
        onChange={(e) => {
          configImport(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      {notice && (
        <div className="toast" role="status">
          <AlertCircle size={17} />
          {notice}
          <button onClick={() => setNotice("")}>
            <X size={15} />
          </button>
        </div>
      )}
      {settingsOpen && settings && <ModelSettings value={settings} onChange={setSettings} onClose={()=>setSettingsOpen(false)} onImport={glossaryImport}/> }
      {mapping && (
        <div className="overlay">
          <div className="modal mapping-modal">
            <div className="modal-heading">
              <div>
                <span className="eyebrow">ALIGNMENT REVIEW</span>
                <h2>对应关系 · {mapping.id}</h2>
              </div>
              <button onClick={() => setMapping(null)}>
                <X />
              </button>
            </div>
            <p className="muted">
              以下是最近同步版本的映射。选中两侧句子建立关系，所有句子必须被覆盖。中文草稿待回写时，不能将它误当成已同步译文。
            </p>
            <div className="mapping-columns">
              <div>
                <h3>英文</h3>
                {mapping.units.map((u) => (
                  <label key={u.id} className="unit-choice">
                    <input
                      type="checkbox"
                      checked={mapEn.includes(u.id)}
                      onChange={(e) =>
                        setMapEn(
                          e.target.checked
                            ? [...mapEn, u.id]
                            : mapEn.filter((x) => x !== u.id),
                        )
                      }
                    />
                    <span>
                      <small>{u.id}</small>
                      {u.text}
                    </span>
                  </label>
                ))}
              </div>
              <div>
                <h3>中文</h3>
                {mapping.targetUnits.map((u) => (
                  <label key={u.id} className="unit-choice">
                    <input
                      type="checkbox"
                      checked={mapZh.includes(u.id)}
                      onChange={(e) =>
                        setMapZh(
                          e.target.checked
                            ? [...mapZh, u.id]
                            : mapZh.filter((x) => x !== u.id),
                        )
                      }
                    />
                    <span>
                      <small>{u.id}</small>
                      {u.text}
                    </span>
                  </label>
                ))}
              </div>
            </div>
            <button
              disabled={!mapEn.length || !mapZh.length}
              onClick={() => {
                setMapLinks([
                  ...mapLinks,
                  { source_ids: mapEn, target_ids: mapZh },
                ]);
                setMapEn([]);
                setMapZh([]);
              }}
            >
              <Link2 size={15} />
              添加选中对应关系
            </button>
            <div className="links-list">
              {mapLinks.map((g, i) => (
                <div key={i}>
                  <span>
                    {g.source_ids.join(", ")} <ArrowRight size={12} />{" "}
                    {g.target_ids.join(", ")}
                  </span>
                  <button
                    onClick={() =>
                      setMapLinks(mapLinks.filter((_, j) => j !== i))
                    }
                  >
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
            <div className="modal-actions">
              <button
                onClick={() => {
                  model(mapping, "repair_alignment");
                  setMapping(null);
                }}
              >
                让模型修复现有映射
              </button>
              <button className="primary" onClick={saveMapping}>
                校验并保存映射
              </button>
            </div>
            {mapping.draftZh !== mapping.zh && (
              <div className="scope-box">
                <h3>明确本次英文回写范围</h3>
                <p className="muted">
                  仅当局部映射有歧义时使用。所选句子允许改写，其余英文保持原样。
                </p>
                {mapping.units.map((u) => (
                  <label key={u.id} className="unit-choice">
                    <input
                      type="checkbox"
                      checked={scope.includes(u.id)}
                      onChange={(e) =>
                        setScope(
                          e.target.checked
                            ? [...scope, u.id]
                            : scope.filter((x) => x !== u.id),
                        )
                      }
                    />
                    {u.text}
                  </label>
                ))}
                <button
                  disabled={!scope.length}
                  onClick={() => {
                    model(mapping, "rewrite_en", scope);
                    setMapping(null);
                  }}
                >
                  在所选范围内回写
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
