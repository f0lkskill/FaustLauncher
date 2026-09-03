import requests
import json
from functions.base.web_config import get_webnote

DEFAULT_API_KEY = get_webnote('simplenote_api_key')[0]

class SimpleNote:
    """SimpleNotes.cc API v2 的 Python 封装类"""
    
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.simplenotes.cc/v2/"
    
    def _make_request(self, endpoint, data) -> dict:
        """发送请求的内部方法"""
        # 确保 key 和 json 参数总被包含
        data['key'] = self.api_key
        data['json'] = 1  # 强制使用 JSON 响应
        
        url = f"{self.base_url}{endpoint}/"
        
        try:
            # 使用 POST 方法，数据以 form 格式发送
            response = requests.post(url, data=data, timeout=30)
            response.raise_for_status()
            
            # 尝试解析 JSON
            result = response.json()
            if result.get('success') == '1':
                return result
            else:
                error_msg = result.get('error', '未知错误')
                print(f"API 操作失败: {error_msg}")
                return {}
        except requests.exceptions.RequestException as e:
            print(f"网络请求失败: {e}")
            return {}
        except json.JSONDecodeError:
            print("响应不是有效的 JSON 格式")
            return {}

    # --- 笔记操作 ---
    
    def list_notes(self):
        """获取所有笔记和文件夹"""
        return self._make_request('get', {})
    
    def get_note(self, note_id) -> dict:
        """获取单条笔记"""
        return self._make_request('get', {'note_id': note_id})
    
    def create_note(self, title, content, folder_id=1):
        """创建新笔记"""
        data = {
            'title': title,
            'content': content,
            'folder_id': folder_id
        }
        result = self._make_request('send', data)
        if result and result.get('action') == 'created':
            print(f"笔记创建成功，ID: {result.get('note_id')}")
        return result
    
    def update_note(self, note_id, title=None, content=None, share=None):
        """更新笔记（只更新提供的字段）"""
        data = {'note_id': note_id}
        if title is not None:
            data['title'] = title
        if content is not None:
            data['content'] = content
        if share is not None:
            data['share'] = '1' if share else '0'
            
        result = self._make_request('send', data)
        if result and result.get('action') == 'updated':
            print(f"笔记 {note_id} 更新成功")
        return result
    
    def delete_note(self, note_id):
        """删除笔记"""
        data = {
            'folder_action': 'delete_note',
            'note_id': note_id
        }
        result = self._make_request('send', data)
        if result and result.get('action') == 'note_deleted':
            print(f"笔记 {note_id} 删除成功")
        return result

    # --- 文件夹操作（可选） ---
    
    def create_folder(self, folder_name):
        """创建新文件夹"""
        data = {
            'folder_action': 'create',
            'folder_name': folder_name
        }
        result = self._make_request('send', data)
        if result and result.get('action') == 'folder_created':
            print(f"文件夹创建成功，ID: {result.get('folder_id')}")
        return result

# ===== 使用示例 =====
if __name__ == "__main__":
    # 替换为你真实的 API Key
    API_KEY = DEFAULT_API_KEY
    
    note = SimpleNote(API_KEY)
    
    # 1. 获取所有笔记
    print("--- 获取所有笔记 ---")
    all_data = note.list_notes()
    if all_data:
        print(f"共有 {len(all_data.get('notes', []))} 条笔记")
        for n in all_data.get('notes', []):
            print(f"- [{n['id']}] {n['title']} (文件夹: {n['folder_id']})")
    
    # # 2. 创建一条新笔记
    # print("\n--- 创建新笔记 ---")
    # create_result = note.create_note(
    #     title="我的Python笔记", 
    #     content="这是通过API创建的第一条笔记内容。",
    #     folder_id=1  # 默认在 Main 文件夹
    # )
    
    # 3. 更新笔记 (假设ID为刚创建返回的ID，或你自己指定)
    # 示例: note.update_note(note_id=123, title="新标题", content="新内容")
    
    # 4. 获取单条笔记
    single_note:dict = note.get_note(note_id=315)
    if single_note:
        if single_note.get('success') == '1':
            # print(f"笔记内容: {json.dumps(single_note, ensure_ascii=False, indent=2)}")
            print(f"笔记内容: {single_note.get('note', {}).get('content', '')}")
    
    # 5. 删除笔记 (谨慎操作!)
    # 示例: note.delete_note(note_id=123)
