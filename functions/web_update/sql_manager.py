import pymysql
import os
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from functions.base.common.mysql_utils import connect_db

def set_bubble_json_files(host, port, user, password, database, battle_speech_file, cultivation_file, mowe_file):
    try:
        connection = connect_db(host, port, user, password, database)
        
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'faust_launcher'")
            table_exists = cursor.fetchone()
            
            if not table_exists:
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
            
            cursor.execute("SELECT COUNT(*) as count FROM faust_launcher")
            record_count = cursor.fetchone()['count'] # type: ignore
            
            if record_count == 0:
                insert_query = """
                INSERT INTO faust_launcher (battle_speech_bubble, battle_speech_bubble_cultivation, battle_speech_bubble_mowe) 
                VALUES (%s, %s, %s)
                """
                cursor.execute(insert_query, (battle_speech_file, cultivation_file, mowe_file))
                print("插入JSON文件记录成功")
            else:
                update_query = """
                UPDATE faust_launcher SET 
                battle_speech_bubble = %s, 
                battle_speech_bubble_cultivation = %s, 
                battle_speech_bubble_mowe = %s 
                WHERE id = 1
                """
                cursor.execute(update_query, (battle_speech_file, cultivation_file, mowe_file))
                print("更新JSON文件记录成功")
            
            cursor.execute("SELECT battle_speech_bubble, battle_speech_bubble_cultivation, battle_speech_bubble_mowe FROM faust_launcher WHERE id = 1")
            result = cursor.fetchone()
            
            if result:
                print(f"JSON文件设置成功")
                print(f" - BattleSpeechBubbleDlg.json: {len(result['battle_speech_bubble'])} 字符")
                print(f" - BattleSpeechBubbleDlg_Cultivation.json: {len(result['battle_speech_bubble_cultivation'])} 字符")
                print(f" - BattleSpeechBubbleDlg_mowe.json: {len(result['battle_speech_bubble_mowe'])} 字符")
        
        connection.commit()
        
        return True
        
    except pymysql.Error as e:
        print(f"MySQL错误: {e}")
        return False
    except Exception as e:
        print(f"错误: {e}")
        return False
    finally:
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def get_bubble_json_files(host, port, user, password, database):
    try:
        connection = connect_db(host, port, user, password, database)
        
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'faust_launcher'")
            table_exists = cursor.fetchone()
            
            if not table_exists:
                print("⚠️ faust_launcher表格不存在")
                return None, None, None
            
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
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def upload_bubble_files_from_temp(host, port, user, password, database, temp_dir=None):
    if temp_dir is None:
        temp_dir = 'temp'
    
    if not os.path.exists(temp_dir):
        print(f"temp目录不存在: {temp_dir}")
        return False
    
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
    print("正在从数据库获取JSON文件内容...")
    battle_speech, cultivation, mowe = get_bubble_json_files(host, port, user, password, database)
    
    if not battle_speech or not cultivation or not mowe:
        print("无法从数据库获取JSON文件内容")
        return False
    
    print(f"成功获取三个JSON文件内容")
    print(f" - BattleSpeechBubbleDlg.json: {len(battle_speech)} 字符")
    print(f" - BattleSpeechBubbleDlg_Cultivation.json: {len(cultivation)} 字符")
    print(f" - BattleSpeechBubbleDlg_mowe.json: {len(mowe)} 字符")
    
    if not os.path.exists(game_path):
        print(f"游戏路径不存在: {game_path}")
        return False
    
    from functions.web_update.translation_source import get_game_lang_dir
    target_dir = get_game_lang_dir(game_path)
    
    try:
        os.makedirs(target_dir, exist_ok=True)
        
        battle_speech_path = os.path.join(target_dir, 'BattleSpeechBubbleDlg.json')
        with open(battle_speech_path, 'w', encoding='utf-8') as f:
            f.write(battle_speech)
        print(f"保存 BattleSpeechBubbleDlg.json 成功")
        
        cultivation_path = os.path.join(target_dir, 'BattleSpeechBubbleDlg_Cultivation.json')
        with open(cultivation_path, 'w', encoding='utf-8') as f:
            f.write(cultivation)
        print(f"保存 BattleSpeechBubbleDlg_Cultivation.json 成功")
        
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
    battle_speech, cultivation, mowe = get_bubble_json_files(host, port, user, password, database)
    return battle_speech is not None and cultivation is not None and mowe is not None

def get_all_records(host, port, user, password, database):
    try:
        connection = connect_db(host, port, user, password, database)
        
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'faust_launcher'")
            table_exists = cursor.fetchone()
            
            if not table_exists:
                print("⚠️ faust_launcher表格不存在")
                return []
            
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
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def create_version_table(host, port, user, password, database):
    try:
        connection = connect_db(host, port, user, password, database)
        
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'faust_versions'")
            table_exists = cursor.fetchone()
            
            if not table_exists:
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
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def add_version(host, port, user, password, database, version_name, bilibili_url, version_description, is_latest=False):
    try:
        connection = connect_db(host, port, user, password, database)
        
        with connection.cursor() as cursor:
            if is_latest:
                cursor.execute("UPDATE faust_versions SET is_latest = FALSE WHERE is_latest = TRUE")
            
            insert_query = """
            INSERT INTO faust_versions (version_name, bilibili_url, version_description, is_latest) 
            VALUES (%s, %s, %s, %s)
            """
            cursor.execute(insert_query, (version_name, bilibili_url, version_description, is_latest))
            
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
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def update_version(host, port, user, password, database, version_id, version_name, bilibili_url, version_description, is_latest=False):
    try:
        connection = connect_db(host, port, user, password, database)
        
        with connection.cursor() as cursor:
            if is_latest:
                cursor.execute("UPDATE faust_versions SET is_latest = FALSE WHERE is_latest = TRUE AND id != %s", (version_id,))
            
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
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def delete_version(host, port, user, password, database, version_id):
    try:
        connection = connect_db(host, port, user, password, database)
        
        with connection.cursor() as cursor:
            delete_query = "DELETE FROM faust_versions WHERE id = %s"
            cursor.execute(delete_query, (version_id,))
            
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
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def get_all_versions(host, port, user, password, database):
    try:
        connection = connect_db(host, port, user, password, database)
        
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM faust_versions ORDER BY id DESC")
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
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def get_latest_version(host, port, user, password, database):
    try:
        connection = connect_db(host, port, user, password, database)
        
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM faust_versions WHERE is_latest = TRUE ORDER BY id DESC LIMIT 1")
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
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

def get_version_by_id(host, port, user, password, database, version_id):
    try:
        connection = connect_db(host, port, user, password, database)
        
        with connection.cursor() as cursor:
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
        if 'connection' in locals() and connection.open: # type: ignore
            connection.close() # type: ignore

class VersionManagerGUI:
    def __init__(self, root, db_config):
        self.root = root
        self.db_config = db_config
        self.current_version_id = None
        
        self.root.title("FaustLauncher - 版本信息管理器")
        self.root.geometry("800x600")
        self.root.resizable(True, True)
        
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        self.create_widgets()
        
        self.refresh_versions()
        
        create_version_table(**db_config) # type: ignore
    
    def create_widgets(self):
        title_label = ttk.Label(self.main_frame, text="版本信息管理器", font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        input_frame = ttk.LabelFrame(self.main_frame, text="版本信息", padding="10")
        input_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        
        ttk.Label(input_frame, text="版本名称:").grid(row=0, column=0, sticky="w", pady=5)
        self.version_name_entry = ttk.Entry(input_frame, width=50)
        self.version_name_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=5, padx=(10, 0))
        
        ttk.Label(input_frame, text="B站视频链接:").grid(row=1, column=0, sticky="w", pady=5)
        self.bilibili_url_entry = ttk.Entry(input_frame, width=50)
        self.bilibili_url_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=5, padx=(10, 0))
        
        ttk.Label(input_frame, text="版本介绍:").grid(row=2, column=0, sticky="nw", pady=5)
        self.version_description_text = scrolledtext.ScrolledText(input_frame, width=50, height=5)
        self.version_description_text.grid(row=2, column=1, columnspan=2, sticky="ew", pady=5, padx=(10, 0))
        
        self.is_latest_var = tk.BooleanVar()
        self.is_latest_check = ttk.Checkbutton(input_frame, text="设为最新版本", variable=self.is_latest_var)
        self.is_latest_check.grid(row=3, column=1, sticky="w", pady=5, padx=(10, 0))
        
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
        
        list_frame = ttk.LabelFrame(self.main_frame, text="版本列表", padding="10")
        list_frame.grid(row=2, column=0, columnspan=3, sticky="nsew", pady=(10, 0))
        
        columns = ("ID", "版本名称", "B站链接", "是否最新", "创建时间")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=10)
        
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100)
        
        self.tree.column("版本名称", width=150)
        self.tree.column("B站链接", width=200)
        self.tree.column("创建时间", width=150)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.rowconfigure(2, weight=1)
        input_frame.columnconfigure(1, weight=1)
    
    def refresh_versions(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        versions = get_all_versions(**self.db_config) # type: ignore
        
        for version in versions:
            self.tree.insert("", tk.END, values=(
                version['id'],
                version['version_name'],
                version['bilibili_url'] or "",
                "是"if version['is_latest'] else "否",
                version['created_at'].strftime("%Y-%m-%d %H:%M:%S") if version['created_at'] else ""
            ))
    
    def on_tree_select(self, event):
        selection = self.tree.selection()
        if selection:
            item = selection[0]
            values = self.tree.item(item, "values")
            self.current_version_id = values[0]
            
            version = get_version_by_id(**self.db_config, version_id=self.current_version_id) # type: ignore
            if version:
                self.version_name_entry.delete(0, tk.END)
                self.version_name_entry.insert(0, version['version_name'])
                
                self.bilibili_url_entry.delete(0, tk.END)
                self.bilibili_url_entry.insert(0, version['bilibili_url'] or "")
                
                self.version_description_text.delete(1.0, tk.END)
                self.version_description_text.insert(1.0, version['version_description'] or "")
                
                self.is_latest_var.set(version['is_latest'])
                
                self.update_button.config(state=tk.NORMAL)
                self.delete_button.config(state=tk.NORMAL)
                self.add_button.config(state=tk.DISABLED)
    
    def add_version(self):
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
        self.version_name_entry.delete(0, tk.END)
        self.bilibili_url_entry.delete(0, tk.END)
        self.version_description_text.delete(1.0, tk.END)
        self.is_latest_var.set(False)
        self.current_version_id = None
        
        self.update_button.config(state=tk.DISABLED)
        self.delete_button.config(state=tk.DISABLED)
        self.add_button.config(state=tk.NORMAL)

def run_version_manager_gui():
    root = tk.Tk()
    app = VersionManagerGUI(root, db_config)
    root.mainloop()

def check_new_version(current_version_name):
    try:
        latest_version = get_latest_version(**db_config)
        
        if not latest_version:
            return False, None
        
        if latest_version['version_name'] != current_version_name:
            return True, {
                'version_name': latest_version['version_name'],
                'bilibili_url': latest_version['bilibili_url'],
                'version_description': latest_version['version_description'],
                'created_at': latest_version['created_at']
            }
        else:
            return False, None
            
    except Exception as e:
        print(f"检测新版本时出错: {e}")
        return False, None

def notify_new_version(current_version_name, info = '发现新版本', root = None, must_show = False, has_new_version = False, latest_info = None):
    try:
        from functions.pages.notice.version_update_window import show_version_update_window, ask_window_just_opened
        from functions.base.settings_manager import get_settings_manager
        version_info:str = get_settings_manager().get_setting('version_info') # type: ignore
        if (has_new_version and latest_info) or must_show:
            if ask_window_just_opened():
                print("版本更新询问窗口已弹出, 跳过重复的详情窗口")
                return True
            try:
                from functions.pages.notice.version_notify import notify_version
                if notify_version(current_version_name, latest_info, info,
                                  has_new_version=has_new_version,
                                  forced=has_new_version, root=root):
                    return True
            except Exception as _e:
                print(f"[Update] 应用内模态窗口推送失败: {_e}")
            if not must_show and ("release" not in latest_info['version_name'] or "release" not in version_info): # type: ignore
                if "release" not in version_info:
                    messagebox.showwarning("警告", f"当前版本: {version_info}\n最新正式版本: {latest_info['version_name']}\n\n您正在使用测试版本，意味着该版本可能不稳定或包含未完成的功能。\n如果你是参与内测的用户,请将你遇到的问题反馈给开发者。") # type: ignore
            
            show_version_update_window(current_version_name, latest_info, info, root)
            return True
        else:
            return False
            
    except Exception as e:
        print(f"通知新版本时出错: {e}")
        return False

db_config = {
    'host': 'mysql2.sqlpub.com',
    'port': 3307,
    'user': 'mirroradmin',
    'password': 'cZGus9c0TrfhaLyd',
    'database': 'mirrorchat_data'
}

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
        run_version_manager_gui()
        success = True
    else:
        print("无效选择")
        success = False
    
    if success:
        print("\n 操作完成!")
    else:
        print("\n 操作失败!")
