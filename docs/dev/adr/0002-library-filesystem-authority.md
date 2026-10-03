# ADR-0002: Library 文件系统是事实来源，导入只复制不移动

SubForge Library 保存用户不可轻易重建的音频、字幕与处理断点，因此决定以每个 Item 的 `metadata.json` 和相对资产路径作为长期事实来源，SQLite 仅作可删除重建的索引；Library 可以整体换盘。导入始终复制并校验到 Library，SubForge 永不移动、修改或删除来源文件，Library 内删除也只移动到 `.trash`。这比数据库主导或直接接管原文件多占磁盘并增加导入步骤，但避免数据库损坏、路径变化或程序错误导致个人媒体资产不可恢复。

_Status: accepted_（2026-08-13）
