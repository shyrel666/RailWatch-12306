import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Input, Modal } from "antd";
import { ArrowUp, FileText, Folder, FolderOpen } from "lucide-react";
import { railwatchApi } from "../lib/railwatchApi";
import type { ExportDirectory, ExportLocation } from "../types";

export function useExportLogDialog() {
  const [request, setRequest] = useState<{ defaultPath?: string; open: boolean } | null>(null);
  const pending = useRef<{ promise: Promise<string | null>; resolve: (path: string | null) => void } | null>(null);
  const choosePath = useCallback((defaultPath?: string) => {
    if (pending.current) return pending.current.promise;
    let resolve!: (path: string | null) => void;
    const promise = new Promise<string | null>(done => { resolve = done; });
    pending.current = { promise, resolve };
    setRequest({ defaultPath, open: true });
    return promise;
  }, []);
  const finish = useCallback((path: string | null) => {
    pending.current?.resolve(path);
    pending.current = null;
    setRequest(current => current ? { ...current, open: false } : null);
  }, []);
  useEffect(() => () => { pending.current?.resolve(null); pending.current = null; }, []);
  return {
    choosePath,
    dialog: request ? <ExportLogDialog open={request.open} defaultPath={request.defaultPath} onFinish={finish}
      afterClose={() => setRequest(current => current?.open ? current : null)} /> : null,
  };
}

function ExportLogDialog({ open, defaultPath, onFinish, afterClose }: {
  open: boolean; defaultPath?: string; onFinish: (path: string | null) => void; afterClose: () => void;
}) {
  const [shortcuts, setShortcuts] = useState<ExportLocation[]>([]);
  const [listing, setListing] = useState<ExportDirectory | null>(null);
  const [directory, setDirectory] = useState("");
  const [fileName, setFileName] = useState("railwatch-events.txt");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const revision = useRef(0);
  const alive = useRef(true);
  const savingRef = useRef(false);
  const browse = useCallback(async (path: string) => {
    const current = ++revision.current;
    setLoading(true);
    setError("");
    setDirectory(path);
    setListing(null);
    try {
      const next = await railwatchApi.listExportDirectory(path);
      if (alive.current && revision.current === current) {
        setListing(next);
        setDirectory(next.directory);
      }
    } catch {
      if (alive.current && revision.current === current) setError("无法读取该文件夹，请检查路径和访问权限，或选择其他位置。");
    } finally {
      if (alive.current && revision.current === current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    if (!open) return;
    alive.current = true;
    let current = true;
    void railwatchApi.getExportLocations(defaultPath).then(value => {
      if (!current) return;
      setShortcuts(value.shortcuts);
      setFileName(value.fileName);
      void browse(value.directory);
    }).catch(() => {
      if (current) { setLoading(false); setError("无法读取默认保存位置，请输入完整的文件夹路径。"); }
    });
    return () => { current = false; alive.current = false; revision.current++; };
  }, [open, defaultPath, browse]);
  const save = async () => {
    if (savingRef.current || loading || !listing || directory !== listing.directory || !fileName.trim()) return;
    savingRef.current = true;
    setSaving(true);
    setError("");
    try {
      const target = await railwatchApi.prepareLogExport(listing.directory, fileName);
      if (alive.current && target) onFinish(target);
    } catch (cause) {
      if (alive.current) setError(cause instanceof Error ? cause.message : "无法保存到该位置。");
    } finally {
      savingRef.current = false;
      if (alive.current) setSaving(false);
    }
  };
  return <Modal open={open} afterClose={afterClose} centered title={<span className="dialog-title"><FolderOpen size={18} />导出事件日志</span>}
    className="railwatch-dialog export-dialog" width={640} mask={{ closable: false }}
    closable={!saving} keyboard={!saving} onCancel={() => onFinish(null)}
    footer={<><Button disabled={saving} onClick={() => onFinish(null)}>取消</Button>
      <Button type="primary" aria-label="导出日志" loading={saving} disabled={saving || loading || !listing || directory !== listing.directory || !fileName.trim()} onClick={() => void save()}>导出日志</Button></>}>
    <div className="export-picker">
      <div className="button-row" aria-label="常用保存位置">
        {shortcuts.map((item, index) => <Button key={index} size="small" disabled={saving} onClick={() => void browse(item.path)}>{item.name}</Button>)}
      </div>
      <div className="export-location-bar">
        <Button icon={<ArrowUp size={15} />} aria-label="上一级文件夹" disabled={saving || loading || !listing || listing.parent === listing.directory}
          onClick={() => listing && void browse(listing.parent)} />
        <Input aria-label="保存文件夹" value={directory} disabled={saving}
          onChange={event => { revision.current++; setLoading(false); setDirectory(event.target.value); }}
          onPressEnter={() => void browse(directory)} />
        <Button aria-label="前往" disabled={saving || !directory.trim()} onClick={() => void browse(directory)}>前往</Button>
      </div>
      <div className="export-folder-list" aria-label="保存位置内容" aria-busy={loading}>
        {loading ? <p role="status">正在读取文件夹…</p> : listing && directory === listing.directory ? <>
          {listing.folders.map(item => <button type="button" key={item.path} disabled={saving} onClick={() => void browse(item.path)}><Folder size={16} /><span>{item.name}</span><small>文件夹</small></button>)}
          {listing.files.map(name => <button type="button" key={name} disabled={saving} onClick={() => setFileName(name)}><FileText size={16} /><span>{name}</span><small>文本文件</small></button>)}
          {!listing.folders.length && !listing.files.length ? <p>此文件夹中没有子文件夹或文本文件，可直接保存。</p> : null}
        </> : <p>输入文件夹路径后点击“前往”，或选择上方的常用位置。</p>}
      </div>
      <label className="field"><span>文件名</span><Input value={fileName} disabled={saving} onChange={event => setFileName(event.target.value)} onPressEnter={() => void save()} /></label>
      <small>保存为文本文件（.txt），包含当前保留的完整事件日志。</small>
      {error ? <p role="alert" className="dialog-error">{error}</p> : null}
    </div>
  </Modal>;
}
