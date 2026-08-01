import pymysql


def connect_db(host, port, user, password, database):
    """连接MySQL数据库"""
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
