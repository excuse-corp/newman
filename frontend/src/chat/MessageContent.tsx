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
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </div>
  );
}
