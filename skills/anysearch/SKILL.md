---
name: anysearch
description: 使用 AnySearch 检索公开网络信息、时效事实和网页资料。遇到新闻、人物、体育、比赛、百科、产品、文档、事实核验或任何需要先发现信息来源的请求时，先读此 skill 并用其 CLI 搜索；仅在用户给出具体 URL 或搜索已返回 URL 后才使用 fetch_url 抓取页面。
---

# AnySearch

## Route Public-Web Requests

- Use this skill for any public-information request whose answer is not already available locally, especially current events, sports, people, products, documentation, fact checks, and general web research.
- Read this `SKILL.md` before the first search action, then run the configured CLI from `runtime.conf`.
- Do not use `fetch_url` to discover an unknown page or answer a broad question. Use it only for a URL supplied by the user or returned by AnySearch when page-level detail is required.
- Answer directly without a network call only when the request is stable common knowledge and does not need verification or current information.

## Runtime

Use the command in `runtime.conf`. In this workspace:

```bash
python3 /root/newman/skills/anysearch/scripts/anysearch_cli.py
```

Do not run `doc` for routine requests. Use it only when command arguments are unclear or the CLI fails unexpectedly.

## Commands

```bash
# General search
python3 /root/newman/skills/anysearch/scripts/anysearch_cli.py search "query" --max_results 5

# Preferred for two to five independent queries: run separate search commands in parallel
python3 /root/newman/skills/anysearch/scripts/anysearch_cli.py search "q1" --max_results 5
python3 /root/newman/skills/anysearch/scripts/anysearch_cli.py search "q2" --max_results 5

# If batch_search is required, write a JSON file first and pass it with @
python3 /root/newman/skills/anysearch/scripts/anysearch_cli.py batch_search --queries @queries.json

# Fetch the body of a URL already identified by the user or search results
python3 /root/newman/skills/anysearch/scripts/anysearch_cli.py extract --url "https://example.com/page"
```

## CLI Usage Notes

- For multiple independent queries, prefer several `search` calls over `batch_search` with inline JSON. In terminal environments, long or Chinese JSON arguments can be misparsed as file paths and trigger `File name too long`.
- Do not inline complex `--queries` JSON in a terminal command, especially when it contains Chinese text, nested quotes, commas, or many query objects.
- If batch search is necessary, first write `queries.json` in a writable working directory (not `/tmp`; use the current workspace or `test_runtimespace` when available). The file must contain a UTF-8 JSON array of 1-5 query objects. Then run `batch_search --queries @queries.json`.
- If `@queries.json` is unsupported or fails, fall back to separate `search` calls instead of retrying the same inline JSON command.
- Keep vertical search discovery (`get_sub_domains`) separate from query execution; cache results within the session.

## Vertical Search

For requests that clearly belong to finance, academic, travel, health, legal, security, code, business, energy, environment, agriculture, gaming, film, IP, resource, or social media, discover the route first:

```bash
python3 /root/newman/skills/anysearch/scripts/anysearch_cli.py get_sub_domains --domain <domain>
```

Include every required parameter returned by `get_sub_domains`; use an empty string only when a required value is inapplicable. When the domain is uncertain, use general search first or run general and vertical queries as separate `search` calls. If `batch_search` is used, pass query objects through `@queries.json` rather than inline JSON.

## Credentials And Failures

- `ANYSEARCH_API_KEY` is supplied by Newman from the project `.env`; do not print or expose it.
- If the request fails because the service, network, or quota is unavailable, report the failure before considering another search method.
- Do not send passwords, personal data, or trade secrets in search queries.
