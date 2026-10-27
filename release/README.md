# Windows 构建说明

目标：Windows 10/11 x64，Python 3.10 x64，PyInstaller onedir，Inno Setup 6。安装包不包含数据库、上传成绩、历史导出或授权凭据。

## 构建

```powershell
py -3.10 -m venv .release-venv
.\.release-venv\Scripts\python.exe -m pip install -r release/requirements-lock.txt
powershell -NoProfile -ExecutionPolicy Bypass -File release/build.ps1
```

也可用 `-PythonExe <已准备好依赖的python.exe路径>` 指定构建解释器。依赖环境只用于构建，不整目录复制进安装包。安装官方 Inno Setup 6 后可编译 Setup；使用 `-OnedirOnly` 仅构建程序目录。

输出：`dist/StudentScoreAnalysis/StudentScoreAnalysis.exe` 与 `_internal/` 必须整体使用；安装程序位于 `dist/installer/`。新产品有独立 AppId、互斥锁及数据目录 `%LOCALAPPDATA%\StudentScoreAnalysis`。不查找其他产品的历史数据库。

`manifest.py` 是资源白名单。工作簿输出由程序生成；只有两份上传模板随包提供。`audit.py` 检查资源、敏感内容、开发路径和压缩 Python 内容，再生成逐文件安装清单。

## 验证

完整源码测试、前端检查、资源审计通过后构建。实际 EXE 用隔离的 LOCALAPPDATA 测试首次空库、静态资源、重启、重复启动和端口冲突。不使用生产服务和真实账号。

编译成功不等于所有机器安装验证通过。发布前还需干净 Windows 10/11、离线启动、实际使用、升级和卸载保留数据的验收。未签名安装包可能显示 Windows 发布者提示，不要伪称已签名。

普通用户无需 Python、Node 或 Inno Setup，安装后免登录使用，无需配置后台。
