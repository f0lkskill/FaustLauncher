import pymysql
import os
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

def set_bubble_json_files(host, port, user, password, database, battle_speech_file, cultivation_file, mowe_file):
    """
    在faust_launcher表格中设置三个JSON文件的内容
    
    Args:
        host: MySQL服务器地址
        port: 端口号
        user: 用户名
        password: 密码
        database: 数据库名
        battle_speech_file: BattleSpeechBubbleDlg.json文件内容
        cultivation_file: BattleSpeechBubbleDlg_Cultivation.json文件内容
        mowe_file: BattleSpeechBubbleDlg_mowe.json文件内容
    """
    try:
        # 连接MySQL数据库
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            # 检查表格是否存在
            cursor.execute("SHOW TABLES LIKE 'faust_launcher'")
            table_exists = cursor.fetchone()
            
            if not table_exists:
                # 如果表格不存在，创建表格
                create_table_query = """
                CREATE TABLE faust_launcher (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    battle_speech_bubble LONGTEXT,
                    battle_speech_bubble_cultivation LONGTEXT,
                    battle_speech_bubble_mowe LONGTEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
                """
                cursor.execute(create_table_query)
                print("创建faust_launcher表格成功")
            
            # 检查记录是否存在
            cursor.execute("SELECT COUNT(*) as count FROM faust_launcher")
            record_count = cursor.fetchone()['count'] # type: ignore
            
            if record_count == 0:
                # 插入新记录
                insert_query = """
                INSERT INTO faust_launcher (battle_speech_bubble, battle_speech_bubble_cultivation, battle_speech_bubble_mowe) 
                VALUES (%s, %s, %s)
                """
                cursor.execute(insert_query, (battle_speech_file, cultivation_file, mowe_file))
                print("插入JSON文件记录成功")
            else:
                # 更新现有记录
                update_query = """
                UPDATE faust_launcher SET 
                battle_speech_bubble = %s, 
                battle_speech_bubble_cultivation = %s, 
                battle_speech_bubble_mowe = %s 
                WHERE id = 1
                """
                cursor.execute(update_query, (battle_speech_file, cultivation_file, mowe_file))
                print("更新JSON文件记录成功")
            
            # 验证设置
            cursor.execute("SELECT battle_speech_bubble, battle_speech_bubble_cultivation, battle_speech_bubble_mowe FROM faust_launcher WHERE id = 1")
            result = cursor.fetchone()
            
            if result:
                print(f"JSON文件设置成功")
                print(f" - BattleSpeechBubbleDlg.json: {len(result['battle_speech_bubble'])} 字符")
                print(f" - BattleSpeechBubbleDlg_Cultivation.json: {len(result['battle_speech_bubble_cultivation'])} 字符")
                print(f" - BattleSpeechBubbleDlg_mowe.json: {len(result['battle_speech_bubble_mowe'])} 字符")
        
        # 提交更改
        connection.commit()
        
        return True
        
    except pymysql.Error as e:
        print(f"MySQL错误: {e}")
        return False
    except Exception as e:
        print(f"错误: {e}")
        return False
    finally:
        # 确保连接关闭
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def get_bubble_json_files(host, port, user, password, database):
    """
    从faust_launcher表格中获取三个JSON文件的内容
    
    Args:
        host: MySQL服务器地址
        port: 端口号
        user: 用户名
        password: 密码
        database: 数据库名
        
    Returns:
        tuple: (battle_speech_file, cultivation_file, mowe_file) 如果不存在则返回(None, None, None)
    """
    try:
        # 连接MySQL数据库
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            # 检查表格是否存在
            cursor.execute("SHOW TABLES LIKE 'faust_launcher'")
            table_exists = cursor.fetchone()
            
            if not table_exists:
                print("⚠️ faust_launcher表格不存在")
                return None, None, None
            
            # 查询JSON文件字段
            cursor.execute("SELECT battle_speech_bubble, battle_speech_bubble_cultivation, battle_speech_bubble_mowe FROM faust_launcher WHERE id = 1")
            result = cursor.fetchone()
            
            if result and result['battle_speech_bubble'] and result['battle_speech_bubble_cultivation'] and result['battle_speech_bubble_mowe']:
                print("获取JSON文件成功")
                return result['battle_speech_bubble'], result['battle_speech_bubble_cultivation'], result['battle_speech_bubble_mowe']
            else:
                print("⚠️ JSON文件字段为空或记录不存在")
                return None, None, None
        
    except pymysql.Error as e:
        print(f"MySQL错误: {e}")
        return None, None, None
    except Exception as e:
        print(f"错误: {e}")
        return None, None, None
    finally:
        # 确保连接关闭
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def upload_bubble_files_from_temp(host, port, user, password, database, temp_dir=None):
    """
    上传temp目录中的三个JSON文件到数据库
    
    Args:
        host: MySQL服务器地址
        port: 端口号
        user: 用户名
        password: 密码
        database: 数据库名
        temp_dir: temp目录路径，如果为None则使用默认路径
        
    Returns:
        bool: 上传是否成功
    """
    if temp_dir is None:
        temp_dir = 'temp'
    
    # 检查temp目录是否存在
    if not os.path.exists(temp_dir):
        print(f"temp目录不存在: {temp_dir}")
        return False
    
    # 检查三个JSON文件是否存在
    battle_speech_path = os.path.join(temp_dir, 'BattleSpeechBubbleDlg.json')
    cultivation_path = os.path.join(temp_dir, 'BattleSpeechBubbleDlg_Cultivation.json')
    mowe_path = os.path.join(temp_dir, 'BattleSpeechBubbleDlg_mowe.json')
    
    if not os.path.exists(battle_speech_path):
        print(f"文件不存在: {battle_speech_path}")
        return False
    if not os.path.exists(cultivation_path):
        print(f"文件不存在: {cultivation_path}")
        return False
    if not os.path.exists(mowe_path):
        print(f"文件不存在: {mowe_path}")
        return False
    
    try:
        # 读取三个JSON文件
        with open(battle_speech_path, 'r', encoding='utf-8') as f:
            battle_speech_content = f.read()
        
        with open(cultivation_path, 'r', encoding='utf-8') as f:
            cultivation_content = f.read()
        
        with open(mowe_path, 'r', encoding='utf-8') as f:
            mowe_content = f.read()
        
        print(f"读取JSON文件成功")
        print(f" - BattleSpeechBubbleDlg.json: {len(battle_speech_content)} 字符")
        print(f" - BattleSpeechBubbleDlg_Cultivation.json: {len(cultivation_content)} 字符")
        print(f" - BattleSpeechBubbleDlg_mowe.json: {len(mowe_content)} 字符")
        
        # 上传到数据库
        if set_bubble_json_files(host, port, user, password, database, 
                               battle_speech_content, cultivation_content, mowe_content):
            print("JSON文件上传到数据库成功")
            return True
        else:
            return False
        
    except Exception as e:
        print(f"上传JSON文件失败: {e}")
        return False

def download_bubble_files_to_game(host, port, user, password, database, game_path):
    """
    从数据库获取三个JSON文件并保存到游戏目录
    
    Args:
        host: MySQL服务器地址
        port: 端口号
        user: 用户名
        password: 密码
        database: 数据库名
        game_path: 游戏目录路径
        
    Returns:
        bool: 下载是否成功
    """
    # 从数据库获取三个JSON文件内容
    print("正在从数据库获取JSON文件内容...")
    battle_speech, cultivation, mowe = get_bubble_json_files(host, port, user, password, database)
    
    if not battle_speech or not cultivation or not mowe:
        print("无法从数据库获取JSON文件内容")
        return False
    
    print(f"成功获取三个JSON文件内容")
    print(f" - BattleSpeechBubbleDlg.json: {len(battle_speech)} 字符")
    print(f" - BattleSpeechBubbleDlg_Cultivation.json: {len(cultivation)} 字符")
    print(f" - BattleSpeechBubbleDlg_mowe.json: {len(mowe)} 字符")
    
    # 检查游戏路径是否存在
    if not os.path.exists(game_path):
        print(f"游戏路径不存在: {game_path}")
        return False
    
    # 目标目录：游戏目录下的LimbusCompany_Data/Lang/LLC_zh-CN
    target_dir = os.path.join(game_path, 'LimbusCompany_Data', 'Lang', 'LLC_zh-CN')
    
    try:
        # 确保目标目录存在
        os.makedirs(target_dir, exist_ok=True)
        
        # 保存BattleSpeechBubbleDlg.json
        battle_speech_path = os.path.join(target_dir, 'BattleSpeechBubbleDlg.json')
        with open(battle_speech_path, 'w', encoding='utf-8') as f:
            f.write(battle_speech)
        print(f"保存 BattleSpeechBubbleDlg.json 成功")
        
        # 保存BattleSpeechBubbleDlg_Cultivation.json
        cultivation_path = os.path.join(target_dir, 'BattleSpeechBubbleDlg_Cultivation.json')
        with open(cultivation_path, 'w', encoding='utf-8') as f:
            f.write(cultivation)
        print(f"保存 BattleSpeechBubbleDlg_Cultivation.json 成功")
        
        # 保存BattleSpeechBubbleDlg_mowe.json
        mowe_path = os.path.join(target_dir, 'BattleSpeechBubbleDlg_mowe.json')
        with open(mowe_path, 'w', encoding='utf-8') as f:
            f.write(mowe)
        print(f"保存 BattleSpeechBubbleDlg_mowe.json 成功")
        
        print(f"JSON文件已成功保存到: {target_dir}")
        return True
        
    except Exception as e:
        print(f"保存JSON文件失败: {e}")
        return False

def check_bubble_files_exist(host, port, user, password, database):
    """
    检查三个JSON文件字段是否存在且不为空
    
    Args:
        host: MySQL服务器地址
        port: 端口号
        user: 用户名
        password: 密码
        database: 数据库名
        
    Returns:
        bool: 三个JSON文件字段是否存在且不为空
    """
    battle_speech, cultivation, mowe = get_bubble_json_files(host, port, user, password, database)
    return battle_speech is not None and cultivation is not None and mowe is not None

def get_all_records(host, port, user, password, database):
    """
    获取faust_launcher表格中的所有记录
    
    Args:
        host: MySQL服务器地址
        port: 端口号
        user: 用户名
        password: 密码
        database: 数据库名
        
    Returns:
        list: 所有记录的列表
    """
    try:
        # 连接MySQL数据库
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            # 检查表格是否存在
            cursor.execute("SHOW TABLES LIKE 'faust_launcher'")
            table_exists = cursor.fetchone()
            
            if not table_exists:
                print("⚠️ faust_launcher表格不存在")
                return []
            
            # 查询所有记录
            cursor.execute("SELECT * FROM faust_launcher ORDER BY id")
            results = cursor.fetchall()
            
            print(f"获取到 {len(results)} 条记录")
            return results
        
    except pymysql.Error as e:
        print(f"MySQL错误: {e}")
        return []
    except Exception as e:
        print(f"错误: {e}")
        return []
    finally:
        # 确保连接关闭
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def create_version_table(host, port, user, password, database):
    """
    创建版本信息表格
    
    Args:
        host: MySQL服务器地址
        port: 端口号
        user: 用户名
        password: 密码
        database: 数据库名
        
    Returns:
        bool: 创建是否成功
    """
    try:
        # 连接MySQL数据库
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            # 检查表格是否存在
            cursor.execute("SHOW TABLES LIKE 'faust_versions'")
            table_exists = cursor.fetchone()
            
            if not table_exists:
                # 如果表格不存在，创建表格
                create_table_query = """
                CREATE TABLE faust_versions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    version_name VARCHAR(255) NOT NULL,
                    bilibili_url VARCHAR(500),
                    version_description TEXT,
                    is_latest BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
                """
                cursor.execute(create_table_query)
                print("创建faust_versions表格成功")
                return True
            else:
                print("faust_versions表格已存在")
                return True
        
    except pymysql.Error as e:
        print(f"MySQL错误: {e}")
        return False
    except Exception as e:
        print(f"错误: {e}")
        return False
    finally:
        # 确保连接关闭
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def add_version(host, port, user, password, database, version_name, bilibili_url, version_description, is_latest=False):
    """
    添加版本信息
    
    Args:
        host: MySQL服务器地址
        port: 端口号
        user: 用户名
        password: 密码
        database: 数据库名
        version_name: 版本名称
        bilibili_url: B站视频链接
        version_description: 版本介绍
        is_latest: 是否是最新版本
        
    Returns:
        bool: 添加是否成功
    """
    try:
        # 连接MySQL数据库
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            # 如果设置为最新版本，先取消其他版本的最新标记
            if is_latest:
                cursor.execute("UPDATE faust_versions SET is_latest = FALSE WHERE is_latest = TRUE")
            
            # 插入新版本
            insert_query = """
            INSERT INTO faust_versions (version_name, bilibili_url, version_description, is_latest) 
            VALUES (%s, %s, %s, %s)
            """
            cursor.execute(insert_query, (version_name, bilibili_url, version_description, is_latest))
            
            # 提交更改
            connection.commit()
            
            print(f"添加版本信息成功: {version_name}")
            return True
        
    except pymysql.Error as e:
        print(f"MySQL错误: {e}")
        return False
    except Exception as e:
        print(f"错误: {e}")
        return False
    finally:
        # 确保连接关闭
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def update_version(host, port, user, password, database, version_id, version_name, bilibili_url, version_description, is_latest=False):
    """
    更新版本信息
    
    Args:
        host: MySQL服务器地址
        port: 端口号
        user: 用户名
        password: 密码
        database: 数据库名
        version_id: 版本ID
        version_name: 版本名称
        bilibili_url: B站视频链接
        version_description: 版本介绍
        is_latest: 是否是最新版本
        
    Returns:
        bool: 更新是否成功
    """
    try:
        # 连接MySQL数据库
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            # 如果设置为最新版本，先取消其他版本的最新标记
            if is_latest:
                cursor.execute("UPDATE faust_versions SET is_latest = FALSE WHERE is_latest = TRUE AND id != %s", (version_id,))
            
            # 更新版本信息
            update_query = """
            UPDATE faust_versions SET 
            version_name = %s, 
            bilibili_url = %s, 
            version_description = %s, 
            is_latest = %s,
            updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """
            cursor.execute(update_query, (version_name, bilibili_url, version_description, is_latest, version_id))
            
            # 提交更改
            connection.commit()
            
            print(f"更新版本信息成功: {version_name}")
            return True
        
    except pymysql.Error as e:
        print(f"MySQL错误: {e}")
        return False
    except Exception as e:
        print(f"错误: {e}")
        return False
    finally:
        # 确保连接关闭
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def delete_version(host, port, user, password, database, version_id):
    """
    删除版本信息
    
    Args:
        host: MySQL服务器地址
        port: 端口号
        user: 用户名
        password: 密码
        database: 数据库名
        version_id: 版本ID
        
    Returns:
        bool: 删除是否成功
    """
    try:
        # 连接MySQL数据库
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            # 删除版本信息
            delete_query = "DELETE FROM faust_versions WHERE id = %s"
            cursor.execute(delete_query, (version_id,))
            
            # 提交更改
            connection.commit()
            
            print(f"删除版本信息成功: ID {version_id}")
            return True
        
    except pymysql.Error as e:
        print(f"MySQL错误: {e}")
        return False
    except Exception as e:
        print(f"错误: {e}")
        return False
    finally:
        # 确保连接关闭
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def get_all_versions(host, port, user, password, database):
    """
    获取所有版本信息
    
    Args:
        host: MySQL服务器地址
        port: 端口号
        user: 用户名
        password: 密码
        database: 数据库名
        
    Returns:
        list: 所有版本信息的列表
    """
    try:
        # 连接MySQL数据库
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            # 查询所有版本信息
            cursor.execute("SELECT * FROM faust_versions ORDER BY created_at DESC")
            results = cursor.fetchall()
            
            print(f"获取到 {len(results)} 个版本信息")
            return results
        
    except pymysql.Error as e:
        print(f"MySQL错误: {e}")
        return []
    except Exception as e:
        print(f"错误: {e}")
        return []
    finally:
        # 确保连接关闭
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def get_latest_version(host, port, user, password, database):
    """
    获取最新版本信息
    
    Args:
        host: MySQL服务器地址
        port: 端口号
        user: 用户名
        password: 密码
        database: 数据库名
        
    Returns:
        dict: 最新版本信息，如果不存在则返回None
    """
    try:
        # 连接MySQL数据库
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            # 查询最新版本信息
            cursor.execute("SELECT * FROM faust_versions WHERE is_latest = TRUE ORDER BY created_at DESC LIMIT 1")
            result = cursor.fetchone()
            
            if result:
                print(f"获取最新版本信息: {result['version_name']}")
                return result
            else:
                print("⚠️ 没有设置最新版本")
                return None
        
    except pymysql.Error as e:
        print(f"MySQL错误: {e}")
        return None
    except Exception as e:
        print(f"错误: {e}")
        return None
    finally:
        # 确保连接关闭
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def get_version_by_id(host, port, user, password, database, version_id):
    """
    根据ID获取版本信息
    
    Args:
        host: MySQL服务器地址
        port: 端口号
        user: 用户名
        password: 密码
        database: 数据库名
        version_id: 版本ID
        
    Returns:
        dict: 版本信息，如果不存在则返回None
    """
    try:
        # 连接MySQL数据库
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            # 根据ID查询版本信息
            cursor.execute("SELECT * FROM faust_versions WHERE id = %s", (version_id,))
            result = cursor.fetchone()
            
            if result:
                print(f"获取版本信息: {result['version_name']}")
                return result
            else:
                print(f"⚠️ 版本ID {version_id} 不存在")
                return None
        
    except pymysql.Error as e:
        print(f"MySQL错误: {e}")
        return None
    except Exception as e:
        print(f"错误: {e}")
        return None
    finally:
        # 确保连接关闭
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

# GUI界面类
class VersionManagerGUI:
    def __init__(self, root, db_config):
        self.root = root
        self.db_config = db_config
        self.current_version_id = None
        
        # 设置窗口标题和大小
        self.root.title("FaustLauncher - 版本信息管理器")
        self.root.geometry("800x600")
        self.root.resizable(True, True)
        
        # 创建主框架
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建控件
        self.create_widgets()
        
        # 加载数据
        self.refresh_versions()
        
        # 确保版本表格存在
        create_version_table(**db_config) # type: ignore
    
    def create_widgets(self):
        # 标题
        title_label = ttk.Label(self.main_frame, text="版本信息管理器", font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        # 输入框架
        input_frame = ttk.LabelFrame(self.main_frame, text="版本信息", padding="10")
        input_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        
        # 版本名称
        ttk.Label(input_frame, text="版本名称:").grid(row=0, column=0, sticky="w", pady=5)
        self.version_name_entry = ttk.Entry(input_frame, width=50)
        self.version_name_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=5, padx=(10, 0))
        
        # B站视频链接
        ttk.Label(input_frame, text="B站视频链接:").grid(row=1, column=0, sticky="w", pady=5)
        self.bilibili_url_entry = ttk.Entry(input_frame, width=50)
        self.bilibili_url_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=5, padx=(10, 0))
        
        # 版本介绍
        ttk.Label(input_frame, text="版本介绍:").grid(row=2, column=0, sticky="nw", pady=5)
        self.version_description_text = scrolledtext.ScrolledText(input_frame, width=50, height=5)
        self.version_description_text.grid(row=2, column=1, columnspan=2, sticky="ew", pady=5, padx=(10, 0))
        
        # 是否最新版本
        self.is_latest_var = tk.BooleanVar()
        self.is_latest_check = ttk.Checkbutton(input_frame, text="设为最新版本", variable=self.is_latest_var)
        self.is_latest_check.grid(row=3, column=1, sticky="w", pady=5, padx=(10, 0))
        
        # 按钮框架
        button_frame = ttk.Frame(input_frame)
        button_frame.grid(row=4, column=0, columnspan=3, pady=10)
        
        self.add_button = ttk.Button(button_frame, text="添加版本", command=self.add_version)
        self.add_button.pack(side=tk.LEFT, padx=5)
        
        self.update_button = ttk.Button(button_frame, text="更新版本", command=self.update_version)
        self.update_button.pack(side=tk.LEFT, padx=5)
        self.update_button.config(state=tk.DISABLED)
        
        self.delete_button = ttk.Button(button_frame, text="删除版本", command=self.delete_version)
        self.delete_button.pack(side=tk.LEFT, padx=5)
        self.delete_button.config(state=tk.DISABLED)
        
        self.clear_button = ttk.Button(button_frame, text="清空输入", command=self.clear_inputs)
        self.clear_button.pack(side=tk.LEFT, padx=5)
        
        # 版本列表框架
        list_frame = ttk.LabelFrame(self.main_frame, text="版本列表", padding="10")
        list_frame.grid(row=2, column=0, columnspan=3, sticky="nsew", pady=(10, 0))
        
        # 创建树形视图
        columns = ("ID", "版本名称", "B站链接", "是否最新", "创建时间")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=10)
        
        # 设置列标题
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100)
        
        # 调整列宽
        self.tree.column("版本名称", width=150)
        self.tree.column("B站链接", width=200)
        self.tree.column("创建时间", width=150)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 绑定选择事件
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        
        # 配置网格权重
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.rowconfigure(2, weight=1)
        input_frame.columnconfigure(1, weight=1)
    
    def refresh_versions(self):
        """刷新版本列表"""
        # 清空现有数据
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # 获取所有版本信息
        versions = get_all_versions(**self.db_config) # type: ignore
        
        # 添加数据到树形视图
        for version in versions:
            self.tree.insert("", tk.END, values=(
                version['id'],
                version['version_name'],
                version['bilibili_url'] or "",
                "是"if version['is_latest'] else "否",
                version['created_at'].strftime("%Y-%m-%d %H:%M:%S") if version['created_at'] else ""
            ))
    
    def on_tree_select(self, event):
        """树形视图选择事件"""
        selection = self.tree.selection()
        if selection:
            item = selection[0]
            values = self.tree.item(item, "values")
            self.current_version_id = values[0]
            
            # 获取版本详细信息
            version = get_version_by_id(**self.db_config, version_id=self.current_version_id) # type: ignore
            if version:
                self.version_name_entry.delete(0, tk.END)
                self.version_name_entry.insert(0, version['version_name'])
                
                self.bilibili_url_entry.delete(0, tk.END)
                self.bilibili_url_entry.insert(0, version['bilibili_url'] or "")
                
                self.version_description_text.delete(1.0, tk.END)
                self.version_description_text.insert(1.0, version['version_description'] or "")
                
                self.is_latest_var.set(version['is_latest'])
                
                # 启用更新和删除按钮
                self.update_button.config(state=tk.NORMAL)
                self.delete_button.config(state=tk.NORMAL)
                self.add_button.config(state=tk.DISABLED)
    
    def add_version(self):
        """添加版本"""
        version_name = self.version_name_entry.get().strip()
        bilibili_url = self.bilibili_url_entry.get().strip()
        version_description = self.version_description_text.get(1.0, tk.END).strip()
        is_latest = self.is_latest_var.get()
        
        if not version_name:
            messagebox.showerror("错误", "版本名称不能为空！")
            return
        
        if add_version(**self.db_config, 
                      version_name=version_name,
                      bilibili_url=bilibili_url,
                      version_description=version_description,
                      is_latest=is_latest): # type: ignore
            messagebox.showinfo("成功", "版本添加成功！")
            self.clear_inputs()
            self.refresh_versions()
        else:
            messagebox.showerror("错误", "版本添加失败！")
    
    def update_version(self):
        """更新版本"""
        if not self.current_version_id:
            messagebox.showerror("错误", "请先选择要更新的版本！")
            return
        
        version_name = self.version_name_entry.get().strip()
        bilibili_url = self.bilibili_url_entry.get().strip()
        version_description = self.version_description_text.get(1.0, tk.END).strip()
        is_latest = self.is_latest_var.get()
        
        if not version_name:
            messagebox.showerror("错误", "版本名称不能为空！")
            return
        
        if update_version(**self.db_config,
                        version_id=self.current_version_id,
                        version_name=version_name,
                        bilibili_url=bilibili_url,
                        version_description=version_description,
                        is_latest=is_latest): # type: ignore
            messagebox.showinfo("成功", "版本更新成功！")
            self.clear_inputs()
            self.refresh_versions()
        else:
            messagebox.showerror("错误", "版本更新失败！")
    
    def delete_version(self):
        """删除版本"""
        if not self.current_version_id:
            messagebox.showerror("错误", "请先选择要删除的版本！")
            return
        
        if messagebox.askyesno("确认", "确定要删除这个版本吗？"):
            if delete_version(**self.db_config, version_id=self.current_version_id): # type: ignore
                messagebox.showinfo("成功", "版本删除成功！")
                self.clear_inputs()
                self.refresh_versions()
            else:
                messagebox.showerror("错误", "版本删除失败！")
    
    def clear_inputs(self):
        """清空输入框"""
        self.version_name_entry.delete(0, tk.END)
        self.bilibili_url_entry.delete(0, tk.END)
        self.version_description_text.delete(1.0, tk.END)
        self.is_latest_var.set(False)
        self.current_version_id = None
        
        # 重置按钮状态
        self.update_button.config(state=tk.DISABLED)
        self.delete_button.config(state=tk.DISABLED)
        self.add_button.config(state=tk.NORMAL)

def run_version_manager_gui():
    """运行版本管理器GUI"""
    root = tk.Tk()
    app = VersionManagerGUI(root, db_config)
    root.mainloop()

def check_new_version(current_version_name):
    """
    检测是否有新版本
    
    Args:
        host: MySQL服务器地址
        port: 端口号
        user: 用户名
        password: 密码
        database: 数据库名
        current_version_name: 当前版本名称
        
    Returns:
        tuple: (has_new_version, latest_version_info) 
               has_new_version: 是否有新版本
               latest_version_info: 最新版本信息字典，如果没有新版本则为None
    """
    try:
        # 获取最新版本信息
        latest_version = get_latest_version(**db_config)
        
        if not latest_version:
            # 没有设置最新版本
            return False, None
        
        # 比较版本名称
        if latest_version['version_name'] != current_version_name:
            # 有新版本
            return True, {
                'version_name': latest_version['version_name'],
                'bilibili_url': latest_version['bilibili_url'],
                'version_description': latest_version['version_description'],
                'created_at': latest_version['created_at']
            }
        else:
            # 版本相同，没有新版本
            return False, None
            
    except Exception as e:
        print(f"检测新版本时出错: {e}")
        return False, None

def notify_new_version(current_version_name, info = '发现新版本', root = None):
    """
    检测并通知新版本（带GUI弹窗）
    
    Args:
        current_version_name: 当前版本名称
    """
    try:
        # 导入tkinter用于显示消息框
        import tkinter as tk
        from functions.pages.version_info import show_version_update_dialog
        
        # 检测新版本
        has_new_version, latest_info = check_new_version(current_version_name=current_version_name)
        
        if has_new_version and latest_info:
            # 显示消息框
            show_version_update_dialog(current_version_name, latest_info, info, root)

            return True
        else:
            return False
            
    except Exception as e:
        print(f"通知新版本时出错: {e}")
        return False

db_config = {
    'host': 'mysql2.sqlpub.com',
    'port': 3307,
    'user': 'mirroradmin',  # 用户名
    'password': 'cZGus9c0TrfhaLyd',  # 密码
    'database': 'mirrorchat_data'   # 数据库名
}

# 使用示例
if __name__ == "__main__":

    print("=" * 50)
    print("SQL Loader - JSON文件管理器")
    print("=" * 50)
    print("1. 上传temp目录中的JSON文件到数据库")
    print("2. 从数据库下载JSON文件到游戏目录")
    print("3. 版本信息管理器")
    print("=" * 50)
    
    choice = input("请选择操作 (1, 2 或 3): ").strip()

    success = True
    
    if choice == "1":
        success = upload_bubble_files_from_temp(**db_config)
    elif choice == "2":
        game_path = input("请输入游戏目录路径: ").strip()
        if not game_path:
            print("游戏目录路径不能为空")
        else:
            success = download_bubble_files_to_game(**db_config, game_path=game_path)
    elif choice == "3":
        # 运行GUI版本管理器
        run_version_manager_gui()
        success = True
    else:
        print("无效选择")
        success = False
    
    if success:
        print("\n 操作完成!")
    else:
        print("\n 操作失败!")