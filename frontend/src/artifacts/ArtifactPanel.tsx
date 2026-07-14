import { forwardRef, memo, useMemo, type PointerEventHandler } from "react";
import { escapeCodeHtml, highlightCode } from "../chat/codeHighlight";
import type { Artifact, ArtifactView } from "./types";

type ArtifactPanelProps = {
  artifact: Artifact | null;
  view: ArtifactView;
  onViewChange: (view: ArtifactView) => void;
  onClose: () => void;
  onResizeStart?: PointerEventHandler<HTMLDivElement>;
  showResizeHandle?: boolean;
};

function patchHtmlPreviewMarkupForSandbox(markup: string) {
  return markup
    .replace(/\b(?:window|self|globalThis)\s*\.\s*parent\s*\.\s*document\b/g, "document")
    .replace(/\b(?:window|self|globalThis)\s*\.\s*top\s*\.\s*document\b/g, "document")
    .replace(/\bparent\s*\.\s*document\b/g, "document")
    .replace(/\btop\s*\.\s*document\b/g, "document");
}

function normalizeArtifactHtmlContent(artifact: Artifact | null) {
  if (!artifact?.content) {
    return "";
  }

  if (artifact.previewMode === "code") {
    const escapedCode = escapeCodeHtml(artifact.content.trimEnd());
    return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      body {
        margin: 0;
        background: #fffaf3;
        color: #2d2722;
        font: 13px/1.65 "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      }
      pre {
        box-sizing: border-box;
        min-height: 100vh;
        margin: 0;
        padding: 18px 20px;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
      }
    </style>
  </head>
  <body>
    <pre>${escapedCode || " "}</pre>
  </body>
</html>`;
  }

  const markup = patchHtmlPreviewMarkupForSandbox(artifact.content.trim());
  if (!markup) {
    return "";
  }

  if (/<html[\s>]/i.test(markup) || /<!doctype html/i.test(markup)) {
    return markup;
  }

  return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
${markup}
  </body>
</html>`;
}

function EyePanelIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.25}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M1.65 8c1.52-2.39 3.64-3.6 6.35-3.6S12.83 5.61 14.35 8c-1.52 2.39-3.64 3.6-6.35 3.6S3.17 10.39 1.65 8Z" />
      <circle cx="8" cy="8" r="2.05" />
    </svg>
  );
}

function CodePanelIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.35}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M6.35 4.25 3 8l3.35 3.75" />
      <path d="m9.65 4.25 3.35 3.75-3.35 3.75" />
    </svg>
  );
}

function ClosePanelIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.45}
      strokeLinecap="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M4 4 12 12" />
      <path d="M12 4 4 12" />
    </svg>
  );
}

function buildArtifactBadge(artifact: Artifact | null) {
  if (!artifact) {
    return "ARTIFACT";
  }
  if (artifact.saveStatus === "failed" || artifact.status === "failed") {
    return "未保存";
  }
  if (artifact.previewMode === "code") {
    return "CODE";
  }
  return artifact.kind.toUpperCase();
}

function buildArtifactTitlePrefix(artifact: Artifact | null) {
  if (!artifact) {
    return "";
  }
  if (artifact.streaming || artifact.status === "creating") {
    return "生成中 · ";
  }
  if (artifact.saveStatus === "failed" || artifact.status === "failed") {
    return "写入失败 · ";
  }
  return "";
}

function renderArtifactFallback(artifact: Artifact) {
  return (
    <div className="artifact-preview-fallback">
      <div className="artifact-preview-fallback-card">
        <span className="html-preview-frame-badge">{artifact.kind.toUpperCase()}</span>
        <h3>{artifact.title}</h3>
        <p>{artifact.summary || "此格式暂不支持内嵌预览，但文件已作为产物提供，可直接下载。"}</p>
        {artifact.sizeBytes ? <span className="artifact-preview-meta">{Math.round(artifact.sizeBytes / 1024).toLocaleString()} KB</span> : null}
        {artifact.downloadUrl ? (
          <a className="artifact-preview-download-link" href={artifact.downloadUrl} download={artifact.title}>
            下载文件
          </a>
        ) : null}
      </div>
    </div>
  );
}

function renderArtifactPreview(artifact: Artifact, normalizedHtmlContent: string) {
  if (artifact.previewMode === "html" || (artifact.content && artifact.kind === "html")) {
    return (
      <iframe
        key={`${artifact.id}:${artifact.streaming ? "streaming" : "complete"}`}
        className="html-preview-iframe"
        title={artifact.title}
        srcDoc={normalizedHtmlContent}
        sandbox="allow-downloads allow-forms allow-modals allow-popups allow-scripts"
        referrerPolicy="no-referrer"
      />
    );
  }

  if (artifact.previewMode === "pdf" && artifact.previewUrl) {
    return <iframe className="html-preview-iframe" title={artifact.title} src={artifact.previewUrl} referrerPolicy="no-referrer" />;
  }

  if (artifact.previewMode === "image" && artifact.previewUrl) {
    return (
      <div className="artifact-preview-image-wrap">
        <img className="artifact-preview-image" src={artifact.previewUrl} alt={artifact.summary || artifact.title} />
      </div>
    );
  }

  return renderArtifactFallback(artifact);
}

const ArtifactPanel = forwardRef<HTMLElement, ArtifactPanelProps>(function ArtifactPanel({
  artifact,
  view,
  onViewChange,
  onClose,
  onResizeStart,
  showResizeHandle = false,
}: ArtifactPanelProps, ref) {
  const sourceCode = artifact?.content ?? "";
  const showPreview = view === "preview";
  const hasSource = Boolean(sourceCode);
  const showSource = view === "source" && hasSource;
  const normalizedHtmlContent = useMemo(
    () => (showPreview ? normalizeArtifactHtmlContent(artifact) : ""),
    [artifact, showPreview],
  );
  const sourceHighlight = useMemo(
    () =>
      showSource
        ? highlightCode(sourceCode, artifact?.language ?? (artifact?.kind === "html" ? "html" : "plaintext"))
        : { html: "", language: null },
    [artifact?.kind, artifact?.language, showSource, sourceCode],
  );

  return (
    <aside
      ref={ref}
      className={`html-preview-panel ${artifact ? "open" : ""}`}
      aria-label="产物预览面板"
    >
      {artifact && showResizeHandle ? (
        <div
          className="html-preview-resize-handle"
          onPointerDown={onResizeStart}
          role="separator"
          aria-orientation="vertical"
          aria-label="调整产物预览宽度"
        />
      ) : null}
      <div className="html-preview-panel-inner">
        <div className="html-preview-frame-topbar">
          <div className="html-preview-frame-topbar-main">
            <span className="html-preview-frame-badge">{buildArtifactBadge(artifact)}</span>
            <span className="html-preview-frame-title">
              {buildArtifactTitlePrefix(artifact)}
              {artifact?.title ?? "产物预览"}
            </span>
          </div>
          <div className="html-preview-frame-actions">
            <div className="html-preview-view-toggle" role="group" aria-label="产物查看模式">
              <button
                type="button"
                className={view === "preview" ? "active" : ""}
                onClick={() => onViewChange("preview")}
                aria-pressed={view === "preview"}
                title="预览模式"
              >
                <EyePanelIcon className="html-preview-view-toggle-icon" />
                <span>预览</span>
              </button>
              <button
                type="button"
                className={view === "source" ? "active" : ""}
                onClick={() => onViewChange("source")}
                aria-pressed={view === "source"}
                disabled={!hasSource}
                title="源码模式"
              >
                <CodePanelIcon className="html-preview-view-toggle-icon" />
                <span>源码</span>
              </button>
            </div>
            {artifact?.downloadUrl ? (
              <a className="html-preview-panel-download" href={artifact.downloadUrl} download={artifact.title}>
                下载
              </a>
            ) : null}
            <button
              type="button"
              className="html-preview-panel-close"
              onClick={onClose}
              aria-label="关闭产物预览"
            >
              <ClosePanelIcon className="html-preview-panel-close-icon" />
            </button>
          </div>
        </div>
        <div className={`html-preview-frame-stage ${showSource ? "code-mode" : "preview-mode"}`}>
          {artifact && showPreview ? renderArtifactPreview(artifact, normalizedHtmlContent) : null}
          {artifact && showSource ? (
            <pre className="chat-code-block-pre html-preview-code">
              <code
                className={sourceHighlight.language ? `language-${sourceHighlight.language}` : undefined}
                dangerouslySetInnerHTML={{ __html: sourceHighlight.html || "&nbsp;" }}
              />
            </pre>
          ) : null}
        </div>
      </div>
    </aside>
  );
});

export default memo(ArtifactPanel);
