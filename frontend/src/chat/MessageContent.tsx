import { Children, isValidElement, memo, useEffect, useMemo, useRef, useState, type ComponentProps, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { highlightCode, inferLanguageFromPath } from "./codeHighlight";

export type ChatAttachment = {
  id: string;
  cacheKey?: string | null;
  filename: string;
  contentType: string;
  source?: string | null;
  kind?: string | null;
  extension?: string | null;
  path?: string | null;
  previewUrl?: string | null;
  summary?: string | null;
  sizeBytes?: number | null;
  workspaceRelativePath?: string | null;
  analysisStatus?: string | null;
  analysisError?: string | null;
};

export type HtmlPreviewPayload = {
  content: string;
  title: string;
  source?: "code_block" | "write_file";
  path?: string | null;
  streaming?: boolean;
  initialView?: "preview" | "code";
  language?: string | null;
  kind?: string | null;
  contentType?: string | null;
  extension?: string | null;
  previewMode?: string | null;
  previewUrl?: string | null;
  downloadUrl?: string | null;
  sizeBytes?: number | null;
  summary?: string | null;
  cacheKey?: string | null;
};

type MessageContentProps = {
  apiBase: string;
  variant: "assistant" | "user";
  content: string;
  attachments?: ChatAttachment[];
  className?: string;
  onOpenHtmlPreview?: (payload: HtmlPreviewPayload) => void;
  deferCodeBlocksUntilComplete?: boolean;
};

type AttachmentPreviewState = {
  attachment: ChatAttachment;
  src: string;
} | null;

const EMPTY_ATTACHMENTS: ChatAttachment[] = [];

function sameStringArray(left: string[], right: string[]) {
  if (left.length !== right.length) {
    return false;
  }
  return left.every((item, index) => item === right[index]);
}

const markdownSchema = {
  ...defaultSchema,
  tagNames: [
    ...(defaultSchema.tagNames ?? []),
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "details",
    "summary",
    "kbd",
  ],
  attributes: {
    ...defaultSchema.attributes,
    a: [...(defaultSchema.attributes?.a ?? []), "target", "rel"],
    code: [...(defaultSchema.attributes?.code ?? []), ["className", /^language-/]],
    img: [...(defaultSchema.attributes?.img ?? []), "src", "alt", "title"],
    th: [...(defaultSchema.attributes?.th ?? []), "align"],
    td: [...(defaultSchema.attributes?.td ?? []), "align"],
  },
};

async function copyTextToClipboard(value: string) {
  const writeWithClipboardApi = navigator.clipboard?.writeText;

  if (writeWithClipboardApi && window.isSecureContext) {
    try {
      await writeWithClipboardApi.call(navigator.clipboard, value);
      return;
    } catch {
      // Fall back for browsers that expose the API but reject it in the current context.
    }
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.top = "0";
  textarea.style.left = "0";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);

  const copied = document.execCommand("copy");
  document.body.removeChild(textarea);
  if (!copied) {
    throw new Error("copy_failed");
  }
}

const URL_TOKEN_REGEX = /(https?:\/\/[A-Za-z0-9\-._~:/?#[\]@!$&'()*+,;=%]+)/g;
const URL_TRAILING_PUNCTUATION = /[),.;!?，。；：！？、】【」』》〉）]+$/u;
const MARKDOWN_IMAGE_SOURCE_REGEX = /!\[[^\]]*\]\(([^)\n]+)\)/g;
const HTML_IMAGE_SOURCE_REGEX = /<img\b[^>]*\bsrc=(['"])(.*?)\1[^>]*>/gi;

function joinClassNames(...values: Array<string | null | undefined | false>) {
  return values.filter(Boolean).join(" ");
}

function trimUrlToken(token: string) {
  const trailing = token.match(URL_TRAILING_PUNCTUATION)?.[0] ?? "";
  const url = trailing ? token.slice(0, -trailing.length) : token;
  return { url, trailing };
}

function compactMiddle(value: string, maxLength: number) {
  if (value.length <= maxLength) {
    return value;
  }
  const head = Math.ceil((maxLength - 1) / 2);
  const tail = Math.floor((maxLength - 1) / 2);
  return `${value.slice(0, head)}…${value.slice(value.length - tail)}`;
}

function formatUserUrlLabel(rawUrl: string) {
  try {
    const parsed = new URL(rawUrl);
    const host = parsed.host.replace(/^www\./, "");
    const path = decodeURIComponent(parsed.pathname || "/").replace(/\/$/, "");
    const base = path && path !== "/" ? `${host}${path}` : host;
    if (parsed.search || parsed.hash) {
      return compactMiddle(`${base}${parsed.search ? "?" : ""}${parsed.hash ? "#" : ""}`, 40);
    }
    return compactMiddle(base, 40);
  } catch {
    return compactMiddle(rawUrl, 40);
  }
}

function renderUserText(content: string) {
  const tokens = content.split(URL_TOKEN_REGEX);
  return tokens.map((token, index) => {
    if (!token) {
      return null;
    }

    if (!/^https?:\/\//.test(token)) {
      return <span key={`text:${index}`}>{token}</span>;
    }

    const { url, trailing } = trimUrlToken(token);
    if (!url) {
      return <span key={`text:${index}`}>{token}</span>;
    }

    return (
      <span key={`url:${index}`}>
        <a
          className="chat-message-link"
          href={url}
          target="_blank"
          rel="noreferrer"
          title={url}
        >
          {formatUserUrlLabel(url)}
        </a>
        {trailing}
      </span>
    );
  });
}

function buildWorkspaceFileUrl(apiBase: string, path: string, options?: { download?: boolean }) {
  const url = new URL(`${apiBase}/api/workspace/file-content`);
  url.searchParams.set("path", path);
  if (options?.download) {
    url.searchParams.set("download", "true");
  }
  return url.toString();
}

function buildAttachmentUrl(apiBase: string, attachment: ChatAttachment, options?: { download?: boolean }) {
  if (attachment.previewUrl) {
    return attachment.previewUrl;
  }
  if (!attachment.path) {
    return null;
  }
  const useAttachmentContentRoute = attachment.source === "user_upload" || attachment.source === "parser_output";
  const url = new URL(
    `${apiBase}${useAttachmentContentRoute ? "/api/workspace/attachment-content" : "/api/workspace/file-content"}`,
  );
  url.searchParams.set("path", attachment.path);
  const cacheKey = attachment.cacheKey || attachment.id;
  if (cacheKey) {
    url.searchParams.set("v", cacheKey);
  }
  if (options?.download) {
    url.searchParams.set("download", "true");
  }
  return url.toString();
}

function decodePathToken(value: string) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function normalizeImageSourceForMatch(source: string) {
  const trimmed = source.trim();
  if (!trimmed) {
    return "";
  }
  if (trimmed.startsWith("file://")) {
    try {
      return decodeURIComponent(new URL(trimmed).pathname).replace(/\\/g, "/");
    } catch {
      return decodePathToken(trimmed.slice("file://".length)).replace(/\\/g, "/");
    }
  }
  if (trimmed.startsWith("<") && trimmed.endsWith(">")) {
    return decodePathToken(trimmed.slice(1, -1).trim()).replace(/\\/g, "/");
  }
  const withoutTitle = trimmed.includes(" ") && !trimmed.startsWith("data:image/") ? trimmed.split(" ", 1)[0] : trimmed;
  return decodePathToken(withoutTitle).replace(/\\/g, "/");
}

function extractFilenameFromSource(source: string) {
  const normalized = normalizeImageSourceForMatch(source);
  if (!normalized) {
    return "image";
  }
  const sanitized = normalized.split(/[?#]/, 1)[0];
  const segments = sanitized.split("/").filter(Boolean);
  return segments[segments.length - 1] || "image";
}

function isDirectImageSource(source: string) {
  return /^(https?:\/\/|data:image\/|blob:)/i.test(source.trim());
}

function collectContentImageSources(content: string) {
  const sources = new Set<string>();
  for (const match of content.matchAll(MARKDOWN_IMAGE_SOURCE_REGEX)) {
    const source = normalizeImageSourceForMatch(match[1] ?? "");
    if (source) {
      sources.add(source);
    }
  }
  for (const match of content.matchAll(HTML_IMAGE_SOURCE_REGEX)) {
    const source = normalizeImageSourceForMatch(match[2] ?? "");
    if (source) {
      sources.add(source);
    }
  }
  return sources;
}

function findAttachmentByImageSource(source: string, attachments: ChatAttachment[]) {
  const normalizedSource = normalizeImageSourceForMatch(source);
  if (!normalizedSource) {
    return null;
  }
  const normalizedFilename = extractFilenameFromSource(normalizedSource);
  const filenameOnlySource = !normalizedSource.includes("/") && !normalizedSource.includes(":");
  return (
    attachments.find((attachment) => {
      const candidates = [
        attachment.path ? normalizeImageSourceForMatch(attachment.path) : "",
        attachment.workspaceRelativePath ? normalizeImageSourceForMatch(attachment.workspaceRelativePath) : "",
        normalizeImageSourceForMatch(attachment.filename),
      ].filter(Boolean);
      return candidates.includes(normalizedSource) || (filenameOnlySource && candidates.includes(normalizedFilename));
    }) ?? null
  );
}

function buildMarkdownImageUrl(apiBase: string, source: string, attachment: ChatAttachment | null) {
  if (attachment) {
    return buildAttachmentUrl(apiBase, attachment);
  }
  const normalizedSource = normalizeImageSourceForMatch(source);
  if (!normalizedSource) {
    return null;
  }
  if (isDirectImageSource(normalizedSource)) {
    return normalizedSource;
  }
  return buildWorkspaceFileUrl(apiBase, normalizedSource);
}

function isImageAttachment(attachment: ChatAttachment) {
  const contentType = attachment.contentType.toLowerCase();
  if (contentType.startsWith("image/")) {
    return true;
  }
  const extension = (attachment.extension ?? `.${attachment.filename.split(".").pop() ?? ""}`).toLowerCase();
  return extension === ".png" || extension === ".jpg" || extension === ".jpeg" || extension === ".webp";
}

function isHtmlAttachment(attachment: ChatAttachment) {
  const extension = (attachment.extension ?? `.${attachment.filename.split(".").pop() ?? ""}`).toLowerCase();
  return attachment.kind === "html" || attachment.contentType.toLowerCase() === "text/html" || extension === ".html" || extension === ".htm";
}

function inferAttachmentKind(attachment: ChatAttachment) {
  const extension = (attachment.extension ?? `.${attachment.filename.split(".").pop() ?? ""}`).toLowerCase();
  const contentType = attachment.contentType.toLowerCase();
  if (isHtmlAttachment(attachment)) return "html";
  if (attachment.kind === "image" || contentType.startsWith("image/")) return "image";
  if (extension === ".pdf" || contentType === "application/pdf") return "pdf";
  if (extension === ".md" || extension === ".markdown") return "markdown";
  if (extension === ".txt" || extension === ".log" || contentType.startsWith("text/")) return "text";
  if (extension === ".doc" || extension === ".docx") return "docx";
  if (extension === ".ppt" || extension === ".pptx") return "pptx";
  if (extension === ".xls" || extension === ".xlsx" || extension === ".csv") return "xlsx";
  return "file";
}

function inferAttachmentPreviewMode(attachment: ChatAttachment, language: string | null) {
  const kind = inferAttachmentKind(attachment);
  if (kind === "html") return "html";
  if (kind === "image") return "image";
  if (kind === "pdf") return "pdf";
  if (kind === "markdown") return "code";
  if (kind === "text" || language) return "code";
  if (kind === "xlsx") return "table";
  if (kind === "pptx") return "slides";
  return "unsupported";
}

function canRenderAttachmentPreview(previewMode: string) {
  return previewMode === "html" || previewMode === "code" || previewMode === "pdf" || previewMode === "image";
}

function normalizeAttachmentPath(attachment: ChatAttachment) {
  return (attachment.workspaceRelativePath || attachment.path || "").replace(/\\/g, "/");
}

function attachmentDirectory(attachment: ChatAttachment) {
  const path = normalizeAttachmentPath(attachment);
  const separatorIndex = path.lastIndexOf("/");
  return separatorIndex >= 0 ? path.slice(0, separatorIndex) : "";
}

function findCompanionHtmlPreview(attachment: ChatAttachment, attachments: ChatAttachment[]) {
  if (inferAttachmentKind(attachment) !== "pptx") {
    return null;
  }
  const directory = attachmentDirectory(attachment);
  return (
    attachments.find((candidate) => {
      if (!isHtmlAttachment(candidate) || candidate.id === attachment.id) {
        return false;
      }
      const filename = candidate.filename.toLowerCase();
      return filename === "preview.html" && (!directory || attachmentDirectory(candidate) === directory);
    }) ?? null
  );
}

function shouldFetchAttachmentTextForPreview(previewMode: string) {
  return previewMode === "html" || previewMode === "code" || previewMode === "markdown" || previewMode === "text";
}

function inferAttachmentPreviewLanguage(attachment: ChatAttachment) {
  return (
    inferLanguageFromPath(attachment.path) ??
    inferLanguageFromPath(attachment.workspaceRelativePath) ??
    inferLanguageFromPath(attachment.filename)
  );
}

function AttachmentFileCard({
  apiBase,
  attachment,
  href,
  companionPreviewAttachment,
  onOpenHtmlPreview,
  tone = "user",
}: {
  apiBase: string;
  attachment: ChatAttachment;
  href: string | null;
  companionPreviewAttachment?: ChatAttachment | null;
  onOpenHtmlPreview?: (payload: HtmlPreviewPayload) => void;
  tone?: "assistant" | "user";
}) {
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const cardTitle = attachment.filename;
  const effectivePreviewAttachment = companionPreviewAttachment ?? attachment;
  const previewHref = companionPreviewAttachment ? buildAttachmentUrl(apiBase, companionPreviewAttachment) : href;
  const isHtml = isHtmlAttachment(effectivePreviewAttachment);
  const previewLanguage = isHtml ? "html" : inferAttachmentPreviewLanguage(effectivePreviewAttachment);
  const previewKind = inferAttachmentKind(attachment);
  const previewMode = companionPreviewAttachment ? "html" : inferAttachmentPreviewMode(attachment, previewLanguage);
  const canPreviewAttachment = Boolean(previewHref && onOpenHtmlPreview && canRenderAttachmentPreview(previewMode));
  const downloadHref = attachment.path ? buildAttachmentUrl(apiBase, attachment, { download: true }) : href;

  const openAttachmentPreview = async () => {
    if (!previewHref || !onOpenHtmlPreview || previewLoading) {
      return;
    }
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      let content = "";
      if (shouldFetchAttachmentTextForPreview(previewMode)) {
        const response = await fetch(previewHref, { credentials: "include", cache: "no-store" });
        if (!response.ok) {
          throw new Error(`预览加载失败：${response.status}`);
        }
        content = await response.text();
      }
      onOpenHtmlPreview({
        content,
        title: attachment.filename,
        source: "write_file",
        path: attachment.path,
        streaming: false,
        initialView: shouldFetchAttachmentTextForPreview(previewMode) && !isHtml ? "code" : "preview",
        language: previewLanguage ?? undefined,
        kind: previewKind,
        contentType: attachment.contentType,
        extension: attachment.extension,
        previewMode,
        previewUrl: previewHref,
        downloadUrl: downloadHref,
        cacheKey: effectivePreviewAttachment.cacheKey || effectivePreviewAttachment.id,
        sizeBytes: attachment.sizeBytes,
        summary: attachment.summary,
      });
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : "预览加载失败");
    } finally {
      setPreviewLoading(false);
    }
  };

  const content = (
    <div className="chat-attachment-file-main">
      <strong className="chat-attachment-file-name">{attachment.filename}</strong>
    </div>
  );

  if (!href) {
    return (
      <div className={joinClassNames("chat-attachment-file", tone === "assistant" && "assistant")} title={cardTitle}>
        {content}
      </div>
    );
  }

  return (
    <div className={joinClassNames("chat-attachment-file", "actionable", tone === "assistant" && "assistant")} title={cardTitle}>
      {content}
      <div className="chat-attachment-file-actions">
        {canPreviewAttachment ? (
          <button
            type="button"
            className="chat-attachment-file-action"
            onClick={() => void openAttachmentPreview()}
            disabled={previewLoading}
          >
            {previewLoading ? "预览中" : "预览"}
          </button>
        ) : null}
        {downloadHref ? (
          <a className="chat-attachment-file-action ghost" href={downloadHref} download={attachment.filename}>
            下载
          </a>
        ) : null}
      </div>
      {previewError ? <span className="chat-attachment-file-error">{previewError}</span> : null}
    </div>
  );
}

function AttachmentGallery({
  apiBase,
  attachments,
  failedAttachmentIds,
  onPreview,
  onOpenHtmlPreview,
  onAttachmentError,
  tone = "user",
  ariaLabel,
}: {
  apiBase: string;
  attachments: ChatAttachment[];
  failedAttachmentIds: string[];
  onPreview: (attachment: ChatAttachment, src: string) => void;
  onOpenHtmlPreview?: (payload: HtmlPreviewPayload) => void;
  onAttachmentError: (attachmentId: string) => void;
  tone?: "assistant" | "user";
  ariaLabel: string;
}) {
  return (
    <div className={joinClassNames("chat-attachment-grid", tone === "assistant" && "assistant")} aria-label={ariaLabel}>
      {attachments.map((attachment) => {
        const src = buildAttachmentUrl(apiBase, attachment);
        if (!isImageAttachment(attachment) || (tone === "assistant" && onOpenHtmlPreview)) {
          const companionPreview = findCompanionHtmlPreview(attachment, attachments);
          return (
            <AttachmentFileCard
              key={attachment.id}
              apiBase={apiBase}
              attachment={attachment}
              href={src}
              companionPreviewAttachment={companionPreview}
              onOpenHtmlPreview={onOpenHtmlPreview}
              tone={tone}
            />
          );
        }
        if (!src) {
          return (
            <div
              key={attachment.id}
              className={joinClassNames("chat-attachment-card", "fallback", tone === "assistant" && "assistant")}
              title={attachment.filename}
            >
              <div className="chat-attachment-fallback">{attachment.filename.slice(0, 1).toUpperCase()}</div>
            </div>
          );
        }

        return (
          <button
            key={attachment.id}
            type="button"
            className={joinClassNames("chat-attachment-card", tone === "assistant" && "assistant")}
            title={attachment.summary || attachment.filename}
            aria-label={`预览图片 ${attachment.filename}`}
            onClick={() => onPreview(attachment, src)}
          >
            {failedAttachmentIds.includes(attachment.id) ? (
              <span className="chat-attachment-fallback">{attachment.filename.slice(0, 1).toUpperCase()}</span>
            ) : (
              <img
                className="chat-attachment-image"
                src={src}
                alt={attachment.summary || attachment.filename}
                loading="lazy"
                onError={() => onAttachmentError(attachment.id)}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}

function AttachmentPreviewDialog({
  attachment,
  src,
  onClose,
}: {
  attachment: ChatAttachment;
  src: string;
  onClose: () => void;
}) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  return (
    <div className="chat-image-preview-backdrop" role="presentation" onClick={onClose}>
      <div
        className="chat-image-preview-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={`图片预览：${attachment.filename}`}
        onClick={(event) => event.stopPropagation()}
      >
        <button type="button" className="chat-image-preview-close" onClick={onClose} aria-label="关闭图片预览">
          关闭
        </button>
        <img className="chat-image-preview-image" src={src} alt={attachment.summary || attachment.filename} />
        <div className="chat-image-preview-meta">
          <strong>{attachment.filename}</strong>
          {attachment.summary ? <span>{attachment.summary}</span> : null}
        </div>
      </div>
    </div>
  );
}

const CODE_LANGUAGE_LABELS: Record<string, string> = {
  bash: "Bash",
  css: "CSS",
  html: "HTML",
  javascript: "JavaScript",
  js: "JavaScript",
  json: "JSON",
  jsx: "JSX",
  markdown: "Markdown",
  md: "Markdown",
  python: "Python",
  py: "Python",
  shell: "Shell",
  sh: "Shell",
  sql: "SQL",
  text: "Text",
  plaintext: "Text",
  ts: "TypeScript",
  tsx: "TSX",
  typescript: "TypeScript",
  yaml: "YAML",
  yml: "YAML",
};

function extractCodeLanguage(className?: string) {
  const match = className?.match(/language-([A-Za-z0-9_-]+)/);
  return match?.[1]?.toLowerCase() ?? null;
}

function formatCodeLanguageLabel(language: string | null) {
  if (!language) {
    return "Code";
  }
  if (CODE_LANGUAGE_LABELS[language]) {
    return CODE_LANGUAGE_LABELS[language];
  }
  return language
    .split(/[-_]/)
    .filter(Boolean)
    .map((segment) => segment.slice(0, 1).toUpperCase() + segment.slice(1))
    .join(" ");
}

function buildDeferredCodeBlockPlaceholder(fenceLanguage: string | null) {
  if (!fenceLanguage) {
    return "代码块生成中，回复完成后自动展示。";
  }
  const languageLabel = formatCodeLanguageLabel(fenceLanguage);
  return `${languageLabel} 代码块生成中，回复完成后自动展示。`;
}

function stripFencedCodeBlocksForStreaming(content: string) {
  const lines = content.split("\n");
  const nextLines: string[] = [];
  let insideFence = false;
  let deferredFenceLanguage: string | null = null;

  for (const line of lines) {
    const trimmed = line.trimStart();
    if (trimmed.startsWith("```")) {
      if (!insideFence) {
        deferredFenceLanguage = trimmed.slice(3).trim().toLowerCase() || null;
        if (nextLines.length > 0 && nextLines[nextLines.length - 1] !== "") {
          nextLines.push("");
        }
        nextLines.push(`> ${buildDeferredCodeBlockPlaceholder(deferredFenceLanguage)}`);
        nextLines.push("");
        insideFence = true;
      } else {
        insideFence = false;
        deferredFenceLanguage = null;
      }
      continue;
    }

    if (!insideFence) {
      nextLines.push(line);
    }
  }

  return nextLines.join("\n").trimEnd();
}

function extractNodeText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map((child) => extractNodeText(child)).join("");
  }
  if (isValidElement<{ children?: ReactNode }>(node)) {
    return extractNodeText(node.props.children);
  }
  return "";
}

function buildHtmlPreviewTitle(markup: string) {
  const titleMatch = markup.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  if (titleMatch?.[1]) {
    const normalized = titleMatch[1].replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
    if (normalized) {
      return normalized;
    }
  }

  const headingMatch = markup.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i);
  if (headingMatch?.[1]) {
    const normalized = headingMatch[1].replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
    if (normalized) {
      return normalized;
    }
  }

  return "HTML 实时预览";
}

function PreviewEyeIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 16 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M1.5 8c1.55-2.44 3.72-3.67 6.5-3.67 2.78 0 4.95 1.23 6.5 3.67-1.55 2.44-3.72 3.67-6.5 3.67-2.78 0-4.95-1.23-6.5-3.67Z"
        stroke="currentColor"
        strokeWidth="1.2"
      />
      <circle cx="8" cy="8" r="2.1" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function MarkdownCodeBlock({
  children,
  onOpenHtmlPreview,
}: ComponentProps<"pre"> & {
  onOpenHtmlPreview?: (payload: HtmlPreviewPayload) => void;
}) {
  const timeoutRef = useRef<number | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const childNodes = Children.toArray(children);
  const codeChild = childNodes.find((child) =>
    isValidElement<{ className?: string; children?: ReactNode }>(child),
  );

  useEffect(() => {
    return () => {
      if (timeoutRef.current !== null) {
        window.clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  if (!isValidElement<{ className?: string; children?: ReactNode }>(codeChild)) {
    return <pre>{children}</pre>;
  }

  const language = extractCodeLanguage(codeChild.props.className);
  const codeText = extractNodeText(codeChild.props.children).replace(/\n$/, "");
  const { language: prismLanguage, html: highlightedCode } = highlightCode(codeText, language);
  const canPreviewHtml = Boolean(onOpenHtmlPreview) && language === "html";

  const handleCopy = async () => {
    try {
      await copyTextToClipboard(codeText);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }

    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current);
    }

    timeoutRef.current = window.setTimeout(() => {
      setCopyState("idle");
      timeoutRef.current = null;
    }, 1800);
  };

  return (
    <div className="chat-code-block">
      <div className="chat-code-block-head">
        <span className="chat-code-block-language">{formatCodeLanguageLabel(language)}</span>
        <div className="chat-code-block-actions">
          {canPreviewHtml ? (
            <button
              type="button"
              className="chat-code-block-action"
              onClick={() =>
                onOpenHtmlPreview?.({
                  content: codeText,
                  title: buildHtmlPreviewTitle(codeText),
                  source: "code_block",
                  streaming: false,
                })
              }
            >
              <PreviewEyeIcon className="chat-code-block-action-icon" />
              <span>预览</span>
            </button>
          ) : null}
          <button
            type="button"
            className={`chat-code-block-action chat-code-block-copy ${copyState !== "idle" ? `is-${copyState}` : ""}`}
            onClick={handleCopy}
          >
            {copyState === "copied" ? "已复制" : copyState === "failed" ? "复制失败" : "复制代码"}
          </button>
        </div>
      </div>
      <pre className="chat-code-block-pre">
        <code
          className={prismLanguage ? `language-${prismLanguage}` : codeChild.props.className}
          dangerouslySetInnerHTML={{ __html: highlightedCode }}
        />
      </pre>
    </div>
  );
}

function MarkdownImage({
  apiBase,
  src,
  alt,
  attachments,
  onPreview,
}: {
  apiBase: string;
  src?: string;
  alt?: string;
  attachments: ChatAttachment[];
  onPreview: (attachment: ChatAttachment, src: string) => void;
}) {
  const [failed, setFailed] = useState(false);
  const source = src ?? "";
  const attachment = findAttachmentByImageSource(source, attachments);
  const resolvedSrc = buildMarkdownImageUrl(apiBase, source, attachment);
  const previewAttachment =
    attachment ??
    ({
      id: `inline:${source}`,
      filename: extractFilenameFromSource(source),
      contentType: "image/*",
      kind: "image",
      previewUrl: resolvedSrc,
      summary: alt?.trim() || null,
    } satisfies ChatAttachment);

  if (!resolvedSrc || failed) {
    return <span className="chat-inline-image-fallback">{alt?.trim() || previewAttachment.filename}</span>;
  }

  return (
    <button
      type="button"
      className="chat-markdown-image-button"
      onClick={() => onPreview(previewAttachment, resolvedSrc)}
      title={previewAttachment.summary || previewAttachment.filename}
      aria-label={`预览图片 ${previewAttachment.filename}`}
    >
      <img
        className="chat-markdown-image"
        src={resolvedSrc}
        alt={alt || previewAttachment.filename}
        loading="lazy"
        onError={() => setFailed(true)}
      />
    </button>
  );
}

function MessageContent({
  apiBase,
  variant,
  content,
  attachments = EMPTY_ATTACHMENTS,
  className,
  onOpenHtmlPreview,
  deferCodeBlocksUntilComplete = false,
}: MessageContentProps) {
  const hasText = Boolean(content.trim());
  const hasAttachments = attachments.length > 0;
  const [preview, setPreview] = useState<AttachmentPreviewState>(null);
  const [failedAttachmentIds, setFailedAttachmentIds] = useState<string[]>([]);
  const renderedAssistantContent = useMemo(
    () => (variant === "assistant" && deferCodeBlocksUntilComplete ? stripFencedCodeBlocksForStreaming(content) : content),
    [content, deferCodeBlocksUntilComplete, variant],
  );
  const assistantLooseAttachments = useMemo(() => {
    if (variant !== "assistant") {
      return EMPTY_ATTACHMENTS;
    }
    const referencedImageSources = collectContentImageSources(content);
    return attachments.filter((attachment) => {
      const candidates = [
        attachment.path ? normalizeImageSourceForMatch(attachment.path) : "",
        attachment.workspaceRelativePath ? normalizeImageSourceForMatch(attachment.workspaceRelativePath) : "",
        normalizeImageSourceForMatch(attachment.filename),
      ].filter(Boolean);
      return !candidates.some((candidate) => referencedImageSources.has(candidate));
    });
  }, [attachments, content, variant]);

  useEffect(() => {
    setFailedAttachmentIds((current) => {
      const next = current.filter((id) => attachments.some((attachment) => attachment.id === id));
      return sameStringArray(current, next) ? current : next;
    });
  }, [attachments]);

  if (variant === "user") {
    return (
      <>
        <div className={joinClassNames("chat-message-content", "user", className)}>
          {hasText ? <p className="chat-message-text">{renderUserText(content)}</p> : null}
          {hasAttachments ? (
            <AttachmentGallery
              apiBase={apiBase}
              attachments={attachments}
              failedAttachmentIds={failedAttachmentIds}
              onPreview={(attachment, src) => setPreview({ attachment, src })}
              onOpenHtmlPreview={onOpenHtmlPreview}
              onAttachmentError={(attachmentId) =>
                setFailedAttachmentIds((current) => (current.includes(attachmentId) ? current : [...current, attachmentId]))
              }
              ariaLabel="已上传附件"
            />
          ) : null}
        </div>
        {preview ? (
          <AttachmentPreviewDialog
            attachment={preview.attachment}
            src={preview.src}
            onClose={() => setPreview(null)}
          />
        ) : null}
      </>
    );
  }

  return (
    <>
      <div className={joinClassNames("chat-message-content", "assistant", className)}>
        {hasText ? (
          <div className="chat-markdown-body">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeRaw, [rehypeSanitize, markdownSchema]]}
              components={{
                a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
                img: ({ node: _node, ...props }) => (
                  <MarkdownImage
                    apiBase={apiBase}
                    src={typeof props.src === "string" ? props.src : undefined}
                    alt={typeof props.alt === "string" ? props.alt : undefined}
                    attachments={attachments}
                    onPreview={(attachment, src) => setPreview({ attachment, src })}
                  />
                ),
                pre: ({ node: _node, ...props }) => <MarkdownCodeBlock {...props} onOpenHtmlPreview={onOpenHtmlPreview} />,
              }}
            >
              {renderedAssistantContent}
            </ReactMarkdown>
          </div>
        ) : null}
        {assistantLooseAttachments.length > 0 ? (
          <AttachmentGallery
            apiBase={apiBase}
            attachments={assistantLooseAttachments}
            failedAttachmentIds={failedAttachmentIds}
            onPreview={(attachment, src) => setPreview({ attachment, src })}
            onOpenHtmlPreview={onOpenHtmlPreview}
            onAttachmentError={(attachmentId) =>
              setFailedAttachmentIds((current) => (current.includes(attachmentId) ? current : [...current, attachmentId]))
            }
            tone="assistant"
            ariaLabel="回复附件"
          />
        ) : null}
      </div>
      {preview ? (
        <AttachmentPreviewDialog
          attachment={preview.attachment}
          src={preview.src}
          onClose={() => setPreview(null)}
        />
      ) : null}
    </>
  );
}

export default memo(MessageContent);
