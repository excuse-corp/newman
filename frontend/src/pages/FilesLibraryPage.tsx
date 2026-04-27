import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./files-library.css";

type KnowledgeDocument = {
  document_id: string;
  title: string;
  source_path: string;
  stored_path: string;
  size_bytes: number;
  content_type: string;
  parser: string;
  chunk_count: number;
  page_count: number | null;
  imported_at: string;
};

type KnowledgeDocumentsResponse = {
  documents: KnowledgeDocument[];
};

type KnowledgeDocumentDetailResponse = {
  document: KnowledgeDocument;
  preview_markdown: string;
};

type KnowledgeUploadResponse = {
  document: KnowledgeDocument;
};

type FilesLibraryPageProps = {
  apiBase: string;
  onClose?: () => void;
};

function formatBytes(size: number) {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function extractFormat(document: KnowledgeDocument) {
  const titleParts = document.title.split(".");
  const suffix = titleParts.length > 1 ? titleParts[titleParts.length - 1] : "";
  if (suffix) {
    return suffix.toUpperCase();
  }

  const contentTypeParts = document.content_type.split("/");
  return contentTypeParts[contentTypeParts.length - 1]?.toUpperCase() ?? "FILE";
}

function describeDocument(document: KnowledgeDocument) {
  const format = extractFormat(document);
  const volume =
    document.page_count !== null
      ? `${document.page_count} 页 / ${document.chunk_count} 个片段`
      : `${document.chunk_count} 个片段`;
  return `原格式 ${format}  大小尺寸 ${formatBytes(document.size_bytes)} / ${volume}`;
}

function buildDocumentDownloadUrl(apiBase: string, path: string) {
  const url = new URL(`${apiBase}/api/workspace/file-content`);
  url.searchParams.set("path", path);
  return url.toString();
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const text = await response.text();
  let payload: unknown = null;

  if (text) {
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    let message = `请求失败：${response.status}`;
    if (payload && typeof payload === "object" && payload !== null) {
      const detail =
        "detail" in payload
          ? payload.detail
          : "message" in payload
            ? payload.message
            : null;
      if (typeof detail === "string" && detail.trim()) {
        message = detail;
      }
    }
    throw new Error(message);
  }

  return payload as T;
}

function FilesLibraryPage({ apiBase, onClose }: FilesLibraryPageProps) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<KnowledgeDocumentDetailResponse | null>(null);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [pageNotice, setPageNotice] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function loadDocuments(preferredId?: string | null) {
    setLibraryLoading(true);
    setPageError(null);

    try {
      const data = await fetchJson<KnowledgeDocumentsResponse>(`${apiBase}/api/knowledge/documents`);
      setDocuments(data.documents);
      setSelectedDocumentId((current) => {
        if (preferredId && data.documents.some((item) => item.document_id === preferredId)) {
          return preferredId;
        }
        if (current && data.documents.some((item) => item.document_id === current)) {
          return current;
        }
        return data.documents[0]?.document_id ?? null;
      });
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "资料库加载失败");
    } finally {
      setLibraryLoading(false);
    }
  }

  useEffect(() => {
    void loadDocuments();
  }, [apiBase]);

  useEffect(() => {
    if (!selectedDocumentId) {
      setSelectedDetail(null);
      return;
    }

    const activeDocumentId = selectedDocumentId;
    const controller = new AbortController();

    async function loadDocumentDetail() {
      setPreviewLoading(true);
      setPageError(null);

      try {
        const data = await fetchJson<KnowledgeDocumentDetailResponse>(
          `${apiBase}/api/knowledge/documents/${encodeURIComponent(activeDocumentId)}`,
          { signal: controller.signal }
        );
        if (controller.signal.aborted) {
          return;
        }
        setSelectedDetail(data);
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }
        setPageError(error instanceof Error ? error.message : "文档预览加载失败");
      } finally {
        if (!controller.signal.aborted) {
          setPreviewLoading(false);
        }
      }
    }

    void loadDocumentDetail();
    return () => controller.abort();
  }, [apiBase, selectedDocumentId]);

  const selectedDocument = documents.find((item) => item.document_id === selectedDocumentId) ?? null;

  const openFilePicker = () => {
    fileInputRef.current?.click();
  };

  const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    void uploadFiles(files);
  };

  const uploadFiles = async (files: File[]) => {
    if (files.length === 0 || uploading) {
      return;
    }

    setUploading(true);
    setPageError(null);
    setPageNotice(null);

    const uploaded: KnowledgeDocument[] = [];
    const failures: string[] = [];

    for (const file of files) {
      const body = new FormData();
      body.append("file", file, file.name);

      try {
        const data = await fetchJson<KnowledgeUploadResponse>(`${apiBase}/api/knowledge/documents/upload`, {
          method: "POST",
          body,
        });
        uploaded.push(data.document);
      } catch (error) {
        failures.push(`${file.name}：${error instanceof Error ? error.message : "上传失败"}`);
      }
    }

    if (uploaded.length > 0) {
      const latestUploaded = uploaded[uploaded.length - 1];
      await loadDocuments(latestUploaded.document_id);
      setPageNotice(
        failures.length === 0
          ? `已导入 ${uploaded.length} 个文件。`
          : `已导入 ${uploaded.length} 个文件，另有 ${failures.length} 个失败。`
      );
    }

    if (uploaded.length === 0 && failures.length > 0) {
      setPageError(failures.join("；"));
    } else if (failures.length > 0) {
      setPageError(failures.join("；"));
    }

    setUploading(false);
  };

  const onDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    setDragActive(false);
    void uploadFiles(Array.from(event.dataTransfer.files));
  };

  return (
    <section className="workspace-page files-library-page">
      <input
        ref={fileInputRef}
        className="files-library-hidden-input"
        type="file"
        multiple
        onChange={handleInputChange}
      />

      <div className="workspace-page-head files-library-head">
        <div>
          <p className="workspace-eyebrow">Library</p>
          <h2>资料库</h2>
        </div>

        <div className="workspace-page-actions files-library-page-actions">
          <button
            type="button"
            className="files-library-upload-button"
            onClick={openFilePicker}
            disabled={uploading}
          >
            {uploading ? "上传中..." : "上传文件"}
          </button>
          {onClose ? (
            <button type="button" className="workspace-secondary-button" onClick={onClose}>
              关闭
            </button>
          ) : null}
        </div>
      </div>

      <div className="workspace-page-meta files-library-meta">
        <span className="workspace-pill">{documents.length} 份文档</span>
        <span className="workspace-pill subtle">支持 PDF / DOCX / PPTX / XLSX / TXT / MD / PNG / JPG</span>
      </div>

      {pageNotice ? <div className="workspace-alert success">{pageNotice}</div> : null}
      {pageError ? <div className="workspace-alert error">{pageError}</div> : null}

      <div className="files-library-grid">
        <article
          className={`workspace-card files-library-card files-library-list-card ${dragActive ? "is-drag-active" : ""}`}
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
          <div className="workspace-card-head files-library-card-head">
            <div>
              <p className="files-library-kicker">Library</p>
              <h3>文档列表</h3>
            </div>
            <span className="files-library-count">{documents.length}</span>
          </div>

          <div className="workspace-card-body workspace-card-scroll files-library-card-body">
            {libraryLoading ? <div className="workspace-empty">正在加载资料库...</div> : null}

            {!libraryLoading && documents.length === 0 ? (
              <button type="button" className="files-library-empty-card" onClick={openFilePicker}>
                <strong>资料库还是空的</strong>
                <span>点击上传文件，或者直接把文档拖到这里。</span>
              </button>
            ) : null}

            {!libraryLoading && documents.length > 0 ? (
              <div className="files-library-list">
                {documents.map((document) => {
                  const isSelected = document.document_id === selectedDocumentId;
                  const downloadUrl = buildDocumentDownloadUrl(apiBase, document.stored_path);

                  return (
                    <button
                      key={document.document_id}
                      type="button"
                      className={`files-library-item ${isSelected ? "is-selected" : ""}`}
                      onClick={() => setSelectedDocumentId(document.document_id)}
                    >
                      <div className="files-library-item-top">
                        <div className="files-library-item-copy">
                          <strong>{document.title}</strong>
                          <span>{describeDocument(document)}</span>
                        </div>
                        <span className="workspace-pill subtle">{document.parser}</span>
                      </div>

                      <div className="files-library-item-meta">
                        <span>导入时间 {formatDateTime(document.imported_at)}</span>
                      </div>

                      <div className="files-library-item-actions">
                        <a
                          className="files-library-link-button"
                          href={downloadUrl}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(event) => event.stopPropagation()}
                        >
                          下载原文件
                        </a>
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>
        </article>

        <article className="workspace-card files-library-card files-library-preview-card">
          <div className="workspace-card-head files-library-card-head">
            <div>
              <p className="files-library-kicker">Preview</p>
              <h3>Markdown 预览</h3>
            </div>
            {selectedDocument ? <span className="workspace-pill accent">{selectedDocument.title}</span> : null}
          </div>

          <div className="workspace-card-body files-library-preview-body">
            {!selectedDocument ? <div className="workspace-empty">上传文件后，这里会显示解析后的 Markdown 预览。</div> : null}

            {selectedDocument ? (
              <div className="files-library-preview-shell">
                {previewLoading ? (
                  <div className="workspace-empty">正在生成文档预览...</div>
                ) : (
                  <div className="files-library-preview-surface">
                    <div className="files-library-preview-markdown">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {selectedDetail?.preview_markdown ?? "当前文档暂无可展示预览。"}
                      </ReactMarkdown>
                    </div>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        </article>
      </div>
    </section>
  );
}

export default FilesLibraryPage;
