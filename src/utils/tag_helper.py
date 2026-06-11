from __future__ import annotations
from PySide6.QtWidgets import QInputDialog, QMessageBox

from src.ui.dialogs.tag_manage_dialog import TagManageDialog

def manage_tags_for_files(parent_widget, selected_data: list[dict], tag_dao, file_service):
    """
    通用的文件标签管理逻辑
    :param parent_widget: 调用此函数的 QWidget (用于作为弹窗的父级)
    :param selected_data: 选中的文件数据列表 (list[dict])
    :param tag_dao: TagDAO 实例
    :param file_service: FileService 实例
    """
    if not selected_data:
        return

    # 以第一个选中的文件作为“模板”来展示当前的标签状态
    first_file = selected_data[0]
    file_id = first_file.get('id')

    if not file_id:
        # 降级处理：如果由于某种原因没拿到 id，退回简单的文本输入模式
        text, ok = QInputDialog.getText(
            parent_widget, "管理标签", 
            "请输入要添加的标签 (多个标签用英文逗号分隔):", 
            text=""
        )
        if ok and text.strip():
            tags_to_add = [t.strip() for t in text.split(',') if t.strip()]
            for file_data in selected_data:
                file_service.manage_file_tags(file_data['path'], tags_to_add, [])
        return

    # 弹出高级标签管理对话框
    dialog = TagManageDialog(first_file['name'], file_id, tag_dao, parent_widget)
    if dialog.exec():
        tags_to_add = dialog.get_tags_to_add()
        tags_to_remove = dialog.get_tags_to_remove()
        
        success_count = 0
        # 将最终的标签决策批量应用到所有选中的文件上
        for file_data in selected_data:
            res = file_service.manage_file_tags(file_data['path'], tags_to_add, tags_to_remove)
            if res['success']:
                success_count += 1
                
        QMessageBox.information(parent_widget, "成功", f"已成功为 {success_count} 个文件更新标签。")