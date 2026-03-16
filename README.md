# up-file: 基于 FastAPI 和 Docker 的文件管理系统

`up-file` 是一个轻量级的文件管理系统，旨在提供安全、便捷的文件存储、管理和分享功能。它基于 Python FastAPI 框架开发，并支持 Docker 容器化部署，使得安装和维护变得异常简单。该系统特别针对需要对文件访问进行权限控制，并为特定文件提供使用说明的场景进行了优化。

## ✨ 主要功能

-   **文件上传与管理**：支持文件的上传、下载和删除操作。
-   **在线预览**：支持常见文本文件（如 `.txt`, `.sh`, `.py`, `.md` 等）和图片文件（如 `.jpg`, `.png`, `.gif` 等）的在线预览。
-   **在线编辑**：管理员可直接在网页上编辑文本类文件内容。
-   **严格的权限控制**：
    -   **未登录用户**：前台页面将完全隐藏“下载”、“复制链接”、“预览”、“编辑”、“用法”和“删除”等所有操作按钮。同时，直接访问下载链接也将被拒绝（返回 403 Forbidden）。
    -   **管理员**：登录后，无论在前台还是后台，均可看到并执行所有文件管理操作。
-   **用法说明**：
    -   管理员可以在后台为每个文件编写详细的“用法说明”。
    -   已登录用户在前台点击“用法”按钮，即可下拉查看该文件的用法说明。
-   **容器化部署**：提供 Docker 和 Docker Compose 配置，实现快速部署和环境隔离。
-   **持久化存储**：文件和配置数据存储在本地文件系统，通过 Docker 卷挂载实现数据持久化。

## 🚀 部署方式

本项目支持两种部署方式：**Docker 部署**（适用于自有服务器）和 **Cloudflare Worker 部署**（适用于无服务器环境）。

### 方式一：Docker 部署 (推荐用于自有服务器)

#### 前提条件

确保您的服务器已安装 Docker 和 Docker Compose。

#### 步骤

1.  **克隆仓库**：
    ```bash
    git clone https://github.com/zzusec/up-file.git
    cd up-file
    ```

2.  **启动服务**：
    使用 Docker Compose 启动服务。首次启动会自动构建 Docker 镜像。
    ```bash
    docker-compose up -d
    ```

3.  **访问应用**：
    服务启动后，您可以通过浏览器访问 `http://您的服务器IP或域名:8399`。

### 方式二：Cloudflare Worker 部署 (推荐用于无服务器环境)

#### 前提条件

1.  拥有一个 Cloudflare 账号。
2.  已配置 Cloudflare R2 存储桶。
3.  已安装 `wrangler` CLI 工具。

#### 步骤

1.  **获取 Worker 脚本**：
    项目根目录下的 `cloudflare_worker.js` 即为 Cloudflare Worker 脚本。

2.  **配置 `wrangler.toml`** (示例，请根据您的实际情况修改):
    ```toml
    name = "your-file-manager-worker"
    main = "cloudflare_worker.js"
    compatibility_date = "2024-01-01"

    [vars]
    DEFAULT_PASSWORD = "password" # 您的管理员密码

    [[r2_buckets]]
    binding = "MY_BUCKET" # 对应 worker.js 中的 BUCKET_BINDING
    bucket_name = "您的R2桶名称"
    preview_bucket_name = "您的R2桶名称"
    ```

3.  **部署 Worker**：
    ```bash
    wrangler deploy
    ```

4.  **访问应用**：
    部署成功后，通过您的 Worker 域名访问。

#### 注意事项

-   Cloudflare Worker 部署方式中，文件和配置数据存储在 Cloudflare R2 存储桶中。
-   `DEFAULT_PASSWORD` 变量需要在 `wrangler.toml` 中配置，或通过 Cloudflare Worker 控制台设置环境变量。
-   `BUCKET_BINDING` 变量应与 `wrangler.toml` 中 `[[r2_buckets]]` 下的 `binding` 名称一致。

## ⚙️ 配置说明

-   **默认端口**：应用默认运行在 `8399` 端口。您可以通过修改 `docker-compose.yml` 文件中的 `ports` 映射来更改。
-   **默认管理员密码**：初始管理员密码为 `password`。强烈建议您在首次登录后通过管理后台进行修改，或在 `docker-compose.yml` 中设置 `ADMIN_PASSWORD` 环境变量来覆盖默认值。
    ```yaml
    # docker-compose.yml 示例
    services:
      file-manager:
        # ...
        environment:
          ADMIN_PASSWORD: "您的新密码" # 修改此处
        # ...
    ```
-   **数据持久化**：所有上传的文件和配置（包括密码和用法说明）都存储在 `./data` 目录下。`docker-compose.yml` 已配置将此目录挂载到容器内部，确保数据在容器重启后不会丢失。
    *   **目录自动创建**：如果宿主机上的 `./data` 目录不存在，Docker Compose 在首次启动时会自动创建它。
    *   **权限说明**：请确保运行 Docker 的用户对 `./data` 目录有读写权限，否则容器可能无法写入文件。如果遇到权限问题，可以尝试修改 `./data` 目录的权限，例如 `sudo chmod -R 777 ./data` (生产环境不推荐，仅供测试)。

## 💡 使用指南

### 1. 访问前台

-   直接访问 `http://您的服务器IP或域名:8399` 即可查看文件列表。此时，您将看不到任何操作按钮。

### 2. 登录管理员后台

-   访问 `http://您的服务器IP或域名:8399/admin`。
-   浏览器会弹出 Basic Auth 认证窗口，输入用户名 `admin` 和密码 `password`（或您设置的新密码）进行登录。
-   登录成功后，您将进入管理后台，可以看到文件上传区域和所有文件的操作按钮。

### 3. 文件操作

-   **上传文件**：在管理后台，通过“文件上传”区域选择文件并点击“开始上传”。
-   **下载/复制链接**：点击对应文件的“下载”或“复制”按钮。
-   **预览文件**：点击“预览”按钮在新标签页中查看文件内容（支持图片和文本）。
-   **编辑文件**：点击“编辑”按钮，在弹出的编辑器中修改文本文件内容并保存。
-   **用法说明**：
    -   **管理员**：点击“用法”按钮，弹出编辑框，您可以为该文件编写详细的使用说明。保存后，该说明将与文件关联。
    -   **已登录用户**：在前台点击“用法”按钮，会下拉显示管理员编写的用法说明。
-   **删除文件**：点击“删除”按钮，确认后即可删除文件及其关联的用法说明。

### 4. 修改管理员密码

-   在管理后台底部，找到“系统设置”区域，输入新密码并点击“确认修改”。修改后，您需要使用新密码重新登录。

## 🛠️ 技术栈

-   **后端**：Python 3.9+, FastAPI (Docker 部署)
-   **无服务器**：Cloudflare Worker, Cloudflare R2 (Worker 部署)
-   **前端**：HTML, CSS, JavaScript (内联)
-   **容器化**：Docker, Docker Compose (Docker 部署)
-   **模板引擎**：Jinja2 (Docker 部署)

## 📄 许可证

本项目采用 MIT 许可证。
