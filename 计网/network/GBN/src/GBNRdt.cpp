#include "Global.h"
#include "RdtSender.h"
#include "RdtReceiver.h"
#include "GBNRdtSender.h"
#include "GBNRdtReceiver.h"

int main(int argc, char *argv[])
{
    // 创建GBN协议发送方和接收方实例
    // 使用3位序列号(0-7)，窗口大小为4
    RdtSender *ps = new GBNRdtSender(4, 3);
    RdtReceiver *pr = new GBNRdtReceiver(3);

    // 初始化模拟网络环境
    pns->init();

    // 设置运行模式：0为VERBOSE模式(输出详细信息)，1为安静模式
    pns->setRunMode(0); // 使用VERBOSE模式便于调试

    // 设置发送方和接收方
    pns->setRtdSender(ps);
    pns->setRtdReceiver(pr);

    // 设置输入输出文件路径
    // 注意：请根据实际文件路径修改
    pns->setInputFile("/home/dx39066812/code/GBN/io/input.txt");
    pns->setOutputFile("/home/dx39066812/code/GBN/io/output.txt");

    // 启动模拟网络环境
    pns->start();

    // 清理资源
    delete ps;
    delete pr;
    delete pUtils; // 指向唯一的工具类实例，只在main函数结束前delete
    delete pns;    // 指向唯一的模拟网络环境类实例，只在main函数结束前delete

    return 0;
}