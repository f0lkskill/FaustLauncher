from json import load
import os

def check_need_up_translate(version_info:str = "") -> bool:
    try:
        if not os.path.exists('workshop/LLC_zh-CN/info/version.json'):
            return True

        if version_info != "":
            version_timestamp = version_info
        else:
            version_timestamp = str(load(
                open('workshop/LimbusCompany_Data/Lang/LLC_zh-CN/info/version.json', 
                    'r', encoding='utf-8')
            )['version'])

        now_timestamp = str(load(
            open('workshop/LLC_zh-CN/info/version.json', 
                'r', encoding='utf-8')
        )['version'])

        version_info.strip()
        now_timestamp.strip()

        if version_timestamp != now_timestamp:
            return True
        
        return False
    
    except:
        return False

if __name__ == '__main__':
    print(check_need_up_translate("20250115"))