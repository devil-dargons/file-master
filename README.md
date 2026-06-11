📂 FileMaster - 智能本地文件管家
FileMaster 是一款基于 Python 和 PySide6 开发的跨平台桌面文件管理工具。它专注于解决本地海量文件的去重清理、标签化管理以及多媒体预览痛点。通过高效的 SQLite 数据库索引和异步缩略图引擎，即使在处理百万级文件时也能保持丝滑流畅的体验。





✨ 核心功能
🚀 高效扫描与检索
增量扫描：支持断点续扫，只更新变动的文件，大幅提升二次启动速度。
多条件组合搜索：支持按文件夹路径、文件名模糊匹配、MD5 精确查找以及文件类型进行实时过滤。
物理分页展示：支持自定义每页显示条数（10/25/50/100），配置自动持久化，内存占用极低。
🖼️ 强大的媒体预览
异步缩略图引擎：后台静默提取视频首帧和图片缩略图，不阻塞 UI 响应。
高清详情面板：右侧独立详情区，点击图片可查看原图并支持滚轮无损缩放，视频支持一键调用系统播放器。
智能分类：自动识别图片、视频、文档、代码等 6 大类文件并展示图标。
🏷️ 灵活的标签系统
多维标签管理：支持为文件添加多个标签，支持标签的增删改查。
批量操作：支持对选中文件进行批量打标签、批量重命名、批量移动/复制。
标签联动搜索：在列表顶部支持通过标签快速筛选相关文件。
🔄 智能去重与清理
MD5 深度去重：基于文件内容哈希值精准识别重复文件，避免误删。
智能清理策略：支持“保留首个，删除其余”的一键清理，或手动选择保留项。
安全删除：支持移入回收站或仅删除数据库记录（保留物理文件）。
🛠️ 技术栈
GUI 框架: PySide6 (Qt for Python)
数据库: SQLite3 (原生支持，无需额外服务)
图像处理: OpenCV (cv2) + NumPy (支持中文路径与高质量缩放)
文件操作: send2trash (安全移入回收站), pathlib
打包工具: PyInstaller
📦 安装与运行
1. 环境准备
确保已安装 Python 3.8 或更高版本。

bash
# 克隆项目
git clone https://github.com/yourusername/FileMaster.git
cd FileMaster

# 创建虚拟环境
python -m venv file_venv
file_venv\Scripts\activate  # Windows
# source file_venv/bin/activate  # macOS/Linux

# 安装依赖
pip install -r requirements.txt

2. 运行程序

bash
python main.py

📦 打包发布 (Windows)
本项目已配置好 filemaster.spec，可直接打包为独立的 .exe 文件。

bash
# 安装打包工具
pip install pyinstaller

# 执行打包
pyinstaller filemaster.spec --clean

打包完成后，可执行文件位于 dist/FileMaster/FileMaster.exe。
注意：打包后的程序会将数据库和缩略图存储在 %APPDATA%\FileMaster 目录下，以确保数据在不同启动路径下的持久性与安全性。
📁 项目结构
text
123456789101112131415161718192021
📝 待办事项 (TODO)
支持更多视频编码格式的解码器集成。
增加文件内容全文检索功能。
导出扫描结果为 Excel/CSV 报表。
🤝 贡献
欢迎提交 Issue 或 Pull Request 来改进这个项目！
📄 许可证
本项目采用 MIT 许可证。详见 LICENSE 文件。