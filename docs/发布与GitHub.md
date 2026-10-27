# 发布检查与 GitHub 操作

本文是后续操作教程，本次不自动上传、公开或提交活动。

可以只发布源码，无需制作安装包。未选择项目许可证时也可以公开代码，但不代表已授予开源使用权；第三方资源仍须遵守各自的许可条件。

## 公开前

1. 确认有权公开和授权项目代码、业务实现、字体与图片等资源。若开发涉及单位成果，先取得相应许可。
2. 选择适合的开源许可证并添加 LICENSE，填写有权授权的权利人信息。MIT、Apache-2.0、GPL 等授予的权利和要求不同，不应随意代替权利人选择。
3. 检查新仓库的当前文件及全部 Git 历史。不提交数据库、真实名单、上传/导出结果、账号、密码、授权密钥或本机配置。
4. 源码目录保持可复现：README、使用指南、依赖、测试、构建脚本、上传模板齐全。不要把整个磁盘工作区、虚拟环境或旧仓库一起上传。
5. 对发布文件核对 SHA-256。安装包放到 GitHub Releases，不作为普通源码文件提交。

## GitHub Desktop

1. 登录自己的 GitHub 账号。
2. 选择 File → Add local repository，选择本项目的源码根目录。如果尚未初始化仓库，使用 Create a repository here；不要选择包含其他产品或内部资料的目录。
3. 在 Changes 查看待提交文件。确认不含 `instance/`、`build/`、`dist/`、`.audit/`、临时测试数据和本机配置；`.gitignore` 只阻止未跟踪文件，不能清除既有历史。
4. 填写简洁提交说明，点击 Commit to main，在本机建立快照。已有提交时不要重复创建。
5. 权属及许可证确认后点击 Publish repository，名称使用 `student-score-analysis`，填写项目简介。公开发布时取消 Keep this code private；若审核尚未完成，则保持私有。点击 Publish 才会上传，本教程不会代你操作。
6. 打开仓库检查 README、模板和文档链接，添加简介及 topics，例如 education、student-performance、python、flask。
7. 发布安装包：Releases → Draft a new release，建立版本标签，写明系统要求、本机数据目录、已验证范围和已知限制，附安装包及 SHA-256 文件，然后人工确认 Publish release。
8. 后续修改先提交，再 Push origin；不要误用 Force push 覆盖协作者历史。

删除工作区文件不能删除已推送的历史。若误传凭据，应立即撤销或轮换，并按官方文档处理历史；不能只补一个删除提交。

官方参考：[GitHub Desktop 创建仓库](https://docs.github.com/en/desktop/overview/creating-your-first-repository-using-github-desktop)、[仓库许可证](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)、[发布版本](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)。
