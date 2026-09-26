#include "Global.h"
#include "RdtSender.h"
#include "RdtReceiver.h"
#include "SRRdtSender.h"
#include "SRRdtReceiver.h"

int main(int argc, char *argv[])
{
    // 检查全局指针是否已初始化
    if (pns == nullptr || pUtils == nullptr)
    {
        std::cerr << "错误：全局指针未正确初始化！" << std::endl;
        return -1;
    }

    RdtSender *ps = new SRRdtSender();
    RdtReceiver *pr = new SRRdtReceiver();

    // 初始化模拟网络环境
    pns->init();

    // 设置运行模式：0为VERBOSE模式(输出详细信息)，1为安静模式
    pns->setRunMode(0); // 使用VERBOSE模式便于调试

    // 设置发送方和接收方
    pns->setRtdSender(ps);
    pns->setRtdReceiver(pr);

    // 设置输入输出文件路径
    pns->setInputFile("/home/dx39066812/code/SR/io/input.txt");
    pns->setOutputFile("/home/dx39066812/code/SR/io/output.txt");

    // 启动模拟网络环境
    pns->start();

    // 清理资源
    delete ps;
    delete pr;
    delete pUtils; // 指向唯一的工具类实例，只在main函数结束前delete
    delete pns;    // 指向唯一的模拟网络环境类实例，只在main函数结束前delete

    return 0;
}