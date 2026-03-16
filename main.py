
import os
import base64
import json
import mimetypes
from datetime import datetime
from typing import Optional, Set

from fastapi import FastAPI, Request, Response, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN, HTTP_404_NOT_FOUND
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

# --- 配置 --- #
DEFAULT_PASSWORD = os.environ.get("ADMIN_PASSWORD", "password")
STORAGE_DIR = "./data"
PASSWORD_FILE = os.path.join(STORAGE_DIR, ".config/password")
USAGE_DIR = os.path.join(STORAGE_DIR, ".config/usage")

# 定义可预览和可编辑的文件后缀
TEXT_EXTS = [".txt", ".sh", ".js", ".css", ".html", ".json", ".md", ".py", ".yml", ".yaml"]
IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"]

app = FastAPI()
security = HTTPBasic()

# 确保存储目录存在
os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(USAGE_DIR, exist_ok=True)

# 模拟 R2 的 get/put/delete/list 操作
class LocalBucket:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _get_full_path(self, key: str) -> str:
        return os.path.join(self.base_dir, key)

    async def get(self, key: str):
        file_path = self._get_full_path(key)
        if not os.path.exists(file_path) or os.path.isdir(file_path):
            return None
        
        # 模拟 R2 的对象结构
        class R2Object:
            def __init__(self, content: bytes, key: str, size: int, uploaded: datetime, content_type: Optional[str] = None):
                self.body = content
                self.key = key
                self.size = size
                self.uploaded = uploaded
                self._content_type = content_type

            async def text(self) -> str:
                return self.body.decode('utf-8')

            def writeHttpMetadata(self, headers: Headers):
                if self._content_type:
                    headers.set("Content-Type", self._content_type)

        with open(file_path, "rb") as f:
            content = f.read()
        
        stat = os.stat(file_path)
        content_type, _ = mimetypes.guess_type(file_path)
        return R2Object(content, key, stat.st_size, datetime.fromtimestamp(stat.st_mtime), content_type)

    async def put(self, key: str, content, httpMetadata: Optional[dict] = None):
        file_path = self._get_full_path(key)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if isinstance(content, bytes):
            with open(file_path, "wb") as f:
                f.write(content)
        elif hasattr(content, 'read'): # For UploadFile
            with open(file_path, "wb") as f:
                while True:
                    chunk = await content.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
        else: # Assume string
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(str(content))

    async def delete(self, key: str):
        file_path = self._get_full_path(key)
        if os.path.exists(file_path):
            os.remove(file_path)

    async def list(self, prefix: str = ""):
        objects = []
        for root, _, files in os.walk(self.base_dir):
            for file_name in files:
                full_path = os.path.join(root, file_name)
                relative_path = os.path.relpath(full_path, self.base_dir)
                if relative_path.startswith(prefix):
                    stat = os.stat(full_path)
                    objects.append({
                        "key": relative_path,
                        "size": stat.st_size,
                        "uploaded": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
        return {"objects": objects}

bucket = LocalBucket(STORAGE_DIR)

# --- 认证逻辑 --- #
async def get_current_password():
    if os.path.exists(PASSWORD_FILE):
        with open(PASSWORD_FILE, "r") as f:
            return f.read().strip()
    return DEFAULT_PASSWORD

async def authenticate_admin(credentials: HTTPBasicCredentials = Depends(security)):
    current_password = await get_current_password()
    correct_username = "admin"
    correct_password = current_password

    if not (credentials.username == correct_username and credentials.password == correct_password):
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.is_authorized = False
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Basic "):
            try:
                encoded_credentials = auth_header.split(" ")[1]
                decoded_credentials = base64.b64decode(encoded_credentials).decode("utf-8")
                username, password = decoded_credentials.split(":", 1)
                current_password = await get_current_password()
                if username == "admin" and password == current_password:
                    request.state.is_authorized = True
            except Exception:
                pass
        response = await call_next(request)
        return response

app.add_middleware(AuthMiddleware)

# --- 页面模板 --- #
templates = Jinja2Templates(directory="templates")

@app.on_event("startup")
async def startup_event():
    # 创建 templates 目录和 index.html
    os.makedirs("templates", exist_ok=True)
    with open("templates/index.html", "w", encoding="utf-8") as f:
        f.write("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>文件管理系统</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: -apple-system, system-ui, sans-serif; max-width: 1000px; margin: 40px auto; padding: 0 20px; background: #f8f9fa; color: #333; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; min-height: 40px; }
        .card { background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #eee; }
        th { color: #666; font-weight: 600; }
        .btn { padding: 6px 12px; border-radius: 6px; text-decoration: none; font-size: 14px; cursor: pointer; border: none; display: inline-block; transition: opacity 0.2s; }
        .btn:hover { opacity: 0.8; }
        .copy { background: #e8f5e9; color: #2e7d32; margin-right: 5px; }
        .download { background: #e3f2fd; color: #1976d2; margin-right: 5px; }
        .preview { background: #f3e5f5; color: #7b1fa2; margin-right: 5px; }
        .edit { background: #fff3e0; color: #ef6c00; margin-right: 5px; }
        .usage-btn { background: #e0f7fa; color: #00838f; margin-right: 5px; }
        .delete { background: #ffebee; color: #c62828; }
        .nav-btn { background: #333; color: white; padding: 8px 16px; }
        .footer { margin-top: 50px; text-align: center; font-size: 14px; color: #999; border-top: 1px solid #eee; padding-top: 20px; }
        .footer a { color: #666; text-decoration: none; }
        .upload-area { display: flex; gap: 10px; align-items: center; }
        
        .usage-box { background: #f1f8e9; padding: 15px; border-radius: 8px; border-left: 4px solid #8bc34a; margin: 5px 0; }
        .usage-text { margin-top: 8px; white-space: pre-wrap; font-family: monospace; font-size: 13px; color: #555; }

        /* 编辑器弹窗样式 */
        #editorModal, #usageModal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; }
        .modal-content { background: white; width: 90%; max-width: 800px; margin: 50px auto; padding: 20px; border-radius: 12px; position: relative; max-height: 80vh; overflow-y: auto; }
        #editorArea { width: 100%; height: 400px; margin: 15px 0; font-family: monospace; padding: 10px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
        #usageArea { width: 100%; height: 200px; margin: 15px 0; font-family: monospace; padding: 10px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
        .modal-footer { text-align: right; padding-top: 10px; }

        .pwd-area-weak { margin-top: 30px; padding: 15px; border-top: 1px solid #eee; color: #999; font-size: 13px; }
        .pwd-area-weak h4 { margin: 0 0 10px 0; font-weight: normal; color: #bbb; }
        .pwd-area-weak input[type="password"] { padding: 5px; border: 1px solid #eee; border-radius: 4px; font-size: 12px; width: 150px; color: #999; }
        .pwd-area-weak .btn-weak { padding: 4px 8px; background: #f5f5f5; color: #999; border: 1px solid #ddd; font-size: 12px; }
        
        input[type="text"], input[type="password"] { padding: 8px; border: 1px solid #ddd; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>{% if is_admin %}管理后台{% else %}文件列表{% endif %}</h1>
        {% if is_admin %}<a href="/" class="btn nav-btn">返回前台</a>{% elif is_authorized %}<a href="/admin" class="btn nav-btn">进入后台</a>{% endif %}
    </div>

    {% if is_admin %}
    <div class="card">
        <h3>文件上传</h3>
        <div class="upload-area">
            <input type="file" id="fileInput">
            <button onclick="uploadFile()" class="btn nav-btn" id="upBtn">开始上传</button>
        </div>
    </div>
    {% endif %}

    <div class="card">
        <table>
            <thead>
                <tr>
                    <th>文件名</th>
                    <th>大小</th>
                    <th>上传时间</th>
                    <th>操作</th>
                </tr>
            </thead>
            <tbody>
                {% if files %}
                    {% for f in files %}
                        <tr id="row-{{ f.key | btoa_safe }}">
                            <td>{{ f.key }}</td>
                            <td>{{ (f.size / 1024) | round(1) }} KB</td>
                            <td>{{ f.uploaded }}</td>
                            <td>
                                {% if is_authorized %}
                                    <button onclick="copyUrl('{{ url_for('download_file', key=f.key) }}')" class="btn copy">复制</button>
                                    <a href="{{ url_for('download_file', key=f.key) }}" class="btn download">下载</a>
                                    {% if f.is_previewable %}<a href="{{ url_for('preview_file', key=f.key) }}" target="_blank" class="btn preview">预览</a>{% endif %}
                                    {% if f.is_editable %}<button onclick="editFile('{{ f.key }}')" class="btn edit">编辑</button>{% endif %}
                                    <button onclick="{% if is_admin %}openUsageEditor('{{ f.key }}'){% else %}toggleUsage('{{ f.key }}'){% endif %}" class="btn usage-btn">用法</button>
                                    {% if is_admin %}<button onclick="deleteFile('{{ f.key }}')" class="btn delete">删除</button>{% endif %}
                                {% else %}
                                    -
                                {% endif %}
                            </td>
                        </tr>
                        <tr id="usage-row-{{ f.key | btoa_safe }}" class="usage-content-row" style="display:none;">
                            <td colspan="4">
                                <div class="usage-box">
                                    <strong>用法说明:</strong>
                                    <div id="usage-text-{{ f.key | btoa_safe }}" class="usage-text">加载中...</div>
                                </div>
                            </td>
                        </tr>
                    {% endfor %}
                {% else %}
                    <tr><td colspan="4">暂无文件</td></tr>
                {% endif %}
            </tbody>
        </table>
    </div>

    <!-- 编辑器弹窗 -->
    <div id="editorModal">
        <div class="modal-content">
            <h3 id="editorTitle">编辑文件</h3>
            <textarea id="editorArea"></textarea>
            <div class="modal-footer">
                <button onclick="closeEditor()" class="btn">取消</button>
                <button onclick="saveFile()" class="btn nav-btn">保存修改</button>
            </div>
        </div>
    </div>

    <!-- 用法编辑器弹窗 -->
    <div id="usageModal">
        <div class="modal-content">
            <h3 id="usageTitle">编辑用法说明</h3>
            <p style="font-size:12px; color:#666;">支持普通文本，管理员保存后授权用户点击“用法”即可查看。</p>
            <textarea id="usageArea" placeholder="请输入该脚本的使用方法..."></textarea>
            <div class="modal-footer">
                <button onclick="closeUsageEditor()" class="btn">取消</button>
                <button onclick="saveUsage()" class="btn nav-btn">保存说明</button>
            </div>
        </div>
    </div>

    {% if is_admin %}
    <div class="pwd-area-weak">
        <h4>系统设置</h4>
        <span>修改管理密码：</span>
        <input type="password" id="newPwd" placeholder="输入新密码">
        <button onclick="changePassword()" class="btn btn-weak">确认修改</button>
    </div>
    {% endif %}

    {% if not is_authorized %}<div class="footer"><a href="/admin">管理入口</a></div>{% endif %}

    <script>
        let currentEditingKey = '';
        let currentUsageKey = '';

        function btoa_safe(str) {
            return btoa(str).replace(/=/g, '');
        }

        async function copyUrl(url) {
            try {
                await navigator.clipboard.writeText(url);
                alert("链接已复制到剪贴板");
            } catch (err) {
                const input = document.createElement('input');
                input.value = url;
                document.body.appendChild(input);
                input.select();
                document.execCommand('copy');
                document.body.removeChild(input);
                alert("链接已复制");
            }
        }

        async function editFile(key) {
            currentEditingKey = key;
            document.getElementById('editorTitle').innerText = '正在编辑: ' + key;
            const resp = await fetch('/api/get-content', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key }) });
            if (resp.ok) {
                const { content } = await resp.json();
                document.getElementById('editorArea').value = content;
                document.getElementById('editorModal').style.display = 'block';
            } else {
                alert("获取内容失败");
            }
        }

        function closeEditor() {
            document.getElementById('editorModal').style.display = 'none';
        }

        async function saveFile() {
            const content = document.getElementById('editorArea').value;
            const resp = await fetch('/api/save-content', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: currentEditingKey, content })
            });
            if (resp.ok) {
                alert("保存成功");
                closeEditor();
                location.reload();
            } else {
                alert("保存失败");
            }
        }

        // 用法说明相关逻辑
        async function toggleUsage(key) {
            const safeKey = btoa_safe(key);
            const row = document.getElementById('usage-row-' + safeKey);
            const textDiv = document.getElementById('usage-text-' + safeKey);
            
            if (row.style.display === 'none') {
                row.style.display = 'table-row';
                const resp = await fetch('/api/get-usage', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key }) });
                if (resp.ok) {
                    const { content } = await resp.json();
                    textDiv.innerText = content || "暂无说明";
                } else {
                    textDiv.innerText = "获取失败，请确认登录状态";
                }
            } else {
                row.style.display = 'none';
            }
        }

        async function openUsageEditor(key) {
            currentUsageKey = key;
            document.getElementById('usageTitle').innerText = '编辑用法说明: ' + key;
            const resp = await fetch('/api/get-usage', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key }) });
            if (resp.ok) {
                const { content } = await resp.json();
                document.getElementById('usageArea').value = content;
                document.getElementById('usageModal').style.display = 'block';
            } else {
                alert("获取内容失败");
            }
        }

        function closeUsageEditor() {
            document.getElementById('usageModal').style.display = 'none';
        }

        async function saveUsage() {
            const content = document.getElementById('usageArea').value;
            const resp = await fetch('/api/save-usage', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: currentUsageKey, content })
            });
            if (resp.ok) {
                alert("用法说明已保存");
                closeUsageEditor();
                location.reload();
            } else {
                alert("保存失败");
            }
        }

        async function uploadFile() {
            const fileInput = document.getElementById('fileInput');
            if (!fileInput.files[0]) return alert("请选择文件");
            const btn = document.getElementById('upBtn');
            btn.disabled = true; btn.innerText = "上传中...";
            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            const resp = await fetch('/api/upload', { method: 'POST', body: formData });
            if (resp.ok) location.reload(); else alert("上传失败");
        }

        async function deleteFile(key) {
            if (confirm('确定删除 ' + key + ' ?')) {
                await fetch('/api/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key }) });
                location.reload();
            }
        }

        async function changePassword() {
            const newPassword = document.getElementById('newPwd').value;
            if (!newPassword) return alert("请输入新密码");
            if (confirm('修改后需使用新密码重新登录，确定吗？')) {
                const resp = await fetch('/api/change-password', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ newPassword }) });
                if (resp.ok) { alert("修改成功，请刷新页面重新登录"); location.href = "/admin"; }
            }
        }
    </script>
</body>
</html>
""")

    with open("templates/preview.html", "w", encoding="utf-8") as f:
        f.write("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>预览: {{ key }}</title>
    <style>
        body { font-family: monospace; padding: 20px; background: #2d2d2d; color: #ccc; line-height: 1.5; }
        .nav { margin-bottom: 20px; font-family: sans-serif; }
        .nav a { color: #3498db; text-decoration: none; }
        pre { background: #1e1e1e; padding: 20px; border-radius: 8px; overflow: auto; white-space: pre-wrap; word-wrap: break-word; border: 1px solid #444; }
    </style>
</head>
<body>
    <div class="nav"><a href="javascript:history.back()">← 返回列表</a> | 文件名: {{ key }}</div>
    <pre>{{ content | e }}</pre>
</body>
</html>
""")

# --- 路由 --- #

@app.get("/")
@app.get("/admin")
async def list_files(request: Request):
    is_admin_route = request.url.path == "/admin"
    is_authorized = request.state.is_authorized

    if is_admin_route and not is_authorized:
        return Response(status_code=HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic realm=\"Admin Area\""})

    objects_data = await bucket.list()
    files = []
    all_usage_keys = set()

    # 获取所有用法说明的key
    usage_objects_data = await bucket.list(prefix=".config/usage/")
    for obj in usage_objects_data["objects"]:
        all_usage_keys.add(obj["key"].replace(".config/usage/", ""))

    for obj in objects_data["objects"]:
        if not obj["key"].startswith(".config/"):
            lower_key = obj["key"].lower()
            is_text = any(lower_key.endswith(ext) for ext in TEXT_EXTS)
            is_image = any(lower_key.endswith(ext) for ext in IMAGE_EXTS)
            files.append({
                "key": obj["key"],
                "size": obj["size"],
                "uploaded": datetime.fromisoformat(obj["uploaded"]).strftime('%Y-%m-%d %H:%M:%S'),
                "is_previewable": is_text or is_image,
                "is_editable": is_admin_route and is_text,
                "has_usage": obj["key"] in all_usage_keys # 检查是否有用法说明
            })
    
    # 注册 Jinja2 过滤器
    templates.env.filters['btoa_safe'] = lambda s: base64.b64encode(s.encode('utf-8')).decode('utf-8').replace('=', '')

    return templates.TemplateResponse(
        "index.html", 
        {"request": request, "files": files, "is_admin": is_admin_route, "is_authorized": is_authorized}
    )

@app.get("/download/{key:path}")
async def download_file(request: Request, key: str):
    if not request.state.is_authorized:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="未授权访问下载链接")
    
    object = await bucket.get(key)
    if not object:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="文件不存在")
    
    content_type, _ = mimetypes.guess_type(key)
    headers = {
        "Content-Disposition": f"attachment; filename=\"{key}\"",
        "Content-Type": content_type or "application/octet-stream"
    }
    return Response(content=object.body, headers=headers)

@app.get("/preview/{key:path}", response_class=HTMLResponse)
async def preview_file(request: Request, key: str):
    if not request.state.is_authorized:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未授权")

    object = await bucket.get(key)
    if not object:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="文件不存在")
    
    lower_key = key.lower()
    if any(lower_key.endswith(ext) for ext in IMAGE_EXTS):
        content_type, _ = mimetypes.guess_type(key)
        return Response(content=object.body, media_type=content_type or "application/octet-stream")
    else:
        content = await object.text()
        return templates.TemplateResponse("preview.html", {"request": request, "key": key, "content": content})

@app.post("/api/get-content")
async def get_content(request: Request, key: str = Form(...)):
    if not request.state.is_authorized:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未授权")
    object = await bucket.get(key)
    if not object:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="文件不存在")
    content = await object.text()
    return JSONResponse({"content": content})

@app.post("/api/save-content")
async def save_content(request: Request, key: str = Form(...), content: str = Form(...)):
    if not request.state.is_authorized:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未授权")
    await bucket.put(key, content.encode('utf-8'))
    return Response("OK")

@app.post("/api/get-usage")
async def get_usage(request: Request, key: str = Form(...)):
    if not request.state.is_authorized:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未授权")
    usage_key = os.path.join(USAGE_DIR, key)
    if os.path.exists(usage_key):
        with open(usage_key, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = ""
    return JSONResponse({"content": content})

@app.post("/api/save-usage")
async def save_usage(request: Request, key: str = Form(...), content: str = Form(...)):
    if not request.state.is_authorized:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未授权")
    usage_key = os.path.join(USAGE_DIR, key)
    if not content or content.strip() == "":
        if os.path.exists(usage_key):
            os.remove(usage_key)
    else:
        os.makedirs(os.path.dirname(usage_key), exist_ok=True)
        with open(usage_key, "w", encoding="utf-8") as f:
            f.write(content)
    return Response("OK")

@app.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    if not request.state.is_authorized:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未授权")
    await bucket.put(file.filename, file.file.read())
    return Response("OK")

@app.post("/api/delete")
async def delete_file(request: Request, key: str = Form(...)):
    if not request.state.is_authorized:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未授权")
    await bucket.delete(key)
    usage_key = os.path.join(USAGE_DIR, key)
    if os.path.exists(usage_key):
        os.remove(usage_key)
    return Response("OK")

@app.post("/api/change-password")
async def change_password(request: Request, newPassword: str = Form(...)):
    if not request.state.is_authorized:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未授权")
    if not newPassword or len(newPassword) < 1:
        raise HTTPException(status_code=400, detail="密码不能为空")
    os.makedirs(os.path.dirname(PASSWORD_FILE), exist_ok=True)
    with open(PASSWORD_FILE, "w") as f:
        f.write(newPassword)
    return Response("OK")

