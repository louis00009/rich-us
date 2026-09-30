"""进阶/前沿策略族（FILE_SIZE_DEBT Batch E-2 从 builtin_advanced.py 拆出）。

每个策略文件独立导入时即通过 @register 完成注册；
`builtin_advanced.py` 现在只是注册表 barrel，保证旧行为（import 一次全部注册）不变。
"""
