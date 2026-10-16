# -*- coding: utf-8 -*-

import requests
import random
from hashlib import md5
import time

class BaiduTranslatorFixed:
    
    def __init__(self, appid: str, appkey: str):
        self.appid = appid
        self.appkey = appkey
        self.endpoint = 'http://api.fanyi.baidu.com'
        self.path = '/api/trans/vip/translate'
        self.url = self.endpoint + self.path
    
    def _make_md5(self, s, encoding='utf-8'):
        return md5(s.encode(encoding)).hexdigest()
    
    def _validate_query(self, query: str) -> bool:
        if not query or not query.strip():
            return False
        if len(query) > 6000:
            return False
        return True
    
    def translate(self, query: str, from_lang: str = 'en', to_lang: str = 'zh'):
        if not self._validate_query(query):
            return {"error": "查询文本无效", "error_code": "54000"}
        
        try:
            salt = random.randint(32768, 65536)
            
            sign_str = self.appid + query + str(salt) + self.appkey
            sign = self._make_md5(sign_str)
            
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            payload = {
                'appid': self.appid,
                'q': query,
                'from': from_lang,
                'to': to_lang,
                'salt': salt,
                'sign': sign
            }
            
            response = requests.post(self.url, data=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                return result
            else:
                return {
                    "error": f"HTTP错误: {response.status_code}",
                    "error_code": "52002"
                }
                
        except requests.exceptions.RequestException as e:
            return {"error": f"网络请求异常: {str(e)}", "error_code": "52001"}
        except Exception as e:
            return {"error": f"翻译异常: {str(e)}", "error_code": "52002"}

def test_fixed_translator():
    appid = "20251225002527257"
    appkey = "1p0t_d5h2m9ocguqhr0nm6e2g"
    
    translator = BaiduTranslatorFixed(appid, appkey)
    
    test_queries = [
        "Hello World",
        "你好",
        "test",
        "apple"
    ]
    
    for query in test_queries:
        print(f"\n测试翻译: '{query}'")
        result = translator.translate(query, 'en', 'zh')
        
        if 'error_code' in result:
            error_code = result['error_code']
            error_msg = result.get('error', '未知错误')
            print(f"翻译失败 - 错误码: {error_code}, 错误信息: {error_msg}")
            
            if error_code == '54001':
                print("签名错误建议:")
                print("1. 检查API密钥是否正确")
                print("2. 检查签名生成顺序: appid + q + salt + appkey")
                print("3. 确保文本编码为UTF-8")
                print("4. 尝试重新生成API密钥")
        else:
            print(f"翻译成功: {result}")
        
        time.sleep(1)

def debug_signature():
    appid = "20251225002527257"
    appkey = "1p0t_d5h2m9ocguqhr0nm6e2g"
    query = "Hello World"
    salt = random.randint(32768, 65536)
    
    print("=== 签名调试信息 ===")
    print(f"AppID: {appid}")
    print(f"AppKey: {appkey}")
    print(f"Query: {query}")
    print(f"Salt: {salt}")
    
    sign_str = appid + query + str(salt) + appkey
    sign = md5(sign_str.encode('utf-8')).hexdigest()
    
    print(f"签名字符串: {sign_str}")
    print(f"MD5签名: {sign}")
    print(f"签名长度: {len(sign)}")
    print("===================")

if __name__ == "__main__":
    print("开始测试百度翻译API...")
    
    debug_signature()
    
    test_fixed_translator()
