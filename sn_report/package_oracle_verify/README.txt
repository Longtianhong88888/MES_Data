Oracle 一键下载验证包
=====================
1. 双击 run_verify.bat(或命令行运行)
2. 脚本会: 解压 Instant Client -> 装 wheels -> 读 sns.txt 逐 SN 查询下载
3. 完成后把本目录的 oracle_download/verify_output 和 downloads 整个拷回分析
   (verify_output 在 oracle_download/output/oracle_verify/ 下,含 verify.json 和 run.log)
4. sns.txt 每行一个 Module SN,可直接修改
