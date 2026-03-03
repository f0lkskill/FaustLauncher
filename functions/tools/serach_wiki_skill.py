import os
import time
from bs4 import BeautifulSoup
from json import load, dump
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 确保html文件夹存在
html_folder = os.path.join(os.path.dirname(__file__), "html")
if not os.path.exists(html_folder):
    os.makedirs(html_folder)

# 确保data文件夹存在
data_folder = os.path.join(os.path.dirname(__file__), "data")
if not os.path.exists(data_folder):
    os.makedirs(data_folder)

target_file_path = "lang/LLC_zh-CN/Personalities.json"

# 加载Personalities.json文件
with open(target_file_path, mode='r', encoding='utf-8') as f:
    loaded_dict = load(f)

# 配置Chrome浏览器选项
chrome_options = Options()
# 禁用无头模式，这样可以看到浏览器操作，方便调试
# chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
# 添加用户代理，模拟真实浏览器
chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
# 禁用自动化控制检测
chrome_options.add_argument("--disable-blink-features=AutomationControlled")

# 创建WebDriver实例
driver = webdriver.Chrome(options=chrome_options) # type: ignore
# 执行JavaScript来隐藏webdriver属性
driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

# 处理每个角色
for character in loaded_dict['dataList']:
    # 生成索引（去除\n）
    index = character['name'] + character['title'].replace('\n', '')
    # 生成URL
    url = f"https://limbuscompany.huijiwiki.com/wiki/{index}"

    if os.path.exists(f'functions/tools/html/{index.replace(':','').replace(' ','')}.html'):
        print(f"{index}.html 已存在，跳过加载。 ")
        continue
    
    try:
        # 打开网页
        driver.get(url)
        # 等待页面加载完成
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        # 等待额外时间确保所有内容加载
        time.sleep(0.5)
        
        # 检查是否是Cloudflare验证码页面
        if "Just a moment..." in driver.page_source:
            print(f"角色 {character['name']} 遇到Cloudflare验证码，需要手动处理")
            # 等待用户手动处理验证码
            input("请手动处理验证码，完成后按Enter继续...")
            # 再次等待页面加载
            time.sleep(1)
        
        # 获取页面源码
        page_source = driver.page_source
        
        # 构建保存路径
        save_path = os.path.join(html_folder, f"{index}.html".replace(":",'').replace(' ',''))
        
        # 保存HTML文件，确保使用utf-8编码
        with open(save_path, 'w', encoding='utf-8') as f:
            f.write(page_source)
        
        print(f"已保存角色 {character['name']} 的HTML文件")
        
        # 处理JSON文件
        # 获取百位数字（id的第3位，从右往左数）
        id_str = str(character['id'])
        if len(id_str) >= 3:
            # 取第3位数字（从0开始索引）
            # print(id_str)
            hundred_digit = str(id_str[1:3])
            print(hundred_digit)
            skill_file = f"lang/LLC_zh-CN/Skills_personality-{hundred_digit}.json"
            
            # 检查文件是否存在
            if os.path.exists(skill_file):
                with open(skill_file, mode='r', encoding='utf-8') as f:
                    skill_data = load(f)
                
                # 解析HTML文件，提取技能信息
                html_file = os.path.join(html_folder, f"{index}.html".replace(":",'').replace(' ',''))
                with open(html_file, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                
                soup = BeautifulSoup(html_content)
                
                # 找到所有技能表格
                skill_tables = soup.find_all('div', class_='table-responsive table-wrapper') # type: ignore

                skills_info = []
                try:    
                    skills_info = load(open(f"functions/tools/data/personality-{hundred_digit}.json",'r',encoding='utf-8'))
                except:
                    pass
                
                # 遍历技能表格，提取技能信息
                for table in skill_tables:
                    # 找到技能标题
                    skill_title_element = table.find('td', width="90px")

                    # print(skill_title_element)

                    if not skill_title_element:
                        continue
                    
                    skill_title = skill_title_element.text.strip()
                    if not ('技能' in skill_title or '守备' in skill_title):
                        continue
                    
                    # 找到技能名称
                    skill_name_element = table.find('b')
                    if skill_name_element:
                        skill_name = skill_name_element.text.strip()
                    else:
                        skill_name = "未知技能"
                    
                    # 提取罪孽类型
                    sin_type = "未知"
                    # 查找技能图标下方的罪孽类型图片
                    # 先查找所有img元素
                    all_imgs = table.find_all('img')
                    print(f"找到 {len(all_imgs)} 个img元素")
                    
                    # 遍历所有img元素，找到包含"技能-"的alt属性
                    for img in all_imgs:
                        alt_text = img.get('alt', '')
                        if '技能-' in alt_text: # type: ignore
                            print(f"找到技能图片: {alt_text}")
                            # 从alt属性中提取罪孽类型
                            if '-' in alt_text: # type: ignore
                                # 格式：技能-类型-罪孽
                                parts = alt_text.split('-') # type: ignore
                                if len(parts) >= 3:
                                    sin_type = parts[-1].replace('.png', '')
                                    print(f"提取到罪孽类型: {sin_type}")
                                break
                    
                    # 遍历技能数据，找到对应技能
                    # 首先根据技能标题确定技能位置
                    skill_index = 0
                    if '技能一' in skill_title:
                        skill_index = 0
                    elif '技能二' in skill_title:
                        skill_index = 1
                    elif '技能三' in skill_title:
                        skill_index = 2
                    elif '守备' in skill_title:
                        skill_index = 3
                    
                    # 根据角色ID和技能索引找到对应技能
                    # 首先获取角色ID的前四位（例如1010504中的1010）
                    character_id_prefix = str(character['id'])[:4]
                    
                    # 遍历技能数据，找到对应角色的技能
                    for skill in skill_data['dataList']:
                        skill_id_str = str(skill['id'])
                        # 检查技能ID是否与角色ID匹配，并且技能索引正确
                        if skill_id_str.startswith(character_id_prefix):
                            # 提取技能ID的最后一位作为技能索引
                            skill_id_last_digit = int(skill_id_str[-1]) - 1  # 转换为0-based索引
                            if skill_id_last_digit == skill_index:
                                skills_info.append({
                                    "id": skill['id'],
                                    "type": sin_type,
                                    "desc": skill_title
                                })
                                break
                    
                    # 如果没有找到匹配的技能，尝试名称匹配
                    if not any(str(skill['id']).startswith(character_id_prefix) for skill in skills_info):
                        for skill in skill_data['dataList']:
                            skill_id = skill['id']
                            skill_name_from_json = skill['levelList'][0]['name']
                            
                            # 简单匹配：如果技能名称包含或被包含
                            if skill_name in skill_name_from_json or skill_name_from_json in skill_name:
                                skills_info.append({
                                    "id": skill_id,
                                    "type": sin_type,
                                    "desc": skill_title
                                })
                                print(f"通过名称匹配到技能: {skill_name_from_json} (ID: {skill_id})，罪孽类型: {sin_type}")
                                break
                
                # 如果没有找到技能信息，使用默认值
                if not skills_info:
                    for skill in skill_data['dataList']:
                        skill_id = skill['id']
                        skills_info.append({
                            "id": skill_id,
                            "type": "未知",
                            "desc": "未知技能"
                        })
                
                # 生成新的JSON文件
                output_file = os.path.join(data_folder, f"personality-{hundred_digit}.json")
                with open(output_file, 'w', encoding='utf-8') as f:
                    dump(skills_info, f, ensure_ascii=False, indent=2)
                
                print(f"已生成角色 {character['name']} 的技能数据文件，提取了 {len(skills_info)} 个技能信息")
                print("-"*50)
            else:
                print(f"技能文件 {skill_file} 不存在")
        else:
            print(f"角色 {character['name']} 的ID长度不足3位")
            
    except Exception as e:
        print(f"处理角色 {character['name']} 时出错: {str(e)}")
    
    # 等待一下再处理下一个角色
    # time.sleep(0.1)

# 关闭浏览器
driver.quit()

print("所有角色处理完成")