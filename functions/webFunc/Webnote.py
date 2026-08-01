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
    
    def fetch_note_info(self):
        """读取笔记内容"""
        try:
            r = requests.get(self.note_url, verify=False)
            self.note_content = r.text
            return {'note_content': self.note_content, 'note_id': self.note_name}
        except:
            self.note_content = ""
            return {'note_content': "", 'note_id': self.note_name}
    
    def update_note_content(self, new_content):
        """更新笔记内容"""
        params = {'key': self.note_name, 'value': new_content}
        r = requests.get("https://textdb.online/update/", params=params, verify=False)
        result = r.json()
        if result.get('status') == 1:
            self.note_url = result['data']['url']
            self.req_id = result['req_id']
        return result
    
    def delete_note(self):
        """删除笔记"""
        params = {'key': self.note_name, 'value': ''}
        r = requests.get("https://textdb.online/update/", params=params, verify=False)
        return r.json()