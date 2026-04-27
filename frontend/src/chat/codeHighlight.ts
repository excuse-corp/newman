import Prism from "prismjs";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-css";
import "prismjs/components/prism-json";
import "prismjs/components/prism-jsx";
import "prismjs/components/prism-markdown";
import "prismjs/components/prism-python";
import "prismjs/components/prism-sql";
import "prismjs/components/prism-tsx";
import "prismjs/components/prism-typescript";
import "prismjs/components/prism-yaml";

export function escapeCodeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function resolvePrismLanguage(language: string | null) {
  if (!language) {
    return null;
  }

  const normalized = language.toLowerCase();
  const aliases: Record<string, string> = {
    html: "markup",
    js: "javascript",
    md: "markdown",
    plaintext: "text",
    py: "python",
    shell: "bash",
    sh: "bash",
    ts: "typescript",
    yml: "yaml",
  };

  const prismLanguage = aliases[normalized] ?? normalized;
  return Prism.languages[prismLanguage] ? prismLanguage : null;
}

export function inferLanguageFromPath(path: string | null | undefined) {
  if (!path) {
    return null;
  }

  const lower = path.toLowerCase();
  if (lower.endsWith(".py")) return "python";
  if (lower.endsWith(".ts")) return "typescript";
  if (lower.endsWith(".tsx")) return "tsx";
  if (lower.endsWith(".js")) return "javascript";
  if (lower.endsWith(".jsx")) return "jsx";
  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".css")) return "css";
  if (lower.endsWith(".sql")) return "sql";
  if (lower.endsWith(".md")) return "markdown";
  if (lower.endsWith(".yaml") || lower.endsWith(".yml")) return "yaml";
  if (lower.endsWith(".sh") || lower.endsWith(".bash")) return "bash";
  if (lower.endsWith(".html") || lower.endsWith(".htm")) return "html";
  return null;
}

export function highlightCode(value: string, language: string | null) {
  const prismLanguage = resolvePrismLanguage(language);
  return {
    language: prismLanguage,
    html: prismLanguage ? Prism.highlight(value, Prism.languages[prismLanguage], prismLanguage) : escapeCodeHtml(value),
  };
}
