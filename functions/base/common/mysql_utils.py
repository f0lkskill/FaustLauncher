"""common 子模块：<mysql_utils>（具体职责见函数文档）。"""

import pymysql

def connect_db(host, port, user, password, database):
    """connectdb相关处理。"""
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
