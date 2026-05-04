#include <iostream>
#include <filesystem>
#include <string>
#include <cstdlib>
#include <windows.h>
#include <vector>

using namespace std;
namespace fs = filesystem;

// 复制重要文件夹函数
bool copyImportantFolders(const string& rootPath, const string& newVersionPath) {
    try {
        // 需要保留的重要文件夹列表
        vector<string> importantFolders = {"config", "addons", "cache", "mods"};
        
        for (const auto& folder : importantFolders) {
            string sourcePath = rootPath + "\\" + folder;
            string destPath = newVersionPath + "\\" + folder;
            
            // 检查源文件夹是否存在
            if (!fs::exists(sourcePath)) {
                cout << "警告: 重要文件夹不存在: " << sourcePath << endl;
                continue;
            }
            
            // 创建目标文件夹
            fs::create_directories(destPath);
            
            // 递归复制文件夹内容
            for (const auto& entry : fs::recursive_directory_iterator(sourcePath)) {
                if (entry.is_regular_file()) {
                    fs::path relativePath = fs::relative(entry.path(), sourcePath);
                    fs::path fullDestPath = destPath / relativePath;
                    
                    // 创建目标目录
                    fs::create_directories(fullDestPath.parent_path());
                    
                    // 复制文件
                    fs::copy_file(entry.path(), fullDestPath, fs::copy_options::overwrite_existing);
                }
            }
            
            cout << "完成复制文件夹: " << folder << endl;
        }
        
        cout << "所有重要文件夹复制完成" << endl;
        return true;
    }
    catch (const exception& e) {
        cerr << "文件夹复制错误: " << e.what() << endl;
        return false;
    }
}

// 清理旧版本文件
bool cleanupOldVersion(const string& rootPath) {
    try {
        // 需要保留的文件夹
        vector<string> preserveFolders = {"config", "addons", "cache", "mods"};
        
        for (const auto& entry : fs::directory_iterator(rootPath)) {
            if (entry.is_directory()) {
                string folderName = entry.path().filename().string();
                
                // 检查是否是需要保留的文件夹
                bool shouldPreserve = false;
                for (const auto& preserve : preserveFolders) {
                    if (folderName == preserve) {
                        shouldPreserve = true;
                        break;
                    }
                }
                
                if (!shouldPreserve) {
                    fs::remove_all(entry.path());
                    cout << "删除文件夹: " << folderName << endl;
                }
            } else if (entry.is_regular_file()) {
                // 删除所有文件（保留的文件夹会在后续步骤中处理）
                fs::remove(entry.path());
                cout << "删除文件: " << entry.path().filename().string() << endl;
            }
        }
        
        cout << "旧版本清理完成" << endl;
        return true;
    }
    catch (const exception& e) {
        cerr << "清理错误: " << e.what() << endl;
        return false;
    }
}

// 移动新版本文件到根目录
bool moveNewVersion(const string& newVersionPath, const string& rootPath) {
    try {
        // 移动所有文件和文件夹到根目录
        for (const auto& entry : fs::directory_iterator(newVersionPath)) {
            fs::path destPath = rootPath / entry.path().filename();
            
            if (fs::exists(destPath)) {
                if (entry.is_directory()) {
                    // 如果是文件夹，合并内容
                    for (const auto& subEntry : fs::recursive_directory_iterator(entry.path())) {
                        if (subEntry.is_regular_file()) {
                            fs::path relativePath = fs::relative(subEntry.path(), entry.path());
                            fs::path subDestPath = destPath / relativePath;
                            fs::create_directories(subDestPath.parent_path());
                            fs::copy_file(subEntry.path(), subDestPath, fs::copy_options::overwrite_existing);
                        }
                    }
                } else {
                    // 如果是文件，直接覆盖
                    fs::copy_file(entry.path(), destPath, fs::copy_options::overwrite_existing);
                }
            } else {
                // 如果目标不存在，直接移动
                fs::rename(entry.path(), destPath);
            }
        }
        
        cout << "新版本移动完成" << endl;
        return true;
    }
    catch (const exception& e) {
        cerr << "移动错误: " << e.what() << endl;
        return false;
    }
}

int main() {
    cout << "=== FaustLauncher 更新器 ===" << endl;
    
    // 路径定义
    string currentDir = fs::current_path().string();
    string rootPath = fs::path(currentDir).parent_path().parent_path().string(); // 项目根目录
    string newVersionPath = currentDir;
    
    cout << "当前目录: " << currentDir << endl;
    cout << "项目根目录: " << rootPath << endl;
    cout << "新版本路径: " << newVersionPath << endl;
    
    // 检查新版本是否存在
    if (!fs::exists(newVersionPath)) {
        cerr << "错误: 新版本文件夹不存在: " << newVersionPath << endl;
        system("pause");
        return 1;
    }
    
    // 1. 复制重要文件夹到新版本
    cout << "\n1. 复制重要文件夹...";
    copyImportantFolders(rootPath, newVersionPath);
    
    // 2. 清理旧版本
    cout << "\n2. 清理旧版本文件...";
    cleanupOldVersion(rootPath);
    
    // 3. 移动新版本到根目录
    cout << "\n3. 移动新版本文件...";
    moveNewVersion(newVersionPath, rootPath);
    
    // 4. 删除缓存文件夹
    cout << "\n4. 清理缓存...";
    try {
        fs::remove_all(currentDir);
        cout << "缓存清理完成" << endl;
    }
    catch (const exception& e) {
        cerr << "缓存清理错误: " << e.what() << endl;
    }
    
    // 5. 启动新版本启动器
    cout << "\n5. 启动新版本启动器...";
    string launcherPath = rootPath + "\\FaustLauncher.exe";
    
    if (fs::exists(launcherPath)) {
        SHELLEXECUTEINFO sei = {0};
        sei.cbSize = sizeof(sei);
        sei.lpVerb = "open";
        sei.lpFile = launcherPath.c_str();
        sei.nShow = SW_SHOWNORMAL;
        
        if (ShellExecuteEx(&sei)) {
            cout << "新版本启动器已启动" << endl;
        } else {
            cerr << "启动新版本启动器失败" << endl;
        }
    } else {
        cerr << "错误: 启动器文件不存在: " << launcherPath << endl;
    }
    
    cout << "\n更新完成!" << endl;
    return 0;
}
