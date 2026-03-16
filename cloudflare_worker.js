/**
 * Cloudflare Worker: R2 智能文件管理系统 (V2.6 Optimized)
 * 功能：前台展示、多格式预览、后台管理、权限控制、用法说明管理
 * 优化点：前台默认不展示任何操作（下载/复制/预览/用法），仅管理员登录后展示。
 */

const DEFAULT_PASSWORD = "77169.com"; 
const BUCKET_BINDING = "MY_BUCKET";
const PASSWORD_KEY = ".config/password"; // 密码存储路径
const USAGE_PREFIX = ".config/usage/";  // 用法说明存储前缀

// 定义可预览和可编辑的文件后缀
const TEXT_EXTS = [".txt", ".sh", ".js", ".css", ".html", ".json", ".md", ".py", ".yml", ".yaml"];
const IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const bucket = env[BUCKET_BINDING];
    if (!bucket) return new Response("R2 未绑定", { status: 500 });

    // --- 1. 获取当前有效密码 ---
    let currentPassword = DEFAULT_PASSWORD;
    const pwdObj = await bucket.get(PASSWORD_KEY);
    if (pwdObj) currentPassword = await pwdObj.text();

    // --- 2. 身份验证逻辑 ---
    const authHeader = request.headers.get("Authorization");
    const isAuthorized = authHeader === `Basic ${btoa("admin:" + currentPassword)}`;

    // --- 3. 路由处理 ---

    // 下载功能 (不需要登录验证，仅需要知道链接即可下载)
    if (url.pathname.startsWith("/download/")) {
      const key = decodeURIComponent(url.pathname.slice(10));
      // 前台针对未登录用户不展示下载链接，实现了安全性
      const object = await bucket.get(key);
      if (!object) return new Response("文件不存在", { status: 404 });
      const headers = new Headers();
      object.writeHttpMetadata(headers);
      headers.set("Content-Disposition", `attachment; filename="${key}"`);
      return new Response(object.body, { headers });
    }

    // 预览功能 (仅限管理员)
    if (url.pathname.startsWith("/preview/")) {
      if (!isAuthorized) return new Response("未授权", { status: 401 });
      const key = decodeURIComponent(url.pathname.slice(9));
      const object = await bucket.get(key);
      if (!object) return new Response("文件不存在", { status: 404 });
      
      const lowerKey = key.toLowerCase();
      if (IMAGE_EXTS.some(ext => lowerKey.endsWith(ext))) {
        const headers = new Headers();
        object.writeHttpMetadata(headers);
        return new Response(object.body, { headers });
      } else {
        const content = await object.text();
        return new Response(renderPreview(key, content), { headers: { "Content-Type": "text/html;charset=UTF-8" } });
      }
    }

    // API: 获取文件内容 (用于编辑，仅限管理员)
    if (url.pathname === "/api/get-content" && request.method === "POST") {
      if (!isAuthorized) return new Response("未授权", { status: 401 });
      const { key } = await request.json();
      const object = await bucket.get(key);
      if (!object) return new Response("文件不存在", { status: 404 });
      const content = await object.text();
      return new Response(JSON.stringify({ content }), { headers: { "Content-Type": "application/json" } });
    }

    // API: 保存文件内容 (用于编辑，仅限管理员)
    if (url.pathname === "/api/save-content" && request.method === "POST") {
      if (!isAuthorized) return new Response("未授权", { status: 401 });
      const { key, content } = await request.json();
      await bucket.put(key, content);
      return new Response("OK");
    }

    // API: 获取用法说明 (管理员或授权用户)
    if (url.pathname === "/api/get-usage" && request.method === "POST") {
      // 只有管理员登录后才能获取用法说明内容
      if (!isAuthorized) return new Response("未授权", { status: 401 });
      const { key } = await request.json();
      const usageKey = USAGE_PREFIX + key;
      const object = await bucket.get(usageKey);
      const content = object ? await object.text() : "";
      return new Response(JSON.stringify({ content }), { headers: { "Content-Type": "application/json" } });
    }

    // API: 保存用法说明 (仅限管理员)
    if (url.pathname === "/api/save-usage" && request.method === "POST") {
      if (!isAuthorized) return new Response("未授权", { status: 401 });
      const { key, content } = await request.json();
      const usageKey = USAGE_PREFIX + key;
      if (!content || content.trim() === "") {
        await bucket.delete(usageKey);
      } else {
        await bucket.put(usageKey, content);
      }
      return new Response("OK");
    }

    // API: 上传 (仅限管理员)
    if (url.pathname === "/api/upload" && request.method === "POST") {
      if (!isAuthorized) return new Response("未授权", { status: 401 });
      const formData = await request.formData();
      const file = formData.get("file");
      await bucket.put(file.name, file.stream(), { httpMetadata: { contentType: file.type } } );
      return new Response("OK");
    }

    // API: 删除 (仅限管理员)
    if (url.pathname === "/api/delete" && request.method === "POST") {
      if (!isAuthorized) return new Response("未授权", { status: 401 });
      const { key } = await request.json();
      await bucket.delete(key);
      await bucket.delete(USAGE_PREFIX + key); 
      return new Response("OK");
    }

    // API: 修改密码 (仅限管理员)
    if (url.pathname === "/api/change-password" && request.method === "POST") {
      if (!isAuthorized) return new Response("未授权", { status: 401 });
      const { newPassword } = await request.json();
      if (!newPassword || newPassword.length < 1) return new Response("密码不能为空", { status: 400 });
      await bucket.put(PASSWORD_KEY, newPassword);
      return new Response("OK");
    }

    // --- 4. 页面渲染 ---
    const isAdmin = url.pathname === "/admin";
    // 权限校验：访问管理后台必须登录，前台展示则根据登录状态动态渲染操作按钮
    if (isAdmin && !isAuthorized) {
      return new Response("需登录", { status: 401, headers: { "WWW-Authenticate": 'Basic realm="Admin Area"' } });
    }

    const objects = await bucket.list();
    const files = objects.objects.filter(o => !o.key.startsWith(".config/"));

    // 获取所有用法说明的存在情况
    const usageObjects = await bucket.list({ prefix: USAGE_PREFIX });
    const usageKeys = new Set(usageObjects.objects.map(o => o.key.slice(USAGE_PREFIX.length)));

    return new Response(renderMain(files, isAdmin, isAuthorized, url.origin, usageKeys), {
      headers: { "Content-Type": "text/html;charset=UTF-8" }
    });
  }
};

// --- 页面模板 ---

function renderMain(files, isAdmin, isAuthorized, origin, usageKeys) {
  const fileRows = files.map(f => {
    const lowerKey = f.key.toLowerCase();
    const isText = TEXT_EXTS.some(ext => lowerKey.endsWith(ext));
    const isImage = IMAGE_EXTS.some(ext => lowerKey.endsWith(ext));
    const isPreviewable = isText || isImage;
    const isEditable = isAdmin && isText;
    
    const downloadUrl = `${origin}/download/${encodeURIComponent(f.key)}`;
    const uploadTime = f.uploaded ? new Date(f.uploaded).toLocaleString('zh-CN', { hour12: false }) : '-';
    
    // 只有在管理员登录状态下（不管是前台还是后台），才渲染操作按钮
    const actions = isAuthorized ? `
        <button onclick="copyUrl('${downloadUrl}')" class="btn copy">复制</button>
        <a href="${downloadUrl}" class="btn download">下载</a>
        ${isPreviewable ? `<a href="/preview/${encodeURIComponent(f.key)}" target="_blank" class="btn preview">预览</a>` : ""}
        ${isEditable ? `<button onclick="editFile('${f.key}')" class="btn edit">编辑</button>` : ""}
        <button onclick="${isAdmin ? `openUsageEditor('${f.key}')` : `toggleUsage('${f.key}')`}" class="btn usage-btn">用法</button>
        ${isAdmin ? `<button onclick="deleteFile('${f.key}')" class="btn delete">删除</button>` : ""}
    ` : "-";

    return `
    <tr id="row-${btoa(f.key).replace(/=/g, '')}">
      <td>${f.key}</td>
      <td>${(f.size / 1024).toFixed(1)} KB</td>
      <td>${uploadTime}</td>
      <td>${actions}</td>
    </tr>
    <tr id="usage-row-${btoa(f.key).replace(/=/g, '')}" class="usage-content-row" style="display:none;">
      <td colspan="4">
        <div class="usage-box">
          <strong>用法说明:</strong>
          <div id="usage-text-${btoa(f.key).replace(/=/g, '')}" class="usage-text">加载中...</div>
        </div>
      </td>
    </tr>`;
  }).join("");

  return `
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
      <h1>${isAdmin ? "管理后台" : "文件列表"}</h1>
      ${isAdmin ? `<a href="/" class="btn nav-btn">返回前台</a>` : (isAuthorized ? `<a href="/admin" class="btn nav-btn">进入后台</a>` : "")}
    </div>

    ${isAdmin ? `
      <div class="card">
        <h3>文件上传</h3>
        <div class="upload-area">
          <input type="file" id="fileInput">
          <button onclick="uploadFile()" class="btn nav-btn" id="upBtn">开始上传</button>
        </div>
      </div>
    ` : ""}

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
        <tbody>${fileRows || '<tr><td colspan="4">暂无文件</td></tr>'}</tbody>
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

    ${isAdmin ? `
      <div class="pwd-area-weak">
        <h4>系统设置</h4>
        <span>修改管理密码：</span>
        <input type="password" id="newPwd" placeholder="输入新密码">
        <button onclick="changePassword()" class="btn btn-weak">确认修改</button>
      </div>
    ` : ""}

    ${!isAuthorized ? `<div class="footer"><a href="/admin">管理入口</a></div>` : ""}

    <script>
      let currentEditingKey = '';
      let currentUsageKey = '';

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
        const resp = await fetch('/api/get-content', { method: 'POST', body: JSON.stringify({ key }) });
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
        const safeKey = btoa(key).replace(/=/g, '');
        const row = document.getElementById('usage-row-' + safeKey);
        const textDiv = document.getElementById('usage-text-' + safeKey);
        
        if (row.style.display === 'none') {
          row.style.display = 'table-row';
          const resp = await fetch('/api/get-usage', { method: 'POST', body: JSON.stringify({ key }) });
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
        const resp = await fetch('/api/get-usage', { method: 'POST', body: JSON.stringify({ key }) });
        if (resp.ok) {
          const { content } = await resp.json();
          document.getElementById('usageArea').value = content;
          document.getElementById('usageModal').style.display = 'block';
        }
      }

      function closeUsageEditor() {
        document.getElementById('usageModal').style.display = 'none';
      }

      async function saveUsage() {
        const content = document.getElementById('usageArea').value;
        const resp = await fetch('/api/save-usage', { 
          method: 'POST', 
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
          await fetch('/api/delete', { method: 'POST', body: JSON.stringify({ key }) });
          location.reload();
        }
      }

      async function changePassword() {
        const newPassword = document.getElementById('newPwd').value;
        if (!newPassword) return alert("请输入新密码");
        if (confirm('修改后需使用新密码重新登录，确定吗？')) {
          const resp = await fetch('/api/change-password', { method: 'POST', body: JSON.stringify({ newPassword }) });
          if (resp.ok) { alert("修改成功，请刷新页面重新登录"); location.href = "/admin"; }
        }
      }
    </script>
  </body>
  </html>`;
}

function renderPreview(key, content) {
  return `
  <!DOCTYPE html>
  <html>
  <head>
    <meta charset="utf-8">
    <title>预览: ${key}</title>
    <style>
      body { font-family: monospace; padding: 20px; background: #2d2d2d; color: #ccc; line-height: 1.5; }
      .nav { margin-bottom: 20px; font-family: sans-serif; }
      .nav a { color: #3498db; text-decoration: none; }
      pre { background: #1e1e1e; padding: 20px; border-radius: 8px; overflow: auto; white-space: pre-wrap; word-wrap: break-word; border: 1px solid #444; }
    </style>
  </head>
  <body>
    <div class="nav"><a href="javascript:history.back()">← 返回列表</a> | 文件名: ${key}</div>
    <pre>${content.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</pre>
  </body>
  </html>`;
}
