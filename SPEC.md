# Spec: Servidor MCP do Trello para Organizações (Workspaces)

> Status: implementado (v1) · Data: 2026-10-08 · Autor: Lucas

## 1. Contexto e objetivo

Construir um servidor **MCP (Model Context Protocol)** que permita a assistentes de IA (Claude Code, Claude Desktop, etc.) consultar e operar o Trello **no nível da organização** (no Trello, "Organization" = *Workspace*). O foco não é só manipular cartões isolados, mas dar visão e controle sobre o workspace inteiro: quadros, membros, atividade, busca transversal e relatórios.

### Objetivos
- Expor recursos da organização (boards, membros, listas, cards, labels, atividade) como **tools** e **resources** MCP.
- Restringir o acesso a um conjunto explícito de organizações (*allowlist*).
- Ser seguro por padrão: modo somente leitura disponível, operações destrutivas sinalizadas e auditáveis.
- Respeitar os limites de taxa da API do Trello.

### Fora de escopo (v1)
- Power-Ups, webhooks em tempo real e automações Butler.
- Interface gráfica própria.
- Recursos exclusivos de Enterprise (`/enterprises/*`) — previstos para a v2 (ver §10).

---

## 2. Requisitos

### Funcionais
| ID | Requisito |
|----|-----------|
| RF01 | Listar as organizações acessíveis ao token e filtrá-las pela allowlist. |
| RF02 | Obter detalhes de uma organização (nome, descrição, URL, nº de boards/membros). |
| RF03 | Listar boards de uma organização (abertos/fechados) com filtros. |
| RF04 | Listar membros da organização e seus papéis (admin/normal), incluindo convidados de boards. |
| RF05 | Adicionar, alterar papel e remover membros da organização (somente admins). |
| RF06 | Ler listas, cards, labels, checklists e comentários de um board. |
| RF07 | Criar/atualizar/mover/arquivar cards e comentar. |
| RF08 | Buscar cards/boards em toda a organização (`/search` com `idOrganizations`). |
| RF09 | Consultar o feed de atividade (actions) da organização com intervalo de datas. |
| RF10 | Gerar relatórios agregados: cards por membro, cards atrasados, carga por lista, boards inativos. |

### Não funcionais
| ID | Requisito |
|----|-----------|
| RNF01 | Python ≥ 3.12 + SDK oficial `mcp` ≥ 2.3 (`MCPServer`, antigo FastMCP), gerenciado com `uv`. Código assíncrono (`asyncio` + `httpx`) e tipado (`mypy --strict`). |
| RNF02 | Transportes: **stdio** (uso local) e **Streamable HTTP** (uso compartilhado na equipe). |
| RNF03 | Rate limiting no cliente: ≤ 100 req/10s por token e ≤ 300 req/10s por API key, com retry exponencial em `429`. |
| RNF04 | Nenhum segredo em logs; logs estruturados (JSON) em stderr. |
| RNF05 | Cobertura de testes ≥ 80% na camada de cliente e tools. |
| RNF06 | Respostas das tools compactas (campos selecionados via `fields=`) para economizar contexto do modelo. |

---

## 3. Arquitetura

```
┌──────────────┐   MCP (stdio / HTTP)   ┌───────────────────────────────────────┐
│ Cliente MCP  │ ─────────────────────▶ │ trello-org-mcp                        │
│ (Claude ...) │                        │                                       │
└──────────────┘                        │  server.py      MCPServer + tools     │
                                        │  ├─ tools/      org, boards, cards,   │
                                        │  │              members, search,      │
                                        │  │              activity, reports     │
                                        │  ├─ resources/  trello://org/{id}/... │
                                        │  ├─ policy/     allowlist, read-only, │
                                        │  │              confirmação, auditoria│
                                        │  └─ trello/     cliente HTTP, rate    │
                                        │                 limiter, paginação    │
                                        └───────────────┬───────────────────────┘
                                                        │ HTTPS
                                                        ▼
                                              api.trello.com/1
```

### Estrutura de diretórios
```
trello-org-mcp/
├── src/trello_org_mcp/
│   ├── __init__.py
│   ├── __main__.py           # entrypoint (escolhe transporte: stdio | http)
│   ├── server.py             # build_server(): MCPServer + registro de tools/resources/prompts
│   ├── config.py             # Settings (pydantic-settings) a partir do ambiente/.env
│   ├── trello/
│   │   ├── client.py         # httpx.AsyncClient + auth + retry
│   │   ├── rate_limiter.py   # token bucket assíncrono
│   │   ├── errors.py         # exceções e mapeamento de status HTTP
│   │   └── models.py         # modelos Pydantic: Organization, Board, Card, Member, Action
│   ├── policy/
│   │   ├── allowlist.py
│   │   ├── guard.py          # read-only / confirmação de operações destrutivas
│   │   └── audit.py
│   ├── tools/
│   │   ├── organizations.py
│   │   ├── boards.py
│   │   ├── members.py
│   │   ├── cards.py
│   │   ├── search.py
│   │   ├── activity.py
│   │   └── reports.py
│   └── resources/
│       └── organization.py
├── tests/
├── .env.example
├── pyproject.toml            # dependências, ruff, mypy, pytest, entry point
└── README.md
```

### Stack
| Função | Biblioteca |
|--------|-----------|
| Servidor MCP | `mcp` 2.x (`MCPServer`: `add_tool()`, `@mcp.resource()`, `@mcp.prompt()`) |
| HTTP | `httpx` (async) |
| Validação / modelos | `pydantic` v2 |
| Configuração | `pydantic-settings` |
| Retry | `tenacity` |
| Logs | `structlog` (JSON em stderr) |
| Testes | `pytest`, `pytest-asyncio`, `respx` (mock do httpx) |
| Qualidade | `ruff` (lint + format), `mypy --strict` |
| Projeto / distribuição | `uv` (`uv run`, `uv build`, `uvx`) |

### Exemplo de tool com MCPServer
```python
from typing import Annotated, Literal
from pydantic import Field
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

mcp = MCPServer("trello-org")

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def trello_list_org_boards(
    org_id: Annotated[str, Field(description="ID ou nome da organização")],
    filter: Literal["open", "closed", "all"] = "open",
) -> list[BoardSummary]:
    """Lista os boards de uma organização permitida."""
    org = await allowlist.require_org(org_id)
    return await trello.get_org_boards(org.id, filter=filter)
```
O schema de entrada é gerado a partir das type hints e o docstring vira a descrição da tool. O retorno tipado (modelo Pydantic) gera *structured output* automaticamente.

---

## 4. Autenticação e configuração

### v1 — API Key + Token (por usuário/instalação)
1. Criar um Power-Up em https://trello.com/power-ups/admin para obter a **API Key**.
2. Gerar o **token** do usuário via `https://trello.com/1/authorize?expiration=never&scope=read,write,account&response_type=token&key=<API_KEY>`.
   - Se precisar só leitura, usar `scope=read` e ativar `TRELLO_READ_ONLY=true`.
3. As credenciais são enviadas no header:
   `Authorization: OAuth oauth_consumer_key="<KEY>", oauth_token="<TOKEN>"`
   (evita colocar o token na query string e, portanto, em logs).

### v2 — Multiusuário (modo HTTP)
- Fluxo OAuth 1.0a do Trello por usuário, tokens armazenados criptografados.
- O servidor MCP HTTP exige autenticação própria (OAuth 2.1 conforme a spec de autorização do MCP) e mapeia cada sessão ao token Trello do usuário.

### Variáveis de ambiente
| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `TRELLO_API_KEY` | sim | API Key do Power-Up |
| `TRELLO_TOKEN` | sim (v1) | Token do usuário |
| `TRELLO_ORG_ALLOWLIST` | sim | IDs ou `name` das organizações permitidas, separados por vírgula |
| `TRELLO_READ_ONLY` | não (default `false`) | Desabilita todas as tools de escrita |
| `TRELLO_ALLOW_DESTRUCTIVE` | não (default `false`) | Habilita remoção de membros, exclusão de cards etc. |
| `MCP_TRANSPORT` | não (default `stdio`) | `stdio` ou `http` |
| `MCP_HTTP_PORT` | não (default `3333`) | Porta do modo HTTP |
| `AUDIT_LOG_PATH` | não | Arquivo JSONL de auditoria das operações de escrita |

---

## 5. Catálogo de tools

Convenções: nomes em `snake_case` com prefixo `trello_`; entrada validada por **Pydantic** (type hints + `Field`); saída em modelos Pydantic enxutos; toda tool que recebe `orgId`/`boardId`/`cardId` valida que o recurso pertence a uma organização da allowlist. Anotações MCP (`readOnlyHint`, `destructiveHint`, `idempotentHint`) preenchidas em todas.

### 5.1 Organizações
| Tool | Endpoint(s) Trello | Tipo |
|------|--------------------|------|
| `trello_list_organizations` | `GET /members/me/organizations` | leitura |
| `trello_get_organization` | `GET /organizations/{id}` | leitura |
| `trello_update_organization` | `PUT /organizations/{id}` (displayName, desc, website) | escrita |

### 5.2 Boards
| Tool | Endpoint(s) | Tipo |
|------|-------------|------|
| `trello_list_org_boards` | `GET /organizations/{id}/boards?filter=open\|closed\|all` | leitura |
| `trello_get_board` | `GET /boards/{id}?lists=open&labels=all&members=all` | leitura |
| `trello_create_board` | `POST /boards` com `idOrganization` | escrita |
| `trello_close_board` | `PUT /boards/{id}` `closed=true` | escrita (destrutiva) |

### 5.3 Membros
| Tool | Endpoint(s) | Tipo |
|------|-------------|------|
| `trello_list_org_members` | `GET /organizations/{id}/members` + `/memberships` | leitura |
| `trello_get_member_workload` | `GET /members/{id}/cards` filtrado pelos boards da org | leitura |
| `trello_invite_org_member` | `PUT /organizations/{id}/members` (email, fullName, type) | escrita |
| `trello_set_org_member_role` | `PUT /organizations/{id}/members/{idMember}` (`type=admin\|normal`) | escrita |
| `trello_remove_org_member` | `DELETE /organizations/{id}/members/{idMember}` | escrita (destrutiva) |

### 5.4 Listas e cards
| Tool | Endpoint(s) | Tipo |
|------|-------------|------|
| `trello_list_cards` | `GET /boards/{id}/cards` ou `/lists/{id}/cards` | leitura |
| `trello_get_card` | `GET /cards/{id}?checklists=all&actions=commentCard` | leitura |
| `trello_create_card` | `POST /cards` | escrita |
| `trello_update_card` | `PUT /cards/{id}` (nome, desc, due, idMembers, idLabels) | escrita |
| `trello_move_card` | `PUT /cards/{id}` (`idList`, `idBoard`, `pos`) | escrita |
| `trello_archive_card` | `PUT /cards/{id}` `closed=true` | escrita |
| `trello_add_comment` | `POST /cards/{id}/actions/comments` | escrita |
| `trello_create_list` | `POST /lists` | escrita |

### 5.5 Busca e atividade
| Tool | Endpoint(s) | Tipo |
|------|-------------|------|
| `trello_search_org` | `GET /search?query=…&idOrganizations=…&modelTypes=cards,boards` | leitura |
| `trello_org_activity` | `GET /organizations/{id}/actions?since=&before=&filter=` (paginado) | leitura |

### 5.6 Relatórios (agregação no servidor)
| Tool | Saída |
|------|-------|
| `trello_report_overdue` | Cards com `due` vencido e `dueComplete=false`, agrupados por board/membro |
| `trello_report_workload` | Nº de cards abertos por membro da org |
| `trello_report_stale_boards` | Boards sem atividade há N dias (`dateLastActivity`) |
| `trello_report_list_distribution` | Contagem de cards por lista em cada board (visão de fluxo/WIP) |

### 5.7 Resources (somente leitura)
- `trello://org/{orgId}` — resumo da organização
- `trello://org/{orgId}/boards` — lista de boards
- `trello://org/{orgId}/members` — membros e papéis
- `trello://board/{boardId}` — board com listas e cards abertos

### 5.8 Prompts (opcional)
- `weekly_org_summary` — resumo semanal da atividade da organização.
- `triage_overdue` — sugere ações para cards atrasados.

---

## 6. Políticas de segurança

1. **Allowlist obrigatória**: qualquer ID fora das organizações permitidas retorna erro `FORBIDDEN_ORG` sem chamar a API de escrita. Para cards/listas, resolver o `idOrganization` via board (com cache em memória, TTL 5 min).
2. **Read-only**: com `TRELLO_READ_ONLY=true`, tools de escrita **não são registradas** (o modelo nem as vê).
3. **Destrutivas**: `remove_org_member`, `close_board`, etc. só são registradas com `TRELLO_ALLOW_DESTRUCTIVE=true`, têm `destructiveHint: true` e exigem parâmetro `confirm: true`.
4. **Auditoria**: toda escrita gera uma linha JSONL `{timestamp, tool, args (sem segredos), orgId, result}`.
5. **Sanitização**: conteúdo vindo do Trello (descrições, comentários) é retornado como dado; o README deve alertar sobre *prompt injection* via conteúdo de cards.
6. **Segredos**: nunca registrar headers de autorização; mascarar tokens em mensagens de erro.

---

## 7. Tratamento de erros e limites

- Mapear erros HTTP para mensagens claras ao modelo:
  `401 → AUTH_INVALID`, `403 → FORBIDDEN`, `404 → NOT_FOUND`, `429 → RATE_LIMITED`, `5xx → UPSTREAM_ERROR`.
- Erros retornados como resultado de tool com `isError: true` e texto acionável (ex.: "Board não encontrado ou fora da allowlist").
- **Rate limiter** token bucket (100 req/10s por token) + respeito a `Retry-After`; até 3 retries com backoff exponencial e jitter.
- **Paginação**: `actions` usa `before`/`since` com `limit` ≤ 1000; tools expõem `limit` (default 50) e retornam um `nextCursor`.
- **Tamanho das respostas**: em vez de truncar, as tools de listagem expõem `limit` e usam `fields=` enxutos.

---

## 8. Plano de implementação (passo a passo)

### Passo 1 — Setup do projeto
- `uv init --package trello-org-mcp` (layout `src/`), Python ≥ 3.12.
- Dependências: `uv add "mcp[cli]" httpx pydantic pydantic-settings tenacity structlog`.
- Dev: `uv add --dev pytest pytest-asyncio respx ruff mypy`.
- `pyproject.toml`: entry point `trello-org-mcp = "trello_org_mcp.__main__:main"`, config de ruff, mypy (`strict = true`) e pytest (`asyncio_mode = "auto"`).
- Comandos: `uv run pytest`, `uv run ruff check`, `uv run mypy src`, `npx @modelcontextprotocol/inspector uv run trello-org-mcp` (abre o MCP Inspector).
- **Pronto quando:** `uv run pytest`, `ruff` e `mypy` passam com um teste vazio.

### Passo 2 — Configuração
- `config.py` com classe `Settings(BaseSettings)` cobrindo as variáveis de §4 (`TRELLO_ORG_ALLOWLIST` parseada para `list[str]`, segredos como `SecretStr`); falha rápida com mensagem clara se faltar algo.
- `.env.example` documentado.
- **Pronto quando:** testes cobrem config válida, ausente e inválida.

### Passo 3 — Cliente Trello
- `client.py`: classe `TrelloClient` sobre `httpx.AsyncClient` (base URL, header OAuth, timeouts, `get/post/put/delete`), retornando modelos Pydantic de `models.py`.
- `rate_limiter.py`: token bucket com `asyncio.Lock`; retry em 429/5xx com `tenacity` (backoff exponencial + jitter, respeitando `Retry-After`).
- `errors.py`: mapeamento de erros (§7) para exceções `TrelloError` tipadas.
- **Pronto quando:** testes com `respx` cobrem sucesso, 401, 404, 429 com retry e 5xx.

### Passo 4 — Esqueleto do servidor MCP
- `server.py` com `build_server(settings, client=None)` criando o `MCPServer("trello-org")`; as dependências (`Deps`: settings, client, allowlist, registry) chegam às tools por closure e o *lifespan* fecha o `TrelloClient`. A fábrica permite injetar um cliente mockado nos testes.
- `__main__.py` com `main()` executando `mcp.run(transport="stdio")`.
- Primeira tool: `trello_list_organizations`.
- **Pronto quando:** o Inspector lista a tool e a chamada retorna as orgs reais.

### Passo 5 — Camada de políticas
- `allowlist.py` (resolve nome → ID na primeira chamada, uma única vez; cache board/lista/card → org com TTL de 5 min), `guard.py` (read-only/destrutivo/confirm), `audit.py` (JSONL).
- `ToolRegistry.tool(kind="read" | "write" | "destructive")`, decorator que envolve `mcp.add_tool()`: define as `ToolAnnotations`, decide se a tool é registrada (conforme `READ_ONLY`/`ALLOW_DESTRUCTIVE`), exige `confirm=True` nas destrutivas e grava a auditoria.
- **Pronto quando:** testes provam que IDs fora da allowlist são rejeitados e que tools de escrita não aparecem em `list_tools` no modo read-only.

### Passo 6 — Tools de organização e boards (§5.1, §5.2)
- **Pronto quando:** cada tool tem teste unitário (mock) e foi validada manualmente no Inspector.

### Passo 7 — Tools de membros (§5.3)
- Combinar `/members` e `/memberships` para retornar papel de cada membro.
- **Pronto quando:** convite/alteração de papel funcionam em uma org de teste; remoção exige `confirm: true`.

### Passo 8 — Tools de listas e cards (§5.4)
- Validar pertencimento à org antes de escrever (via cache board → org).
- **Pronto quando:** fluxo criar → mover → comentar → arquivar funciona ponta a ponta.

### Passo 9 — Busca e atividade (§5.5)
- Paginação com cursor; filtros por tipo de action e intervalo de datas.
- **Pronto quando:** busca retorna apenas resultados das orgs permitidas.

### Passo 10 — Relatórios (§5.6)
- Agregações com chamadas por board em paralelo (`asyncio.gather`), cadenciadas pelo token bucket do cliente. (`/batch` foi descartado: o parâmetro `urls` é separado por vírgulas e conflita com `fields=` nas URLs internas.)
- **Pronto quando:** relatórios rodam em uma org com ≥ 20 boards em < 15 s sem estourar o rate limit.

### Passo 11 — Resources e prompts (§5.7, §5.8)
- **Pronto quando:** os resources aparecem e são lidos no Inspector/Claude Desktop.

### Passo 12 — Transporte HTTP
- `mcp.run("streamable-http", host=..., port=...)` (endpoint `/mcp`); health check `GET /healthz` via `@mcp.custom_route`; validação de `Origin`/`Host` (proteção contra DNS rebinding do SDK, ativa quando o bind é `127.0.0.1`/`localhost`); bind em `127.0.0.1` por padrão.
- **Pronto quando:** cliente MCP remoto conecta e executa tools via HTTP.

### Passo 13 — Testes de integração
- Suíte opcional (`uv run pytest -m e2e`) contra uma org de testes real, habilitada por `TRELLO_E2E=1`; cria e limpa seus próprios boards.
- **Pronto quando:** suíte e2e passa e não deixa resíduos.

### Passo 14 — Empacotamento e documentação
- `uv build` e publicação no PyPI (execução via `uvx trello-org-mcp`) e/ou imagem Docker (`python:3.12-slim` + `uv`).
- README com: geração de credenciais, configuração no Claude Code/Desktop, tabela de tools, avisos de segurança.
- Exemplo para Claude Code:
  ```bash
  claude mcp add trello-org \
    -e TRELLO_API_KEY=... -e TRELLO_TOKEN=... -e TRELLO_ORG_ALLOWLIST=minha-org \
    -- uvx trello-org-mcp
  ```
- **Pronto quando:** uma pessoa nova configura e usa o servidor só seguindo o README.

---

## 9. Estratégia de testes

| Camada | Ferramenta | O que cobre |
|--------|-----------|-------------|
| Unitário | pytest + pytest-asyncio | config, rate limiter, mapeamento de erros, políticas |
| Tools | pytest + `respx` | contrato de entrada/saída de cada tool |
| Protocolo | MCP Inspector / `mcp.Client` do SDK conectado em memória ao servidor nos testes | listagem de tools, schemas, anotações |
| E2E | org de teste real | fluxos completos de escrita e limpeza |

---

## 10. Roadmap pós-v1
- **v1.1**: webhooks (`POST /webhooks`) para notificar mudanças e manter cache atualizado.
- **v2**: multiusuário com OAuth; tools de Enterprise (`/enterprises/{id}/members`, auditoria, licenças); custom fields; anexos.
- **v2.x**: relatórios históricos (cycle time, lead time) a partir das actions.

---

## 11. Questões em aberto
1. O servidor será usado só localmente (stdio) ou compartilhado pela equipe (HTTP)? Isso define a prioridade do Passo 12 e da auth v2.
2. A organização usa Trello Enterprise? Se sim, antecipar tools de `/enterprises`.
3. Quais relatórios são mais valiosos para o time além dos listados em §5.6?
4. Gestão de membros (convidar/remover) deve ficar disponível ao modelo ou apenas leitura?
