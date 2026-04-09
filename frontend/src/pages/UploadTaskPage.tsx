import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";
import "./upload-task.css";

type ErrorPayload = {
  code: string;
  message: string;
};

type ResponseEnvelope<T> = {
  success: boolean;
  data: T | null;
  error: ErrorPayload | null;
};

type FileItem = {
  file_id: string;
  user_id: string;
  file_name: string;
  file_ext: string;
  content_type: string;
  file_size: number;
  storage_path: string;
  parse_status: string;
  is_searchable: boolean;
  task_id: string;
  error_code?: string | null;
  error_message?: string | null;
  doc_version: number;
  created_at: string;
  updated_at: string;
};

type TaskItem = {
  task_id: string;
  user_id: string;
  file_id: string;
  task_type: string;
  task_status: string;
  progress: number;
  current_stage: string;
  error_code?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  updated_at: string;
};

type UploadResultItem = {
  file_name: string;
  status: "accepted" | "rejected";
  file?: FileItem | null;
  task?: TaskItem | null;
  error_code?: string | null;
  error_message?: string | null;
};

type UploadBatchResponse = {
  items: UploadResultItem[];
  accepted_count: number;
  rejected_count: number;
};

type FileListResponse = {
  items: FileItem[];
};

const TERMINAL_STAGES = new Set(["success", "failed"]);

function defaultApiBaseUrl() {
  return `${window.location.protocol}//${window.location.hostname}:8000/api`;
}

function formatBytes(size: number) {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(value: string | null | undefined) {
  if (!value) {
    return "未开始";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(new Date(value));
}

function stageLabel(stage: string) {
  const mapping: Record<string, string> = {
    queued: "排队中",
    parsing: "解析中",
    chunking: "切块中",
    embedding: "向量化中",
    success: "已完成",
    failed: "失败"
  };
  return mapping[stage] ?? stage;
}

function stageTone(stage: string) {
  if (stage === "failed") {
    return "failed";
  }
  if (stage === "success") {
    return "success";
  }
  if (stage === "queued") {
    return "queued";
  }
  return "working";
}

function dedupeFiles(incoming: File[], current: File[]) {
  const seen = new Set(current.map((file) => `${file.name}:${file.size}:${file.lastModified}`));
  const next = [...current];
  for (const file of incoming) {
    const key = `${file.name}:${file.size}:${file.lastModified}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    next.push(file);
  }
  return next;
}

async function requestApi<T>(baseUrl: string, token: string, path: string, init?: RequestInit) {
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${token}`
    }
  });

  let payload: ResponseEnvelope<T> | null = null;
  try {
    payload = (await response.json()) as ResponseEnvelope<T>;
  } catch {
    throw new Error(`请求失败：${response.status}`);
  }

  if (!response.ok || !payload.success || payload.data === null) {
    throw new Error(payload.error?.message ?? `请求失败：${response.status}`);
  }
  return payload.data;
}

function UploadTaskPage() {
  const [apiBaseUrl, setApiBaseUrl] = useState(() => localStorage.getItem("fileman-api-base") ?? defaultApiBaseUrl());
  const [token, setToken] = useState(() => localStorage.getItem("fileman-token") ?? "change-me-admin-token");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [files, setFiles] = useState<FileItem[]>([]);
  const [tasksById, setTasksById] = useState<Record<string, TaskItem>>({});
  const [batchResults, setBatchResults] = useState<UploadResultItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [loadingFiles, setLoadingFiles] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    localStorage.setItem("fileman-api-base", apiBaseUrl);
  }, [apiBaseUrl]);

  useEffect(() => {
    localStorage.setItem("fileman-token", token);
  }, [token]);

  useEffect(() => {
    let cancelled = false;

    async function loadFiles() {
      if (!token.trim()) {
        setFiles([]);
        setTasksById({});
        setLoadingFiles(false);
        return;
      }

      setLoadingFiles(true);
      setPageError(null);
      try {
        const data = await requestApi<FileListResponse>(apiBaseUrl, token, "/files");
        if (cancelled) {
          return;
        }
        setFiles(data.items);
        setLastSyncedAt(new Date().toISOString());
      } catch (error) {
        if (cancelled) {
          return;
        }
        setPageError(error instanceof Error ? error.message : "文件列表加载失败");
      } finally {
        if (!cancelled) {
          setLoadingFiles(false);
        }
      }
    }

    void loadFiles();
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, token]);

  useEffect(() => {
    if (!token.trim()) {
      return;
    }

    const activeFiles = files.filter((file) => !TERMINAL_STAGES.has(file.parse_status));
    if (activeFiles.length === 0) {
      return;
    }

    let cancelled = false;

    async function pollActiveTasks() {
      try {
        const taskResults = await Promise.all(
          activeFiles.map(async (file) => {
            const task = await requestApi<TaskItem>(apiBaseUrl, token, `/tasks/${file.task_id}`);
            return [file.task_id, task] as const;
          })
        );

        if (cancelled) {
          return;
        }

        setTasksById((current) => {
          const next = { ...current };
          for (const [taskId, task] of taskResults) {
            next[taskId] = task;
          }
          return next;
        });

        const refreshed = await requestApi<FileListResponse>(apiBaseUrl, token, "/files");
        if (cancelled) {
          return;
        }
        setFiles(refreshed.items);
        setLastSyncedAt(new Date().toISOString());
      } catch (error) {
        if (!cancelled) {
          setPageError(error instanceof Error ? error.message : "任务轮询失败");
        }
      }
    }

    void pollActiveTasks();
    const timer = window.setInterval(() => {
      void pollActiveTasks();
    }, 1200);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [apiBaseUrl, token, files]);

  const handleFileSelection = (nextFiles: File[]) => {
    setSelectedFiles((current) => dedupeFiles(nextFiles, current));
  };

  const openFilePicker = () => {
    fileInputRef.current?.click();
  };

  const onInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    handleFileSelection(Array.from(event.target.files ?? []));
    event.target.value = "";
  };

  const removeSelectedFile = (fileToRemove: File) => {
    setSelectedFiles((current) =>
      current.filter(
        (file) =>
          !(
            file.name === fileToRemove.name &&
            file.size === fileToRemove.size &&
            file.lastModified === fileToRemove.lastModified
          )
      )
    );
  };

  const onDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    setDragActive(false);
    handleFileSelection(Array.from(event.dataTransfer.files));
  };

  const uploadFiles = async () => {
    if (selectedFiles.length === 0 || uploading) {
      return;
    }

    setUploading(true);
    setUploadError(null);
    setPageError(null);

    const formData = new FormData();
    for (const file of selectedFiles) {
      formData.append("files", file);
    }

    try {
      const data = await requestApi<UploadBatchResponse>(apiBaseUrl, token, "/files/upload", {
        method: "POST",
        body: formData
      });
      setBatchResults(data.items);
      setSelectedFiles([]);
      const refreshed = await requestApi<FileListResponse>(apiBaseUrl, token, "/files");
      setFiles(refreshed.items);
      setLastSyncedAt(new Date().toISOString());
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "上传失败");
    } finally {
      setUploading(false);
    }
  };

  const totalFiles = files.length;
  const searchableFiles = files.filter((file) => file.is_searchable).length;
  const activeFiles = files.filter((file) => !TERMINAL_STAGES.has(file.parse_status)).length;
  const failedFiles = files.filter((file) => file.parse_status === "failed").length;

  return (
    <div className="upload-page">
      <div className="upload-ambient upload-ambient-left" />
      <div className="upload-ambient upload-ambient-right" />

      <header className="upload-hero">
        <div className="upload-hero-copy">
          <p className="upload-eyebrow">File Intake Console</p>
          <h1>上传与任务追踪现在是独立子页面。</h1>
          <p className="upload-hero-text">
            这里专门处理文件上传、批量校验、任务轮询、失败原因和可检索状态，不再侵入主页面。
          </p>
        </div>

        <div className="upload-hero-metrics">
          <article className="upload-metric-card">
            <span>文件总数</span>
            <strong>{totalFiles}</strong>
          </article>
          <article className="upload-metric-card">
            <span>处理中</span>
            <strong>{activeFiles}</strong>
          </article>
          <article className="upload-metric-card">
            <span>可检索</span>
            <strong>{searchableFiles}</strong>
          </article>
          <article className="upload-metric-card">
            <span>失败</span>
            <strong>{failedFiles}</strong>
          </article>
        </div>
      </header>

      <main className="upload-dashboard-grid">
        <section className="upload-panel upload-control-panel">
          <div className="upload-panel-head">
            <div>
              <p className="upload-panel-kicker">连接配置</p>
              <h2>上传入口</h2>
            </div>
            <span className="upload-panel-note">Bearer 鉴权</span>
          </div>

          <div className="upload-field-grid">
            <label className="upload-field">
              <span>API Base</span>
              <input value={apiBaseUrl} onChange={(event) => setApiBaseUrl(event.target.value)} />
            </label>
            <label className="upload-field">
              <span>Token</span>
              <input value={token} onChange={(event) => setToken(event.target.value)} type="password" />
            </label>
          </div>

          <div
            className={`upload-dropzone ${dragActive ? "drag-active" : ""}`}
            onDragEnter={(event) => {
              event.preventDefault();
              setDragActive(true);
            }}
            onDragOver={(event) => {
              event.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={(event) => {
              event.preventDefault();
              if (event.currentTarget === event.target) {
                setDragActive(false);
              }
            }}
            onDrop={onDrop}
          >
            <input ref={fileInputRef} className="upload-hidden-input" multiple type="file" onChange={onInputChange} />
            <p className="upload-dropzone-badge">支持 Word / Excel / PDF / PPT / TXT / Markdown / JPG / PNG</p>
            <h3>拖拽文件到这里，或者直接挑选一批上传。</h3>
            <p className="upload-dropzone-text">单文件上限 50MB，单次最多 5 个。非法文件会在本批次里单独标红，不会阻塞其他文件。</p>
            <div className="upload-dropzone-actions">
              <button className="upload-ghost-button" type="button" onClick={openFilePicker}>
                选择文件
              </button>
              <button className="upload-primary-button" type="button" onClick={uploadFiles} disabled={selectedFiles.length === 0 || uploading}>
                {uploading ? "上传中..." : `上传 ${selectedFiles.length || ""}`.trim()}
              </button>
            </div>
          </div>

          <section className="upload-subsection">
            <div className="upload-subsection-head">
              <h3>待上传队列</h3>
              <span>{selectedFiles.length} 个文件</span>
            </div>

            {selectedFiles.length === 0 ? (
              <div className="upload-empty-card">还没有选择文件。</div>
            ) : (
              <div className="upload-selected-list">
                {selectedFiles.map((file) => (
                  <article className="upload-selected-card" key={`${file.name}:${file.size}:${file.lastModified}`}>
                    <div>
                      <strong>{file.name}</strong>
                      <p>
                        {formatBytes(file.size)} · {file.type || "unknown"}
                      </p>
                    </div>
                    <button type="button" className="upload-remove-button" onClick={() => removeSelectedFile(file)}>
                      移除
                    </button>
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="upload-subsection">
            <div className="upload-subsection-head">
              <h3>最近上传结果</h3>
              <span>{batchResults.length} 条</span>
            </div>

            {batchResults.length === 0 ? (
              <div className="upload-empty-card">上传后会在这里显示本批次的接收与拒绝结果。</div>
            ) : (
              <div className="upload-batch-result-list">
                {batchResults.map((item) => (
                  <article className={`upload-batch-result-card ${item.status}`} key={`${item.file_name}:${item.status}`}>
                    <div>
                      <strong>{item.file_name || "未命名文件"}</strong>
                      <p>{item.status === "accepted" ? "已创建任务，进入排队" : item.error_message ?? "上传被拒绝"}</p>
                    </div>
                    <span className={`upload-status-pill ${item.status === "accepted" ? "success" : "failed"}`}>
                      {item.status === "accepted" ? "已接收" : "已拒绝"}
                    </span>
                  </article>
                ))}
              </div>
            )}
          </section>

          {uploadError ? <div className="upload-alert upload-alert-error">{uploadError}</div> : null}
          {pageError ? <div className="upload-alert upload-alert-error">{pageError}</div> : null}
        </section>

        <section className="upload-panel upload-status-panel">
          <div className="upload-panel-head">
            <div>
              <p className="upload-panel-kicker">任务跟踪</p>
              <h2>文件处理状态</h2>
            </div>
            <span className="upload-panel-note">{lastSyncedAt ? `最近同步 ${formatTime(lastSyncedAt)}` : "等待首次同步"}</span>
          </div>

          {loadingFiles ? <div className="upload-empty-card">正在加载文件列表...</div> : null}
          {!loadingFiles && files.length === 0 ? <div className="upload-empty-card">当前 filespace 还没有文件。</div> : null}

          <div className="upload-status-list">
            {files
              .slice()
              .sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime())
              .map((file) => {
                const task = tasksById[file.task_id];
                const stage = task?.current_stage ?? file.parse_status;
                const progress = task?.progress ?? (file.parse_status === "success" ? 100 : 0);
                const errorMessage = task?.error_message ?? file.error_message ?? null;

                return (
                  <article className="upload-status-card" key={file.file_id}>
                    <div className="upload-status-card-top">
                      <div>
                        <div className="upload-file-title-row">
                          <strong>{file.file_name}</strong>
                          <span className={`upload-status-pill ${stageTone(stage)}`}>{stageLabel(stage)}</span>
                          {file.is_searchable ? <span className="upload-searchable-chip">可检索</span> : null}
                        </div>
                        <p className="upload-file-meta">
                          {formatBytes(file.file_size)} · {file.file_ext} · task {file.task_id.slice(0, 8)}
                        </p>
                      </div>
                      <div className="upload-progress-copy">
                        <strong>{progress}%</strong>
                        <span>{stageLabel(stage)}</span>
                      </div>
                    </div>

                    <div className="upload-progress-rail" aria-hidden="true">
                      <div className={`upload-progress-fill ${stageTone(stage)}`} style={{ width: `${progress}%` }} />
                    </div>

                    <div className="upload-status-meta-grid">
                      <div>
                        <span>创建时间</span>
                        <strong>{formatTime(file.created_at)}</strong>
                      </div>
                      <div>
                        <span>启动时间</span>
                        <strong>{formatTime(task?.started_at)}</strong>
                      </div>
                      <div>
                        <span>完成时间</span>
                        <strong>{formatTime(task?.finished_at)}</strong>
                      </div>
                      <div>
                        <span>当前阶段</span>
                        <strong>{task?.current_stage ?? file.parse_status}</strong>
                      </div>
                    </div>

                    {errorMessage ? <div className="upload-alert upload-inline-error">{errorMessage}</div> : null}
                  </article>
                );
              })}
          </div>
        </section>
      </main>
    </div>
  );
}

export default UploadTaskPage;
