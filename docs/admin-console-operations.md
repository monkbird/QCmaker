# 管理控制台部署与恢复

管理入口为 `/admin`，接口为 `/api/admin`。管理账号与业务访问令牌独立。默认 `ADMIN_ENABLED=false`，开启前应先完成备份和本机验收。

## 首次初始化

1. 停止 API、清理任务和恢复 worker，运行 `python scripts/admin_snapshot.py backup <项目目录> <项目外的新快照目录> --service-stopped`。快照含配置密钥，仅允许服务账号和备份管理员读取。
2. 使用 `python scripts/gen_admin_password.py` 生成密码哈希，按脚本提示输入密码；将哈希写入 `.env` 的 `ADMIN_BOOTSTRAP_PASSWORD_HASH`，设置账号及 `ADMIN_ENABLED=true`。不要把明文密码放入命令行、版本库或截图。
3. 启动服务后，空库首次创建管理员。数据库已有账号时，环境中的 bootstrap 值不再覆盖账号；更换密码使用安全中心或受控的本机恢复脚本。
4. 登录 `/admin`，检查看板、会话到期、退出和重新登录。不要使用静态演示页代替真实接口验收。

## 同源部署

浏览器只访问一个 HTTPS 站点。反向代理将 `/api/` 转发到 API，将其他路径交给前端静态文件；`/admin/*` 必须回退到 `index.html`。原始 Host/Origin 保持一致。仅信任实际反向代理的转发头，禁止对任意来源开启可信代理。

生产 Cookie 使用 Secure、HttpOnly、SameSite=Strict 和 `/api/admin` 路径。开发使用显式 development 环境、localhost/127.0.0.1、仅绑定回环地址以及 Vite 同源代理。不能通过放宽跨域来修复 Cookie 配置错误。

业务接口仍沿用业务令牌，管理审计覆盖管理接口，不等于已经审计所有遗留业务入口。未配置业务令牌时必须绑定回环地址或由网络访问控制限制，不应公开监听。

## 常见状态

- `ADMIN_DISABLED`：检查显式启用开关。
- `ADMIN_NOT_INITIALIZED`：检查首次账号与哈希配置、数据目录权限和初始化日志。
- 401：会话空闲/绝对到期、改密、吊销或恢复后需要重新登录。
- CSRF 过期：页面重新获取一次会话信息后重试；持续失败检查 Origin、代理和 Cookie 路径。
- 配置冲突：刷新当前 revision 后重新确认；环境变量覆盖项需在部署环境修改。
- 操作超时：使用页面提供的操作记录查询结果，再决定是否重试。不要重新创建多个删除任务。

## 令牌轮换

轮换后保存一次展示的新值，更新业务前端构建环境 `VITE_API_TOKEN`，重新构建并发布。旧令牌对新 HTTP 请求和新 WebSocket 失效；既有 WebSocket 保持到关闭。管理 Cookie 不替代业务令牌。

## 备份与恢复

快照工具使用 SQLite backup API 并验证完整性，同时复制同批 `.env`、PPT、Chroma 和默认 CSRF 密钥文件，生成 SHA-256 清单。执行前必须停止服务、等待 worker 退出并关闭 Chroma。自定义 `ADMIN_CSRF_KEY_FILE` 需另行安全备份并在恢复时匹配。

运行 `python scripts/admin_snapshot.py restore <快照目录> <新的暂存目录> --service-stopped` 验证并恢复到新目录。工具拒绝覆盖现有目录，恢复数据库会移除旧管理会话。核验暂存内容与部署版本后，由维护人员在停机窗口替换同批数据和配置；先保留原数据，不混用不同批次文件。重新启动并完成登录、数据读取、文件下载及项目隔离核验。

关闭管理端或回退软件不能找回已删除数据。存在 unknown 用量时仍须向供应商对账，不得通过 TTL 或恢复操作擅自释放未知占用。
