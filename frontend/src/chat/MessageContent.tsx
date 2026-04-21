import { Children, isValidElement, useEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";

export type ChatAttachment = {
  id: string;
  filename: string;
  contentType: string;
  path?: string | null;
  previewUrl?: string | null;
  summary?: string | null;
  sizeBytes?: number | null;
};

type MessageContentProps = {
  apiBase: string;
  variant: "assistant" | "user";
  content: string;
  attachments?: ChatAttachment[];
  className?: string;
};

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
    th: [...(defaultSchema.attributes?.th ?? []), "align"],
    td: [...(defaultSchema.attributes?.td ?? []), "align"],
  },
};

const URL_TOKEN_REGEX = /(https?:\/\/[A-Za-z0-9\-._~:/?#[\]@!$&'()*+,;=%]+)/g;
const URL_TRAILING_PUNCTUATION = /[),.;!?，。；：！？、】【」』》〉）]+$/u;

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

function buildAttachmentUrl(apiBase: string, attachment: ChatAttachment) {
  if (attachment.previewUrl) {
    return attachment.previewUrl;
  }
  if (!attachment.path) {
    return null;
  }
  const url = new URL(`${apiBase}/api/workspace/file-content`);
  url.searchParams.set("path", attachment.path);
  return url.toString();
}

function renderAttachmentGrid(apiBase: string, attachments: ChatAttachment[]) {
  if (attachments.length === 0) {
    return null;
  }

  return (
    <div className={joinClassNames("chat-attachment-grid", attachments.length === 1 ? "single" : "multi")}>
      {attachments.map((attachment) => {
        const src = buildAttachmentUrl(apiBase, attachment);
        if (!src) {
          return (
            <div key={attachment.id} className="chat-attachment-card fallback">
              <div className="chat-attachment-fallback">{attachment.filename}</div>
            </div>
          );
        }

        return (
          <a
            key={attachment.id}
            className="chat-attachment-card"
            href={src}
            target="_blank"
            rel="noreferrer"
            title={attachment.summary || attachment.filename}
          >
            <img
              className="chat-attachment-image"
              src={src}
              alt={attachment.summary || attachment.filename}
              loading="lazy"
            />
            <span className="chat-attachment-caption">{attachment.filename}</span>
          </a>
        );
      })}
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

function MarkdownCodeBlock({ children }: ComponentProps<"pre">) {
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

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(codeText);
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
        <button
          type="button"
          className={`chat-code-block-copy ${copyState !== "idle" ? `is-${copyState}` : ""}`}
          onClick={handleCopy}
        >
          {copyState === "copied" ? "已复制" : copyState === "failed" ? "复制失败" : "复制代码"}
        </button>
      </div>
      <pre className="chat-code-block-pre">
        <code className={codeChild.props.className}>{codeText}</code>
      </pre>
    </div>
  );
}

export default function MessageContent({
  apiBase,
  variant,
  content,
  attachments = [],
  className,
}: MessageContentProps) {
  const hasText = Boolean(content.trim());
  const hasAttachments = attachments.length > 0;

  if (variant === "user") {
    return (
      <div className={joinClassNames("chat-message-content", "user", className)}>
        {hasText ? <p className="chat-message-text">{renderUserText(content)}</p> : null}
        {hasAttachments ? renderAttachmentGrid(apiBase, attachments) : null}
      </div>
    );
  }

  return (
    <div className={joinClassNames("chat-message-content", "assistant", className)}>
      <div className="chat-markdown-body">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeRaw, [rehypeSanitize, markdownSchema]]}
          components={{
            a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
            pre: ({ node: _node, ...props }) => <MarkdownCodeBlock {...props} />,
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </div>
  );
}
