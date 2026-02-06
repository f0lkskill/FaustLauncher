import os

def count_lines_in_file(file_path):
    """统计单个文件的行数"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return len(f.readlines())
    except Exception as e:
        print(f"无法读取文件 {file_path}: {e}")
        return 0

def find_py_files(directory):
    """递归查找所有.py文件"""
    py_files = []
    for root, dirs, files in os.walk(directory):
        # 排除一些不需要的目录
        dirs[:] = [d for d in dirs if d not in ['_internal', '__pycache__', '.git', 'build', 'dist', 'temp']]
        
        for file in files:
            if file.endswith('.py'):
                py_files.append(os.path.join(root, file))
    return py_files

def main():
    current_dir = os.getcwd()
    print(f"正在统计目录: {current_dir}")
    print("正在查找所有.py文件...")
    
    py_files = find_py_files(current_dir)
    
    if not py_files:
        print("未找到任何.py文件")
        return
    
    print(f"找到 {len(py_files)} 个.py文件")
    print("-" * 50)
    
    total_lines = 0
    file_stats = []
    
    for file_path in py_files:
        lines = count_lines_in_file(file_path)
        total_lines += lines
        file_stats.append((file_path, lines))
        print(f"{os.path.relpath(file_path, current_dir)}: {lines} 行")
    
    print("-" * 50)
    print(f"总计: {len(py_files)} 个文件, {total_lines} 行代码")
    
    # 按行数排序显示前10个最大的文件
    file_stats.sort(key=lambda x: x[1], reverse=True)
    print("\n📊 文件大小排行 (前10名):")
    for i, (file_path, lines) in enumerate(file_stats[:10], 1):
        rel_path = os.path.relpath(file_path, current_dir)
        print(f"{i:2d}. {rel_path}: {lines} 行")
    
    # 显示平均行数
    avg_lines = total_lines / len(py_files) if py_files else 0
    print(f"\n📈 平均每个文件: {avg_lines:.1f} 行")

if __name__ == "__main__":
    main()