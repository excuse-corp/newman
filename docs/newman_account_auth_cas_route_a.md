# Newman 账号体系与统一身份认证接入技术方案

版本：v0.1  
日期：2026-07-13  
方案路线：路线 A - 内部账号体系 + CAS Provider

## 1. 背景

Newman 当前的认证机制是单实例访问密钥模式：服务端配置一个全局 `admin_token`，用户通过 `/api/auth/login` 提交该密钥，后端校验通过后把同一个 token 写入 HttpOnly cookie。认证中间件只判断请求是否已认证，不区分具体用户、角色或资源归属。

这种模式适合单人或小范围自用部署，但不适合多人协作、统一身份认证接入、会话隔离、用户管理和审计追踪。

本方案目标是在 Newman 中补一套内部账号体系，同时兼容学校统一身份认证资料包中的 CAS/LDAP 接入能力。

## 2. 设计目标

- 支持 Newman 本地用户、角色、登录会话和 API Token。
- 支持 CAS 单点登录接入统一身份认证平台。
- CAS 登录成功后映射或自动创建 Newman 本地用户。
- 保留现有 `admin_token` 作为首次初始化和紧急恢复通道。
- 第一阶段实现最小可用 RBAC：`owner`、`admin`、`member`、`viewer`。
- 第一阶段优先保护关键资源：会话、自动化任务、记忆、配置管理。
- 为后续 OIDC、飞书、企业微信等登录方式预留 Provider 扩展点。

## 3. 现状基线

当前相关实现：

- `backend/api/auth_utils.py`：全局实例密钥校验、cookie 设置、bootstrap key 管理。
- `backend/api/routes/auth.py`：`/api/auth/status`、`/api/auth/login`、`/api/auth/logout`、`/api/auth/regenerate-token`。
- `backend/api/middleware/auth.py`：请求鉴权中间件，仅判断 authenticated，不注入用户身份。
- `frontend/src/pages/LoginPage.tsx`：登录页只有实例访问密钥输入框。
- `frontend/src/RootPage.tsx`：根据 `/api/auth/status` 决定展示 setup、login 或主应用。

现有问题：

- 无用户模型，无法识别当前操作人。
- 无角色/权限，所有已登录用户都是实例管理员。
- cookie 中直接承载实例密钥，不适合多人使用。
- 无单用户踢下线、禁用、会话撤销能力。
- 无资源 owner，无法做到会话和任务隔离。
- 无外部身份源扩展点。

## 4. 推荐总体架构

核心原则：外部认证只负责证明“这个人是谁”，Newman 自己负责用户、角色、资源权限和登录会话。

```text
Browser
  |
  | Newman session cookie
  v
Newman Auth Middleware
  |
  +-- AuthSessionStore: session_id -> user_id / role / auth_method
  |
  +-- AuthProvider
        |
        +-- LocalProvider: 本地账号密码
        +-- CasProvider: 学校统一身份认证 CAS
        +-- AdminTokenProvider: bootstrap / recovery
```

## 5. 数据存储方案

第一阶段建议使用 SQLite，路径为：

```text
backend_data/auth/newman_auth.sqlite
```

原因：

- 账号、会话、唯一索引、过期清理适合数据库。
- 不强依赖外部 Postgres，部署简单。
- 可以后续迁移到 Postgres。
- 比 JSON 文件更适合并发更新和唯一约束。

## 6. 数据模型

### 6.1 users

```sql
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  display_name TEXT,
  email TEXT,
  role TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_login_at TEXT
);
```

字段说明：

- `role`：`owner`、`admin`、`member`、`viewer`。
- `status`：`active`、`disabled`。
- `username`：Newman 内部用户名，CAS 用户默认使用统一认证返回的用户名/学工号。

### 6.2 user_identities

```sql
CREATE TABLE user_identities (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  external_id TEXT NOT NULL,
  username TEXT,
  raw_profile_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(provider, external_id),
  FOREIGN KEY(user_id) REFERENCES users(id)
);
```

用途：

- 绑定 Newman 用户与外部身份源。
- 一个用户未来可绑定多个身份：`local`、`cas`、`ldap`、`feishu` 等。

### 6.3 local_credentials

```sql
CREATE TABLE local_credentials (
  user_id TEXT PRIMARY KEY,
  password_hash TEXT NOT NULL,
  password_updated_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id)
);
```

密码 hash 建议使用 `argon2id`，备选 `bcrypt`。

### 6.4 auth_sessions

```sql
CREATE TABLE auth_sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  token_hash TEXT UNIQUE NOT NULL,
  auth_method TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_seen_at TEXT,
  ip TEXT,
  user_agent TEXT,
  revoked_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id)
);
```

说明：

- 浏览器 cookie 中只放随机 session token。
- 服务端只存 `token_hash`，不存明文 token。
- `auth_method` 可为 `local`、`cas`、`admin_token`。

### 6.5 api_tokens

```sql
CREATE TABLE api_tokens (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  token_hash TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  scopes TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT,
  revoked_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id)
);
```

用途：

- 代替长期使用全局 `admin_token`。
- 支持 CLI、自动化、外部系统调用 Newman API。

## 7. 配置设计

扩展 `auth` 配置，保留现有字段并新增 providers。

```yaml
auth:
  enabled: true

  # 兼容旧机制：仅用于首次初始化 / 紧急恢复
  admin_token: null
  bootstrap_key_required: false

  cookie_name: "newman_session"
  cookie_secure: false
  cookie_samesite: "lax"
  session_ttl_hours: 168

  providers:
    local:
      enabled: true
      allow_password_login: true

    cas:
      enabled: false
      server_url: "http://ids.zuel.edu.cn/authserver"
      service_base_url: "https://newman.example.com"
      auto_create_users: true
      default_role: "member"
      allowed_usernames: []
      allowed_domains: []
      logout_redirect_url: "/login"

    ldap:
      enabled: false
      host: "10.175.205.200"
      port: 389
      base_dn: "dc=znufe,dc=edu,dc=cn"
      bind_dn: null
      bind_password: null
      user_filter: "(uid={username})"
      profile_sync: true
```

统一认证资料包中的核心地址：

```text
CAS 认证地址: http://ids.zuel.edu.cn/authserver
CAS 注销地址: http://ids.zuel.edu.cn/authserver/logout
LDAP 地址: 10.175.205.200:389
LDAP baseDn: dc=znufe,dc=edu,dc=cn
```

LDAP 建议作为 profile sync 使用，不建议第一阶段作为主登录方式。

## 8. 后端模块设计

新增模块：

```text
backend/auth/
  __init__.py
  models.py
  store.py
  password.py
  sessions.py
  permissions.py
  cas_client.py
  providers/
    __init__.py
    base.py
    local.py
    cas.py
    admin_token.py
```

职责划分：

- `models.py`：`User`、`CurrentUser`、`AuthSession`、`UserIdentity`。
- `store.py`：SQLite 建表、迁移、CRUD、唯一约束。
- `password.py`：密码 hash 和校验。
- `sessions.py`：session token 生成、hash、创建、撤销、过期清理。
- `permissions.py`：角色与资源权限判断。
- `cas_client.py`：CAS `serviceValidate` 请求和 XML 解析。
- `providers/base.py`：定义 `AuthProvider` 协议。
- `providers/local.py`：本地账号密码登录。
- `providers/cas.py`：CAS 登录、回调、用户映射。
- `providers/admin_token.py`：admin token recovery。

改造模块：

- `backend/api/auth_utils.py`
  - 保留 bootstrap/admin token 工具。
  - 新增基于 session cookie 的认证解析。
- `backend/api/middleware/auth.py`
  - 注入 `request.state.user`。
  - 注入 `request.state.auth_method`。
- `backend/api/routes/auth.py`
  - 改造本地登录。
  - 增加 CAS 登录、回调、注销。
  - 增加 `/api/auth/me`。
- `backend/api/routes/bootstrap.py`
  - 首次初始化时创建 owner 用户。
  - admin token 变为 recovery token。

## 9. 接口设计

### 9.1 查询认证状态

```http
GET /api/auth/status
```

返回：

```json
{
  "enabled": true,
  "needs_setup": false,
  "authenticated": true,
  "auth_method": "cas",
  "admin_token_configured": true,
  "user": {
    "id": "usr_xxx",
    "username": "20230001",
    "display_name": "张三",
    "email": null,
    "role": "member"
  },
  "providers": {
    "local": {
      "enabled": true
    },
    "cas": {
      "enabled": true,
      "login_url": "/api/auth/cas/login"
    }
  }
}
```

### 9.2 本地账号登录

```http
POST /api/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "..."
}
```

兼容期内可支持旧参数：

```json
{
  "admin_token": "..."
}
```

但 `admin_token` 登录应标记为 `auth_method=admin_token`，并限制为 owner/recovery 场景。

### 9.3 当前用户信息

```http
GET /api/auth/me
```

返回：

```json
{
  "user": {
    "id": "usr_xxx",
    "username": "admin",
    "display_name": "Admin",
    "email": null,
    "role": "owner",
    "status": "active"
  },
  "auth_method": "local"
}
```

### 9.4 注销

```http
POST /api/auth/logout
```

行为：

- 撤销当前 Newman auth session。
- 清除 Newman session cookie。
- 不强制退出 CAS 全局登录态。

### 9.5 CAS 登录

```http
GET /api/auth/cas/login?redirect=/
```

行为：

```text
1. 校验 redirect，只允许站内路径。
2. 生成 service:
   https://newman.example.com/api/auth/cas/callback
3. 记录临时 state，可放入短 TTL cookie 或服务端临时表。
4. 302 跳转到:
   http://ids.zuel.edu.cn/authserver/login?service=<encoded_service>
```

### 9.6 CAS 回调

```http
GET /api/auth/cas/callback?ticket=ST-xxx
```

行为：

```text
1. 使用完全相同的 service 调 CAS 校验接口:
   /authserver/serviceValidate?service=<service>&ticket=<ticket>
2. 解析 CAS 返回 XML。
3. 提取 principal:
   external_id = cas:user
   username = cas:user
4. 查 user_identities(provider='cas', external_id)。
5. 若不存在且 auto_create_users=true，则创建 Newman 用户。
6. 若用户 disabled，则拒绝登录。
7. 创建 Newman auth_session。
8. 写 Newman session cookie。
9. 302 回前端 redirect。
```

### 9.7 CAS 全局注销

```http
GET /api/auth/cas/logout
```

行为：

```text
1. 撤销 Newman 当前 session。
2. 清 Newman cookie。
3. 302 到:
   http://ids.zuel.edu.cn/authserver/logout?service=<newman_login_url>
```

## 10. CAS 接入细节

登录跳转地址：

```text
http://ids.zuel.edu.cn/authserver/login?service=<encoded_service>
```

票据校验地址：

```text
http://ids.zuel.edu.cn/authserver/serviceValidate?service=<encoded_service>&ticket=<ticket>
```

注销地址：

```text
http://ids.zuel.edu.cn/authserver/logout?service=<encoded_redirect>
```

关键要求：

- 登录时生成的 `service` 和 callback 校验时传入的 `service` 必须完全一致。
- `service_base_url` 应由配置指定，不要完全依赖请求 Host，避免反向代理和 Host header 风险。
- `redirect` 只能接受站内路径，例如 `/`、`/settings`，不能接受完整外部 URL。
- callback 必须处理 CAS 错误响应。

CAS 成功响应通常类似：

```xml
<cas:serviceResponse>
  <cas:authenticationSuccess>
    <cas:user>20230001</cas:user>
    <cas:attributes>
      <cas:cn>张三</cas:cn>
      <cas:mail>zhangsan@example.edu.cn</cas:mail>
    </cas:attributes>
  </cas:authenticationSuccess>
</cas:serviceResponse>
```

字段映射建议：

```text
external_id = cas:user
username = cas:user
display_name = cn / name / displayName / username
email = mail / email
raw_profile_json = 完整 attributes
```

如果 CAS 不返回姓名、邮箱等字段，可用 LDAP profile sync 补充。

## 11. LDAP 补充资料同步

LDAP 不建议第一阶段作为主登录方式。建议作为 CAS 登录成功后的资料补充：

```text
1. CAS 返回 username。
2. 若 ldap.profile_sync=true，则按 user_filter 查询：
   (uid={username})
3. 从 LDAP 读取 cn、mail、department 等字段。
4. 更新 users.display_name / users.email / raw_profile_json。
5. LDAP 失败不阻断登录，只记录 warning。
```

资料包中的 LDAP 参数：

```text
host: 10.175.205.200
port: 389
baseDn: dc=znufe,dc=edu,dc=cn
bindDn 示例: uid=xxxxxx,ou=1002,ou=People,dc=znufe,dc=edu,dc=cn
```

LDAP bind 账号密码应通过环境变量配置，不写入仓库。

## 12. 权限模型

### 12.1 角色定义

```text
owner
- 管理全部用户、配置、模型、全局技能、所有会话。
- 可创建/删除 admin。
- 可执行 recovery 操作。

admin
- 管理用户。
- 查看或管理所有会话。
- 管理自动化任务。
- 不能移除 owner。
- 不能修改核心安全配置。

member
- 创建和管理自己的会话、任务、记忆。
- 使用已启用工具和技能。

viewer
- 只读自己的会话。
- 不能运行任务，不能修改文件。
```

### 12.2 权限函数

建议新增 FastAPI dependency 或工具函数：

```python
require_user()
require_role("admin")
require_owner()
require_owner_or_self(resource_owner_id)
require_session_access(session_id, action="read")
require_session_access(session_id, action="write")
```

中间件只负责认证，不在中间件里写复杂业务权限。

## 13. 资源归属与隔离

第一阶段至少为这些资源增加归属：

### 13.1 Sessions

短期可放在 `SessionRecord.metadata`：

```json
{
  "owner_user_id": "usr_xxx",
  "visibility": "private"
}
```

改造规则：

- 创建 session 时写入当前 `user_id`。
- list sessions 默认只返回自己的 session。
- owner/admin 可通过参数查看全部。
- get/update/delete session 前校验权限。

### 13.2 Scheduler Tasks

新增：

```text
created_by_user_id
owner_user_id
```

规则：

- member 只能管理自己的任务。
- admin/owner 可查看全部任务。
- scheduler 执行任务时应带上任务 owner 的身份上下文。

### 13.3 Memory

建议区分个人记忆和全局记忆：

```text
backend_data/memory/users/{user_id}/USER.md
backend_data/memory/global/
```

规则：

- member 默认只读写自己的 memory。
- owner/admin 可管理 global memory。

### 13.4 Audit

事件 payload 增加：

```json
{
  "user_id": "usr_xxx",
  "username": "20230001",
  "auth_method": "cas"
}
```

用于追踪谁触发了工具、文件修改、审批和任务。

### 13.5 Workspace Outputs

建议输出路径从：

```text
outputs/chat/{session_id}/...
```

调整为：

```text
outputs/chat/{user_id}/{session_id}/...
```

短期也可以先维持原路径，但在附件/输出访问接口处校验 session owner。

## 14. 兼容与迁移策略

### 14.1 首次启用账号体系

```text
1. 检查 auth sqlite 是否存在 owner。
2. 若不存在 owner，则进入 setup。
3. setup 完成时创建 owner 用户。
4. 生成或保留 admin_token 作为 recovery token。
```

### 14.2 旧 session 归属

现有 session 没有 `owner_user_id`。迁移策略：

```text
1. 如果系统只有一个 owner：
   自动把旧 session 归属给 owner。
2. 如果已有多个用户：
   旧 session 标记为 legacy/unassigned。
   仅 owner/admin 可见。
   后台提供批量认领/分配。
```

### 14.3 旧 admin_token

兼容期内：

- `Bearer admin_token` 仍可通过。
- `/api/auth/login` 可继续接受 `admin_token`。
- 登录结果标记为 `auth_method=admin_token`。
- 只授予 owner/recovery 能力。
- 前端提示迁移到本地账号或 CAS 登录。

后续版本：

- admin token 只允许命令行 recovery 或 bootstrap 使用。
- 日常 API 调用改用个人 API Token。

## 15. 前端改造

### 15.1 RootPage

`/api/auth/status` 返回结构扩展后，RootPage 判断逻辑变为：

```text
1. needs_setup -> SetupPage
2. authenticated -> App
3. 未登录 -> LoginPage
4. LoginPage 根据 providers 展示可用登录方式
```

### 15.2 LoginPage

登录页改为多入口：

```text
Newman 登录页

[使用统一身份认证登录]

账号密码登录
- 用户名
- 密码
- 登录按钮

恢复入口
- 实例恢复密钥 / admin token
```

CAS 登录按钮直接跳转：

```ts
window.location.href = `${apiBase}/api/auth/cas/login?redirect=/`
```

### 15.3 用户与管理员页面

新增或扩展设置页：

- 当前用户信息。
- 修改本地密码。
- 登录会话列表与撤销。
- API Token 管理。
- 用户列表。
- 禁用用户。
- 调整角色。
- CAS/LDAP 配置状态。

## 16. 安全要求

- Cookie 中只放随机 session token，不放 `admin_token`。
- 服务端只保存 session token hash。
- session token 至少 32 bytes 随机值。
- 密码 hash 使用 `argon2id` 或 `bcrypt`。
- 线上必须设置 `cookie_secure=true`。
- `cookie_samesite` 默认 `lax`。
- CAS callback 的 `redirect` 必须限制为站内路径。
- CAS `service_base_url` 应显式配置。
- 管理接口必须做角色校验。
- 用户禁用后应撤销其全部 auth sessions。
- 用户角色变更、禁用、登录失败、CAS callback 失败都应写审计日志。
- LDAP bind 密码不得写入代码或普通文档，应走环境变量。

## 17. 实施里程碑

### Phase 1: AuthStore 与 owner 用户

- 新增 `backend/auth/store.py`。
- 初始化 SQLite 表。
- setup 完成时创建 owner。
- 增加 `/api/auth/me`。
- 单元测试覆盖用户创建、唯一约束、session 创建和过期。

### Phase 2: Session Cookie 替换

- 新增 Newman session token。
- 中间件从 session cookie 解析 `CurrentUser`。
- 旧 admin token 进入 recovery provider。
- `/api/auth/status` 返回 user 和 providers。
- 前端 RootPage 兼容新状态结构。

### Phase 3: 本地账号密码登录

- 新增 `local_credentials`。
- `/api/auth/login` 支持 username/password。
- 登录页支持账号密码表单。
- owner 可创建用户。
- 支持 logout 撤销当前 session。

### Phase 4: CAS Provider

- 新增 CAS 配置。
- 实现 `/api/auth/cas/login`。
- 实现 `/api/auth/cas/callback`。
- 实现 CAS XML 解析和错误处理。
- CAS 用户自动创建/绑定 Newman 用户。
- 登录页展示统一身份认证按钮。

### Phase 5: 资源归属与最小权限隔离

- session 创建写 `owner_user_id`。
- session list/get/update/delete 做权限过滤。
- scheduler task 增加 owner。
- memory 切分 user/global。
- audit event 增加 user 信息。

### Phase 6: 管理员能力

- 用户列表。
- 禁用/启用用户。
- 调整角色。
- 撤销用户 session。
- API Token 管理。

### Phase 7: LDAP Profile Sync

- 增加 LDAP client。
- CAS 登录后按 username 查询 LDAP。
- 同步 display_name、email、department 等字段。
- 失败只记录 warning，不阻断登录。

## 18. 第一版建议范围

第一版建议交付：

- SQLite AuthStore。
- 本地 owner 账号。
- Newman session cookie。
- CAS 登录。
- `owner/admin/member/viewer`。
- session 级资源隔离。
- admin token recovery。
- 简单用户列表和禁用用户。

第一版暂不建议交付：

- 完整组织架构。
- 复杂资源共享权限。
- OAuth/OIDC。
- CAS Single Logout 后端通知处理。
- 强依赖 LDAP 的主登录。
- 全量 workspace 文件级权限。

## 19. 风险与应对

### CAS service 不一致导致登录失败

风险：登录跳转和 ticket 校验使用的 `service` 字符串不完全一致。

应对：统一由 `CasProvider.build_service_url()` 生成，并在 login/callback 中复用同一逻辑。

### 反向代理 Host 造成 callback URL 错误

风险：部署在 Nginx/HTTPS 后，后端看到的是内部 Host。

应对：必须配置 `auth.providers.cas.service_base_url`，不要仅依赖请求 Host。

### 旧 session 无 owner

风险：启用账号体系后旧数据不可见。

应对：单 owner 自动归属；多用户场景进入 legacy 管理视图。

### admin token 兼容带来权限绕过

风险：旧 token 继续具备全局权限。

应对：兼容期内限制为 recovery/owner，并在 UI 提示迁移；后续降级为仅 bootstrap。

### LDAP 不稳定影响登录

风险：LDAP 网络或账号配置问题导致 CAS 用户无法登录。

应对：LDAP 只做资料同步，不阻断 CAS 主认证。

## 20. 验收标准

- 未登录访问受保护 API 返回 401。
- 登录后 `request.state.user` 可获得 `user_id`、`username`、`role`、`auth_method`。
- 本地账号可登录、注销、撤销 session。
- CAS 登录可完成跳转、ticket 校验、用户创建、session cookie 写入。
- member 只能看到自己的 session。
- owner/admin 可查看全部 session。
- disabled 用户无法登录，已登录 session 被撤销。
- 旧 admin token 仍可用于 recovery，但不作为普通多人登录方案。
- 前端登录页可展示 CAS 登录、本地登录和恢复入口。
- 关键认证和权限路径有单元测试或集成测试覆盖。

