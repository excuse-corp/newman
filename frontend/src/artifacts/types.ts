import type { HtmlPreviewPayload } from "../chat/MessageContent";

export type ArtifactKind =
  | "html"
  | "markdown"
  | "text"
  | "pdf"
  | "docx"
  | "pptx"
  | "xlsx"
  | "image"
  | "file";

export type ArtifactStatus = "creating" | "ready" | "failed";

export type ArtifactPreviewMode =
  | "html"
  | "code"
  | "markdown"
  | "text"
  | "pdf"
  | "image"
  | "table"
  | "slides"
  | "unsupported";

export type ArtifactView = "preview" | "source";

export type Artifact = {
  id: string;
  title: string;
  kind: ArtifactKind;
  mime: string;
  status: ArtifactStatus;
  sourcePath: string | null;
  previewPath?: string | null;
  downloadPath: string | null;
  editable: boolean;
  previewMode: ArtifactPreviewMode;
  exportTargets: ArtifactKind[];
  sizeBytes?: number | null;
  createdAt: string;
  updatedAt: string;
  content?: string;
  language?: string | null;
  source?: HtmlPreviewPayload["source"];
  cacheKey?: string | null;
  previewUrl?: string | null;
  downloadUrl?: string | null;
  summary?: string | null;
  extension?: string | null;
  streaming?: boolean;
  saveStatus?: "saving" | "saved" | "failed";
  toolCallId?: string | null;
  metadata?: Record<string, unknown>;
};

export type ArtifactPreviewPayload = Artifact;

function buildArtifactId(payload: HtmlPreviewPayload) {
  const cacheKey = payload.cacheKey ? `:${payload.cacheKey}` : "";
  if (payload.path) {
    return `path:${payload.path}${cacheKey}`;
  }
  const seed = `${payload.title}:${payload.content.length}:${payload.content.slice(0, 80)}${cacheKey}`;
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) >>> 0;
  }
  return `inline-html:${hash.toString(16)}`;
}

function normalizeArtifactKind(value: string | null | undefined): ArtifactKind {
  if (
    value === "html" ||
    value === "markdown" ||
    value === "text" ||
    value === "pdf" ||
    value === "docx" ||
    value === "pptx" ||
    value === "xlsx" ||
    value === "image" ||
    value === "file"
  ) {
    return value;
  }
  return "file";
}

function normalizePreviewMode(value: string | null | undefined, kind: ArtifactKind, initialView: HtmlPreviewPayload["initialView"]): ArtifactPreviewMode {
  if (
    value === "html" ||
    value === "code" ||
    value === "markdown" ||
    value === "text" ||
    value === "pdf" ||
    value === "image" ||
    value === "table" ||
    value === "slides" ||
    value === "unsupported"
  ) {
    return value;
  }
  if (initialView === "code") return "code";
  if (kind === "html") return "html";
  if (kind === "pdf") return "pdf";
  if (kind === "image") return "image";
  if (kind === "xlsx") return "table";
  if (kind === "pptx") return "slides";
  if (kind === "markdown") return "markdown";
  if (kind === "text") return "text";
  return "unsupported";
}

export function htmlPreviewToArtifact(
  payload: HtmlPreviewPayload & {
    toolCallId?: string | null;
    saveStatus?: "saving" | "saved" | "failed";
  },
): Artifact {
  const now = new Date().toISOString();
  const initialView = payload.initialView ?? "preview";
  const kind = normalizeArtifactKind(payload.kind ?? (payload.contentType === "text/html" ? "html" : null));
  const previewMode = normalizePreviewMode(payload.previewMode, kind, initialView);
  return {
    id: buildArtifactId(payload),
    title: payload.title,
    kind,
    mime: payload.contentType ?? (kind === "html" ? "text/html" : "application/octet-stream"),
    status: payload.streaming || payload.saveStatus === "saving" ? "creating" : payload.saveStatus === "failed" ? "failed" : "ready",
    sourcePath: payload.path ?? null,
    previewPath: payload.path ?? null,
    downloadPath: payload.path ?? null,
    editable: false,
    previewMode,
    exportTargets: ["pdf", "docx"],
    sizeBytes: payload.sizeBytes,
    createdAt: now,
    updatedAt: now,
    content: payload.content,
    language: payload.language ?? "html",
    source: payload.source,
    cacheKey: payload.cacheKey,
    previewUrl: payload.previewUrl,
    downloadUrl: payload.downloadUrl,
    summary: payload.summary,
    extension: payload.extension,
    streaming: payload.streaming,
    saveStatus: payload.saveStatus,
    toolCallId: payload.toolCallId,
  };
}

export function artifactToHtmlPreviewPayload(artifact: Artifact): HtmlPreviewPayload & {
  toolCallId?: string | null;
  saveStatus?: "saving" | "saved" | "failed";
} {
  return {
    content: artifact.content ?? "",
    title: artifact.title,
    source: artifact.source,
    path: artifact.sourcePath,
    streaming: artifact.streaming,
    initialView: artifact.previewMode === "code" ? "code" : "preview",
    language: artifact.language,
    kind: artifact.kind,
    contentType: artifact.mime,
    extension: artifact.extension,
    previewMode: artifact.previewMode,
    previewUrl: artifact.previewUrl,
    downloadUrl: artifact.downloadUrl,
    sizeBytes: artifact.sizeBytes,
    summary: artifact.summary,
    cacheKey: artifact.cacheKey,
    toolCallId: artifact.toolCallId,
    saveStatus: artifact.saveStatus,
  };
}
