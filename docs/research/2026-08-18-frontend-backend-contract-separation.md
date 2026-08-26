# Protein Workbench 前后端契约分离调研

- 日期：2026-08-18
- 状态：历史调研与未来客户端设计输入，尚未形成 ADR；其中旧前端事实固定于已退役实现
- 范围：可独立构建、发布和部署的 React 前端与 Python 后端之间的公共契约
- 来源边界：外部事实仅使用官方规范、官方文档和第一方源码；后端项目事实来自调研时仓库，已退役前端事实使用固定 commit permalink

## 1. 结论摘要

当前后端已经有一个很好的分离起点：
[`protein_workbench_public/resources/v2/bundle.json`](../../protein_workbench_public/resources/v2/bundle.json)
是单一公共 payload contract；FastAPI 路由从其中读取 route、request schema、response
schema 和 event-stream 定义；source wheel 与 installed wheel 已验证 bundle 和 Catalog
identity 相同。

但是，2026-08-18 当时仍存在、后来已删除的旧前端没有真正消费这条 seam。它当时：

- 手写 `/api/v2/...` URL；
- 手写不完整的 TypeScript DTO；
- 用 `as T` / `as unknown as ...` 信任服务端 JSON，而不做运行时验证；
- 用 `window.location.host` 推导 WebSocket 地址；
- 在上传流程中硬编码 `protein_io.import_structure` 和
  `protein_io.import_sequence`；
- 只按 Port Type 的 `id@version` 比较连接，忽略 exact contract digest；
- 没有读取 `/api/v2/protocol`、验证协议版本或验证 Catalog 声明的
  `protocol_digest`。

因此，本项目不需要在 React 与 FastAPI 之间增加 BFF、共享 Python model 或手写
DTO；需要的是把现有 public bundle 提升为真正的 **language-neutral contract
package**，并让前端的唯一网络入口成为生成/验证驱动的 **Protocol Adapter**。

建议采用以下边界：

```text
React feature modules
  Project / Canvas / Prompt Studio / Run / Results
                     |
                     v
Frontend Protocol Adapter
  generated DTOs + runtime validators + operation table
  HTTP/WS URL construction + error mapping + replay/resume
                     |
             public protocol only
                     |
                     v
Python public handlers
  request admission + application services + response validation
                     |
                     v
core / datatypes / modules / adapters
```

最重要的具体决定是：

1. **继续保留一个 authored protocol source。** 近期不为追求标准化而重写现有
   bundle；从它确定性生成 OpenAPI 3.1、TypeScript declarations、浏览器 runtime
   validators 和 operation table。生成物不可手工编辑。
2. **payload schema 正式声明 JSON Schema Draft 2020-12 dialect。** 当前 bundle
   没有 `$schema` 或 `$id`；按 JSON Schema Core，根 schema 缺少 `$schema` 时 dialect
   行为由实现决定，不适合作为跨语言边界。
3. **前端不得直接调用 `fetch` 或 `new WebSocket`。** 只有 Protocol Adapter 可以
   知道 route、header、status、cursor 和 wire DTO。
4. **Catalog 继续拥有科学定义。** 前端只拥有 presentation；表单、Port、Binding、
   Metric、Method、unit、direction 和可用性都从 Catalog 读取，不能复制到 React
   常量。
5. **复杂 authoring 通过 capability contract 解耦。** Prompt Studio 不硬编码一组
   `prompt_authoring.*` Node ID；后端暴露版本化的 authoring capability/recipe，接收
   Prompt 编辑文档并编译成显式 Node 子图。
6. **UI layout 是前端拥有的 opaque state。** 后端只保存带 media type、UI schema
   ID、digest、size 和 revision/ETag 的 payload，不解释 React Flow 坐标、面板和颜色。
7. **独立部署不等于必须跨源。** 前端静态产物和 Python wheel 独立构建；推荐部署时
   仍用反向代理形成同源 URL。直接跨源作为受支持模式时，再显式配置 CORS、暴露
   response headers，并为 WebSocket 配置 Origin/subprotocol。
8. **在前端实现开始前做一次 pre-release contract reset，然后冻结 v2 基线。** reset
   时修复 `Digest` header、参数 schema、并发控制、分页和缺失的产品资源；之后 v2
   只接受明确兼容的变化，breaking change 进入 `/api/v3`，不增加兼容 shim。

## 2. 外部规范事实与它们能支持的结论

本节只陈述外部规范事实；下一节开始给出本项目观察和建议。

### 2.1 JSON Schema 2020-12

**外部事实：** JSON Schema Core 把 `$schema` 同时定义为 dialect identifier 和对应
meta-schema 的标识；规范建议在根 schema 中使用 `$schema`。如果根 schema 不包含
`$schema`，如何解释 schema 是 implementation-defined。`$id` 则提供 schema 的 canonical
URI，`$defs` 用于复用 schema。参见
[JSON Schema Core 2020-12 §8.1.1、§8.2](https://json-schema.org/draft/2020-12/json-schema-core#section-8.1.1)。

**外部事实：** JSON Schema 的 assertion 用于判断实例是否满足约束；annotation
供应用程序使用。`title`、`description`、`default`、`deprecated`、`readOnly`、
`writeOnly` 和 `examples` 属于 metadata annotation，其中 `title` / `description`
明确可以用于 UI 展示；`default` 不等于 validator 自动把值写入实例。参见
[JSON Schema Validation 2020-12 §9](https://json-schema.org/draft/2020-12/json-schema-validation#section-9)。

**外部事实：** `additionalProperties` 未声明时与 empty schema 具有相同 assertion
行为，即未知属性默认被允许；若希望 closed object，需要显式使用
`additionalProperties: false` 或等价的 2020-12 结构。参见
[JSON Schema Core 2020-12 §10.3.2.3](https://json-schema.org/draft/2020-12/json-schema-core#section-10.3.2.3)。

由这些事实只能推出：跨语言 payload 应显式选择 dialect、声明 object openness，并
用同一 schema 做 runtime validation；它们不能单独决定 Workbench 应使用哪个 UI
framework 或 endpoint 形状。

### 2.2 OpenAPI 3.1

**外部事实：** OpenAPI 是 language-neutral HTTP API description；3.1 的 Schema
Object 使用 JSON Schema 2020-12 parsing requirements。OpenAPI Object 可以通过
`jsonSchemaDialect` 声明 Schema Object dialect，并建议显式声明以提高互操作性。参见
[OpenAPI 3.1.1 §4.3.1、§4.8.24](https://spec.openapis.org/oas/v3.1.1.html#schema-object)。

**外部事实：** OpenAPI 可以描述 path/query/header parameters、request body、不同
status 的 response、media types、binary content 和 reusable components；允许以
`x-` 开头的 Specification Extensions 承载标准未覆盖的信息。参见
[OpenAPI 3.1.1 §4.8](https://spec.openapis.org/oas/v3.1.1.html#schema) 和
[§4.9](https://spec.openapis.org/oas/v3.1.1.html#specification-extensions)。

由这些事实可知 OpenAPI 适合作为当前 REST operation table 的标准投影；但 OpenAPI
本身不能替代 Workbench 已有的 Run Ledger cursor、replay-to-live transition 和完整
WebSocket message semantics。因此本项目不应手写第二份 OpenAPI source；应从唯一
bundle 确定性生成 OpenAPI，并用 `x-protein-workbench-*` 指向 event-stream contract。

### 2.3 TypeScript 与 runtime validation

**外部事实：** TypeScript 编译完成后会擦除 type information；类型不改变 JavaScript
运行时行为，也不验证网络收到的 JSON。参见
[TypeScript Handbook: Erased Types](https://www.typescriptlang.org/docs/handbook/typescript-from-scratch.html#erased-types)。

**外部事实：** `json-schema-to-typescript` 可以从 JSON Schema 生成 TypeScript type
declarations；它生成的是类型，不是网络边界 runtime validator。参见
[项目第一方 README](https://github.com/bcherny/json-schema-to-typescript)。

**外部事实：** Ajv 官方文档提供 Draft 2020-12 validator 入口和把 schema 编译成
validation function / standalone module 的能力。参见
[Ajv JSON Schema versions](https://ajv.js.org/json-schema.html) 和
[Ajv CLI compile](https://ajv.js.org/packages/ajv-cli.html)。

所以，生成 TypeScript declarations 与 runtime validation 是两个不同交付物。仅把
`response.json()` cast 成 interface 并没有建立公共契约边界。

### 2.4 HTTP concurrency、integrity 和 errors

**外部事实：** HTTP strong validator 可用于避免 lost update；`If-Match` 在状态修改
请求中常用于防止多个 user agent 意外覆盖，失败时 origin server 可以返回 412。
参见 [RFC 9110 §8.8.1、§13.1.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.1)。

**外部事实：** RFC 9530 定义 `Content-Digest` 用于 HTTP message content bytes，
定义 `Repr-Digest` 用于 selected representation，并明确废弃 RFC 3230 的 `Digest`
和 `Want-Digest` header。新字段使用 Structured Fields，例如 SHA-256 值是 base64 byte
sequence，而不是项目内部的 `sha256:<hex>` 字符串。参见
[RFC 9530 §1.3、§2](https://www.rfc-editor.org/rfc/rfc9530.html#section-2)。

**外部事实：** RFC 9530 明确说明 Integrity fields 与 `Content-Encoding` 绑定，同一资源
采用不同 content coding 时可能得到不同 digest。Fetch 在向 JavaScript 暴露 response body
前会处理并解码受支持的 content codings。因此，启用 gzip/br 时，浏览器从 `arrayBuffer()`
取得的解码后 bytes 不能直接重算针对编码后 HTTP message content 的 `Content-Digest`。参见
[RFC 9530 §1.2、§6.5](https://www.rfc-editor.org/rfc/rfc9530.html#section-1.2) 和
[Fetch：handle content codings](https://fetch.spec.whatwg.org/#handle-content-codings)。

**外部事实：** RFC 9457 的 Problem Details 是可复用的 HTTP error format，但规范也
明确表示：若应用已经有更合适的 application-specific format，继续使用该格式可能更好；
消费者不应解析 human-readable `detail` 来决定程序行为。参见
[RFC 9457 §1、§3.1.4、§4](https://www.rfc-editor.org/rfc/rfc9457.html)。

因此，本项目应采用标准 `ETag` / `If-Match`。`Content-Digest` 可以表达 transport content
integrity，但浏览器不能在任意压缩代理后声称已经重算验证它；浏览器应对解析后的 bundle
执行 RFC 8785 canonicalization，重算 Workbench domain digest，并与 protocol 声明的
domain-digest field 比较。只有强制 `Content-Encoding: identity` 或能够访问原始编码 bytes
的客户端才验证 `Content-Digest`。无需为了“看起来标准”而立即把已经闭合、机器可判定的
structured error vocabulary 改写成 Problem Details。错误的 `code` 和 typed `details` 比
message string 更重要。

### 2.5 WebSocket 与浏览器跨源行为

**外部事实：** RFC 6455 定义 WebSocket framing、opening/closing handshake、status
code 和 subprotocol negotiation；application-level message、resume cursor 和 replay
语义必须由应用协议定义。规范还说明 breaking subprotocol 可以通过改变 subprotocol
name 来版本化。参见
[RFC 6455 §1.9、§4、§7](https://www.rfc-editor.org/rfc/rfc6455.html)。

**外部事实：** 浏览器 WebSocket handshake 会发送 `Origin`；server 可以据此决定是否
接受连接。RFC 6455 还建议 abnormal closure 后的重连使用随机初始延迟和逐渐增加的
backoff，避免所有客户端立即持续重连。参见
[RFC 6455 §4.1、§7.2.3](https://www.rfc-editor.org/rfc/rfc6455.html#section-7.2.3)。

**外部事实：** Fetch 的 CORS filtered response 只向 JavaScript 暴露 safelisted 或
`Access-Control-Expose-Headers` 明确列出的 response header。参见
[WHATWG Fetch Standard: CORS protocol and credentials](https://fetch.spec.whatwg.org/#http-new-header-syntax)。

因此独立源部署不仅是换一个 base URL：Typed Value 当前依赖的 ETag、digest 和多个
`X-*` headers 必须被 CORS 暴露；WebSocket URL、Origin policy、subprotocol 和 reconnect
都必须进入 Protocol Adapter，而不能散落在 React component。

### 2.6 Cursor pagination 与版本

**外部事实：** HTTP 没有规定一种通用 cursor payload。RFC 8288 标准化了 Web Link 和
`next` / `previous` relation，可用于暴露下一页 URI；cursor 本身的内容与稳定性仍由
application contract 定义。参见
[RFC 8288 §3](https://www.rfc-editor.org/rfc/rfc8288.html#section-3)。

**外部事实：** Semantic Versioning 要求先声明清楚 public API；incompatible API
change 增加 major，backward-compatible functionality 增加 minor，backward-compatible
fix 增加 patch；pre-release identifier 表示版本不稳定且可能不满足正常版本所表达的
兼容性。参见 [SemVer 2.0.0](https://semver.org/spec/v2.0.0.html)。

这里不意味着本项目必须把所有科学 Contract 都绑在一个 SemVer 上。Protocol、Workflow
schema、Catalog Contract、Port Value 和前端 UI state 是不同演化轴，必须分别标识。

## 3. 当前项目接缝审计

### 3.1 已有的正确基础

当前 bundle：

- namespace 为 `protein-workbench-public/v2`，bundle version 为 `2.3.0`；
- 定义 14 个 REST operations、139 个 `$defs` 和 14 个 Run event variants；
- 每个 operation 声明 method、route、request schema、success response、status mapping；
- Run stream 已声明 opaque cursor、exclusive resume、durable-ledger replay 以及
  replay-to-live 无 gap/duplicate transition；
- JSON response object 基本使用 `additionalProperties: false`；
- 使用 RFC 8785 canonicalization 与 SHA-256 给 bundle 建立稳定 identity；
- Catalog snapshot 带 `protocol_digest` 与 `catalog_contract_digest`。

这些事实见
[`bundle.json`](../../protein_workbench_public/resources/v2/bundle.json)、
[`protein_workbench_public/protocol.py`](../../protein_workbench_public/protocol.py) 和
[`protein_workbench_public/http/app.py`](../../protein_workbench_public/http/app.py)
与其 route owners。

server handler 已经从 bundle 取 route，并在边界调用 `decode_rest_request()` 与
`validate_response()`；这意味着后端不是由 FastAPI/Pydantic model 偶然定义协议，
而是在执行已发布 contract。保留这个方向是正确的。

installed-package 测试已经证明：

- wheel/sdist 包含 public bundle；
- installed bundle canonical bytes/digest 等于 source；
- installed Catalog bytes/digest 等于 source；
- 安装产物通过 public-only client 完成项目创建、输入发布、commit、Run、events、
  output 和 Artifact journey。

证据见
[`tests/test_installed_backend_v2.py`](../../tests/test_installed_backend_v2.py) 和
[`tests/public_protocol_acceptance_client.py`](../../tests/public_protocol_acceptance_client.py)。

### 3.2 当前 bundle 尚未形成标准跨语言 schema boundary

当前文件顶部直接从 `$defs` 开始，没有 `$schema` 和 `$id`。当前 Python validator 是
项目自写的 closed subset evaluator，不是声明了 dialect 的标准 JSON Schema validator。
这在一个 Python-only backend 内可工作，但浏览器 validator 和 code generator 无法仅凭
artifact 确定它应按哪一版 JSON Schema 解释。

另一个更直接的缺口是：`NodeTypeContractDescriptor.node_parameters` 和
`BindingContractDescriptor.binding_parameters` 在 public bundle 中只引用 opaque
`JsonObject`。后端 Catalog Builder 实际支持并验证一个更丰富的 closed grammar，见
[`core/parameters/contract.py`](../../core/parameters/contract.py)，但 public payload schema
没有把 `ParameterDefinition`、`value_contract` 和 `parameter_groups` 的结构完整发布。

结果是旧前端自行发明了一份较窄的 `ParameterDefinition`：只认识 type、enum、minimum
和 maximum，不认识 nested object/array、allOf/anyOf/oneOf、string/array/property
limits、pattern、exclusive bounds、unit、group、resource kind 等当前后端已经支持的字段。
这不是纯展示代码，而是第二份、不完整的参数契约。

### 3.3 已退役前端曾绕过 public protocol

已退役实现的 [`frontend/src/currentProtocol.ts`](https://github.com/natsusorahoshinochan-max/modules-ESM/blob/ef8e253d0754d13ee6b9dab635393396de683608/frontend/src/currentProtocol.ts) 手写 DTO，并把
`response.json()` 直接 cast 为泛型 `T`。Catalog translation 通过
`as unknown as NodeTypeDescriptor` 绕过结构证明。Workflow schema version
`2.1.0` 也作为 TypeScript literal 手写。

已退役实现的 [`frontend/src/App.tsx`](https://github.com/natsusorahoshinochan-max/modules-ESM/blob/ef8e253d0754d13ee6b9dab635393396de683608/frontend/src/App.tsx) 直接手写 Catalog、Project、Draft、
Commit、Run 和 Cancel URL；WebSocket 使用当前页面的 host；没有读 protocol discovery，
没有 reconnect/resume，也没有检查 stream event envelope 的完整 schema。

已退役实现的 [`frontend/src/typedOutputs.ts`](https://github.com/natsusorahoshinochan-max/modules-ESM/blob/ef8e253d0754d13ee6b9dab635393396de683608/frontend/src/typedOutputs.ts) 再次手写 Typed Value
route 与 header 名，并以 non-null assertion 接受所有 header。旧前端因此会把 protocol
drift 变成运行时 null、错误状态或静默错误，而不会在 adapter boundary 失败。

上传流程还根据文件扩展名硬编码两个具体 Node Type ID。这既复制 Catalog 能力，也使新
格式、新导入 Node 或 Module Package 改名必须修改前端。

### 3.4 已退役前端的独立部署不可直接工作

已退役实现的 Vite development proxy 和 `window.location.host` 假设同源；当时 backend
未配置 cross-origin response policy。即使 REST body 可以访问，Typed Value 依赖的非
safelisted headers 在跨源 Fetch 下也不会自动暴露给该前端。当前 checkout 没有前端，
CORS、Vite proxy 和 WebSocket Origin 因此是未来客户端的显式部署设计选择，不是当前
backend deployment blocker。

同时，所有 public FastAPI routes 都 `include_in_schema=False`，所以 FastAPI 自动生成的
`/openapi.json` 不是当前 public v2 contract。未来不能从 FastAPI introspection 重新生成
另一份 API 并称之为 source of truth。

### 3.5 当前 HTTP digest header 不是现行标准字段

bundle discovery、Typed Value 与 Artifact response 使用名为 `Digest` 的 header，值为
项目内部 `sha256:<hex>` domain digest。RFC 9530 已废弃 `Digest` field，并且新的
`Content-Digest` 使用不同的 Structured Field/base64 wire syntax。

这不影响当前内部科学 identity，但在冻结可独立实现的 browser contract 前应拆开：

- JSON descriptor 内继续使用 `sha256:<hex>` 作为 Workbench content identity；
- protocol discovery 通过明确的 application field/header 传递 canonical bundle 的 Workbench
  domain digest，浏览器 canonicalize 解码后的 JSON 后重算它；
- RFC 9530 `Content-Digest` 只描述实际 HTTP message content；经 Fetch 自动解压后，浏览器
  不声称重算验证它。raw HTTP client 或 identity-encoded response 可以验证；
- concurrency/cache validator 使用 quoted strong `ETag`；
- domain identity、transport integrity 和 concurrency validator 不得在前端共用一个未经
  区分的 `digest: string`。

## 4. 推荐的契约包结构

### 4.1 单一 authored source，多个 deterministic products

近期建议保留当前 bundle 为唯一 authored source，避免为了 OpenAPI 改写而阻塞前端。
新增的 contract build 产生以下只读生成物：

```text
protocol source
  protein_workbench_public/resources/v2/bundle.json
        |
        +-- validate outer bundle/meta contract
        +-- validate payload schema dialect 2020-12
        +-- generate openapi-v2.json
        +-- generate TypeScript declarations
        +-- generate browser runtime validators
        +-- generate operation/stream table
        +-- retain canonical bundle bytes + digest
```

OpenAPI 3.1 是标准工具投影，不是第二个可以手工修改的 source。FastAPI route、Python
SDK、TypeScript SDK、mock server 和文档都必须消费同一个 operation ID。

第一步需要让 schema dialect 显式化。可以选择下面两种实现方式；推荐 A：

- **A（推荐，改动较小）：** outer bundle 保持 Workbench manifest；其中的 payload
  schema 成为一个带 `$schema: https://json-schema.org/draft/2020-12/schema` 和稳定 `$id`
  的完整 schema resource；outer manifest 由 repository-owned meta-schema 验证。
- **B（以后可选）：** 把 OpenAPI 3.1 document 变成 canonical outer artifact，并把 Run
  stream 放进 `x-protein-workbench-run-event-stream`。这更标准，但会一次性改动 server
  operation lookup 和 bundle identity，不应与前端垂直切片并行发生。

### 4.2 protocol artifact 必须拥有的内容

Protocol package 必须完整拥有：

| 类别 | 必须进入 contract | 不应进入 contract |
|---|---|---|
| HTTP operation | stable operation ID、method、route template、path/query/header/body schema、status、media type、response headers | FastAPI function name、Python exception class |
| JSON payload | closed discriminated union、required/optional、bounds、identifier/timestamp/digest grammar | React state、Python dataclass layout |
| Binary payload | media type、metadata headers、size/digest semantics、range policy（若支持） | 浏览器 download component |
| Errors | stable code、typed details、retryable、correlation ID、status mapping | raw traceback、message parsing rule |
| Run stream | WS route、subprotocol、query schema、event union、cursor/replay、close code、terminal behavior | React node badge state |
| Pagination | limit contract、opaque cursor、exclusive/inclusive rule、stable ordering/snapshot semantics、next-page relation | page number guessed from cursor |
| Concurrency | ETag emission、required `If-Match`、412 error shape | React autosave timing |
| Discovery | namespace、protocol version、bundle digest、server/base route、feature/capability IDs | environment credential or provider secret |

### 4.3 protocol artifact 不应拥有的内容

以下内容明确不进入 backend public protocol 的科学 schema：

- Canvas x/y、viewport、panel width、颜色、折叠状态；
- React component 名称；
- Prompt Studio 当前选区、hover residue、临时 undo stack；
- 临时展示筛选；
- 前端 route 名称和 toast 文案；
- backend filesystem path、provider SDK object、Python class path。

需要持久化的 Canvas/Workbench UI state 使用一个 outer public resource：

```json
{
  "ui_state_id": "canvas/main",
  "ui_schema_id": "protein-workbench-ui/canvas@1",
  "media_type": "application/json",
  "content_digest": "sha256:...",
  "size": 1234,
  "payload": { "...": "frontend-owned" }
}
```

backend 只验证 envelope、JSON/I-JSON、size 和 durable write；`payload` 对 backend 是 opaque。
GET 返回 strong ETag，PUT 要求 `If-Match`。这样 React Flow、Prompt Studio 和 Results
layout 能独立升级，而不迫使 Python backend 理解或迁移 UI schema。

## 5. Frontend Protocol Adapter 设计

### 5.1 唯一网络入口

建议前端只暴露一个创建入口：

```ts
createProteinWorkbenchClient({
  httpBaseUrl,
  websocketBaseUrl,
  supportedProtocol,
})
```

feature code 只使用语义方法：

```ts
client.projects.list(...)
client.projects.create(...)
client.workflow.loadDraft(...)
client.workflow.saveDraft(...)
client.runs.start(...)
client.runs.subscribe(...)
client.results.pageCandidates(...)
client.authoring.preview(...)
client.uiState.load(...)
```

这个 factory 可以复用一个 production transport implementation，但 feature 不应依赖整个
client shape。Project、Workflow、Run、Results、Authoring 和 UI state 分别暴露小 Interface，
每个 feature 只注入自己需要的 slice；测试只实现对应的 in-memory Adapter。

feature code不得出现 `/api/v2`、header 名、HTTP status、`fetch()`、`new WebSocket()` 或
wire DTO cast。Artifact download link 也由 adapter 生成。

### 5.2 bootstrap

前端启动顺序：

1. 从独立部署的 runtime `config.json` 读取 HTTP/WS base URL；base URL 不烘焙进 bundle。
2. GET protocol discovery；检查 media type、namespace 和 protocol version；对解析后的
   bundle 做 RFC 8785 canonicalization，重算 Workbench domain digest，并和 discovery
   声明的 application domain-digest field 比较。不能在 gzip/br 后把 Fetch 解码 bytes
   误称为已验证的 `Content-Digest`。
3. 建立 operation table 和 runtime validator；缺少前端所需 capability 时显示明确的
   incompatible backend 页面，不继续请求。
4. GET Catalog；验证 Catalog payload，并要求其 `protocol_digest` 等于本次 discovery
   bundle digest。
5. 把 wire Catalog 转换为前端只读 view model；原始 wire object 不进入 component state。

运行时兼容不应只比较 exact digest。digest 用于证明“Catalog 与哪份 bundle 一致”和诊断；
UI 启动应按 major namespace、支持的 protocol version range 和 required capability set
决定是否兼容。否则任何新增 endpoint 都会迫使前后端锁步发布。

### 5.3 request/response boundary

每个 generated operation 执行：

1. runtime validate request model；
2. 根据 operation table encode path/query/body；
3. 设置明确 Accept / Content-Type / conditional headers；
4. 按 status mapping 选择 success 或 structured error schema；
5. runtime validate response JSON/header；
6. 转换为 feature-facing model；
7. 失败时抛出 typed `ProtocolError`，保留 code、details、retryable、correlation ID 和
   operation ID，不让 UI 解析 message。

TypeScript declarations只负责开发期；Ajv 或等价生成 validator 负责网络边界。为了避免
把大型动态 compiler 带进浏览器，可以在 build 时从支持的 protocol schema 生成 standalone
validators。若要允许 compatible minor bundle，adapter 还需要明确的 capability/version
策略，而不是“未知字段一律忽略”。

### 5.4 WebSocket owner

`RunSubscription` 由 adapter 完整拥有：

- 从 protocol descriptor 构造 WS URL；
- 发送/验证版本化 subprotocol；
- runtime validate每个 JSON message；
- 只在 validated event 后更新 last durable cursor；
- abnormal close 使用 bounded exponential backoff + jitter；
- reconnect 时传 `after_sequence=<last opaque cursor>`，保持当前 exclusive resume；
- `1000` 且已见 `run_terminal` 时结束；
- `1008` 转成 structured policy/cursor error；
- `1011` 或连接中断时先读取 exact Run Projection 判断是否 terminal，再决定恢复 stream；
- React unmount 只取消本地 subscription，不等同于 cancel Run。

这里的 REST projection 检查和 WS resume 应写入 adapter contract 与测试，不是隐藏 fallback。
用户主动 Cancel 仍调用显式 cancel operation。

## 6. Catalog-driven UI 如何避免复制 science

### 6.1 generic Node/parameter UI

public Catalog 需要把当前后端已经支持的参数 grammar 完整投影为明确 schema：

- `ParameterDefinition`；
- `value_contract` 的完整 closed keyword subset；
- required/default/scientific meaning；
- title/display name/description/unit/group；
- `resource_kind=project_input`；
- Node `parameter_groups`；
- Binding parameter contracts。

前端 form engine 只做：

- JSON Schema type -> input widget；
- annotation -> label/help/unit/group；
- local runtime validation -> 即时反馈；
- 生成 parameter JSON。

它不做：

- unit conversion；
- provider/model 推断；
- hidden Binding selection；
- scientific default 猜测；
- missing field repair；
- Node-specific parameter validation hardcode。

backend compiler 仍是 authoritative gate；浏览器 validation 只是使用同一 contract 提供即时
反馈。

### 6.2 exact Port compatibility

前端连接反馈应比较完整 `ContractReference`，至少包含 kind、ID、version、digest；不能像
旧前端一样只拼 `id@version`。若未来存在多输入 constraint、adapter-insertable conversion
或其他兼容规则，应由 Catalog 发布显式 authoring compatibility/capability，前端不推导。

### 6.3 specialized surfaces 不应硬编码科学子图

Prompt Studio、Structure Compare 和 Results Workbench 必然有专用组件；“Catalog-driven”
不等于所有科学对象都用 JSON textarea。正确的边界是：

- 前端可以按版本化 `presentation_capability` 选择 renderer/editor；
- capability 描述数据/操作角色，不暴露 Python implementation；
- 前端负责颜色、轨道、3D interaction、selection 和 undo/redo；
- backend 负责 canonical ResidueIdentity、ResidueMap、mask/track invariant、scientific
  validation 和显式 Workflow 子图编译。

Prompt Builder 建议由 Catalog 或独立 authoring capability 发布：

```text
capability_id: protein_prompt.authoring
capability_version: 1.0.0
input_roles: source_structure / source_sequence
document_schema: PromptEditDocument
preview_operation: preview_prompt_authoring
materialize_operation: materialize_prompt_builder_subgraph
output_role: protein_prompt
```

Prompt Studio 提交 role-based edit document；backend 返回 preview 和 residue-identity
projection，保存时返回显式 Node/edge patch。前端可以把该 patch 显示成一个组合单元，但不
知道 `resolve_axis -> map_track -> assemble_prompt` 的具体 Node IDs 和连接顺序。

同理，上传文件不能按扩展名映射 Node ID。Catalog 应发布 importer capability，包含 accepted
media types/extensions、produced Port Type、Node/Binding reference 和需要的 Project Input
parameter role。前端只呈现可用 importer；科学内容由 import Node 验证。

### 6.4 Results Workbench 不自行关联 science

Candidate 与 Score/Observation、paired structure、parent lineage 的关联必须由 backend
返回 stable IDs/reference；前端不得按数组位置 join。临时展示筛选可以在已加载 page 上
执行，但“Save as Workflow Selection”必须提交 declarative objective，由 backend 编译成
Workflow Node/selector。

## 7. 为三个前端场景补齐的 resource contract

以下不是最终 route 命名，而是首个冻结基线必须覆盖的 operation capability。

| Capability | 资源/操作 | 分离要求 |
|---|---|---|
| Project lifecycle | list/get/create/rename/delete/duplicate | Project DTO 由协议生成；mutations 用 ETag/If-Match |
| UI state | get/put/delete opaque UI payload | backend 不理解 layout internals |
| Project Inputs | list/get/publish | cursor page；importer 来自 Catalog，不硬编码 Node ID |
| Workflow | get/save Draft、commit、list Commit、load exact Commit | Draft save 用 ETag/If-Match；Run 只引用 immutable Commit |
| Run history | list/get/start/cancel/derive/subscribe | list cursor；stream cursor 与 list cursor 是不同 nominal type |
| Authoring Preview | preview ancestor closure / materialize composition | 返回 typed preview；不替换 active Commit |
| Prompt authoring | capability/read/edit/validate/materialize | 后端拥有 residue semantics，前端拥有 interaction |
| Candidate results | collection summary/page candidate/get value | immutable collection cursor；结构/PAE lazy load |
| Observations | page/query by associated Candidate and metric roles | 后端做 association；前端不按顺序 join |
| Compare | 只读投影已发布 pairing/alignment/Observation Evidence | 不猜 counterpart；新比较必须 materialize 普通 Workflow Nodes 并产生正常 Run |
| Export | 获取 explicit export Node 已发布的 Artifact | 首版不建第二条 export-job 路径；PDB/mmCIF/CSV/ZIP 是显式 format contract |
| Environment status | list startup Binding Availability | 不公开脱离 Run 的 Readiness；不暴露 credential/path/config |

Cache 清理不是首个科学用户路径的必要项；可以排在上述资源之后。它仍应通过 public operation
实现，而不是让前端知道 Cache filesystem。

`Readiness Attestation` 只能在 exact Run 的 Cache miss/bypass 即将进入 Provider seam 时产生。
UI 通过该 Run 的 Evidence、Node outcome 或 Binding Failure 查看它；startup/environment 页面
只能显示 `FrozenCatalog` 已发布的 Binding Availability snapshot。

## 8. Pagination 具体建议

### 8.1 统一 envelope

列表接口统一使用：

```json
{
  "items": [],
  "next_cursor": "opaque-or-absent",
  "page_size": 50,
  "snapshot": "opaque-stable-view-id"
}
```

request 使用 `cursor?` 与 bounded `limit?`；cursor 对 UI 永远 opaque。可以同时返回
`Link: <...>; rel="next"`，但 JSON `next_cursor` 是 application contract 的主体。

### 8.2 不同资源的稳定性

- Candidate Collection、Score Collection 和 Run Ledger 是 immutable publication：cursor
  固定引用 collection/ledger identity 与 exclusive position，最容易稳定分页。
- Project、Input、Commit、Run history 是会增加/修改的列表：首个 page 创建 snapshot，后续
  cursor 绑定同一 snapshot，避免分页过程中插入项目造成 duplicate/skip。
- cursor 失效返回 typed `invalid_cursor`，不能静默从第一页重启。
- Candidate 的典型上限 1000 只决定默认 page size 和虚拟列表，不进入科学合同硬上限。

建议默认 `limit=50`、协议允许 `1..200`；这属于产品建议，不是外部标准要求。

## 9. 前后端独立构建与部署

### 9.1 artifact boundary

建议形成三个独立 artifact：

```text
protein-workbench backend wheel
protein-workbench protocol npm package / generated SDK
protein-workbench frontend static dist
```

backend wheel 不包含 Vite build output；frontend 不 import Python 文件或读取 repository
路径。protocol npm package 只含生成的 types、validators、operation metadata，以及由协议
人工维护的公开 semantic fixtures；不含 React components。schema 工具可以确定性生成机械
负例，但不能取代人工维护的语义边界样例。

### 9.2 runtime URL configuration

前端启动时读取一个部署提供的 `config.json`：

```json
{
  "http_base_url": "http://127.0.0.1:8000",
  "websocket_base_url": "ws://127.0.0.1:8000"
}
```

同一前端 dist 因此可以连接不同 backend，不需要为每台机器重建。生产本机应用优先让一个
reverse proxy 同时暴露静态前端与 `/api`、`/events`，使浏览器看到同源；两者仍是独立
artifact 和进程。

若允许浏览器直接跨源连接：

- backend 配置一个明确的 UI origin；
- REST 允许 contract 声明的方法/headers；
- `Access-Control-Expose-Headers` 至少包含 ETag、Content-Disposition、protocol 声明的
  Workbench domain-digest header，以及 Typed Value 的公开 metadata headers；如果只为诊断
  暴露 `Content-Digest`，frontend 仍不能在 content coding 解码后声称已验证它；
- WebSocket handshake 检查配置的 Origin；
- client 和 server 协商例如 `protein-workbench.v2` subprotocol；
- 不把 wildcard CORS、credentials 或 hosted multi-tenant security 引入当前 loopback trust
  model。

## 10. 版本与迁移策略

### 10.1 五条版本轴

| 版本轴 | 例子 | 谁消费 | breaking 结果 |
|---|---|---|---|
| Public transport protocol | `protein-workbench-public/v2`, bundle semver | frontend adapter / external client | 新 `/api/v3` namespace |
| Workflow/persistence schema | current Workflow `2.1.0` | authoring/compiler | 旧 dev state fail closed/clear |
| Scientific Catalog Contract | Node/Port/Method/Metric exact version+digest | compiler/run/evidence/UI Catalog | current Catalog 原子替换 |
| Frontend UI state schema | `protein-workbench-ui/canvas@1` | frontend only | 前端丢弃/迁移自己的 state |
| Authoring/presentation capability | `protein_prompt.authoring@1` | specialized frontend feature / backend materializer | unsupported capability 明确显示；不猜测 fallback |

五者不能共享一个“app version”并互相猜兼容性。Capability descriptor 的 wire schema 由
public transport protocol 拥有，但某个 capability 的编辑语义、document schema 和
materialization semantics 使用独立 capability version；因此它不是 protocol semver 的别名。

### 10.2 当前 pre-release 阶段

在前端开始大规模实现前，允许一次明确的 v2 reset，把本调研发现的 seam 一次补齐：

1. 参数/parameter-group schema 完整公开；
2. schema dialect 与 generated TS/runtime validators；
3. missing Project/UI/Input/Run/Result pagination operations；
4. Draft/UI state ETag + If-Match；
5. HTTP `Content-Digest` 与 domain digest 分离；
6. WS subprotocol、reconnect/resume contract；
7. authoring/importer/presentation capabilities。

reset 修改所有 source consumers、tests、examples 和 docs；旧 dev Project/Cache/Run/UI state
直接失效，不实现 migrator、alias 或双 route。

### 10.3 冻结后的 v2 compatibility rule

冻结后：

- patch：不改变 observable contract 的修复；
- minor：增加独立 operation/capability，或增加只有 opt-in request 才会返回的 union variant；
- major：改变现有 field、requiredness、status、route、header、cursor semantics、event ordering
  或现有 client 必然看到的 closed response shape。

由于当前 response object 大量使用 `additionalProperties: false`，在旧 response 中新增字段对
strict older validator 也是 breaking change，不能简单称为“additive minor”。若预计经常需要
扩展，必须在冻结前设计明确的 `extensions`/capability 容器；不能在冻结后要求 client 忽略
任意未知科学字段。

前端发布物记录：

- supported protocol namespace/semver range；
- required operation/capability IDs；
- codegen source bundle digest；
- generated SDK version。

runtime 不要求 backend exact digest 永远等于 build digest，但要求 version/capability 兼容，
并要求 live Catalog 的 `protocol_digest` 等于 live discovery bundle digest。

## 11. Source / installed / protocol / frontend parity 测试

### 11.1 contract source tests

每次修改 bundle 必须：

1. 通过 outer bundle meta-schema；
2. payload schemas 通过 Draft 2020-12 meta-schema；
3. 所有 `$ref` 可解析；
4. 每个 operation ID 唯一且 request/response/error 完整；
5. 每个 event union discriminator 唯一；
6. OpenAPI 3.1 projection 通过 official/schema-aware lint；
7. codegen 两次输出 byte-identical；
8. generated files 与 git 工作树一致，手改 generated file 使 CI 失败。

### 11.2 cross-language fixture tests

为每个 operation/event 人工维护 protocol-owned semantic valid/invalid fixtures；同一份
fixture 同时经过：

- Python request/response/event validator；
- TypeScript/Ajv validator；
- generated request encoder；
- mock server decoder。

必须覆盖 unknown field、wrong discriminator、numeric boundary、header absence、binary digest、
structured error 和 cursor。这样能证明“两边都通过自己的测试”，而不是只证明两边各自相信
一份不同的 schema。工具可以从 closed schema 确定性生成 missing-required、unknown-field 等
机械负例作为补充，但生成物不能替代 discriminator、关联、cursor 和 error semantics 的人工
fixture。

### 11.3 router parity

从 bundle 枚举所有 REST/WS operation，断言：

- backend 恰好实现每个 operation；
- public `/api/v2` 没有 bundle 未声明的 route；
- handler method/route/status/media type/header 与 bundle 一致；
- server responses 在发送前通过 schema；
- Python route 不依赖 FastAPI 自动 OpenAPI 作为第二真相。

### 11.4 installed backend parity

保留当前 installed tests，并增加：

- installed `/api/v2/protocol` 的 canonical Workbench domain digest 与 source 相同；另以 raw
  HTTP/identity-encoded response 测试 `Content-Digest`（若 protocol 要求发送它）；
- generated protocol SDK 只通过 HTTP/WS 驱动 installed wheel；
- pagination、If-Match conflict、WS disconnect/resume、binary header/digest；
- source backend 与 installed backend 对同一 fixture 产生同一 public shape。

### 11.5 frontend artifact parity

前端 CI 需要：

1. 在没有 Python import/PYTHONPATH 的 Node 环境生成或安装 protocol SDK；
2. 用 protocol mock server 运行 Project -> Draft -> Commit -> Run -> replay -> Results journeys；
3. 构建 static dist，并断言 dist 不含 localhost、absolute repository path 或手写 API route；
4. 把 static dist 与 installed backend 作为两个进程启动，运行一个 browser smoke journey；
5. 验证同源 reverse-proxy 模式和直接跨源模式的 headers/WS；
6. 断开 WS 后用最后 cursor 恢复，保证 projection 最终与 uninterrupted stream 相同。

### 11.6 Catalog-driven UI parity

生产 Catalog 测试还需反向证明：

- 每个 parameter declaration 都被 public parameter schema 接纳；
- frontend form renderer 能表示支持 grammar 中的每一种结构，而不是只覆盖当前刚好出现的
  primitive；
- 每个 active Binding 有 Availability；
- 每个 specialized presentation/authoring capability 都有前端支持版本或明确 unsupported
  展示；
- 添加普通 Module Package/Node Type 不修改前端源码也能出现在 Catalog、Canvas 和参数表单；
- Prompt/structure/result specialized component 只按 capability/version 选择，不按 package
  Python path 或偶然 Node title 选择。

## 12. 最快且风险最低的实施顺序

### Phase 0：冻结前的 contract foundation

1. 为 bundle/payload 声明明确 dialect；完整公开 parameter grammar。
2. 建立 deterministic TS type + runtime validator + operation table codegen。
3. 新建 frontend Protocol Adapter，删除 component 内所有直接 fetch/WS/route。
4. 分离 Workbench domain digest、transport `Content-Digest` 与 ETag，并修复 Draft/UI
   concurrency contract。

这是前端全面开发前必须完成的最小地基。否则每增加一个页面都会扩大手写 DTO 和 route 债务。

### Phase 1：场景 1 垂直切片

1. Project list/detail/rename/delete、opaque UI state；
2. Project Input list + Catalog importer capability；
3. Multi-FASTA import；
4. Canvas/Draft/Commit/Run/WS；
5. Candidate + Observation cursor pages；
6. 临时筛选与 Save as Workflow Selection；
7. explicit batch export Node 与已发布 Artifact 获取。

这会先证明 protocol、独立部署、1000 Candidate、分页、run resume 和结果关联。

### Phase 2：Prompt Studio / 场景 2

1. authoring preview；
2. versioned Prompt authoring capability；
3. residue-track + 3D synchronized presentation projection；
4. materialize explicit Prompt Builder subgraph；
5. structure comparison/pairing results。

### Phase 3：场景 3

在同一 seam 上增加 ProteinMPNN inverse folding、第二轮 folding/scoring/selection；不新增
专用 transport，也不让前端理解 ProteinMPNN provider payload。

## 13. 建议形成的 ADR

本调研建议后续用一个 ADR 固定以下决定：

1. current public bundle 是唯一 authored protocol source；OpenAPI/TS/validators 均为生成物；
2. JSON payload dialect 是 Draft 2020-12；
3. 前端只能经 Protocol Adapter 访问 backend；
4. independent artifacts、runtime base URL、same-origin preferred deployment；
5. UI state opaque persistence；
6. capability-driven specialized authoring/presentation；
7. ETag/If-Match、Workbench domain digest 与 transport `Content-Digest` 的分工、cursor
   pagination 和 WS resume；
8. v2 freeze 后的 compatibility policy 与 parity gates。

若接受该方向，下一步不应先画更多页面；应先把 **Phase 0 的 protocol diff** 写成明确 spec：
列出新增 operations、schemas、headers、capabilities 和 compatibility rule，然后再让前端与后端
按同一 artifact 并行实现。
