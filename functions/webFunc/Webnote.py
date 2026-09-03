import requests

class Note:
    def __init__(self, address, pwd="", read_only=False):
        self.note_name = address
        self.pwd = pwd
        self.note_url = f"https://textdb.online/{address}"
        self.read_only = read_only
        self.note_content = ""
        self.note_id = address
        self.req_id = None
        self.has_get = False
    
    def fetch_note_info(self):
        """读取笔记内容"""
        try:
            if not self.has_get:
                r = requests.get(self.note_url, verify=False)
                self.note_content = r.text
                self.has_get = True
                return {'note_content': self.note_content, 'note_id': self.note_name}
            else:
                return {'note_content': self.note_content, 'note_id': self.note_name}
        except:
            self.note_content = ""
            return {'note_content': "", 'note_id': self.note_name}
    
    def update_note_content(self, new_content):
        """更新笔记内容"""
        # 1. 准备参数
        params = {'key': self.note_name}  # key 放在 URL 参数中
        data = {'value': new_content}      # value 放在请求体中

        try:
            # ✅ 核心修复：使用 POST 方法，将 value 放在 data 参数中
            r = requests.post(
                "https://textdb.online/update/",
                params=params,      # key 放在 URL 参数中
                data=data,          # value 放在请求体 (application/x-www-form-urlencoded)
                verify=False,
                timeout=30
            )
            
            # print(f"状态码: {r.status_code}")
            # 调试时打印响应内容前200字符
            # print(f"响应内容: {r.text[:200]}") 

            # 2. 检查响应状态
            r.raise_for_status()  # 如果不是 2xx，会抛出异常
            
            # 3. 检查响应内容是否为空
            if not r.text or not r.text.strip():
                print("API 返回空内容")
                # 但数据已经更新到内存
                self.note_content = new_content
                return {'status': 0, 'error': 'Empty response'}

            # 4. 尝试解析 JSON 响应
            try:
                result = r.json()
            except ValueError as e:
                print(f"JSON 解析失败: {e}")
                print(f"原始响应: {r.text[:500]}")
                # 虽然 API 调用失败，但为了程序继续运行，更新内存
                self.note_content = new_content
                return {'status': 0, 'error': 'Invalid JSON'}

            # 5. 处理成功响应
            if result.get('status') == 1:
                self.note_url = result['data']['url']
                self.req_id = result['req_id']
                self.note_content = new_content
                print(f"笔记更新成功！URL: {self.note_url}")
            else:
                print(f"API 返回失败: {result}")
                # 即使失败，也更新内存
                self.note_content = new_content

            return result

        except requests.exceptions.RequestException as e:
            print(f"网络请求失败: {e}")
            # 发生网络错误时，降级处理：只更新内存
            self.note_content = new_content
            return {'status': 0, 'error': str(e)}
    
    def delete_note(self):
        """删除笔记"""
        params = {'key': self.note_name, 'value': ''}
        r = requests.get("https://textdb.online/update/", params=params, verify=False)
        return r.json()